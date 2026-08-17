"""Tests e2e Fase 7 — Screening / Registro / Export / Providers / Riesgo.
Server efímero 8019 + scratch `prosper_kyb_tests_phase7`.

Cobertura:
  * Resolución de hits (20 chars, valores, gate de aprobación).
  * Promote/demote bloqueante manual (fuera del template).
  * Vista Screening agrupada por sujeto.
  * Vista Registro (mode manual → mapping item_key ↔ campo por notas).
  * Registry accept / observe (observe inyecta observation en la sección).
  * Rerun-verifications idempotente.
  * Export ZIP con case.json / resumen.pdf / documents/ / manual_evidence/
    / audit.jsonl / MANIFEST.
  * Providers: CRUD, last4, health-check, enable en producción requiere
    health OK, contador de webhooks con firma inválida.
  * Modelo de riesgo: default bootstrap, save incrementa versión, preview,
    recompute persiste model_version.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

_DB = "prosper_kyb_tests_phase7"
_PORT = 8019
API = f"http://127.0.0.1:{_PORT}/api/v1"
ADMIN = f"{API}/admin/compliance/kyb"
PDF = b"%PDF-1.4\n" + b"x" * 2048
SLOTS = ["tax_registration_certificate", "constitutive_document",
         "funds_origin_evidence", "authorities_appointment",
         "company_proof_of_address"]
INTERNALS = [("super@prosper.foundation", "super_admin"),
             ("compliance@prosper.foundation", "compliance_officer"),
             ("compl2@prosper.foundation", "compliance_officer")]


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
    # F7 usa el path de encrypt de credenciales; el key de integraciones
    # tiene que estar cargado para el test de providers.
    from cryptography.fernet import Fernet as _F
    senv = {**os.environ, "DB_NAME": _DB, "KYB_MODULE_ENABLED": "true",
            "KYB_ENVIRONMENT": "production", "KYB_SLA_HOURS": "72",
            "PROSPER_DISABLE_RATELIMIT": "1", "RESEND_API_KEY": "",
            "DEMO_MODE": "true",
            "INTEGRATIONS_FERNET_KEY":
                os.environ.get("INTEGRATIONS_FERNET_KEY")
                or _F.generate_key().decode()}
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
            raise RuntimeError("server 8019 no arrancó en 120s")
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
        # Caso submitted para todos los tests
        s = requests.Session()
        tok = s.post(f"{API}/kyb/signup/start",
                     json={"email": "p7@preview-prosper.io",
                           "company_name": "Fase7 Corp SA"},
                     timeout=10).json()["signup_token"]
        s.post(f"{API}/kyb/signup/contact", json={
            "signup_token": tok, "full_name": "T",
            "phone": {"country_code": "+54", "number": "1150000009"}},
            timeout=10)
        s.post(f"{API}/kyb/signup/country",
               json={"signup_token": tok, "country": "AR"}, timeout=10)
        act = re.search(r"token=([\w\-]+)", db["outbound_emails"].find_one(
            {"to": "p7@preview-prosper.io"})["html"]).group(1)
        s.post(f"{API}/kyb/signup/activate",
               json={"activation_token": act}, timeout=10)
        keys = [d["document_key"] for d in
                s.get(f"{API}/kyb/case", timeout=10).json()["legal_docs"]]
        s.put(f"{API}/kyb/case/tax-identification",
              json={"tax_id": _cuit(), "accepted_documents": keys},
              timeout=10)
        s.put(f"{API}/kyb/case/legal-representative",
              json={"country_of_residence": "AR", "full_name": "Rep Uno",
                    "email": "rep@p7.io", "tax_id": "20111111112"},
              timeout=10)
        for p, b in [("legal-name", {"legal_name": "Fase7 Corp SA",
                                     "legal_structure": "SA"}),
                     ("data", {"activity_description": "x" * 120}),
                     ("address", {"raw": "Av 9 de Julio 1", "city": "CABA",
                                  "country": "AR"}),
                     ("operations", {"estimated_monthly_volume_usd": 5000,
                                     "purposes": ["YIELD_ARS"],
                                     "funds_subscribed": ["PROSPER_ARS"]}),
                     ("funds-origin", {"type": "OWN_TREASURY"})]:
            s.put(f"{API}/kyb/case/company/{p}", json=b, timeout=10)
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
            "ownership_percentage": 100.0, "document_front_id": fid,
            "is_pep": True}, timeout=10)
        s.post(f"{API}/kyb/case/ubos/confirm",
               json={"declaration": True}, timeout=10)
        rs = s.post(f"{API}/kyb/case/submit", timeout=10)
        assert rs.status_code == 200, rs.text
        cid = db["kyb_cases"].find_one(
            {"applicant_email": "p7@preview-prosper.io"})["case_id"]
        yield {"db": db, "cid": cid, "uid": uid, "client": s,
               "super": _login("super@prosper.foundation"),
               "compl": _login("compliance@prosper.foundation"),
               "compl2": _login("compl2@prosper.foundation")}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        for c, n in base.items():
            assert real[c].count_documents({}) == n, \
                f"¡{c} REAL cambió durante los tests!"
        mongo.drop_database(_DB)
        mongo.close()


def _seed_hit(db, cid, **over):
    from models import utc_now
    doc = {"hit_id": over.get("hit_id", "hit_p7_a"), "case_id": cid,
           "verification_id": None,
           "subject_type": "company", "subject_id": cid,
           "subject_name": "Fase7 Corp SA",
           "list_type": "screening", "list_name": "OFAC",
           "matched_name": "Fase7 Corp SA", "match_score": 92.5,
           "is_blocking": True, "details": {"src": "seed"},
           "source": "provider", "provider_hit_id": "provider_hit_1",
           "detected_after_approval": False, "resolution": None,
           "provider_sync": None,
           "created_at": utc_now(), "updated_at": utc_now()}
    doc.update(over)
    db["kyb_screening_hits"].insert_one(doc)
    return doc["hit_id"]


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
def test_01_screening_view_and_resolve(env):
    compl, cid, db = env["compl"], env["cid"], env["db"]
    hid = _seed_hit(db, cid)
    r = compl.get(f"{ADMIN}/cases/{cid}/screening", timeout=10).json()
    groups_by_type = {g["subject_type"]: g for g in r["groups"]}
    assert "company" in groups_by_type and "legal_representative" in groups_by_type
    assert any(h["hit_id"] == hid for h in groups_by_type["company"]["hits"])
    assert r["blocking_hits"] == 1
    # Aprobación bloqueada por hit bloqueante sin resolver
    rej = compl.post(f"{ADMIN}/cases/{cid}/approve", timeout=10)
    assert rej.status_code == 422
    assert any(b["code"] == "BLOCKING_HITS"
               for b in rej.json()["detail"]["blockers"])
    # Notas cortas → 422
    r1 = compl.post(f"{ADMIN}/hits/{hid}/resolve",
                    json={"decision": "confirmed", "notes": "corta"},
                    timeout=10)
    assert r1.status_code == 422
    # Decisión inválida → 422
    r2 = compl.post(f"{ADMIN}/hits/{hid}/resolve",
                    json={"decision": "nope",
                          "notes": "x" * 25}, timeout=10)
    assert r2.status_code == 422
    # OK: confirmed (no rechaza automáticamente, solo deja de bloquear)
    r3 = compl.post(f"{ADMIN}/hits/{hid}/resolve",
                    json={"decision": "confirmed",
                          "notes": "Coincidencia confirmada por análisis "
                                   "documental del reporte de la lista"},
                    timeout=10)
    assert r3.status_code == 200
    doc = db["kyb_screening_hits"].find_one({"hit_id": hid})
    assert doc["resolution"]["decision"] == "confirmed"
    assert doc["provider_sync"]["pending"] is True  # source=provider
    # Doble resolve → 409
    assert compl.post(f"{ADMIN}/hits/{hid}/resolve",
                      json={"decision": "false_positive",
                            "notes": "x" * 25},
                      timeout=10).status_code == 409
    # Auditoría
    assert db["audit_logs"].find_one({"action": "kyb.hit.resolved"})
    assert db["audit_logs"].find_one(
        {"action": "kyb.hit.provider_sync_scheduled"})


def test_02_manual_hit_no_provider_sync(env):
    compl, cid, db = env["compl"], env["cid"], env["db"]
    hid = _seed_hit(db, cid, hit_id="hit_p7_manual", source="manual",
                    provider_hit_id=None, is_blocking=False)
    r = compl.post(f"{ADMIN}/hits/{hid}/resolve",
                   json={"decision": "false_positive",
                         "notes": "Falso positivo — homónimo sin coincidencia "
                                  "de fecha de nacimiento"}, timeout=10)
    assert r.status_code == 200
    doc = db["kyb_screening_hits"].find_one({"hit_id": hid})
    # Los hits manuales NO se propagan
    assert doc["provider_sync"] is None
    assert doc["resolution"]["decision"] == "false_positive"


def test_03_promote_demote_blocking(env):
    compl, cid, db = env["compl"], env["cid"], env["db"]
    hid = _seed_hit(db, cid, hit_id="hit_p7_prom", is_blocking=False,
                    source="manual", provider_hit_id=None)
    # motivo corto → 422
    assert compl.post(f"{ADMIN}/hits/{hid}/promote-blocking",
                      json={"reason": "corto"}, timeout=10).status_code == 422
    r = compl.post(f"{ADMIN}/hits/{hid}/promote-blocking",
                   json={"reason": "Requiere revisión previa a aprobar"},
                   timeout=10)
    assert r.status_code == 200
    assert db["kyb_screening_hits"].find_one(
        {"hit_id": hid})["is_blocking"] is True
    # Segundo promote → 409
    assert compl.post(f"{ADMIN}/hits/{hid}/promote-blocking",
                      json={"reason": "otra vez el mismo caso"},
                      timeout=10).status_code == 409
    r = compl.post(f"{ADMIN}/hits/{hid}/demote-blocking",
                   json={"reason": "Aclarada la coincidencia con el analista"},
                   timeout=10)
    assert r.status_code == 200
    assert db["kyb_screening_hits"].find_one(
        {"hit_id": hid})["is_blocking"] is False


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def test_04_registry_view_manual_mode(env):
    compl, cid = env["compl"], env["cid"]
    r = compl.get(f"{ADMIN}/cases/{cid}/registry", timeout=10).json()
    assert r["mode"] == "manual" and r["verified_source"] == "manual"
    by_field = {f["field"]: f for f in r["fields"]}
    # Declarado presente
    assert by_field["legal_name"]["declared"] == "Fase7 Corp SA"
    # Sin ítems del checklist completados: verified queda None
    assert by_field["legal_name"]["verified"] is None
    assert by_field["legal_name"]["match"] is None


def test_05_registry_verified_maps_from_check_notes(env):
    compl, cid, db = env["compl"], env["cid"], env["db"]
    # Aseguramos que existen checks para company_registry
    compl.post(f"{ADMIN}/cases/{cid}/manual-checks/generate", timeout=10)
    check = db["kyb_manual_checks"].find_one(
        {"case_id": cid, "category": "company_registry"})
    assert check, "no hay checklist company_registry generado"
    # Inyectamos un ítem con item_key='legal_name' para la simulación
    # de mapping campo↔item. El template AR real no lo trae; lo agregamos
    # en el doc del check para probar el mapping.
    db["kyb_manual_checks"].update_one(
        {"check_id": check["check_id"]},
        {"$push": {"items": {
            "item_key": "legal_name", "label": "Razón social observada",
            "possible_outcomes": ["clear"], "outcome": "clear",
            "notes": "Fase7 Corp SA", "evidence_document_ids": [],
            "completed_by": env["uid"]["compliance"],
            "completed_at": None, "order": 99}}})
    r = compl.get(f"{ADMIN}/cases/{cid}/registry", timeout=10).json()
    field = next(f for f in r["fields"] if f["field"] == "legal_name")
    assert field["verified"] == "Fase7 Corp SA"
    assert field["match"] is True


def test_06_registry_accept_and_observe_writes_section(env):
    compl, cid, db = env["compl"], env["cid"], env["db"]
    r = compl.post(f"{ADMIN}/cases/{cid}/registry/legal_name/accept",
                   json={"action": "accept",
                         "notes": "Coincide con Boletín Oficial"},
                   timeout=10)
    assert r.status_code == 200
    # Observar inyecta observation en la sección company_data
    r = compl.post(f"{ADMIN}/cases/{cid}/registry/activity_description/accept",
                   json={"action": "observe",
                         "notes": "Ampliar detalle de línea de negocio"},
                   timeout=10)
    assert r.status_code == 200
    case = db["kyb_cases"].find_one({"case_id": cid})
    sec = case["sections"]["company_data"]
    assert sec["status"] == "observed"
    assert "activity_description" in sec["observation"]
    # field inválido → 422
    assert compl.post(f"{ADMIN}/cases/{cid}/registry/no_existe/accept",
                      json={"action": "accept",
                            "notes": "12345678901"},
                      timeout=10).status_code == 422
    assert db["audit_logs"].find_one(
        {"action": "kyb.case.registry_field_accepted"})
    assert db["audit_logs"].find_one(
        {"action": "kyb.case.registry_field_observed"})


# ---------------------------------------------------------------------------
# Rerun
# ---------------------------------------------------------------------------
def test_07_rerun_idempotent(env):
    compl, cid = env["compl"], env["cid"]
    r = compl.post(f"{ADMIN}/cases/{cid}/rerun-verifications", timeout=10)
    assert r.status_code == 200
    # Ya se generaron en test_05 → no debe crear más
    assert r.json()["generated"] == 0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def test_08_export_zip_structure(env):
    compl, cid = env["compl"], env["cid"]
    r = compl.get(f"{ADMIN}/cases/{cid}/export", timeout=30)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "case.json" in names
    assert "resumen.pdf" in names
    assert "audit.jsonl" in names
    assert "MANIFEST.txt" in names
    assert "manual_evidence/README.md" in names
    # Documentos por slot: al menos constitutive_document está en documents/
    assert any(n.startswith("documents/constitutive_document/")
               for n in names), names
    # PDF válido (empieza con %PDF)
    assert zf.read("resumen.pdf").startswith(b"%PDF")
    # case.json sin storage_key ni _id ni raw_response_ref
    body = zf.read("case.json").decode()
    assert "storage_key" not in body
    assert '"_id"' not in body


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
def test_09_providers_config_and_health(env):
    sup, compl, db = env["super"], env["compl"], env["db"]
    # compliance no puede ver la pantalla de proveedores
    assert compl.get(f"{ADMIN}/settings/providers",
                     timeout=10).status_code == 403
    r = sup.get(f"{ADMIN}/settings/providers", timeout=10).json()
    assert any(x["category"] == "identity" and x["provider"] == "sumsub"
               for x in r["items"])
    assert r["webhook_invalid_signatures_30d"] == 0
    # Update: environment + credentials
    r = sup.put(f"{ADMIN}/settings/providers/identity/sumsub",
                json={"environment": "sandbox",
                      "credentials": "test_secret_ABCDEFG"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["credentials_last4"].endswith("DEFG")
    assert "credentials_encrypted" not in r.json()
    # Health-check pasa: creds + env presentes
    r = sup.post(f"{ADMIN}/settings/providers/identity/sumsub/health-check",
                 timeout=10).json()
    assert r["ok"] is True
    # Producción sin health OK → 409
    sup.put(f"{ADMIN}/settings/providers/screening/sumsub",
            json={"environment": "production",
                  "credentials": "prod_secret_XYZ12"}, timeout=10)
    r = sup.post(f"{ADMIN}/settings/providers/screening/sumsub/enable",
                 json={"enabled": True}, timeout=10)
    assert r.status_code == 409
    # Después de health-check OK → sí
    sup.post(f"{ADMIN}/settings/providers/screening/sumsub/health-check",
             timeout=10)
    r = sup.post(f"{ADMIN}/settings/providers/screening/sumsub/enable",
                 json={"enabled": True}, timeout=10)
    assert r.status_code == 200
    # Auditoría
    assert db["audit_logs"].find_one({"action": "kyb.provider.enabled"})
    assert db["audit_logs"].find_one(
        {"action": "kyb.provider.health_check"})


# ---------------------------------------------------------------------------
# Modelo de riesgo
# ---------------------------------------------------------------------------
def test_10_risk_model_bootstrap_save_preview_recompute(env):
    sup, cid, db = env["super"], env["cid"], env["db"]
    # Bootstrap: sin doc previo → devuelve default y persiste v1
    r = sup.get(f"{ADMIN}/settings/risk-model", timeout=10).json()
    assert r["version"] == 1 and r["active"] is True
    assert any(f["key"] == "is_pep" for f in r["factors"])
    # Compliance no accede al risk-model
    assert env["compl"].get(f"{ADMIN}/settings/risk-model",
                            timeout=10).status_code == 403
    # Preview con thresholds muy bajos → todos los casos pasan a high
    preview = sup.post(f"{ADMIN}/settings/risk-model/preview", json={
        "factors": r["factors"],
        "thresholds": {"low_max": 0, "medium_max": 0},
        "review_months": r["review_months"]}, timeout=10).json()
    assert preview["cases_evaluated"] >= 1
    # Save → nueva versión activa
    r2 = sup.put(f"{ADMIN}/settings/risk-model", json={
        "factors": r["factors"],
        "thresholds": {"low_max": 10, "medium_max": 30},
        "review_months": r["review_months"]}, timeout=10).json()
    assert r2["version"] == 2
    active = db["kyb_risk_model_versions"].find_one({"active": True})
    assert active["version"] == 2
    # Recompute: persiste risk con model_version=2
    r3 = sup.post(f"{ADMIN}/settings/risk-model/recompute/{cid}",
                  timeout=10).json()
    assert r3["risk"]["model_version"] == 2
    assert r3["risk"]["level"] in ("low", "medium", "high")
    case = db["kyb_cases"].find_one({"case_id": cid})
    assert case["risk"]["model_version"] == 2
    # Historial expone ambas versiones
    hist = sup.get(f"{ADMIN}/settings/risk-model/history", timeout=10).json()
    assert {i["version"] for i in hist["items"]} >= {1, 2}
    assert db["audit_logs"].find_one({"action": "kyb.risk_model.published"})
    assert db["audit_logs"].find_one({"action": "kyb.case.risk_recomputed"})
