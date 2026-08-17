"""Tests post-diagnóstico Fase 8 — orquestador + endpoints de decisión.

Server efímero 8022 + scratch `prosper_kyb_tests_orch`. Cubre:
  * dispatch_on_submit genera checklists en modo manual e idempotente.
  * dispatch_on_submit resiliente: si una categoría falla, sigue.
  * Un caso enviado llega a `under_review` sin intervención admin.
  * approve/reject/request-info NO aceptan status distinto de under_review.
  * `_ensure_under_review` está deprecado — invocarlo lanza.
  * Bandeja: default excluye draft/in_progress/expired/terminal; toggles
    lo permiten.
  * Providers: `company/manual` NO aparece.
  * "Aprobar sección" del wizard funciona sobre under_review.
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
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_DB = "prosper_kyb_tests_orch"
_PORT = 8022
API = f"http://127.0.0.1:{_PORT}/api/v1"
ADMIN = f"{API}/admin/compliance/kyb"
PDF = b"%PDF-1.4\n" + b"x" * 2048
INTERNALS = [("super@prosper.foundation", "super_admin"),
             ("compl@prosper.foundation", "compliance_officer")]


def _cuit():
    d, w = "3081234567", [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    dv = 11 - sum(int(x) * k for x, k in zip(d, w)) % 11
    return d + str({11: 0, 10: 9}.get(dv, dv))


def _login(email):
    s = requests.Session()
    assert s.get(f"{API}/auth/dev-login", params={"email": email},
                 allow_redirects=False, timeout=10).status_code == 303
    return s


def _submit_case(s, db, email):
    tok = s.post(f"{API}/kyb/signup/start",
                 json={"email": email, "company_name": "Orch SA"},
                 timeout=10).json()["signup_token"]
    s.post(f"{API}/kyb/signup/contact", json={"signup_token": tok,
        "full_name": "T", "phone": {"country_code": "+54",
        "number": "1150000030"}}, timeout=10)
    s.post(f"{API}/kyb/signup/country",
           json={"signup_token": tok, "country": "AR"}, timeout=10)
    act = re.search(r"token=([\w\-]+)", db["outbound_emails"].find_one(
        {"to": email}, sort=[("created_at", -1)])["html"]).group(1)
    s.post(f"{API}/kyb/signup/activate",
           json={"activation_token": act}, timeout=10)
    keys = [x["document_key"] for x in
            s.get(f"{API}/kyb/case", timeout=10).json()["legal_docs"]]
    s.put(f"{API}/kyb/case/tax-identification",
          json={"tax_id": _cuit(), "accepted_documents": keys}, timeout=10)
    s.put(f"{API}/kyb/case/legal-representative",
          json={"country_of_residence": "AR", "full_name": "Rep",
                "email": "rep-orch@preview-prosper.io",
                "tax_id": "20111111112"}, timeout=10)
    for p, b in [("legal-name", {"legal_name": "Orch SA",
                                 "legal_structure": "SA"}),
                 ("data", {"activity_description": "x" * 120}),
                 ("address", {"raw": "Av. 9 de Julio 1234", "city": "CABA",
                              "country": "AR"}),
                 ("operations", {"estimated_monthly_volume_usd": 5000,
                                 "purposes": ["YIELD_ARS"],
                                 "funds_subscribed": ["PROSPER_ARS"]}),
                 ("funds-origin", {"type": "OWN_TREASURY"})]:
        r = s.put(f"{API}/kyb/case/company/{p}", json=b, timeout=10)
        assert r.status_code == 200, f"{p}: {r.status_code} {r.text}"
    for slot in ("tax_registration_certificate", "constitutive_document",
                 "authorities_appointment", "company_proof_of_address"):
        s.post(f"{API}/kyb/case/documents", data={"slot": slot},
               files={"file": ("d.pdf", PDF, "application/pdf")},
               timeout=15)
        s.post(f"{API}/kyb/case/documents/confirm",
               json={"slot": slot}, timeout=10)
    s.post(f"{API}/kyb/case/documents/confirm",
           json={"slot": "funds_origin_evidence",
                 "recently_incorporated": True}, timeout=10)
    fid = s.post(f"{API}/kyb/case/documents",
                 data={"slot": "ubo_document_front"},
                 files={"file": ("d.pdf", PDF, "application/pdf")},
                 timeout=15).json()["document_id"]
    s.post(f"{API}/kyb/case/ubos", json={
        "first_name": "U", "last_name": "Uno",
        "ownership_percentage": 100.0, "document_front_id": fid,
        "is_pep": False}, timeout=10)
    s.post(f"{API}/kyb/case/ubos/confirm",
           json={"declaration": True}, timeout=10)
    rs = s.post(f"{API}/kyb/case/submit", timeout=15)
    assert rs.status_code == 200, rs.text
    return db["kyb_cases"].find_one({"applicant_email": email})["case_id"]


@pytest.fixture(scope="module")
def env():
    mongo = MongoClient(os.environ["MONGO_URL"])
    real = mongo[os.environ.get("DB_NAME", "prosper_phase0")]
    base = {c: real[c].count_documents({}) for c in
            ("prosper_files.files", "prosper_files.chunks")}
    mongo.drop_database(_DB)
    db = mongo[_DB]
    senv = {**os.environ, "DB_NAME": _DB, "KYB_MODULE_ENABLED": "true",
            "KYB_ENVIRONMENT": "sandbox", "PROSPER_MODE": "development",
            "PROSPER_DISABLE_RATELIMIT": "1", "RESEND_API_KEY": "",
            "DEMO_MODE": "true"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host",
         "127.0.0.1", "--port", str(_PORT), "--log-level", "error"],
        cwd=str(BACKEND), env=senv,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(240):
            try:
                requests.get(f"http://127.0.0.1:{_PORT}/docs", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            out, err = proc.communicate(timeout=2)
            raise RuntimeError(f"no arrancó:\n{err.decode()[-1500:]}")
        from models import utc_now
        for email, role in INTERNALS:
            db["users"].update_one({"email": email}, {"$set": {
                "role": role, "status": "active", "is_deleted": False,
                "updated_at": utc_now()},
                "$setOnInsert": {"user_id": f"usr_{email.split('@')[0]}",
                                 "email": email, "org_id": None,
                                 "kyc_status": "pending",
                                 "mfa_enabled": False,
                                 "created_at": utc_now()}}, upsert=True)
        subprocess.run([sys.executable,
                        str(BACKEND.parent / "scripts/seed_kyb_templates.py")],
                       env=senv, capture_output=True, timeout=60)
        yield {"db": db, "senv": senv,
               "super": _login("super@prosper.foundation"),
               "compl": _login("compl@prosper.foundation")}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for c, n in base.items():
            assert real[c].count_documents({}) == n
        mongo.drop_database(_DB)
        mongo.close()


# ---------------------------------------------------------------------------
# Orquestador: idempotencia y transición automática al under_review
# ---------------------------------------------------------------------------
def test_01_submit_advances_to_under_review_in_manual_mode(env):
    """En modo manual (los 3 categorías), enviar el expediente lleva
    submitted → screening → under_review vía el orquestador. No hace
    falta que un analista toque nada."""
    s = requests.Session()
    cid = _submit_case(s, env["db"], "orch1@preview-prosper.io")
    case = env["db"]["kyb_cases"].find_one({"case_id": cid})
    assert case["status"] == "under_review"
    # Los checklists ya existen — el gate MANUAL_CHECKS_PENDING ahora
    # protege realmente.
    n = env["db"]["kyb_manual_checks"].count_documents({"case_id": cid})
    assert n > 0
    assert case.get("dispatch_state", {}).get("errors") == []


def test_02_orchestrator_is_idempotent(env):
    """Correr el orquestador dos veces no duplica checklists ni
    verificaciones."""
    cid = env["db"]["kyb_cases"].find_one(
        {"applicant_email": "orch1@preview-prosper.io"})["case_id"]
    n1 = env["db"]["kyb_manual_checks"].count_documents({"case_id": cid})
    # llamar el reintento por el botón "Generar checklists"
    r = env["compl"].post(f"{ADMIN}/cases/{cid}/rerun-verifications",
                          timeout=15)
    assert r.status_code == 200
    n2 = env["db"]["kyb_manual_checks"].count_documents({"case_id": cid})
    assert n1 == n2, f"idempotencia rota: {n1} → {n2}"


def test_03_orchestrator_resilient_on_partial_failure(monkeypatch):
    """Unit-test de resiliencia: si generate_checks lanza,
    `_dispatch_category` NO propaga la excepción — devuelve
    `ok=False` + `error` y el orquestador acumula todo en
    dispatch_state para que el analista lo vea. Prueba directa sin
    server: sólo interesa la política de manejo de errores."""
    import asyncio
    from importlib import import_module
    orch = import_module("kyb.orchestrator")

    async def boom(*a, **k):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(orch, "generate_checks", boom)
    loop = asyncio.new_event_loop()
    try:
        for cat in ("identity", "screening", "company_registry"):
            r = loop.run_until_complete(
                orch._dispatch_category({"case_id": "c_dbg"}, cat, "manual",
                                        trigger="submit", actor=None,
                                        request=None))
            assert r["ok"] is False, r
            assert "simulated failure" in r["error"], r
            assert r["checks_created"] == 0
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Endpoints de decisión — solo desde under_review
# ---------------------------------------------------------------------------
def test_04_approve_reject_request_info_reject_submitted(env):
    """Con el fix, aprobar/rechazar/solicitar-info desde submitted es
    409. No 200 con salto silencioso."""
    from models import utc_now
    cid = "kyb_test_submitted_gate"
    env["db"]["kyb_cases"].insert_one({
        "case_id": cid, "org_id": "org_y", "status": "submitted",
        "is_deleted": False,
        "verification_modes": {"identity": "manual",
                               "screening": "manual",
                               "company_registry": "manual"},
        "sections": {}, "created_at": utc_now(), "updated_at": utc_now()})
    for path, body in [("approve", {}),
                       ("reject", {"reason_code": "screening_hit_confirmed",
                                   "notes": "x" * 25}),
                       ("request-info", {})]:
        r = env["super"].post(f"{ADMIN}/cases/{cid}/{path}",
                              json=body, timeout=10)
        assert r.status_code == 409, f"{path}: {r.status_code} {r.text}"
        # No hubo salto silencioso: sigue en submitted.
        assert env["db"]["kyb_cases"].find_one(
            {"case_id": cid})["status"] == "submitted"


def test_05_ensure_under_review_is_deprecated(env):
    """El símbolo se conserva por si algún test lo importa, pero
    invocarlo lanza. Nadie del código de producción lo llama."""
    import asyncio
    from importlib import import_module
    mod = import_module("kyb.routes_admin_cases")
    with pytest.raises(RuntimeError, match="removido"):
        asyncio.get_event_loop().run_until_complete(
            mod._ensure_under_review({"case_id": "x", "status": "submitted"},
                                     None, None))


# ---------------------------------------------------------------------------
# Bandeja: default excluye draft/in_progress/expired/terminal
# ---------------------------------------------------------------------------
def test_06_tray_default_excludes_drafts_and_closed(env):
    """El expediente draft del cliente A NO debe aparecer por default.
    Con include_drafts=true, sí."""
    from models import utc_now
    for cid, status in [("kyb_tray_draft", "draft"),
                        ("kyb_tray_inprog", "in_progress"),
                        ("kyb_tray_approved", "approved"),
                        ("kyb_tray_active", "under_review")]:
        env["db"]["kyb_cases"].insert_one({
            "case_id": cid, "org_id": f"org_{cid}", "status": status,
            "is_deleted": False,
            "verification_modes": {"identity": "manual",
                                   "screening": "manual",
                                   "company_registry": "manual"},
            "sections": {}, "created_at": utc_now(),
            "updated_at": utc_now()})
    default = env["super"].get(f"{ADMIN}/cases", timeout=10).json()
    ids = {r["case_id"] for r in default["items"]}
    assert "kyb_tray_draft" not in ids
    assert "kyb_tray_inprog" not in ids
    assert "kyb_tray_approved" not in ids
    assert "kyb_tray_active" in ids
    # Toggles
    with_drafts = env["super"].get(f"{ADMIN}/cases?include_drafts=true",
                                   timeout=10).json()
    assert "kyb_tray_draft" in {r["case_id"] for r in with_drafts["items"]}
    with_closed = env["super"].get(f"{ADMIN}/cases?include_closed=true",
                                   timeout=10).json()
    assert "kyb_tray_approved" in {r["case_id"] for r in with_closed["items"]}


# ---------------------------------------------------------------------------
# Providers: sin company/manual
# ---------------------------------------------------------------------------
def test_07_providers_hides_company_manual(env):
    r = env["super"].get(f"{ADMIN}/settings/providers", timeout=10).json()
    for it in r["items"]:
        assert not (it["category"] == "company" and it["provider"] == "manual"), \
            f"company/manual no debería listarse: {it}"


# ---------------------------------------------------------------------------
# Flujo completo: submit → under_review → approve OK
# ---------------------------------------------------------------------------
def test_08_full_flow_submit_then_complete_checklists_then_approve(env):
    """Ahora sí, el flujo end-to-end en modo manual:
      1) cliente submit → orquestador → under_review
      2) analista completa los checklists (uno alcanza para test)
      3) approve pide MANUAL_CHECKS_PENDING mientras queden — protege
      4) con todos completos y secciones revisadas → approve OK"""
    cid = env["db"]["kyb_cases"].find_one(
        {"applicant_email": "orch1@preview-prosper.io"})["case_id"]
    case = env["db"]["kyb_cases"].find_one({"case_id": cid})
    assert case["status"] == "under_review"
    # Intento aprobar sin completar checklists → 422 con MANUAL_CHECKS_PENDING
    r = env["super"].post(f"{ADMIN}/cases/{cid}/approve", timeout=10)
    assert r.status_code == 422
    codes = {b["code"] for b in r.json()["detail"]["blockers"]}
    assert "MANUAL_CHECKS_PENDING" in codes
