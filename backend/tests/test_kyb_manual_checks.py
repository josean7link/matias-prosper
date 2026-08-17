"""Tests e2e Fase 5a — modos de verificación + checklists manuales.
Server efímero puerto 8016 (KYB_ENVIRONMENT=production para la regla
anti-mock) + DB scratch `prosper_kyb_tests_checks`. Un segundo server
corto (8017, sandbox) valida que mock SÍ es seleccionable fuera de prod.
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

_SCRATCH_DB = "prosper_kyb_tests_checks"
_PORT = 8016
API = f"http://127.0.0.1:{_PORT}/api/v1"
ADMIN = f"{API}/admin/compliance/kyb"

PDF = b"%PDF-1.4\n" + b"x" * 2048
PHASE3_SLOTS = ["tax_registration_certificate", "constitutive_document",
                "funds_origin_evidence", "authorities_appointment",
                "company_proof_of_address"]

INTERNALS = [("super@prosper.foundation", "super_admin"),
             ("compliance@prosper.foundation", "compliance_officer"),
             ("staff@prosper.foundation", "admin")]


def _valid_cuit() -> str:
    digits = "3071234567"
    w = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    dv = 11 - sum(int(d) * k for d, k in zip(digits, w)) % 11
    dv = {11: 0, 10: 9}.get(dv, dv)
    return digits + str(dv)


def _server_env(**extra):
    return {**os.environ, "DB_NAME": _SCRATCH_DB,
            "KYB_MODULE_ENABLED": "true", "KYB_ENVIRONMENT": "production",
            "PROSPER_DISABLE_RATELIMIT": "1", "RESEND_API_KEY": "",
            "DEMO_MODE": "true", **extra}


def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{API}/auth/dev-login", params={"email": email},
              allow_redirects=False, timeout=10)
    assert r.status_code == 303, r.text
    return s


@pytest.fixture(scope="module")
def env():
    mongo = MongoClient(os.environ["MONGO_URL"])
    real = mongo[os.environ.get("DB_NAME", "prosper_phase0")]
    baseline = {c: real[c].count_documents({}) for c in
                ("prosper_files.files", "prosper_files.chunks",
                 "file_access_tokens")}
    mongo.drop_database(_SCRATCH_DB)
    db = mongo[_SCRATCH_DB]
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(_PORT), "--log-level", "error"],
        cwd=str(BACKEND), env=_server_env(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # El startup siembra demo data y llama al CMS: arranque variable,
        # a veces >60s sobre una scratch recién dropeada.
        for _ in range(240):
            try:
                requests.get(f"http://127.0.0.1:{_PORT}/docs", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("el server efímero 8016 no arrancó en 120s")
        # Usuarios internos con los roles correctos (dev-login usa el rol
        # del user existente).
        from models import utc_now
        for email, role in INTERNALS:
            db["users"].update_one(
                {"email": email},
                {"$set": {"role": role, "status": "active",
                          "is_deleted": False, "updated_at": utc_now()},
                 "$setOnInsert": {
                     "user_id": f"usr_{role}", "email": email,
                     "org_id": None, "kyc_status": "pending",
                     "mfa_enabled": False, "created_at": utc_now()}},
                upsert=True)
        uid = {role: db["users"].find_one({"email": email})["user_id"]
               for email, role in INTERNALS}
        # Caso completo listo para submit (fase 3 + UBO confirmado).
        s = requests.Session()
        r = s.post(f"{API}/kyb/signup/start",
                   json={"email": "checks@preview-prosper.io",
                         "company_name": "Checks Corp SA"}, timeout=10)
        tok = r.json()["signup_token"]
        s.post(f"{API}/kyb/signup/contact", json={
            "signup_token": tok, "full_name": "Chk Tester",
            "phone": {"country_code": "+54", "number": "1150000003"}},
            timeout=10)
        s.post(f"{API}/kyb/signup/country",
               json={"signup_token": tok, "country": "AR"}, timeout=10)
        mail = db["outbound_emails"].find_one(
            {"to": "checks@preview-prosper.io"})
        act = re.search(r"token=([A-Za-z0-9_\-]+)", mail["html"]).group(1)
        s.post(f"{API}/kyb/signup/activate",
               json={"activation_token": act}, timeout=10)
        case = db["kyb_cases"].find_one(
            {"applicant_email": "checks@preview-prosper.io"})
        cid = case["case_id"]
        keys = [d["document_key"] for d in
                s.get(f"{API}/kyb/case", timeout=10).json()["legal_docs"]]
        s.put(f"{API}/kyb/case/tax-identification",
              json={"tax_id": _valid_cuit(), "accepted_documents": keys},
              timeout=10)
        s.put(f"{API}/kyb/case/legal-representative",
              json={"country_of_residence": "AR", "full_name": "Rep Uno",
                    "email": "rep@checks.io", "tax_id": "20111111112"},
              timeout=10)
        s.put(f"{API}/kyb/case/company/legal-name", json={
            "legal_name": "Checks Corp SA", "legal_structure": "SA"},
            timeout=10)
        s.put(f"{API}/kyb/case/company/data",
              json={"activity_description": "x" * 120}, timeout=10)
        s.put(f"{API}/kyb/case/company/address", json={
            "raw": "Corrientes 1", "city": "CABA", "country": "AR"},
            timeout=10)
        s.put(f"{API}/kyb/case/company/operations", json={
            "estimated_monthly_volume_usd": 5000, "purposes": ["YIELD_ARS"],
            "funds_subscribed": ["PROSPER_ARS"]}, timeout=10)
        s.put(f"{API}/kyb/case/company/funds-origin",
              json={"type": "OWN_TREASURY"}, timeout=10)
        for slot in PHASE3_SLOTS:
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
                     files={"file": ("dni.pdf", PDF, "application/pdf")},
                     timeout=15).json()["document_id"]
        s.post(f"{API}/kyb/case/ubos", json={
            "first_name": "Ubo", "last_name": "Uno",
            "tax_id": "27222222226", "ownership_percentage": 100.0,
            "document_front_id": fid}, timeout=10)
        s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": True}, timeout=10)
        yield {"db": db, "case_id": cid, "client": s, "uid": uid,
               "super": _login("super@prosper.foundation"),
               "compl": _login("compliance@prosper.foundation"),
               "staff": _login("staff@prosper.foundation")}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for c, n in baseline.items():
            assert real[c].count_documents({}) == n, \
                f"¡{c} REAL cambió durante los tests!"
        mongo.drop_database(_SCRATCH_DB)
        mongo.close()


def test_01_modes_and_mock_blocked_in_production(env):
    compl, sup = env["compl"], env["super"]
    g = compl.get(f"{ADMIN}/verification-modes", timeout=10).json()
    assert g["environment"] == "production"
    for c in ("identity", "screening", "company_registry"):
        assert g[c]["mode"] == "manual"
    # Cambiar modo: solo super_admin
    r = compl.put(f"{ADMIN}/verification-modes/screening",
                  json={"mode": "automatic"}, timeout=10)
    assert r.status_code == 403
    r = sup.put(f"{ADMIN}/verification-modes/screening",
                json={"mode": "automatic"}, timeout=10)
    assert r.status_code == 200
    # mock en producción → 409 explícito, incluso forzándolo por API
    r = sup.put(f"{ADMIN}/verification-modes/identity",
                json={"mode": "mock"}, timeout=10)
    assert r.status_code == 409 and "producción" in r.json()["detail"]
    r = sup.put(f"{ADMIN}/verification-modes/nope",
                json={"mode": "manual"}, timeout=10)
    assert r.status_code == 422
    # El environment jamás sale de la colección (no es fuente de verdad)
    doc = env["db"]["kyb_verification_modes"].find_one({})
    assert "environment" not in doc


def test_02_mock_allowed_in_sandbox(env):
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", "8017", "--log-level", "error"],
        cwd=str(BACKEND), env=_server_env(KYB_ENVIRONMENT="sandbox"),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(240):
            try:
                requests.get("http://127.0.0.1:8017/docs", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        s = requests.Session()
        r = s.get("http://127.0.0.1:8017/api/v1/auth/dev-login",
                  params={"email": "super@prosper.foundation"},
                  allow_redirects=False, timeout=10)
        assert r.status_code == 303
        base = "http://127.0.0.1:8017/api/v1/admin/compliance/kyb"
        assert s.get(f"{base}/verification-modes",
                     timeout=10).json()["environment"] == "sandbox"
        r = s.put(f"{base}/verification-modes/identity",
                  json={"mode": "mock"}, timeout=10)
        assert r.status_code == 200
        # devolver a manual para no afectar el resto de la suite
        s.put(f"{base}/verification-modes/identity",
              json={"mode": "manual"}, timeout=10)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_03_seed_templates_idempotent_and_upgrade(env):
    envv = _server_env()
    for _ in range(2):
        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts/seed_kyb_templates.py")],
            env=envv, capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
    tpls = list(env["db"]["kyb_manual_check_templates"].find({}))
    assert len(tpls) == 3
    assert {t["template_id"] for t in tpls} == \
        {"tpl_screening_ar", "tpl_registry_ar", "tpl_identity_global"}
    ident = next(t for t in tpls if t["template_id"] ==
                 "tpl_identity_global")
    assert {i["item_key"] for i in ident["items"]} == \
        {"identity_match", "doc_validity", "doc_legibility"}
    # Upgrade: si la última versión sigue siendo del seed y los ítems
    # difieren, el seed publica versión nueva…
    env["db"]["kyb_manual_check_templates"].update_one(
        {"template_id": "tpl_identity_global", "version": 1},
        {"$set": {"items": [{"item_key": "viejo", "label": "Ítem viejo",
                             "possible_outcomes": ["clear"]}]}})
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/seed_kyb_templates.py")],
        env=envv, capture_output=True, text=True, timeout=60)
    assert "1 actualizadas" in out.stdout, out.stdout
    v2 = env["db"]["kyb_manual_check_templates"].find_one(
        {"template_id": "tpl_identity_global", "version": 2})
    assert v2 and v2["active"] and len(v2["items"]) == 3
    # …pero si Compliance editó (updated_by != seed), NUNCA se pisa.
    env["db"]["kyb_manual_check_templates"].update_one(
        {"template_id": "tpl_identity_global", "version": 2},
        {"$set": {"items": [{"item_key": "custom", "label": "De Compliance",
                             "possible_outcomes": ["clear"]}],
                  "updated_by": "usr_humano"}})
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/seed_kyb_templates.py")],
        env=envv, capture_output=True, text=True, timeout=60)
    assert "0 actualizadas" in out.stdout, out.stdout
    # restaurar los ítems del seed para el resto de la suite
    env["db"]["kyb_manual_check_templates"].update_one(
        {"template_id": "tpl_identity_global", "version": 2},
        {"$set": {"items": v2["items"], "updated_by": "seed"}})


def test_04_submit_snapshots_modes(env):
    s, db = env["client"], env["db"]
    # screening quedó automatic (test_01); identity/registry manual
    r = s.post(f"{API}/kyb/case/submit", timeout=10)
    assert r.status_code == 200, r.text
    case = db["kyb_cases"].find_one({"case_id": env["case_id"]})
    assert case["verification_modes"] == {
        "identity": "manual", "screening": "automatic",
        "company_registry": "manual"}
    assert case["verification_states"]["screening"]["state"] == "automatic"
    assert case["verification_states"]["identity"]["state"] == "manual"


def test_05_generate_checks_by_subject_and_category(env):
    compl, db = env["compl"], env["db"]
    cid = env["case_id"]
    r = compl.post(f"{ADMIN}/cases/{cid}/manual-checks/generate", timeout=10)
    assert r.status_code == 200
    checks = list(db["kyb_manual_checks"].find({"case_id": cid}))
    # identity (manual): rep legal + 1 UBO = 2. company_registry (manual):
    # empresa = 1. screening (automatic): SIN checklist (spec 5a).
    got = {(c["category"], c["subject_type"]) for c in checks}
    assert got == {("identity", "legal_representative"), ("identity", "ubo"),
                   ("company_registry", "company")}
    assert all(c["trigger"] == "mode_manual" for c in checks)
    # Idempotente
    r = compl.post(f"{ADMIN}/cases/{cid}/manual-checks/generate", timeout=10)
    assert r.json()["created"] == 0
    g = compl.get(f"{ADMIN}/cases/{cid}/manual-checks", timeout=10).json()
    assert g["case"]["case_id"] == cid and len(g["checks"]) == 3
    assert "storage_key" not in str(g)


def test_06_item_rules_evidence_and_notes(env):
    compl, db = env["compl"], env["db"]
    reg = db["kyb_manual_checks"].find_one(
        {"case_id": env["case_id"], "category": "company_registry"})
    chk = reg["check_id"]
    # outcome inválido / notas cortas → 422
    r = compl.patch(f"{ADMIN}/manual-checks/{chk}/items/arca_constancia",
                    json={"outcome": "nope", "notes": "notas suficientes"},
                    timeout=10)
    assert r.status_code == 422
    r = compl.patch(f"{ADMIN}/manual-checks/{chk}/items/arca_constancia",
                    json={"outcome": "clear", "notes": "corta"}, timeout=10)
    assert r.status_code == 422
    # evidencia obligatoria sin documento → 422
    r = compl.patch(f"{ADMIN}/manual-checks/{chk}/items/arca_constancia",
                    json={"outcome": "clear",
                          "notes": "constancia verificada ok"}, timeout=10)
    assert r.status_code == 422 and "evidencia" in r.json()["detail"]
    # subir evidencia → patch OK, contributor registrado
    up = compl.post(f"{ADMIN}/manual-checks/{chk}/evidence",
                    data={"item_key": "arca_constancia"},
                    files={"file": ("captura.pdf", PDF, "application/pdf")},
                    timeout=15)
    assert up.status_code == 200 and "storage_key" not in up.json()
    did = up.json()["document_id"]
    r = compl.patch(f"{ADMIN}/manual-checks/{chk}/items/arca_constancia",
                    json={"outcome": "clear",
                          "notes": "Constancia ARCA coincide con lo declarado",
                          "evidence_document_ids": [did]}, timeout=10)
    assert r.status_code == 200
    fresh = db["kyb_manual_checks"].find_one({"check_id": chk})
    assert fresh["status"] == "in_progress"
    assert env["uid"]["compliance_officer"] in fresh["contributors"]
    item = next(i for i in fresh["items"]
                if i["item_key"] == "arca_constancia")
    assert item["outcome"] == "clear" and item["evidence_document_ids"] == [did]


def test_07_complete_produces_normalized_output_and_hits(env):
    compl, db = env["compl"], env["db"]
    ident = db["kyb_manual_checks"].find_one(
        {"case_id": env["case_id"], "category": "identity",
         "subject_type": "legal_representative"})
    chk = ident["check_id"]
    # completar con ítems pendientes → 422 estructurado
    r = compl.post(f"{ADMIN}/manual-checks/{chk}/complete", timeout=10)
    assert r.status_code == 422 and r.json()["detail"]["pending_items"]
    compl.patch(f"{ADMIN}/manual-checks/{chk}/items/identity_match",
                json={"outcome": "hit",
                      "notes": "El documento no coincide con lo declarado"},
                timeout=10)
    compl.patch(f"{ADMIN}/manual-checks/{chk}/items/doc_validity",
                json={"outcome": "clear",
                      "notes": "Documento vigente hasta 2030"}, timeout=10)
    compl.patch(f"{ADMIN}/manual-checks/{chk}/items/doc_legibility",
                json={"outcome": "clear",
                      "notes": "Frente y dorso legibles sin cortes"},
                timeout=10)
    r = compl.post(f"{ADMIN}/manual-checks/{chk}/complete", timeout=10)
    assert r.status_code == 200 and r.json()["outcome"] == "hit"
    # Salida normalizada: MISMA forma que producirá el proveedor (5b)
    ver = db["kyb_verifications"].find_one(
        {"case_id": env["case_id"], "kind": "identity"})
    assert ver["mode"] == "manual" and ver["source"] == "manual"
    assert ver["performed_by"] == env["uid"]["compliance_officer"]
    nr = ver["normalized_result"]
    assert nr["outcome"] == "hit" and nr["hit_count"] == 1
    assert {i["item_key"] for i in nr["items"]} == \
        {"identity_match", "doc_validity", "doc_legibility"}
    hit = db["kyb_screening_hits"].find_one(
        {"case_id": env["case_id"], "verification_id":
         ver["verification_id"]})
    assert hit["source"] == "manual" and hit["is_blocking"] is False
    # re-completar → 409
    assert compl.post(f"{ADMIN}/manual-checks/{chk}/complete",
                      timeout=10).status_code == 409
    assert db["audit_logs"].find_one({"action": "kyb.manual_check.completed"})


def test_08_maker_checker_dependency(env):
    """La dependencia se conecta al endpoint de decisión en Fase 6 — acá
    se testea directo, en un subprocess con DB scratch."""
    code = f"""
import asyncio, os, sys
sys.path.insert(0, {str(BACKEND)!r})
from types import SimpleNamespace
from fastapi import HTTPException
from kyb.manual_checks import enforce_maker_checker

CASE = {env["case_id"]!r}
MAKER_ID = {env["uid"]["compliance_officer"]!r}

async def main():
    def user(uid, role):
        return SimpleNamespace(user_id=uid, role=role, email=None,
                               org_id=None, acting_as_org=None,
                               ip=None, user_agent=None)
    clean = user("usr_never_touched", "super_admin")
    maker = user(MAKER_ID, "compliance_officer")
    sup_maker = user(MAKER_ID, "super_admin")
    await enforce_maker_checker(CASE, clean)            # no participó: pasa
    try:
        await enforce_maker_checker(CASE, maker)
        print("FAIL: maker no bloqueado"); return
    except HTTPException as e:
        assert e.status_code == 403
    try:
        await enforce_maker_checker(CASE, sup_maker, override_reason="corto")
        print("FAIL: override sin motivo largo"); return
    except HTTPException as e:
        assert e.status_code == 403
    await enforce_maker_checker(
        CASE, sup_maker,
        override_reason="Analista único disponible durante la contingencia")
    print("MAKER_CHECKER_OK")

asyncio.run(main())
"""
    out = subprocess.run([sys.executable, "-c", code], env=_server_env(),
                         capture_output=True, text=True, timeout=60)
    assert "MAKER_CHECKER_OK" in out.stdout, out.stdout + out.stderr
    ev = env["db"]["audit_logs"].find_one(
        {"action": "kyb.approval.maker_checker_override"})
    assert ev and len(ev["metadata"]["reason"]) >= 20


def test_09_force_manual(env):
    compl, staff, db = env["compl"], env["staff"], env["db"]
    cid = env["case_id"]
    # admin está en compliance pero NO en decide → 403
    r = staff.post(f"{ADMIN}/cases/{cid}/force-manual",
                   json={"category": "screening",
                         "reason": "Proveedor no disponible"}, timeout=10)
    assert r.status_code == 403
    r = compl.post(f"{ADMIN}/cases/{cid}/force-manual",
                   json={"category": "screening",
                         "reason": "Sin cobertura del proveedor en AR"},
                   timeout=10)
    assert r.status_code == 200 and r.json()["checks_created"] == 3
    case = db["kyb_cases"].find_one({"case_id": cid})
    assert case["verification_states"]["screening"]["state"] == \
        "manual_forced"
    forced = list(db["kyb_manual_checks"].find(
        {"case_id": cid, "category": "screening"}))
    assert len(forced) == 3   # empresa + rep + ubo
    assert all(c["trigger"] == "forced_by_admin" for c in forced)
    assert db["audit_logs"].find_one({"action": "kyb.case.forced_manual"})


def test_10_authorization(env):
    cid = env["case_id"]
    # Sin sesión → 401
    r = requests.get(f"{ADMIN}/verification-modes", timeout=10)
    assert r.status_code == 401
    # Cliente (client_admin del caso) → 403 en todo el módulo admin
    cl = env["client"]
    assert cl.get(f"{ADMIN}/verification-modes",
                  timeout=10).status_code == 403
    assert cl.get(f"{ADMIN}/cases/{cid}/manual-checks",
                  timeout=10).status_code == 403
    assert cl.post(f"{ADMIN}/cases/{cid}/manual-checks/generate",
                   timeout=10).status_code == 403


def test_11_discard_evidence(env):
    compl, db = env["compl"], env["db"]
    reg = db["kyb_manual_checks"].find_one(
        {"case_id": env["case_id"], "category": "company_registry"})
    chk = reg["check_id"]

    def _up():
        return compl.post(f"{ADMIN}/manual-checks/{chk}/evidence",
                          data={"item_key": "registro_societario"},
                          files={"file": ("cap.pdf", PDF,
                                          "application/pdf")},
                          timeout=15).json()["document_id"]
    d1, d2 = _up(), _up()
    r = compl.patch(f"{ADMIN}/manual-checks/{chk}/items/registro_societario",
                    json={"outcome": "clear",
                          "notes": "Inscripción cotejada contra estatuto",
                          "evidence_document_ids": [d1, d2]}, timeout=10)
    assert r.status_code == 200
    # Motivo corto → 422; inexistente → 404
    r = compl.post(f"{ADMIN}/manual-checks/{chk}/evidence/{d1}/discard",
                   json={"reason": "corto"}, timeout=10)
    assert r.status_code == 422
    r = compl.post(f"{ADMIN}/manual-checks/{chk}/evidence/doc_nope/discard",
                   json={"reason": "PDF equivocado, era de otro cliente"},
                   timeout=10)
    assert r.status_code == 404
    # Descartar d1: queda d2 → el ítem conserva su resultado
    r = compl.post(f"{ADMIN}/manual-checks/{chk}/evidence/{d1}/discard",
                   json={"reason": "PDF equivocado, era de otro cliente"},
                   timeout=10)
    assert r.status_code == 200 and r.json()["reset_items"] == []
    doc = db["kyb_documents"].find_one({"document_id": d1})
    assert doc["discarded"]["reason"] == "PDF equivocado, era de otro cliente"
    assert doc["discarded"]["by"] == env["uid"]["compliance_officer"]
    item = next(i for i in db["kyb_manual_checks"].find_one(
        {"check_id": chk})["items"] if i["item_key"] ==
        "registro_societario")
    assert item["evidence_document_ids"] == [d2] and item["outcome"] == "clear"
    # Re-descartar → 409. Usar evidencia descartada en un patch → 422
    assert compl.post(f"{ADMIN}/manual-checks/{chk}/evidence/{d1}/discard",
                      json={"reason": "Insistencia sobre descartada"},
                      timeout=10).status_code == 409
    r = compl.patch(f"{ADMIN}/manual-checks/{chk}/items/registro_societario",
                    json={"outcome": "clear",
                          "notes": "Intento con evidencia descartada",
                          "evidence_document_ids": [d1]}, timeout=10)
    assert r.status_code == 422
    # Descartar la última evidencia de un ítem obligatorio (checklist
    # abierto) → el resultado del ítem se anula y debe re-completarse
    r = compl.post(f"{ADMIN}/manual-checks/{chk}/evidence/{d2}/discard",
                   json={"reason": "Captura ilegible, rehacer consulta"},
                   timeout=10)
    assert r.status_code == 200
    assert r.json()["reset_items"] == ["registro_societario"]
    item = next(i for i in db["kyb_manual_checks"].find_one(
        {"check_id": chk})["items"] if i["item_key"] ==
        "registro_societario")
    assert item["outcome"] is None and item["evidence_document_ids"] == []
    # Auditoría + visible como descartada en el GET (sin storage_key)
    evs = list(db["audit_logs"].find(
        {"action": "kyb.manual_check.evidence_discarded"}))
    assert len(evs) == 2
    g = compl.get(f"{ADMIN}/cases/{env['case_id']}/manual-checks",
                  timeout=10).json()
    discarded = [d for d in g["evidence_documents"] if d.get("discarded")]
    assert {d["document_id"] for d in discarded} == {d1, d2}
    assert "storage_key" not in str(g)
