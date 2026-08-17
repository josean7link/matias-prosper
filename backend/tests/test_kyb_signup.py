"""Tests e2e del signup KYB (Fase 2) — contra SERVERS DE PRUEBA.

Se levantan DOS uvicorn efímeros:
  * puerto 8013, DB scratch, `KYB_MODULE_ENABLED=true` — camino feliz.
  * puerto 8014, DB scratch, `KYB_MODULE_ENABLED=false` — flag-off,
    verifica que las rutas no existan.

Antes este archivo apuntaba `PROD_API` al backend del pod (puerto
8001), lo que rompía el baseline cuando `KYB_MODULE_ENABLED` estaba
encendido en runtime. Ahora es 100% autocontenido: cero dependencia
del backend real.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_SCRATCH_DB = "prosper_kyb_tests_signup"
_SCRATCH_DB_OFF = "prosper_kyb_tests_signup_flag_off"
_PORT = 8013
_PORT_OFF = 8014
TEST_API = f"http://127.0.0.1:{_PORT}/api/v1"
FLAG_OFF_API = f"http://127.0.0.1:{_PORT_OFF}/api/v1"


def _spawn_server(port: int, db_name: str, kyb_enabled: bool):
    mongo = MongoClient(os.environ["MONGO_URL"])
    mongo.drop_database(db_name)
    env = {**os.environ,
           "DB_NAME": db_name,
           "KYB_MODULE_ENABLED": "true" if kyb_enabled else "false",
           "PROSPER_DISABLE_RATELIMIT": "1",
           "RESEND_API_KEY": "",
           "DEMO_MODE": "true"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            requests.get(f"http://127.0.0.1:{port}/docs", timeout=1)
            return proc, mongo, mongo[db_name]
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    proc.wait(timeout=10)
    mongo.close()
    raise RuntimeError(f"test server no arrancó en puerto {port}")


@pytest.fixture(scope="module")
def server():
    proc, mongo, db = _spawn_server(_PORT, _SCRATCH_DB, kyb_enabled=True)
    try:
        yield db
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        mongo.drop_database(_SCRATCH_DB)
        mongo.close()


@pytest.fixture(scope="module")
def server_flag_off():
    proc, mongo, db = _spawn_server(_PORT_OFF, _SCRATCH_DB_OFF,
                                     kyb_enabled=False)
    try:
        yield db
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        mongo.drop_database(_SCRATCH_DB_OFF)
        mongo.close()


def _start(email: str, company: str = "Empresa Test SA") -> dict:
    r = requests.post(f"{TEST_API}/kyb/signup/start",
                      json={"email": email, "company_name": company},
                      timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


def _extract_activation_token(db, email: str) -> str:
    doc = db["outbound_emails"].find_one({"to": email},
                                         sort=[("created_at", -1)])
    assert doc is not None, "no se guardó el email de activación"
    assert doc["status"] == "preview_only"      # RESEND_API_KEY vacía
    m = re.search(r"token=([A-Za-z0-9_\-]+)", doc["html"])
    assert m, "el html no contiene la URL con el token"
    return m.group(1)


# ---------------------------------------------------------------------------
# Flag apagado → las rutas no existen (server efímero dedicado, no el pod)
# ---------------------------------------------------------------------------
def test_flag_off_routes_do_not_exist_in_prod(server_flag_off):
    r = requests.post(f"{FLAG_OFF_API}/kyb/signup/start",
                      json={"email": "x@y.com", "company_name": "X"},
                      timeout=10)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Camino feliz completo + token de un solo uso
# ---------------------------------------------------------------------------
def test_full_signup_flow_and_single_use_activation(server):
    db = server
    email = "founder@empresa-nueva.io"
    body = _start(email)
    assert set(body) == {"ok", "signup_token", "message"}
    tok = body["signup_token"]

    # contact + country
    r = requests.post(f"{TEST_API}/kyb/signup/contact", json={
        "signup_token": tok, "full_name": "Ana Founder",
        "phone": {"country_code": "+54", "number": "1155555555"}},
        timeout=10)
    assert r.status_code == 200, r.text
    r = requests.post(f"{TEST_API}/kyb/signup/country", json={
        "signup_token": tok, "country": "ar"}, timeout=10)
    assert r.status_code == 200, r.text

    case = db["kyb_cases"].find_one({"applicant_email": email})
    assert case["status"] == "draft"            # sin transición en Fase 2
    assert case["applicant_name"] == "Ana Founder"
    assert case["country_of_incorporation"] == "AR"
    org = db["organizations"].find_one({"org_id": case["org_id"]})
    # kyb_status="pending" (escritura única en el alta) → kyb_locked=true
    assert org["kyb_status"] == "pending"
    assert org["kyb_status"] not in ("approved",)   # kyb_locked = True
    assert org["kyb_case_id"] == case["case_id"]

    # email con idempotency_key (event, case, recipient, disc del token)
    mail = db["outbound_emails"].find_one({"to": email})
    assert mail["subject"] == "Activá tu cuenta de Prosper"
    assert mail["idempotency_key"].startswith(
        f"kyb.activation:{case['case_id']}:{email}:")
    act_token = _extract_activation_token(db, email)
    # hash en reposo: el claro no está en Mongo
    assert db["kyb_signup_tokens"].find_one({"token_hash": act_token}) is None

    # activación → sesión
    r = requests.post(f"{TEST_API}/kyb/signup/activate",
                      json={"activation_token": act_token}, timeout=10)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["portal"] == "/client" and out["case_status"] == "draft"
    assert "prosper_session" in r.cookies
    user = db["users"].find_one({"email": email})
    assert user["role"] == "client_admin"
    assert user["org_id"] == case["org_id"]

    # ---- un solo uso: el segundo intento falla ----
    r2 = requests.post(f"{TEST_API}/kyb/signup/activate",
                       json={"activation_token": act_token}, timeout=10)
    assert r2.status_code == 401

    # ---- Fase 2.1: /client/me legacy NO ve el caso del modelo nuevo ----
    me = requests.get(f"{TEST_API}/client/me",
                      cookies={"prosper_session": r.cookies["prosper_session"]},
                      timeout=10)
    assert me.status_code == 200, me.text
    onboarding = me.json().get("onboarding") or {}
    # Sin el filtro, el caso draft nuevo aparecía como "applied"/40%.
    assert onboarding.get("stage") == "not_started", onboarding


# ---------------------------------------------------------------------------
# Idempotencia por email + reingreso con nombre distinto
# ---------------------------------------------------------------------------
def test_start_is_idempotent_by_email_and_reentry_audited(server):
    db = server
    email = "founder@empresa-idem.io"
    _start(email, "Nombre Original SA")
    n_cases = db["kyb_cases"].count_documents({"applicant_email": email})
    n_orgs = db["organizations"].count_documents(
        {"legal_name": "Nombre Original SA"})

    body2 = _start(email, "Nombre Distinto SRL")
    assert set(body2) == {"ok", "signup_token", "message"}
    # No duplica caso ni org; no pisa el nombre original.
    assert db["kyb_cases"].count_documents(
        {"applicant_email": email}) == n_cases == 1
    assert db["organizations"].count_documents(
        {"legal_name": "Nombre Original SA"}) == n_orgs == 1
    case = db["kyb_cases"].find_one({"applicant_email": email})
    assert case["company_name_declared"] == "Nombre Original SA"
    audit = db["audit_logs"].find_one(
        {"action": "kyb.signup.reentry_name_mismatch",
         "resource_id": case["case_id"]})
    assert audit is not None
    assert audit["metadata"]["original"] == "Nombre Original SA"
    assert audit["metadata"]["attempted"] == "Nombre Distinto SRL"
    # El signup_token nuevo escribe sobre el MISMO caso.
    r = requests.post(f"{TEST_API}/kyb/signup/contact", json={
        "signup_token": body2["signup_token"], "full_name": "Reingreso Ok",
        "phone": {"country_code": "+54", "number": "1144444444"}},
        timeout=10)
    assert r.status_code == 200
    assert db["kyb_cases"].find_one(
        {"applicant_email": email})["applicant_name"] == "Reingreso Ok"


# ---------------------------------------------------------------------------
# Anti-enumeración: aprobado / rechazado / inexistente → 200 idéntico,
# sin email, con registro interno del sondeo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_probe_resolved_case_same_200_no_email(server, status):
    db = server
    email = f"probe-{status}@empresa-resuelta.io"
    db["kyb_cases"].insert_one({
        "case_id": f"kyb_probe_{status}", "org_id": None, "status": status,
        "applicant_email": email, "is_deleted": False,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00"})
    mails_before = db["outbound_emails"].count_documents({})

    body = _start(email, "Sonda SA")
    assert set(body) == {"ok", "signup_token", "message"}
    assert len(body["signup_token"]) > 20        # señuelo con mismo shape

    # Sin correo, sin caso nuevo, con registro del sondeo.
    assert db["outbound_emails"].count_documents({}) == mails_before
    assert db["kyb_cases"].count_documents(
        {"applicant_email": email}) == 1
    probe = db["audit_logs"].find_one(
        {"action": "kyb.signup.probe_attempt", "metadata.email": email})
    assert probe is not None
    assert probe["metadata"]["reason"] == f"case_{status}"

    # El señuelo no habilita escritura: contact falla como token vencido.
    r = requests.post(f"{TEST_API}/kyb/signup/contact", json={
        "signup_token": body["signup_token"], "full_name": "X Y",
        "phone": {"country_code": "+54", "number": "1122222222"}},
        timeout=10)
    assert r.status_code == 401

    # resend sobre el mismo email: 200 idéntico, sin correo.
    r = requests.post(f"{TEST_API}/kyb/signup/resend",
                      json={"email": email}, timeout=10)
    assert r.status_code == 200
    assert set(r.json()) == {"ok", "message"}
    assert db["outbound_emails"].count_documents({}) == mails_before


def test_probe_unknown_email_resend_same_200_no_email(server):
    db = server
    mails_before = db["outbound_emails"].count_documents({})
    r = requests.post(f"{TEST_API}/kyb/signup/resend",
                      json={"email": "nadie@inexistente.io"}, timeout=10)
    assert r.status_code == 200
    assert set(r.json()) == {"ok", "message"}
    assert db["outbound_emails"].count_documents({}) == mails_before


def test_probe_timing_floor(server):
    """El sondeo (menos trabajo interno) respeta el piso de tiempo."""
    t0 = time.monotonic()
    requests.post(f"{TEST_API}/kyb/signup/resend",
                  json={"email": "timing@inexistente.io"}, timeout=10)
    assert (time.monotonic() - t0) >= 0.30


# ---------------------------------------------------------------------------
# signup_token: vencido → error claro y accionable; solo su caso
# ---------------------------------------------------------------------------
def test_signup_token_expired_returns_actionable_error(server):
    db = server
    email = "vencido@empresa-ttl.io"
    _start(email)
    case = db["kyb_cases"].find_one({"applicant_email": email})
    # Forzamos el vencimiento del token vivo.
    from datetime import datetime, timedelta, timezone
    db["kyb_signup_tokens"].update_many(
        {"case_id": case["case_id"], "kind": "signup"},
        {"$set": {"expires_at": datetime.now(timezone.utc)
                  - timedelta(minutes=1)}})
    # El claro no lo tenemos (hasheado) — probamos con cualquier valor del
    # mismo shape: debe dar el MISMO 401 accionable.
    r = requests.post(f"{TEST_API}/kyb/signup/contact", json={
        "signup_token": "a" * 43, "full_name": "X Y",
        "phone": {"country_code": "+54", "number": "1133333333"}},
        timeout=10)
    assert r.status_code == 401
    assert "/kyb/signup" in r.json()["detail"]
    # El caso persiste — se retoma con un start nuevo.
    assert db["kyb_cases"].find_one(
        {"applicant_email": email}) is not None


# ---------------------------------------------------------------------------
# Rate limit horario (unitario): 3/h por clave, honra el disable flag
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Fase 2.1: la bandeja legacy NO puede ver ni tocar un caso del modelo
# nuevo por ninguno de los cuatro caminos (queue/detail/checklist/decision)
# ---------------------------------------------------------------------------
def test_legacy_tray_cannot_touch_new_model_case(server):
    db = server
    email = "tray-guard@empresa-nueva.io"
    _start(email, "Guard SA")
    case = db["kyb_cases"].find_one({"applicant_email": email})
    cid = case["case_id"]

    s = requests.Session()
    r = s.get(f"{TEST_API}/auth/dev-login",
              params={"email": "admin@prosper.foundation"},
              timeout=10, allow_redirects=False)
    assert "prosper_session" in s.cookies, r.text

    # F6: la bandeja legacy está RETIRADA con el flag encendido — los GET
    # redirigen (308) al portal nuevo y las mutaciones devuelven 410. El
    # caso nuevo queda intacto: ninguna escritura legacy es posible.
    r = s.get(f"{TEST_API}/admin/compliance/kyb/queue", timeout=10,
              allow_redirects=False)
    assert r.status_code == 308
    assert r.headers["Location"].endswith("/admin/compliance/kyb/cases")

    r = s.get(f"{TEST_API}/admin/compliance/kyb/{cid}", timeout=10,
              allow_redirects=False)
    assert r.status_code == 308
    assert r.headers["Location"].endswith(f"/cases/{cid}")

    r = s.patch(f"{TEST_API}/admin/compliance/kyb/{cid}/checklist",
                json={"key": "certificate", "checked": True}, timeout=10)
    assert r.status_code == 410

    r = s.post(f"{TEST_API}/admin/compliance/kyb/{cid}/decision",
               json={"action": "approve",
                     "reason": "intento de aprobar desde la bandeja legacy"},
               timeout=10)
    assert r.status_code == 410
    after = db["kyb_cases"].find_one({"case_id": cid})
    assert after["status"] == "draft"
    assert "decision" not in after and "decided_by" not in after


def test_hourly_limit_unit(monkeypatch):
    monkeypatch.delenv("PROSPER_DISABLE_RATELIMIT", raising=False)
    from fastapi import HTTPException
    from kyb.routes_signup import _hour_buckets, hourly_limit
    _hour_buckets.clear()
    for _ in range(3):
        hourly_limit("unit-test", "mail@x.io", 3)
    with pytest.raises(HTTPException) as e:
        hourly_limit("unit-test", "mail@x.io", 3)
    assert e.value.status_code == 429
    # Otra clave (otro email / otra IP) no se ve afectada.
    hourly_limit("unit-test", "otra@x.io", 3)
    # Con el disable flag, no limita.
    monkeypatch.setenv("PROSPER_DISABLE_RATELIMIT", "1")
    for _ in range(10):
        hourly_limit("unit-test", "mail@x.io", 3)
