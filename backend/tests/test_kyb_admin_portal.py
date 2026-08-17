"""Tests e2e Fase 6 — Portal Admin KYB (bandeja, revisión, decisión).
Server efímero 8018 + scratch `prosper_kyb_tests_admin`.
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

_DB = "prosper_kyb_tests_admin"
_PORT = 8018
API = f"http://127.0.0.1:{_PORT}/api/v1"
ADMIN = f"{API}/admin/compliance/kyb"
PDF = b"%PDF-1.4\n" + b"x" * 2048
SLOTS = ["tax_registration_certificate", "constitutive_document",
         "funds_origin_evidence", "authorities_appointment",
         "company_proof_of_address"]
INTERNALS = [("super@prosper.foundation", "super_admin"),
             ("compliance@prosper.foundation", "compliance_officer"),
             ("compl2@prosper.foundation", "compliance_officer"),
             ("staff@prosper.foundation", "admin")]


def _cuit():
    d = "3071234567"
    w = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
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
            ("prosper_files.files", "prosper_files.chunks")}
    mongo.drop_database(_DB)
    db = mongo[_DB]
    senv = {**os.environ, "DB_NAME": _DB, "KYB_MODULE_ENABLED": "true",
            "KYB_ENVIRONMENT": "production", "KYB_SLA_HOURS": "72",
            "PROSPER_DISABLE_RATELIMIT": "1", "RESEND_API_KEY": "",
            "DEMO_MODE": "true"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host",
         "127.0.0.1", "--port", str(_PORT), "--log-level", "error"],
        cwd=str(BACKEND), env=senv,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(240):
            try:
                requests.get(f"http://127.0.0.1:{_PORT}/docs", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("server 8018 no arrancó en 120s")
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
        uid = {e.split("@")[0]: db["users"].find_one({"email": e})["user_id"]
               for e, _ in INTERNALS}
        subprocess.run([sys.executable,
                        str(ROOT / "scripts/seed_kyb_templates.py")],
                       env=senv, capture_output=True, timeout=60)
        # Caso completo submitted
        s = requests.Session()
        tok = s.post(f"{API}/kyb/signup/start",
                     json={"email": "adm@preview-prosper.io",
                           "company_name": "Admin Corp SA"},
                     timeout=10).json()["signup_token"]
        s.post(f"{API}/kyb/signup/contact", json={
            "signup_token": tok, "full_name": "T",
            "phone": {"country_code": "+54", "number": "1150000007"}},
            timeout=10)
        s.post(f"{API}/kyb/signup/country",
               json={"signup_token": tok, "country": "AR"}, timeout=10)
        act = re.search(r"token=([\w\-]+)", db["outbound_emails"].find_one(
            {"to": "adm@preview-prosper.io"})["html"]).group(1)
        s.post(f"{API}/kyb/signup/activate",
               json={"activation_token": act}, timeout=10)
        keys = [d["document_key"] for d in
                s.get(f"{API}/kyb/case", timeout=10).json()["legal_docs"]]
        s.put(f"{API}/kyb/case/tax-identification",
              json={"tax_id": _cuit(), "accepted_documents": keys},
              timeout=10)
        s.put(f"{API}/kyb/case/legal-representative",
              json={"country_of_residence": "AR", "full_name": "Rep A",
                    "email": "rep@adm.io"}, timeout=10)
        for path, body in [
                ("legal-name", {"legal_name": "Admin Corp SA",
                                "legal_structure": "SA"}),
                ("data", {"activity_description": "x" * 120}),
                ("address", {"raw": "Corrientes 1234", "city": "CABA",
                             "country": "AR"}),
                ("operations", {"estimated_monthly_volume_usd": 5000,
                                "purposes": ["YIELD_ARS"],
                                "funds_subscribed": ["PROSPER_ARS"]}),
                ("funds-origin", {"type": "OWN_TREASURY"})]:
            rr = s.put(f"{API}/kyb/case/company/{path}", json=body,
                       timeout=10)
            assert rr.status_code == 200, f"{path}: {rr.text}"
        for slot in SLOTS:
            if slot == "funds_origin_evidence":
                s.post(f"{API}/kyb/case/documents/confirm",
                       json={"slot": slot, "recently_incorporated": True},
                       timeout=10)
                continue
            s.post(f"{API}/kyb/case/documents", data={"slot": slot},
                   files={"file": ("d.pdf", PDF, "application/pdf")},
                   timeout=15)
            s.post(f"{API}/kyb/case/documents/confirm",
                   json={"slot": slot}, timeout=10)
        fid = s.post(f"{API}/kyb/case/documents",
                     data={"slot": "ubo_document_front"},
                     files={"file": ("d.pdf", PDF, "application/pdf")},
                     timeout=15).json()["document_id"]
        s.post(f"{API}/kyb/case/ubos", json={
            "first_name": "U", "last_name": "Uno",
            "ownership_percentage": 100.0, "document_front_id": fid},
            timeout=10)
        s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": True}, timeout=10)
        rs = s.post(f"{API}/kyb/case/submit", timeout=10)
        assert rs.status_code == 200, rs.text
        cid = db["kyb_cases"].find_one(
            {"applicant_email": "adm@preview-prosper.io"})["case_id"]
        yield {"db": db, "cid": cid, "uid": uid, "client": s,
               "super": _login("super@prosper.foundation"),
               "compl": _login("compliance@prosper.foundation"),
               "compl2": _login("compl2@prosper.foundation"),
               "staff": _login("staff@prosper.foundation")}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for c, n in base.items():
            assert real[c].count_documents({}) == n
        mongo.drop_database(_DB)
        mongo.close()


def test_01_tray_filters_and_workload(env):
    compl, cid = env["compl"], env["cid"]
    g = compl.get(f"{ADMIN}/cases", timeout=10).json()
    assert g["total"] == 1 and g["sla_hours"] == 72
    row = g["items"][0]
    assert row["case_id"] == cid and row["sla"] == "green"
    assert row["tax_id"] and row["company_name"] == "Admin Corp SA"
    assert compl.get(f"{ADMIN}/cases?q=Admin+Corp",
                     timeout=10).json()["total"] == 1
    assert compl.get(f"{ADMIN}/cases?q=NoExiste",
                     timeout=10).json()["total"] == 0
    assert compl.get(f"{ADMIN}/cases?mine=true",
                     timeout=10).json()["items"] == []
    r = compl.post(f"{ADMIN}/cases/{cid}/assign",
                   json={"assignee_user_id": env["uid"]["compliance"]},
                   timeout=10)
    assert r.status_code == 200
    assert compl.get(f"{ADMIN}/cases?mine=true",
                     timeout=10).json()["items"][0]["case_id"] == cid
    assert env["db"]["audit_logs"].find_one({"action": "kyb.case.assigned"})


def test_02_section_review_and_request_info(env):
    compl, sup, db, cid = env["compl"], env["super"], env["db"], env["cid"]
    r = compl.post(f"{ADMIN}/cases/{cid}/sections/company_data/review",
                   json={"action": "observe", "observation": "corta"},
                   timeout=10)
    assert r.status_code == 422
    # request-info sin secciones observadas → 422
    assert compl.post(f"{ADMIN}/cases/{cid}/request-info",
                      timeout=10).status_code == 422
    text = "Falta el detalle de la actividad principal declarada"
    assert compl.post(f"{ADMIN}/cases/{cid}/sections/company_data/review",
                      json={"action": "observe", "observation": text},
                      timeout=10).status_code == 200
    case = db["kyb_cases"].find_one({"case_id": cid})
    assert case["sections"]["company_data"]["observation"] == text
    assert env["uid"]["compliance"] in case["observers"]
    r = compl.post(f"{ADMIN}/cases/{cid}/request-info", timeout=10)
    assert r.status_code == 200 and r.json()["status"] == "info_required"
    mail = db["outbound_emails"].find_one({"template": "kyb_request_info"})
    assert mail and text in mail["html"]      # texto EXACTO al cliente
    # volver el caso a revisión y aprobar las 4 secciones (super)
    db["kyb_cases"].update_one({"case_id": cid},
                               {"$set": {"status": "under_review"}})
    for sec in ("tax_identification", "legal_representative",
                "company_data", "documentation"):
        assert sup.post(f"{ADMIN}/cases/{cid}/sections/{sec}/review",
                        json={"action": "approve"},
                        timeout=10).status_code == 200


def test_03_approve_gates(env):
    sup, compl, db, cid = env["super"], env["compl"], env["db"], env["cid"]
    # checklists pendientes (gate anti-atajo del modo manual)
    assert compl.post(f"{ADMIN}/cases/{cid}/manual-checks/generate",
                      timeout=10).status_code == 200
    r = sup.post(f"{ADMIN}/cases/{cid}/approve", timeout=10)
    assert r.status_code == 422
    codes = {b["code"] for b in r.json()["detail"]["blockers"]}
    assert "MANUAL_CHECKS_PENDING" in codes
    db["kyb_manual_checks"].update_many(
        {"case_id": cid}, {"$set": {"status": "completed"}})
    # hit bloqueante sin resolver
    db["kyb_screening_hits"].insert_one(
        {"hit_id": "hit_x", "case_id": cid, "is_blocking": True,
         "resolution": None, "source": "manual"})
    r = sup.post(f"{ADMIN}/cases/{cid}/approve", timeout=10)
    assert r.status_code == 422
    assert {b["code"] for b in r.json()["detail"]["blockers"]} == \
        {"BLOCKING_HITS"}
    db["kyb_screening_hits"].update_one(
        {"hit_id": "hit_x"}, {"$set": {"resolution": "cleared"}})
    # reject con reason_code inválido → 422
    assert sup.post(f"{ADMIN}/cases/{cid}/reject",
                    json={"reason_code": "nope",
                          "notes": "notas suficientes"},
                    timeout=10).status_code == 422


def test_04_maker_checker_and_observer_rules(env):
    compl, db, cid = env["compl"], env["db"], env["cid"]
    # compliance observó el caso → no puede aprobar (aunque no sea maker)
    r = compl.post(f"{ADMIN}/cases/{cid}/approve", timeout=10)
    assert r.status_code == 403 and "cuatro ojos" in r.json()["detail"]
    # compl2 como contributor de un checklist → 403 maker-checker
    db["kyb_manual_checks"].update_one(
        {"case_id": cid}, {"$addToSet": {"contributors":
                                         env["uid"]["compl2"]}})
    r = env["compl2"].post(f"{ADMIN}/cases/{cid}/approve", timeout=10)
    assert r.status_code == 403 and "Maker-checker" in r.json()["detail"]
    # admin (rol sin decide) → 403 por rol
    assert env["staff"].post(f"{ADMIN}/cases/{cid}/approve",
                             timeout=10).status_code == 403


def test_05_high_risk_second_signature_and_approve(env):
    sup, db, cid = env["super"], env["db"], env["cid"]
    assert sup.post(f"{ADMIN}/cases/{cid}/risk-override",
                    json={"level": "high",
                          "justification": "Volumen y jurisdicción"},
                    timeout=10).status_code == 200
    r = sup.post(f"{ADMIN}/cases/{cid}/approve", timeout=10)
    assert r.status_code == 200 and r.json()["pending_second_approval"]
    case = db["kyb_cases"].find_one({"case_id": cid})
    assert case["pending_second_approval"]["first_by"] == env["uid"]["super"]
    assert case["status"] != "approved"
    # el mismo usuario no puede dar la segunda firma
    assert sup.post(f"{ADMIN}/cases/{cid}/approve",
                    timeout=10).status_code == 403
    # compl2 sigue siendo contributor → override super requerido... no:
    # segunda firma la da compl2 CON override de maker-checker imposible
    # (no es super). Se la quita de contributors y firma limpio.
    db["kyb_manual_checks"].update_many(
        {"case_id": cid}, {"$pull": {"contributors": env["uid"]["compl2"]}})
    r = env["compl2"].post(f"{ADMIN}/cases/{cid}/approve", timeout=10)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    case = db["kyb_cases"].find_one({"case_id": cid})
    assert case["status"] == "approved"
    assert case["pending_second_approval"] is None
    assert db["audit_logs"].find_one(
        {"action": "kyb.case.approval_first_signature"})
    assert db["audit_logs"].find_one({"action": "kyb.case.approved"})
    # organizations.kyb_status NUNCA tocado por el módulo nuevo
    org = db["organizations"].find_one({"org_id": case["org_id"]})
    assert org["kyb_status"] == "pending"


def test_06_suspend_unsuspend(env):
    sup, db, cid = env["super"], env["db"], env["cid"]
    assert sup.post(f"{ADMIN}/cases/{cid}/unsuspend",
                    json={"reason": "no aplica todavía"},
                    timeout=10).status_code == 409
    r = sup.post(f"{ADMIN}/cases/{cid}/suspend",
                 json={"reason": "Alerta de sanciones sobrevenida"},
                 timeout=10)
    assert r.status_code == 200
    case = db["kyb_cases"].find_one({"case_id": cid})
    assert case["suspended"]["reason"] == "Alerta de sanciones sobrevenida"
    assert sup.post(f"{ADMIN}/cases/{cid}/suspend",
                    json={"reason": "duplicada intencional"},
                    timeout=10).status_code == 409
    r = sup.post(f"{ADMIN}/cases/{cid}/unsuspend",
                 json={"reason": "Falso positivo confirmado"}, timeout=10)
    assert r.status_code == 200
    case = db["kyb_cases"].find_one({"case_id": cid})
    assert case["suspended"] is None and case["suspension_history"]
    # approve sobre caso aprobado → 409
    assert sup.post(f"{ADMIN}/cases/{cid}/approve",
                    timeout=10).status_code == 409


def test_07_legacy_contact_email(env):
    from models import utc_now
    sup, db, cid = env["super"], env["db"], env["cid"]
    # contact-email en caso NO legacy → 409
    assert sup.post(f"{ADMIN}/cases/{cid}/contact-email",
                    json={"email": "x@y.io"}, timeout=10).status_code == 409
    db["kyb_cases"].insert_one({
        "case_id": "kyb_legacy_t", "org_id": None, "status": "under_review",
        "applicant_email": None, "company_name_declared": "Legacy SA",
        "is_deleted": False, "legacy_origin": "kyb_apply__test",
        "verification_modes": {"identity": "manual", "screening": "manual",
                               "company_registry": "manual"},
        "sections": {}, "created_at": utc_now(), "updated_at": utc_now()})
    # request-info sin contacto → 409 (con una sección observada igual falla)
    assert sup.post(f"{ADMIN}/cases/kyb_legacy_t/request-info",
                    timeout=10).status_code in (409, 422)
    r = sup.post(f"{ADMIN}/cases/kyb_legacy_t/contact-email",
                 json={"email": "Contacto@Legacy.io"}, timeout=10)
    assert r.status_code == 200
    case = db["kyb_cases"].find_one({"case_id": "kyb_legacy_t"})
    assert case["applicant_email"] == "contacto@legacy.io"
    # escritura ÚNICA
    assert sup.post(f"{ADMIN}/cases/kyb_legacy_t/contact-email",
                    json={"email": "otro@x.io"}, timeout=10).status_code == 409
    assert db["audit_logs"].find_one(
        {"action": "kyb.case.contact_email_registered"})


def test_08_legacy_endpoints_retired(env):
    sup, cid = env["super"], env["cid"]
    r = sup.get(f"{ADMIN}/queue", allow_redirects=False, timeout=10)
    assert r.status_code == 308
    assert r.headers["Location"].endswith("/admin/compliance/kyb/cases")
    # F8-bugfix (R3/R4): el redirect por case_id sólo aplica a casos del
    # modelo nuevo. Los casos legacy siguen respondiendo desde el router
    # viejo para no romper flujos aún migrándose. Usamos `cid` que es un
    # caso del modelo nuevo creado por el fixture.
    r = sup.get(f"{ADMIN}/{cid}", allow_redirects=False, timeout=10)
    assert r.status_code == 308 and r.headers["Location"].endswith(
        f"/cases/{cid}")
    assert sup.patch(f"{ADMIN}/{cid}/checklist", json={},
                     timeout=10).status_code == 410
    assert sup.post(f"{ADMIN}/{cid}/decision", json={},
                    timeout=10).status_code == 410


def test_09_audit_endpoint_and_authz(env):
    sup, cid = env["super"], env["cid"]
    g = sup.get(f"{ADMIN}/cases/{cid}/audit", timeout=10).json()
    actions = {r["action"] for r in g["items"]}
    assert "kyb.case.approved" in actions
    g = sup.get(f"{ADMIN}/cases/{cid}/audit?action=kyb.case.suspended",
                timeout=10).json()
    assert {r["action"] for r in g["items"]} == {"kyb.case.suspended"}
    assert requests.get(f"{ADMIN}/cases", timeout=10).status_code == 401
    assert env["client"].get(f"{ADMIN}/cases",
                             timeout=10).status_code == 403
