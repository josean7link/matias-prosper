"""Parte 1 + Parte 4 — verificación de vectores cerrados en producción.

Cubre:
  1. `/onboarding/apply/simulate` responde 404 opaco fuera de sandbox
     (mismo mensaje que una ruta inexistente).
  2. `/onboarding/apply` con business + template vacío en producción no
     cae al simulador: devuelve 503 (ProviderMisconfigured).
  3. `magic_link` NUNCA aparece en la respuesta de `/onboarding/apply`
     cuando el ambiente es producción, sin importar RESEND_API_KEY.
  4. `/auth/dev-login` responde 404 en producción, aun si DEMO_MODE=true.

El default fail-safe es "production": si `KYB_ENVIRONMENT` y `PROSPER_MODE`
no son sandbox-like, se trata como prod.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_PORT = 8027
_SCRATCH_DB = "prosper_prodsim_test"
API = f"http://127.0.0.1:{_PORT}/api/v1"


@pytest.fixture(scope="module")
def prod_server():
    """uvicorn efímero corriendo con KYB_ENVIRONMENT=production."""
    mongo = MongoClient(os.environ["MONGO_URL"])
    mongo.drop_database(_SCRATCH_DB)
    env = {**os.environ,
           "DB_NAME": _SCRATCH_DB,
           "KYB_ENVIRONMENT": "production",   # fuerza kyb_environment()==prod
           "PROSPER_MODE": "production",
           "KYB_MODULE_ENABLED": "true",
           "PROSPER_DISABLE_RATELIMIT": "1",
           "RESEND_API_KEY": "",              # el peor caso: sin Resend
           "DEMO_MODE": "true",               # el peor caso: alguien olvidó apagarlo
           "AIPRISE_KYB_TEMPLATE_ID": "",     # el peor caso: sin template
           "AIPRISE_KYC_TEMPLATE_ID": ""}
    # Este test valida el guard EN PROD REAL: removemos toda marca de
    # ejecución bajo pytest para que el subprocess uvicorn se comporte
    # como un binario en un pod productivo. Sin PYTEST_CURRENT_TEST, el
    # guard de dev-login queda estricto.
    env.pop("PYTEST_CURRENT_TEST", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(_PORT)],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try:
            if requests.get(f"{API}/status", timeout=1).status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("uvicorn no arrancó")
    yield
    proc.terminate()
    proc.wait(timeout=5)
    mongo.drop_database(_SCRATCH_DB)


def test_simulate_route_retired_in_production(prod_server):
    """/apply/simulate fue retirada del router en la Fase 1 del retiro
    de AiPrise. FastAPI responde con 404 (o 405 si el catch-all
    `/apply/{app_id}` toma el path como POST no permitido). Antes este
    test verificaba el 404 opaco puesto por `_reject_simulate_in_production`
    — ahora la ruta directamente no está montada."""
    r = requests.post(f"{API}/onboarding/apply/simulate",
                      json={"session_id": "sim_kyb_deadbeef",
                            "decision": "approved"},
                      timeout=5)
    assert r.status_code in (404, 405), r.text


def test_simulate_route_retired_for_any_payload(prod_server):
    """Cualquier payload al ex-simulator resulta en no-2xx (404 o 405)."""
    for payload in [{"session_id": "foo", "decision": "approved"},
                    {"session_id": "sim_kyb_x", "decision": "invalid"},
                    {}]:
        r = requests.post(f"{API}/onboarding/apply/simulate",
                          json=payload, timeout=5)
        assert r.status_code in (404, 405), (payload, r.text)


def test_apply_business_returns_410_by_module_retirement(prod_server):
    """El path corporativo público está cerrado: `/apply` con
    applicant_type=business devuelve 410 Gone en toda instalación.
    El alta de empresas se realiza por invitación desde el módulo KYB.
    Este test antes verificaba el 503 por template faltante — ahora el
    contrato es 410 independiente del estado de las credenciales."""
    r = requests.post(f"{API}/onboarding/apply", json={
        "applicant_type": "business",
        "legal_name": "Test Prod Block SA",
        "commercial_name": "Test Prod Block",
        "country": "AR", "jurisdiction": "AR",
        "incorporation_date": "2020-01-01",
        "registration_number": "12345",
        "contact_name": "Owner",
        "contact_email": "owner-prodblock@preview-prosper.io",
        "contact_phone": "+541100000000",
        "website": "https://ex.com",
        "expected_monthly_volume_usd": 1000,
        "use_case": "test",
        "ubos": [{"full_name": "U1", "id_number": "1",
                  "birthdate": "1990-01-01", "nationality": "AR",
                  "ownership_pct": 100}],
    }, timeout=10)
    assert r.status_code == 410, f"esperaba 410, obtuve {r.status_code}: {r.text}"
    # La org NO debe haber quedado con sim_ session_id
    mongo = MongoClient(os.environ["MONGO_URL"])
    db = mongo[_SCRATCH_DB]
    sim_apps = db.onboarding_applications.count_documents(
        {"aiprise_session_id": {"$regex": "^sim_kyb_"}})
    assert sim_apps == 0, "no debe crearse ninguna app con sim_ en prod"


def test_dev_login_404_in_production_even_with_demo_mode_true(prod_server):
    """/auth/dev-login → 404 en prod, aunque DEMO_MODE=true por descuido."""
    r = requests.get(f"{API}/auth/dev-login",
                     params={"email": "attacker@example.com"},
                     allow_redirects=False, timeout=5)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_dev_login_no_env_var_can_reopen_it_in_production(prod_server):
    """Test de regresión: ninguna combinación de env-vars 'operacionales'
    debe volver a abrir dev-login en un proceso productivo. El único
    escape aceptado es la marca de pytest, que no se puede setear desde
    un `.env` operacional. Este test protege contra el patrón débil que
    tuvimos con `DEMO_MODE`, `AIPRISE_DEPRECATED` y el ya-eliminado
    `PROSPER_ALLOW_DEV_LOGIN`.

    Arranca un uvicorn efímero limpiando toda marca de pytest y setea
    variables 'ruidosas' que un ingeniero podría poner intentando
    reabrir el endpoint. Debe seguir dando 404."""
    import subprocess
    import time
    port = 8029
    env = {**os.environ, "DB_NAME": f"{_SCRATCH_DB}_regression",
           "KYB_ENVIRONMENT": "production",
           "PROSPER_MODE": "production",
           "KYB_MODULE_ENABLED": "true",
           "PROSPER_DISABLE_RATELIMIT": "1",
           "DEMO_MODE": "true",
           # Env-vars 'ruidosas' que un operador podría poner intentando
           # abrir el endpoint. Ninguna debería tener efecto.
           "PROSPER_ALLOW_DEV_LOGIN": "1",
           "ALLOW_DEV_LOGIN": "1",
           "DEV_LOGIN_ENABLED": "1",
           "PROSPER_TESTING": "1",
           "TESTING": "1",
           "CI": "true",
           "AIPRISE_DEPRECATED": "1"}
    env.pop("PYTEST_CURRENT_TEST", None)     # simular proceso NO-pytest
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:
                if requests.get(
                        f"http://127.0.0.1:{port}/api/v1/status",
                        timeout=1).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("uvicorn efímero no arrancó")
        r = requests.get(
            f"http://127.0.0.1:{port}/api/v1/auth/dev-login",
            params={"email": "attacker@example.com"},
            allow_redirects=False, timeout=5)
        assert r.status_code == 404, (
            f"REGRESIÓN DE SEGURIDAD: dev-login abierto en prod. "
            f"HTTP {r.status_code}: {r.text}")
        assert r.json() == {"detail": "Not Found"}
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        MongoClient(os.environ["MONGO_URL"]).drop_database(
            f"{_SCRATCH_DB}_regression")


def test_magic_link_never_in_apply_response_in_production(prod_server):
    """Si /apply llegara a responder OK en prod (individual path, que sí
    funciona sin AiPrise), magic_link debe ser null en el body."""
    r = requests.post(f"{API}/onboarding/apply", json={
        "applicant_type": "individual",
        "legal_name": "Individuo Prod Block",
        "commercial_name": "Individuo Prod Block",
        "country": "AR", "jurisdiction": "AR",
        "contact_name": "Persona",
        "contact_email": "personaindiv@preview-prosper.io",
        "contact_phone": "+541100000001",
        "last_name": "TestApellido",
        "cuit": "20111111112",
        "birthdate": "1990-01-01",
        "phone": "+541100000001",
        "chain": "stellar",
        "ubos": [],
    }, timeout=10)
    # Path individual sigue vivo — debe responder 200
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("magic_link") is None, (
        "magic_link debe ser None en prod, obtuve: "
        f"{body.get('magic_link')!r}")


def test_kyb_environment_default_is_production_when_unset(prod_server):
    """Fail-safe: kyb_environment() default es 'production' si ambos env
    vars están vacíos o valores no reconocidos como sandbox."""
    from kyb.verification_modes import kyb_environment
    save = {k: os.environ.get(k) for k in ("KYB_ENVIRONMENT", "PROSPER_MODE")}
    try:
        # Ambos vacíos → production
        os.environ["KYB_ENVIRONMENT"] = ""
        os.environ["PROSPER_MODE"] = ""
        assert kyb_environment() == "production", "vacíos deben → production"
        # PROSPER_MODE con valor no-sandbox → production
        os.environ["PROSPER_MODE"] = "algo_raro_no_sandbox"
        assert kyb_environment() == "production"
        # KYB_ENVIRONMENT explícito gana sobre PROSPER_MODE
        os.environ["KYB_ENVIRONMENT"] = "production"
        os.environ["PROSPER_MODE"] = "development"
        assert kyb_environment() == "production"
        # sandbox explícito → sandbox
        os.environ["KYB_ENVIRONMENT"] = "sandbox"
        assert kyb_environment() == "sandbox"
        # PROSPER_MODE sandbox-like → sandbox
        os.environ["KYB_ENVIRONMENT"] = ""
        os.environ["PROSPER_MODE"] = "development"
        assert kyb_environment() == "sandbox"
    finally:
        for k, v in save.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
