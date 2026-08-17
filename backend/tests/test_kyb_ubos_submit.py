"""Tests e2e Fase 4 — beneficiarios finales (UBO) + envío a revisión.
Server efímero puerto 8015 + DB scratch `prosper_kyb_tests_ubos`.
Guardarraíl: las colecciones REALES de storage no cambian.
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

_SCRATCH_DB = "prosper_kyb_tests_ubos"
_PORT = 8015
API = f"http://127.0.0.1:{_PORT}/api/v1"

PDF = b"%PDF-1.4\n" + b"x" * 2048
PHASE3_SLOTS = ["tax_registration_certificate", "constitutive_document",
                "funds_origin_evidence", "authorities_appointment",
                "company_proof_of_address"]
REP_TAX = "20111111112"


def _valid_cuit() -> str:
    digits = "3071234567"
    w = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    dv = 11 - sum(int(d) * k for d, k in zip(digits, w)) % 11
    dv = {11: 0, 10: 9}.get(dv, dv)
    return digits + str(dv)


def _upload(s, slot, name="doc.pdf", ubo_id=None, content=PDF):
    data = {"slot": slot}
    if ubo_id:
        data["ubo_id"] = ubo_id
    return s.post(f"{API}/kyb/case/documents", data=data,
                  files={"file": (name, content, "application/pdf")},
                  timeout=15)


def _ubo_body(**over):
    base = {"first_name": "Juan", "last_name": "Pérez",
            "birth_date": "1980-05-01", "nationality": "AR",
            "address": "Av. Siempreviva 742", "marital_status": "casado",
            "profession": "empresario", "phone": "+5411500001",
            "email": "juan@corp.io", "document_number": "28123456",
            "tax_id": "20281234563", "ownership_percentage": 50.0,
            "relationship_start_date": "2015-01-01",
            "is_obliged_subject": False, "is_pep": False}
    base.update(over)
    return base


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
        s = requests.Session()
        r = s.post(f"{API}/kyb/signup/start",
                   json={"email": "ubos@preview-prosper.io",
                         "company_name": "Ubos Corp SA"}, timeout=10)
        tok = r.json()["signup_token"]
        s.post(f"{API}/kyb/signup/contact", json={
            "signup_token": tok, "full_name": "Ubo Tester",
            "phone": {"country_code": "+54", "number": "1150000002"}},
            timeout=10)
        s.post(f"{API}/kyb/signup/country",
               json={"signup_token": tok, "country": "AR"}, timeout=10)
        mail = db["outbound_emails"].find_one(
            {"to": "ubos@preview-prosper.io"})
        act = re.search(r"token=([A-Za-z0-9_\-]+)", mail["html"]).group(1)
        s.post(f"{API}/kyb/signup/activate",
               json={"activation_token": act}, timeout=10)
        case = db["kyb_cases"].find_one(
            {"applicant_email": "ubos@preview-prosper.io"})
        cid = case["case_id"]
        # --- Fase 3 completa (prerequisito del submit) ---
        keys = [d["document_key"] for d in
                s.get(f"{API}/kyb/case", timeout=10).json()["legal_docs"]]
        assert s.put(f"{API}/kyb/case/tax-identification",
                     json={"tax_id": _valid_cuit(),
                           "accepted_documents": keys},
                     timeout=10).status_code == 200
        assert s.put(f"{API}/kyb/case/legal-representative",
                     json={"country_of_residence": "AR",
                           "full_name": "Juan Pérez",
                           "email": "juan@corp.io", "tax_id": REP_TAX},
                     timeout=10).status_code == 200
        assert s.put(f"{API}/kyb/case/company/legal-name", json={
            "legal_name": "Ubos Corp SA", "legal_structure": "SA"},
            timeout=10).status_code == 200
        assert s.put(f"{API}/kyb/case/company/data", json={
            "activity_description": "x" * 120}, timeout=10).status_code == 200
        assert s.put(f"{API}/kyb/case/company/address", json={
            "raw": "Corrientes 1", "city": "CABA", "country": "AR"},
            timeout=10).status_code == 200
        assert s.put(f"{API}/kyb/case/company/operations", json={
            "estimated_monthly_volume_usd": 10000,
            "purposes": ["YIELD_ARS"], "funds_subscribed": ["PROSPER_ARS"]},
            timeout=10).status_code == 200
        assert s.put(f"{API}/kyb/case/company/funds-origin", json={
            "type": "OWN_TREASURY"}, timeout=10).status_code == 200
        for slot in PHASE3_SLOTS:
            if slot == "funds_origin_evidence":
                assert s.post(f"{API}/kyb/case/documents/confirm",
                              json={"slot": slot,
                                    "recently_incorporated": True},
                              timeout=10).status_code == 200
                continue
            assert _upload(s, slot).status_code == 200
            assert s.post(f"{API}/kyb/case/documents/confirm",
                          json={"slot": slot},
                          timeout=10).status_code == 200
        yield {"s": s, "db": db, "case_id": cid, "ids": {}}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for c, n in baseline.items():
            assert real[c].count_documents({}) == n, \
                f"¡{c} REAL cambió durante los tests!"
        mongo.drop_database(_SCRATCH_DB)
        mongo.close()


def _case(env):
    return env["db"]["kyb_cases"].find_one({"case_id": env["case_id"]})


def test_01_create_validations(env):
    s = env["s"]
    # Sin frente de documento → 422
    r = s.post(f"{API}/kyb/case/ubos", json=_ubo_body(), timeout=10)
    assert r.status_code == 422 and "frente" in r.json()["detail"]
    # Porcentaje con 3 decimales / fuera de rango → 422
    for pct in (10.123, 101, -1, None):
        r = s.post(f"{API}/kyb/case/ubos",
                   json=_ubo_body(ownership_percentage=pct,
                                  document_front_id="doc_x"), timeout=10)
        assert r.status_code == 422, pct
    # CONTROL_BODY con porcentaje → 422
    r = s.post(f"{API}/kyb/case/ubos",
               json=_ubo_body(control_type="CONTROL_BODY",
                              ownership_percentage=50,
                              document_front_id="doc_x"), timeout=10)
    assert r.status_code == 422


def test_02_create_with_docs_and_rep_link(env):
    s, db = env["s"], env["db"]
    # La sección documentation NO está completa: falta beneficial_owners.
    assert _case(env)["sections"]["documentation"]["status"] == "pending"
    # Upload frente (sin ubo_id: alta nueva) + dorso
    front = _upload(s, "ubo_document_front", "dni-frente.pdf")
    assert front.status_code == 200 and "storage_key" not in front.json()
    back = _upload(s, "ubo_document_back", "dni-dorso.pdf")
    fid, bid = front.json()["document_id"], back.json()["document_id"]
    # ubo_id inexistente → 404 / slot societario con ubo_id → 422
    assert _upload(s, "ubo_document_front", ubo_id="ubo_nope").status_code == 404
    assert _upload(s, "tax_registration_certificate",
                   ubo_id="ubo_x").status_code == 422
    # UBO 1: mismo tax_id que el representante legal → vínculo declarativo
    r = s.post(f"{API}/kyb/case/ubos", json=_ubo_body(
        tax_id=REP_TAX, document_front_id=fid, document_back_id=bid),
        timeout=10)
    assert r.status_code == 200
    assert r.json()["is_also_legal_representative"] is True
    env["ids"]["u1"] = r.json()["ubo_id"]
    # Los docs quedan vinculados al ubo
    d = db["kyb_documents"].find_one({"document_id": fid})
    assert d["ubo_id"] == env["ids"]["u1"]
    # UBO 2: otro tax_id → sin vínculo (40%, total 90)
    f2 = _upload(s, "ubo_document_front", "dni2.pdf").json()["document_id"]
    r = s.post(f"{API}/kyb/case/ubos", json=_ubo_body(
        first_name="Ana", last_name="Gómez", tax_id="27222222226",
        ownership_percentage=40.0, document_front_id=f2), timeout=10)
    assert r.status_code == 200
    assert r.json()["is_also_legal_representative"] is False
    env["ids"]["u2"] = r.json()["ubo_id"]
    g = s.get(f"{API}/kyb/case", timeout=10).json()
    assert len(g["ubos"]) == 2 and "storage_key" not in str(g)
    codes = {b["code"] for b in g["progress"]["submit_blockers"]}
    assert "UBO_NOT_CONFIRMED" in codes and g["progress"]["can_submit"] is False


def test_03_confirm_below_100_acknowledgment(env):
    s = env["s"]
    # DDJJ obligatoria
    r = s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": False}, timeout=10)
    assert r.status_code == 422
    # 90% sin acknowledgment → 409 estructurado (modal en el frontend)
    r = s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": True}, timeout=10)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "OWNERSHIP_BELOW_100"
    assert r.json()["detail"]["total_percentage"] == 90.0
    # Con acknowledgment → snapshot exacto del % al momento
    r = s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": True, "acknowledge_incomplete": True},
               timeout=10)
    assert r.status_code == 200
    case = _case(env)
    conf = case["ubo_confirmation"]
    assert conf["acknowledged_incomplete"] is True
    assert conf["ownership_percentage_at_acknowledgment"] == 90.0
    assert conf["total_percentage"] == 90.0 and conf["declared_at"]
    assert case["sections"]["documentation"]["slots"][
        "beneficial_owners"] == "confirmed"
    # Los 5 slots + beneficial_owners ⇒ documentation completa
    assert case["sections"]["documentation"]["status"] == "completed"
    assert env["db"]["audit_logs"].find_one({"action": "kyb.ubo.confirmed"})


def test_04_mutation_invalidates_with_history(env):
    s = env["s"]
    # Edición post-DDJJ (40 → 30): invalida y ARCHIVA el acknowledgment
    r = s.put(f"{API}/kyb/case/ubos/{env['ids']['u2']}", json=_ubo_body(
        first_name="Ana", last_name="Gómez", tax_id="27222222226",
        ownership_percentage=30.0,
        document_front_id="whatever"), timeout=10)
    assert r.status_code == 200
    case = _case(env)
    assert case["ubo_confirmation"] is None
    assert case["sections"]["documentation"]["slots"][
        "beneficial_owners"] is None
    assert case["sections"]["documentation"]["status"] == "pending"
    hist = case["ubo_confirmation_history"]
    assert len(hist) == 1
    h = hist[0]
    assert h["ownership_percentage_at_acknowledgment"] == 90.0
    assert h["invalidated_by_change"]["action"] == "updated"
    assert h["invalidated_by_change"]["ubo_id"] == env["ids"]["u2"]
    before = {(c["ubo_id"], c["ownership_percentage"])
              for c in h["cuadro_before"]}
    after = {(c["ubo_id"], c["ownership_percentage"])
             for c in h["cuadro_after"]}
    assert (env["ids"]["u2"], 40.0) in before
    assert (env["ids"]["u2"], 30.0) in after
    ev = env["db"]["audit_logs"].find_one(
        {"action": "kyb.ubo.confirmation_invalidated"})
    assert ev and ev["metadata"]["cuadro_anterior"]
    assert ev["metadata"]["acknowledgment_archivado"][
        "ownership_percentage_at_acknowledgment"] == 90.0


def test_05_rep_taxid_recompute_does_not_invalidate(env):
    s, db = env["s"], env["db"]
    hist_len = len(_case(env)["ubo_confirmation_history"])
    # El rep legal cambia su CUIT al de Ana → los flags se recalculan
    assert s.put(f"{API}/kyb/case/legal-representative",
                 json={"country_of_residence": "AR",
                       "full_name": "Ana Gómez", "email": "ana@corp.io",
                       "tax_id": "27-22222222-6"},
                 timeout=10).status_code == 200
    u1 = db["kyb_beneficial_owners"].find_one({"ubo_id": env["ids"]["u1"]})
    u2 = db["kyb_beneficial_owners"].find_one({"ubo_id": env["ids"]["u2"]})
    assert u1["is_also_legal_representative"] is False
    assert u2["is_also_legal_representative"] is True
    # No es mutación del cuadro: el historial no crece
    assert len(_case(env)["ubo_confirmation_history"]) == hist_len


def test_06_ownership_over_100_blocks_confirm_and_submit(env):
    s = env["s"]
    # 50 + 60 = 110%
    r = s.put(f"{API}/kyb/case/ubos/{env['ids']['u2']}", json=_ubo_body(
        first_name="Ana", last_name="Gómez", tax_id="27222222226",
        ownership_percentage=60.0, document_front_id="whatever"), timeout=10)
    assert r.status_code == 200
    r = s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": True, "acknowledge_incomplete": True},
               timeout=10)
    assert r.status_code == 422 and "110" in r.json()["detail"]
    # También bloquea el submit — dato imposible, nunca llega a revisión
    r = s.post(f"{API}/kyb/case/submit", timeout=10)
    assert r.status_code == 422
    codes = {m["code"] for m in r.json()["detail"]["missing"]}
    assert "OWNERSHIP_EXCEEDS_100" in codes and "UBO_NOT_CONFIRMED" in codes
    for m in r.json()["detail"]["missing"]:
        assert set(m) == {"code", "section", "description"}


def test_07_delete_last_ubo_and_control_body(env):
    s = env["s"]
    for k in ("u2", "u1"):
        assert s.delete(f"{API}/kyb/case/ubos/{env['ids'][k]}",
                        timeout=10).status_code == 200
    # Delete de inexistente → 404
    assert s.delete(f"{API}/kyb/case/ubos/{env['ids']['u1']}",
                    timeout=10).status_code == 404
    # Sin beneficiarios: confirmar es imposible y el submit lo dice
    r = s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": True}, timeout=10)
    assert r.status_code == 422
    r = s.post(f"{API}/kyb/case/submit", timeout=10)
    codes = {m["code"] for m in r.json()["detail"]["missing"]}
    assert {"UBO_MISSING", "UBO_NOT_CONFIRMED"} <= codes
    # Control body: sin porcentaje, satisface el requisito
    fid = _upload(s, "ubo_document_front", "cb.pdf").json()["document_id"]
    r = s.post(f"{API}/kyb/case/ubos", json=_ubo_body(
        first_name="Pedro", last_name="Directorio", tax_id="20333333339",
        control_type="CONTROL_BODY", ownership_percentage=None,
        document_front_id=fid), timeout=10)
    assert r.status_code == 200
    env["ids"]["cb"] = r.json()["ubo_id"]
    # Solo control body: NO exige acknowledgment aunque el total sea 0
    r = s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": True}, timeout=10)
    assert r.status_code == 200
    assert r.json()["confirmation"]["acknowledged_incomplete"] is False


def test_08_observed_to_resubmitted(env):
    s, db = env["s"], env["db"]
    cid = env["case_id"]
    db["kyb_cases"].update_one({"case_id": cid}, {"$set": {
        "status": "info_required",
        "sections.documentation.status": "observed",
        "sections.documentation.observation": "Falta el dorso del DNI"}})
    # Corrige: edita el UBO (invalida DDJJ, la sección sigue observed)
    r = s.put(f"{API}/kyb/case/ubos/{env['ids']['cb']}", json=_ubo_body(
        first_name="Pedro", last_name="Directorio", tax_id="20333333339",
        control_type="CONTROL_BODY", ownership_percentage=None,
        document_front_id="whatever"), timeout=10)
    assert r.status_code == 200
    case = _case(env)
    assert case["sections"]["documentation"]["status"] == "observed"
    assert len(case["ubo_confirmation_history"]) == 2
    # Re-confirma → resubmitted (no completed) y observación conservada
    assert s.post(f"{API}/kyb/case/ubos/confirm",
                  json={"declaration": True},
                  timeout=10).status_code == 200
    sec = _case(env)["sections"]["documentation"]
    assert sec["status"] == "resubmitted"
    assert sec["observation"] == "Falta el dorso del DNI"


def test_09_ubo_document_versioning(env):
    s, db = env["s"], env["db"]
    db["kyb_cases"].update_one({"case_id": env["case_id"]},
                               {"$set": {"status": "in_progress"}})
    cb = env["ids"]["cb"]
    v1 = _upload(s, "ubo_document_front", "cb-v1.pdf", ubo_id=cb)
    v2 = _upload(s, "ubo_document_front", "cb-v2.pdf", ubo_id=cb)
    assert v1.status_code == 200 and v2.status_code == 200
    docs = sorted(db["kyb_documents"].find(
        {"slot": "ubo_document_front", "ubo_id": cb,
         "document_id": {"$in": [v1.json()["document_id"],
                                 v2.json()["document_id"]]}}),
        key=lambda d: d["version"])
    d1, d2 = docs
    # Versionado incremental dentro del bucket (case, slot, ubo): la nueva
    # versión no pisa, apaga is_current de la anterior.
    assert d2["version"] == d1["version"] + 1
    assert (d1["is_current"], d2["is_current"]) == (False, True)
    only_current = list(db["kyb_documents"].find(
        {"slot": "ubo_document_front", "ubo_id": cb, "is_current": True}))
    assert [d["document_id"] for d in only_current] == \
        [v2.json()["document_id"]]
    # Los docs de otros beneficiarios no se ven afectados
    others = db["kyb_documents"].count_documents(
        {"slot": "ubo_document_front", "ubo_id": {"$ne": cb},
         "is_current": True})
    assert others >= 1
    # Contenido inválido → 422 sin registro ni binario nuevo
    n_docs = db["kyb_documents"].count_documents({})
    n_files = db["prosper_files.files"].count_documents({})
    r = _upload(s, "ubo_document_front", "x.pdf", content=b"no-pdf" * 100)
    assert r.status_code == 422
    assert db["kyb_documents"].count_documents({}) == n_docs
    assert db["prosper_files.files"].count_documents({}) == n_files


def test_10_submit_full_flow(env):
    s, db = env["s"], env["db"]
    cid = env["case_id"]
    db["kyb_cases"].update_one({"case_id": cid},
                               {"$set": {"status": "in_progress"}})
    g = s.get(f"{API}/kyb/case", timeout=10).json()
    assert g["progress"]["can_submit"] is True
    assert g["progress"]["submit_blockers"] == []
    r = s.post(f"{API}/kyb/case/submit", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "submitted" and r.json()["submitted_at"]
    case = _case(env)
    # F8: la respuesta HTTP siempre reporta 'submitted' en el momento del
    # POST, pero el orquestador (kyb.orchestrator.dispatch_on_submit) avanza
    # el caso sincrónicamente hasta 'screening' o 'under_review' cuando no
    # hay verificaciones de proveedor pendientes. La aserción abarca el
    # rango legal post-submit.
    assert case["status"] in ("submitted", "screening", "under_review"), \
        f"estado inesperado tras submit: {case['status']}"
    assert case["submitted_at"]
    assert db["audit_logs"].find_one({"action": "kyb.case.submitted"})
    assert db["audit_logs"].find_one(
        {"action": "kyb.case.state_changed",
         "metadata.from": "in_progress", "metadata.to": "submitted"})
    # Tras el envío: read-only total, y re-submit imposible
    assert s.post(f"{API}/kyb/case/submit", timeout=10).status_code == 403
    r = s.post(f"{API}/kyb/case/ubos", json=_ubo_body(
        document_front_id="x"), timeout=10)
    assert r.status_code == 403
    g = s.get(f"{API}/kyb/case", timeout=10).json()
    assert g["editable"] is False and g["progress"]["can_submit"] is False
