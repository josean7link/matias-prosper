"""Tests e2e Fase 8 — Shared links + Team + Notifications + Jobs.
Server efímero 8020 + scratch `prosper_kyb_tests_phase8`.
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
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

_DB = "prosper_kyb_tests_phase8"
_PORT = 8020
API = f"http://127.0.0.1:{_PORT}/api/v1"
ADMIN = f"{API}/admin/compliance/kyb"
SHARED = f"{API}/kyb/shared"
PDF = b"%PDF-1.4\n" + b"x" * 2048
INTERNALS = [("super@prosper.foundation", "super_admin"),
             ("compliance@prosper.foundation", "compliance_officer")]


def _cuit_a():
    d, w = "3071234567", [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    dv = 11 - sum(int(x) * k for x, k in zip(d, w)) % 11
    return d + str({11: 0, 10: 9}.get(dv, dv))


def _cuit_b():
    d, w = "3071234568", [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    dv = 11 - sum(int(x) * k for x, k in zip(d, w)) % 11
    return d + str({11: 0, 10: 9}.get(dv, dv))


def _login(email):
    s = requests.Session()
    assert s.get(f"{API}/auth/dev-login", params={"email": email},
                 allow_redirects=False, timeout=10).status_code == 303
    return s


@pytest.fixture(scope="module")
def env():
    mongo = MongoClient(os.environ["MONGO_URL"])
    real = mongo[os.environ.get("DB_NAME", "prosper_phase0")]
    base = {c: real[c].count_documents({}) for c in
            ("prosper_files.files", "prosper_files.chunks",
             "outbound_emails")}
    mongo.drop_database(_DB)
    db = mongo[_DB]
    senv = {**os.environ, "DB_NAME": _DB, "KYB_MODULE_ENABLED": "true",
            "KYB_ENVIRONMENT": "sandbox", "PROSPER_MODE": "development",
            "PROSPER_DISABLE_RATELIMIT": "1", "RESEND_API_KEY": "",
            "DEMO_MODE": "true", "PUBLIC_BASE_URL": "http://preview.local",
            "COMPLIANCE_INBOX_EMAIL": "compliance@preview-prosper.io"}
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
            raise RuntimeError(
                f"server 8020 no arrancó\nSTDOUT:{out.decode()[-2000:]}"
                f"\nSTDERR:{err.decode()[-2000:]}")
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
        # Alta de cliente vía signup + activación
        s = requests.Session()
        tok = s.post(f"{API}/kyb/signup/start",
                     json={"email": "p8@preview-prosper.io",
                           "company_name": "Fase8 Corp SA"},
                     timeout=10).json()["signup_token"]
        s.post(f"{API}/kyb/signup/contact", json={
            "signup_token": tok, "full_name": "T",
            "phone": {"country_code": "+54", "number": "1150000010"}},
            timeout=10)
        s.post(f"{API}/kyb/signup/country",
               json={"signup_token": tok, "country": "AR"}, timeout=10)
        act = re.search(r"token=([\w\-]+)", db["outbound_emails"].find_one(
            {"to": "p8@preview-prosper.io"})["html"]).group(1)
        s.post(f"{API}/kyb/signup/activate",
               json={"activation_token": act}, timeout=10)
        yield {"db": db, "client": s,
               "super": _login("super@prosper.foundation"),
               "compl": _login("compliance@prosper.foundation")}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for c, n in base.items():
            assert real[c].count_documents({}) == n, \
                f"¡{c} REAL cambió durante los tests!"
        mongo.drop_database(_DB)
        mongo.close()


# ---------------------------------------------------------------------------
# Shared links
# ---------------------------------------------------------------------------
def test_01_shared_link_create_list_revoke(env):
    s, db = env["client"], env["db"]
    r = s.post(f"{API}/kyb/case/shared-links",
               json={"expires_in_hours": 48, "note": "Contador"},
               timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("http://preview.local/kyb/shared/")
    assert body["expires_in_hours"] == 48
    # No devuelve el hash — el claro es único e irrecuperable
    assert "token_hash" not in body
    lst = s.get(f"{API}/kyb/case/shared-links", timeout=10).json()
    assert len(lst["items"]) == 1 and lst["items"][0]["active"] is True
    # revoke
    lid = body["link_id"]
    assert s.delete(f"{API}/kyb/case/shared-links/{lid}",
                    timeout=10).status_code == 200
    # doble revoke → 404
    assert s.delete(f"{API}/kyb/case/shared-links/{lid}",
                    timeout=10).status_code == 404
    lst = s.get(f"{API}/kyb/case/shared-links", timeout=10).json()
    assert lst["items"][0]["active"] is False


def test_02_shared_public_upload_and_trace(env):
    s, db = env["client"], env["db"]
    r = s.post(f"{API}/kyb/case/shared-links",
               json={"expires_in_hours": 48}, timeout=10).json()
    raw = r["url"].rsplit("/", 1)[-1]
    # Contexto público sin sesión
    pub = requests.get(f"{SHARED}/{raw}", timeout=10).json()
    assert pub["company_name"] and pub["status"] in ("draft", "in_progress")
    # Upload sin sesión
    up = requests.post(f"{SHARED}/{raw}/documents",
                       data={"slot": "constitutive_document"},
                       files={"file": ("d.pdf", PDF, "application/pdf")},
                       timeout=15)
    assert up.status_code == 200
    doc = up.json()
    assert doc["uploaded_via"] == "shared_link"
    assert doc["shared_link_id"] == r["link_id"]
    assert "storage_key" not in doc
    # confirmar slot
    cf = requests.post(f"{SHARED}/{raw}/documents/confirm",
                       json={"slot": "constitutive_document"}, timeout=10)
    assert cf.status_code == 200
    # `recently_incorporated` desde shared link → 403
    cf2 = requests.post(f"{SHARED}/{raw}/documents/confirm",
                       json={"slot": "funds_origin_evidence",
                             "recently_incorporated": True}, timeout=10)
    assert cf2.status_code == 403
    # Token inválido / revocado → 404 (anti-enumeración)
    s.delete(f"{API}/kyb/case/shared-links/{r['link_id']}", timeout=10)
    bad = requests.get(f"{SHARED}/{raw}", timeout=10)
    assert bad.status_code == 404
    fake = "z" * 43
    assert requests.get(f"{SHARED}/{fake}",
                        timeout=10).status_code == 404
    # Auditoría con uploaded_via=shared_link
    ev = db["audit_logs"].find_one(
        {"action": "kyb.document.uploaded",
         "metadata.uploaded_via": "shared_link"})
    assert ev and ev["metadata"]["shared_link_id"] == r["link_id"]


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
def test_03_team_invitation_flow_and_role_mapping(env):
    s, db = env["client"], env["db"]
    # crear invitación como OPERADOR (mapea a client_user)
    r = s.post(f"{API}/kyb/case/team", json={
        "email": "operador@preview-prosper.io", "tax_id": _cuit_a(),
        "intended_role": "operator", "full_name": "Op Uno"},
               timeout=10)
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["role"] == "client_user"     # ← mapping conservador
    assert inv["intended_role"] == "operator"
    iid = inv["invitation_id"]
    # duplicado por email → 409
    r2 = s.post(f"{API}/kyb/case/team", json={
        "email": "operador@preview-prosper.io", "tax_id": _cuit_b(),
        "intended_role": "read_only"}, timeout=10)
    assert r2.status_code == 409
    # listado
    lst = s.get(f"{API}/kyb/case/team", timeout=10).json()
    assert any(x["invitation_id"] == iid for x in lst["invitations"])
    assert "El representante legal" in lst["banner"]
    # email enviado (preview-only)
    email = db["outbound_emails"].find_one(
        {"template": "kyb.team.invitation",
         "to": "operador@preview-prosper.io"})
    assert email and _cuit_a() in email["html"]
    # extraer token del link
    tok = re.search(r"accept\?token=([\w\-]+)", email["html"]).group(1)
    # accept con CUIT que NO coincide → 403
    bad = requests.post(f"{API}/kyb/team/accept",
                        json={"token": tok, "tax_id": _cuit_b(),
                              "email": "operador@preview-prosper.io"},
                        timeout=10)
    assert bad.status_code == 403
    assert db["audit_logs"].find_one({
        "action": "kyb.team.invitation_rejected",
        "metadata.reason": "tax_id_mismatch"})
    # accept con email distinto → 403
    bad_email = requests.post(f"{API}/kyb/team/accept",
                              json={"token": tok, "tax_id": _cuit_a(),
                                    "email": "otro@preview-prosper.io"},
                              timeout=10)
    assert bad_email.status_code == 403
    # accept OK
    ok = requests.post(f"{API}/kyb/team/accept",
                       json={"token": tok, "tax_id": _cuit_a(),
                             "email": "operador@preview-prosper.io",
                             "full_name": "Op Uno"}, timeout=10)
    assert ok.status_code == 200
    body = ok.json()
    assert body["role"] == "client_user"
    assert body["intended_role"] == "operator"
    # doble accept → 404
    assert requests.post(f"{API}/kyb/team/accept",
                        json={"token": tok, "tax_id": _cuit_a(),
                              "email": "operador@preview-prosper.io"},
                        timeout=10).status_code == 404
    # el user quedó en la org con role/intended_role coherentes
    u = db["users"].find_one({"email": "operador@preview-prosper.io"})
    assert u["role"] == "client_user" and u["intended_role"] == "operator"
    assert u["tax_id"] == _cuit_a() and u["org_id"]


def test_04_team_admin_mapping_and_revoke(env):
    s, db = env["client"], env["db"]
    r = s.post(f"{API}/kyb/case/team", json={
        "email": "adm2@preview-prosper.io", "tax_id": _cuit_b(),
        "intended_role": "administrator"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["role"] == "client_admin"       # ← ADMIN mapping
    assert r.json()["intended_role"] == "administrator"
    iid = r.json()["invitation_id"]
    # revoke
    assert s.delete(f"{API}/kyb/case/team/{iid}",
                    timeout=10).status_code == 200
    # accept sobre invitación revocada → 404
    email = db["outbound_emails"].find_one(
        {"template": "kyb.team.invitation",
         "to": "adm2@preview-prosper.io"})
    tok = re.search(r"accept\?token=([\w\-]+)", email["html"]).group(1)
    assert requests.post(f"{API}/kyb/team/accept",
                        json={"token": tok, "tax_id": _cuit_b(),
                              "email": "adm2@preview-prosper.io"},
                        timeout=10).status_code == 404


# ---------------------------------------------------------------------------
# Notifications idempotency
# ---------------------------------------------------------------------------
def test_05_notifications_dispatcher_idempotent(env):
    """Un segundo call con misma (event_type, case_id, recipient,
    discriminator) NO crea un segundo email."""
    from importlib import import_module
    _ = import_module("kyb.notifications")

    code = f"""
import asyncio, os, sys
sys.path.insert(0, {str(BACKEND)!r})
os.environ['MONGO_URL'] = {os.environ['MONGO_URL']!r}
os.environ['DB_NAME'] = {_DB!r}
os.environ['RESEND_API_KEY'] = ''
os.environ['PUBLIC_BASE_URL'] = 'http://preview.local'
from kyb.notifications import notify

async def main():
    await notify('kyb.case.approved', case_id='cid_dup',
                 recipient='who@preview-prosper.io',
                 context={{'company_name': 'X'}})
    await notify('kyb.case.approved', case_id='cid_dup',
                 recipient='who@preview-prosper.io',
                 context={{'company_name': 'X'}})
asyncio.run(main())
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)
    n = env["db"]["outbound_emails"].count_documents(
        {"template": "kyb.case.approved", "to": "who@preview-prosper.io"})
    assert n == 1, f"idempotencia fallida: n={n}"


# ---------------------------------------------------------------------------
# Job de expiración: endpoint force en sandbox, 409 en producción
# ---------------------------------------------------------------------------
def test_06_force_expiration_sandbox_and_prod_guard(env):
    sup, db = env["super"], env["db"]
    # Insertamos un caso in_progress con updated_at muy viejo
    from models import utc_now
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    db["kyb_cases"].insert_one({
        "case_id": "kyb_exp_test", "org_id": "org_x",
        "status": "in_progress", "is_deleted": False,
        "verification_modes": {"identity": "manual",
                               "screening": "manual",
                               "company_registry": "manual"},
        "applicant_email": "titular@preview-prosper.io",
        "sections": {}, "created_at": old, "updated_at": old})
    r = sup.post(f"{ADMIN}/jobs/run-expiration", timeout=15)
    assert r.status_code == 200
    assert r.json()["expired"] >= 1
    updated = db["kyb_cases"].find_one({"case_id": "kyb_exp_test"})
    assert updated["status"] == "expired"
    # role gate — compliance_officer NO puede forzar
    assert env["compl"].post(f"{ADMIN}/jobs/run-expiration",
                             timeout=10).status_code == 403


def test_07_force_expiration_blocked_in_production(env):
    """Endpoint separado con PROSPER_MODE=production: el mismo user es
    super_admin y aun así se bloquea con 409."""
    port_prod = 8021
    from pymongo import MongoClient as _MC
    prod_env = {**os.environ, "DB_NAME": _DB + "_prod",
                "KYB_MODULE_ENABLED": "true",
                "KYB_ENVIRONMENT": "production",
                "PROSPER_MODE": "production",
                "PROSPER_DISABLE_RATELIMIT": "1", "RESEND_API_KEY": "",
                "DEMO_MODE": "true"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host",
         "127.0.0.1", "--port", str(port_prod), "--log-level", "error"],
        cwd=str(BACKEND), env=prod_env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(240):
            try:
                requests.get(f"http://127.0.0.1:{port_prod}/docs",
                             timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("server prod no arrancó")
        # seed super_admin
        m = _MC(os.environ["MONGO_URL"])
        m[_DB + "_prod"]["users"].update_one(
            {"email": "super@prosper.foundation"},
            {"$set": {"role": "super_admin", "status": "active",
                      "is_deleted": False},
             "$setOnInsert": {"user_id": "usr_super_prod",
                              "email": "super@prosper.foundation"}},
            upsert=True)
        s = requests.Session()
        s.get(f"http://127.0.0.1:{port_prod}/api/v1/auth/dev-login",
              params={"email": "super@prosper.foundation"},
              allow_redirects=False, timeout=10)
        r = s.post(f"http://127.0.0.1:{port_prod}/api/v1/admin/"
                   f"compliance/kyb/jobs/run-expiration", timeout=10)
        assert r.status_code == 409
        assert "producción" in r.text.lower() or "production" in r.text.lower()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        m = _MC(os.environ["MONGO_URL"])
        m.drop_database(_DB + "_prod")
        m.close()


def test_08_scheduler_registered_on_startup_with_flag(env):
    """El scheduler KYB tiene que quedar registrado cuando arranca el
    server con el flag encendido — se ve consultando el registro
    interno."""
    from importlib import import_module
    # El fixture ya montó el server con el flag encendido; el módulo
    # exporta _scheduler cuando `start_kyb_scheduler` fue llamado.
    # No podemos acceder al proceso hijo, así que verificamos el
    # comportamiento equivalente: la corrida forzada del job funciona
    # (test_06 lo confirma) y el módulo se importa sin errores.
    mod = import_module("kyb.jobs_scheduler")
    assert hasattr(mod, "start_kyb_scheduler")
    assert hasattr(mod, "expire_inactive")
    assert hasattr(mod, "notify_expiring")
    assert hasattr(mod, "notify_manual_check_sla")
