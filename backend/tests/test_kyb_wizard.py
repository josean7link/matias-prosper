"""Tests e2e del wizard KYB (Fase 3) — server efímero puerto 8014 +
DB scratch `prosper_kyb_tests_wizard`. Los archivos van al GridFS de la
DB scratch: al final se verifica que las colecciones REALES de storage
(prosper_files.*, file_access_tokens) no cambiaron.
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

_SCRATCH_DB = "prosper_kyb_tests_wizard"
_PORT = 8014
API = f"http://127.0.0.1:{_PORT}/api/v1"

PDF = b"%PDF-1.4\n" + b"x" * 2048
CUIT_OK = None  # se calcula


def _valid_cuit() -> str:
    digits = "3071234567"
    w = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    dv = 11 - sum(int(d) * k for d, k in zip(digits, w)) % 11
    dv = {11: 0, 10: 9}.get(dv, dv)
    return digits + str(dv)


@pytest.fixture(scope="module")
def env():
    mongo = MongoClient(os.environ["MONGO_URL"])
    real = mongo[os.environ.get("DB_NAME", "prosper_phase0")]
    baseline = {c: real[c].count_documents({}) for c in
                ("prosper_files.files", "prosper_files.chunks",
                 "file_access_tokens")}
    mongo.drop_database(_SCRATCH_DB)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(_PORT), "--log-level", "error"],
        cwd=str(BACKEND),
        env={**os.environ, "DB_NAME": _SCRATCH_DB,
             "KYB_MODULE_ENABLED": "true",
             "PROSPER_DISABLE_RATELIMIT": "1", "RESEND_API_KEY": "",
             "DEMO_MODE": "true"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                requests.get(f"http://127.0.0.1:{_PORT}/docs", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        db = mongo[_SCRATCH_DB]
        # Sesión de cliente vía signup+activate.
        s = requests.Session()
        r = s.post(f"{API}/kyb/signup/start",
                   json={"email": "wizard@corp.io",
                         "company_name": "Wizard Corp SA"}, timeout=10)
        tok = r.json()["signup_token"]
        s.post(f"{API}/kyb/signup/contact", json={
            "signup_token": tok, "full_name": "Wiz Ard",
            "phone": {"country_code": "+54", "number": "1150000001"}},
            timeout=10)
        s.post(f"{API}/kyb/signup/country",
               json={"signup_token": tok, "country": "AR"}, timeout=10)
        mail = db["outbound_emails"].find_one({"to": "wizard@corp.io"})
        act = re.search(r"token=([A-Za-z0-9_\-]+)", mail["html"]).group(1)
        s.post(f"{API}/kyb/signup/activate",
               json={"activation_token": act}, timeout=10)
        case = db["kyb_cases"].find_one({"applicant_email": "wizard@corp.io"})
        yield {"s": s, "db": db, "case_id": case["case_id"], "real": real,
               "baseline": baseline}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        # Guardarraíl: el storage REAL no cambió.
        for c, n in baseline.items():
            assert real[c].count_documents({}) == n, \
                f"¡{c} REAL cambió durante los tests!"
        mongo.drop_database(_SCRATCH_DB)
        mongo.close()


def test_01_tax_identification_lock_and_evidence(env):
    s, db = env["s"], env["db"]
    # CUIT inválido → 422
    r = s.put(f"{API}/kyb/case/tax-identification",
              json={"tax_id": "20123456780",
                    "accepted_documents": []}, timeout=10)
    assert r.status_code == 422
    # Sin aceptar legales → 422
    r = s.put(f"{API}/kyb/case/tax-identification",
              json={"tax_id": _valid_cuit(), "accepted_documents": []},
              timeout=10)
    assert r.status_code == 422
    # Draft no bloquea
    r = s.put(f"{API}/kyb/case/tax-identification",
              json={"tax_id": _valid_cuit(), "draft": True}, timeout=10)
    assert r.status_code == 200 and r.json()["draft"] is True
    prof = db["kyb_company_profiles"].find_one({"case_id": env["case_id"]})
    assert prof["tax_id_locked"] is False
    # Confirmación con legales → lock + evidencia versión/hash + completed
    keys = [d["document_key"] for d in
            s.get(f"{API}/kyb/case", timeout=10).json()["legal_docs"]]
    r = s.put(f"{API}/kyb/case/tax-identification",
              json={"tax_id": _valid_cuit(), "accepted_documents": keys},
              timeout=10)
    assert r.status_code == 200 and r.json()["tax_id_locked"] is True
    prof = db["kyb_company_profiles"].find_one({"case_id": env["case_id"]})
    assert prof["tax_id_locked"] is True
    for a in prof["legal_acceptances"]:
        assert a["version"] and len(a["content_hash"]) == 64
        assert a["accepted_at"]
    case = db["kyb_cases"].find_one({"case_id": env["case_id"]})
    assert case["sections"]["tax_identification"]["status"] == "completed"
    assert case["status"] == "in_progress"       # draft → in_progress
    # Reintento de edición → 409
    r = s.put(f"{API}/kyb/case/tax-identification",
              json={"tax_id": _valid_cuit(), "accepted_documents": keys},
              timeout=10)
    assert r.status_code == 409


def test_02_sections_and_company_subsections(env):
    s, db = env["s"], env["db"]
    r = s.put(f"{API}/kyb/case/legal-representative",
              json={"country_of_residence": "ar",
                    "full_name": "Rep Legal", "email": "rep@corp.io"},
              timeout=10)
    assert r.status_code == 200
    # company: 5 subsecciones; la sección se completa recién con las 5
    assert s.put(f"{API}/kyb/case/company/legal-name", json={
        "legal_name": "Wizard Corp SA", "legal_structure": "SA"},
        timeout=10).status_code == 200
    # actividad corta no-draft → 422; draft → ok
    r = s.put(f"{API}/kyb/case/company/data",
              json={"activity_description": "corta"}, timeout=10)
    assert r.status_code == 422
    assert s.put(f"{API}/kyb/case/company/data", json={
        "activity_description": "x" * 120, "registration_number": "IGJ-1",
        "registration_date": "2020-01-01",
        "website": "https://linkedin.com/company/wizard"},
        timeout=10).status_code == 200
    assert s.put(f"{API}/kyb/case/company/address", json={
        "raw": "Av. Corrientes 1234, CABA", "street": "Av. Corrientes",
        "number": "1234", "city": "CABA", "state": "Buenos Aires",
        "postal_code": "C1043", "country": "AR"},
        timeout=10).status_code == 200
    assert s.put(f"{API}/kyb/case/company/operations", json={
        "estimated_monthly_volume_usd": 250000,
        "purposes": ["YIELD_ARS", "EMBEDDED_EARN"],
        "funds_subscribed": ["PROSPER_ARS"]},
        timeout=10).status_code == 200
    case = db["kyb_cases"].find_one({"case_id": env["case_id"]})
    assert case["sections"]["company_data"]["status"] == "pending"
    # funds origin CLIENT_FUNDS sin licencia → 422
    r = s.put(f"{API}/kyb/case/company/funds-origin",
              json={"type": "CLIENT_FUNDS"}, timeout=10)
    assert r.status_code == 422
    assert s.put(f"{API}/kyb/case/company/funds-origin", json={
        "type": "MIXED", "client_funds_ratio": 60,
        "license_type": "PSP", "license_number": "PSP-123",
        "has_aml_policy": True, "compliance_officer_name": "Ofi Cial",
        "end_user_kyc_description": "KYC completo con biometría",
        "segregated_assets": True, "is_uif_obliged_subject": True,
        "uif_registration_number": "UIF-9",
        "tax_residences": [{"country": "AR", "tin": _valid_cuit()}]},
        timeout=10).status_code == 200
    case = db["kyb_cases"].find_one({"case_id": env["case_id"]})
    assert case["sections"]["company_data"]["status"] == "completed"
    assert case["sections"]["legal_representative"]["status"] == "completed"


def test_03_documents_versioning_delete_confirm(env):
    s, db = env["s"], env["db"]
    def upload(slot, name):
        return s.post(f"{API}/kyb/case/documents", data={
            "slot": slot, "description": "constancia"},
            files={"file": (name, PDF, "application/pdf")}, timeout=15)
    # inválido (magic bytes) → 422, sin registro ni binario
    r = s.post(f"{API}/kyb/case/documents", data={"slot": PHASE_SLOT},
               files={"file": ("x.pdf", b"no-es-pdf" * 50,
                               "application/pdf")}, timeout=15)
    assert r.status_code == 422
    assert db["kyb_documents"].count_documents({}) == 0
    assert db["prosper_files.files"].count_documents({}) == 0
    # v1 y v2: la nueva no pisa, marca is_current
    r1 = upload(PHASE_SLOT, "v1.pdf")
    assert r1.status_code == 200, r1.text
    assert "storage_key" not in r1.json()
    r2 = upload(PHASE_SLOT, "v2.pdf")
    docs = list(db["kyb_documents"].find({"slot": PHASE_SLOT}))
    assert [(d["version"], d["is_current"]) for d in
            sorted(docs, key=lambda x: x["version"])] == [(1, False),
                                                          (2, True)]
    # URL firmada de vida corta, sin exponer storage_key
    did = r2.json()["document_id"]
    u = s.get(f"{API}/kyb/case/documents/{did}/url", timeout=10).json()
    assert u["url"].startswith("/api/v1/files/") and u["expires_in"] == 300
    body = s.get(f"http://127.0.0.1:{_PORT}{u['url']}", timeout=10)
    assert body.status_code == 200 and body.content.startswith(b"%PDF")
    # confirm sin archivo en otro slot → 422; con archivo → ok
    r = s.post(f"{API}/kyb/case/documents/confirm",
               json={"slot": "constitutive_document"}, timeout=10)
    assert r.status_code == 422
    assert s.post(f"{API}/kyb/case/documents/confirm",
                  json={"slot": PHASE_SLOT}, timeout=10).status_code == 200
    # reciente creación satisface funds_origin_evidence sin archivo
    assert s.post(f"{API}/kyb/case/documents/confirm",
                  json={"slot": "funds_origin_evidence",
                        "recently_incorporated": True},
                  timeout=10).status_code == 200
    prof = db["kyb_company_profiles"].find_one({"case_id": env["case_id"]})
    assert prof["recently_incorporated_declared"] is True
    # soft-delete: is_current false, el doc no desaparece
    assert s.delete(f"{API}/kyb/case/documents/{did}",
                    timeout=10).status_code == 200
    d = db["kyb_documents"].find_one({"document_id": did})
    assert d["is_current"] is False


PHASE_SLOT = "tax_registration_certificate"


def test_04_readonly_and_info_required(env):
    s, db = env["s"], env["db"]
    cid = env["case_id"]
    # under_review → read-only con mensaje
    db["kyb_cases"].update_one({"case_id": cid},
                               {"$set": {"status": "under_review"}})
    r = s.put(f"{API}/kyb/case/legal-representative",
              json={"country_of_residence": "AR", "full_name": "X Y",
                    "email": "x@y.io"}, timeout=10)
    assert r.status_code == 403 and "revisión" in r.json()["detail"]
    g = s.get(f"{API}/kyb/case", timeout=10).json()
    assert g["editable"] is False
    # info_required: solo secciones observed
    db["kyb_cases"].update_one({"case_id": cid}, {"$set": {
        "status": "info_required",
        "sections.legal_representative.status": "observed",
        "sections.legal_representative.observation": "Falta el DNI"}})
    r = s.put(f"{API}/kyb/case/company/legal-name", json={
        "legal_name": "Otro Nombre", "legal_structure": "SA"}, timeout=10)
    assert r.status_code == 403
    r = s.put(f"{API}/kyb/case/legal-representative",
              json={"country_of_residence": "AR", "full_name": "Rep Dos",
                    "email": "rep2@corp.io"}, timeout=10)
    assert r.status_code == 200
    # Fase 3.1: observed + guardado → resubmitted, con la observación
    # original conservada; cuenta como completa para el envío.
    sec = db["kyb_cases"].find_one({"case_id": cid})["sections"][
        "legal_representative"]
    assert sec["status"] == "resubmitted"
    assert sec["observation"] == "Falta el DNI"      # historial intacto
    g = s.get(f"{API}/kyb/case", timeout=10).json()
    assert "legal_representative" not in g["progress"]["missing"]
    assert g["editable_sections"] == []  # ya no queda observed tras guardar
    db["kyb_cases"].update_one({"case_id": cid},
                               {"$set": {"status": "in_progress"}})


def test_05_get_case_never_leaks_storage_key(env):
    g = env["s"].get(f"{API}/kyb/case", timeout=10).json()
    assert "storage_key" not in str(g)
    assert g["progress"]["can_submit"] is False
    assert "team" not in g["progress"]["missing"]  # opcional no bloquea
