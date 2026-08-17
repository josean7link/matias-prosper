"""Bloque 3 — orchestrator hook + Sumsub webhook receiver.

Tests obligatorios (8):
  1. Duplicado x3 → un solo cambio de estado
  2. Fuera de orden → descartado y registrado
  3. Firma inválida → 401, nada modificado
  4. Ambiente cruzado → 409, nada modificado
  5. Revisión post-aprobación → apply_transition approved→under_review
     con reopen_reason=provider_alert
  6. Fallo del proveedor en _dispatch_category → ok=False, caso sigue
  7. Flag apagado → orchestrator devuelve skipped_no_provider byte-a-byte
  8. raw_response_ref poblado y recuperable
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_DB = "prosper_kyb_wh_sumsub_tests"


@pytest.fixture(autouse=True)
async def _iso(monkeypatch):
    monkeypatch.setenv("DB_NAME", _DB)
    monkeypatch.setenv("SUMSUB_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("SUMSUB_LEVEL_INDIVIDUAL", "kyc-level")
    monkeypatch.setenv("SUMSUB_LEVEL_UBO", "kyc-level")
    monkeypatch.setenv("SUMSUB_LEVEL_COMPANY", "kyb-level")
    monkeypatch.setenv("KYB_MODULE_ENABLED", "true")
    import db as _dbmod
    _dbmod._client = None
    from kyb.providers.registry import _reset_cache_for_tests
    _reset_cache_for_tests()
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(_DB)
    yield
    await client.drop_database(_DB)
    client.close()


async def _seed_config(env_="sandbox", secret="w3bh00k_secret"):
    from db import col
    from kyb.models import KYB_PROVIDER_CONFIGS
    from services.secret_box import encrypt
    enc = encrypt(json.dumps({"api_key": "ak", "secret": secret}))
    await col(KYB_PROVIDER_CONFIGS).update_one(
        {"provider": "sumsub", "environment": env_},
        {"$set": {"category": "identity", "provider": "sumsub",
                    "environment": env_, "enabled": True,
                    "credentials_encrypted": enc,
                    "credentials_last4": "test"}}, upsert=True)


async def _seed_case_and_applicant(case_id="kyb_wh_case", is_test=True,
                                     status="under_review",
                                     applicant_id="app_1"):
    from db import col
    from kyb.models import KYB_CASES, KYB_EXTERNAL_SUBJECTS
    await col(KYB_CASES).insert_one({
        "case_id": case_id, "status": status,
        "is_test_case": is_test, "is_deleted": False})
    await col(KYB_EXTERNAL_SUBJECTS).insert_one({
        "case_id": case_id, "subject_type": "ubo",
        "subject_id": "u1", "provider": "sumsub", "environment": "sandbox",
        "external_user_id": "eid_1",
        "provider_applicant_id": applicant_id,
        "level_name": "kyc-level"})


def _make_event(applicant_id="app_1", event_id="evt_1", ts=1000,
                 answer="GREEN"):
    return {"id": event_id, "applicantId": applicant_id,
             "externalUserId": "eid_1", "createdAtMs": ts,
             "type": "applicantReviewed",
             "reviewResult": {"reviewAnswer": answer,
                              "rejectLabels": []}}


def _sig(secret, body): return hmac.new(secret.encode(), body,
                                          hashlib.sha256).hexdigest()


# ------------------------------------------------------------------
# 7. Flag OFF — orchestrator conserva skipped_no_provider byte-a-byte
# ------------------------------------------------------------------
async def test_orchestrator_flag_off_returns_skipped_byte_for_byte(
        monkeypatch):
    from kyb.orchestrator import _dispatch_category
    monkeypatch.setenv("KYB_PROVIDER_SUMSUB_ENABLED", "false")
    case = {"case_id": "kyb_orchoff", "verification_modes":
            {"identity": "automatic"}, "verification_states": {}}
    out = await _dispatch_category(case, "identity", "automatic",
                                    trigger="submit", actor=None,
                                    request=None)
    assert out == {"category": "identity", "mode": "automatic",
                    "ok": True, "checks_created": 0,
                    "provider_pending": False,
                    "note": "skipped_no_provider"}


# ------------------------------------------------------------------
# 6. Fallo del proveedor → ok=False, no tumba el submit
# ------------------------------------------------------------------
async def test_dispatch_category_provider_failure_ok_false(monkeypatch):
    from kyb.orchestrator import _dispatch_category
    from kyb.providers.base import (ProviderError, SubjectRef,
                                     VerificationSnapshot)
    from kyb.providers.registry import _reset_cache_for_tests
    monkeypatch.setenv("KYB_PROVIDER_SUMSUB_ENABLED", "true")
    _reset_cache_for_tests()

    class FailingProvider:
        async def ensure_applicant(self, subject, *, level_hint):
            raise ProviderError("boom")
        async def start_verification(self, *a, **kw):
            raise AssertionError("must not be called")

    async def fake_get_provider(cap):
        return FailingProvider()
    monkeypatch.setattr("kyb.providers.registry.get_provider",
                         fake_get_provider)

    case = {"case_id": "kyb_fail", "verification_modes":
            {"identity": "automatic"},
            "ubos": [{"ubo_id": "u1"}]}
    out = await _dispatch_category(case, "identity", "automatic",
                                    trigger="submit", actor=None,
                                    request=None)
    assert out["ok"] is False
    assert "boom" in out.get("error", "")


# ------------------------------------------------------------------
# 3. Firma inválida → 401
# 4. Ambiente cruzado → 409
# 1. Duplicado x3 → 1 sólo doc
# 2. Fuera de orden → descartado
# 5. Post-aprobación → apply_transition
# 8. raw_response_ref recuperable
# ------------------------------------------------------------------
async def _post_webhook(app, body, sig, port_ok=200):
    """Utility para invocar el receptor con TestClient async."""
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport,
                            base_url="http://t") as c:
        return await c.post("/api/v1/kyb/webhooks/sumsub",
                             content=body,
                             headers={"content-type": "application/json",
                                       "x-payload-digest": sig})


@pytest.fixture
async def app():
    monkey_env = {"KYB_PROVIDER_SUMSUB_ENABLED": "true"}
    for k, v in monkey_env.items():
        os.environ[k] = v
    from server import app as _app
    yield _app


async def test_invalid_signature_returns_401(app):
    from db import col
    from kyb.models import KYB_VERIFICATIONS
    await _seed_config()
    await _seed_case_and_applicant()
    body = json.dumps(_make_event()).encode()
    r = await _post_webhook(app, body, sig="deadbeef")
    assert r.status_code == 401
    # Nada modificado
    await asyncio.sleep(0.1)
    assert await col(KYB_VERIFICATIONS).count_documents({}) == 0


async def test_env_mismatch_returns_409(app):
    from db import col
    from kyb.models import KYB_CASES, KYB_VERIFICATIONS
    await _seed_config()
    # Caso is_test_case=False + applicant sandbox → mismatch
    await _seed_case_and_applicant(is_test=False)
    body = json.dumps(_make_event()).encode()
    r = await _post_webhook(app, body, _sig("w3bh00k_secret", body))
    assert r.status_code == 409
    await asyncio.sleep(0.1)
    assert await col(KYB_VERIFICATIONS).count_documents({}) == 0


async def test_duplicate_delivered_thrice_only_one_effect(app):
    from db import col
    from kyb.models import KYB_VERIFICATIONS
    await _seed_config()
    await _seed_case_and_applicant()
    body = json.dumps(_make_event()).encode()
    sig = _sig("w3bh00k_secret", body)
    # Crear el índice de idempotencia (db_setup.py corre en startup, pero
    # el TestClient ASGI puede saltarlo — lo forzamos):
    await col(KYB_VERIFICATIONS).create_index(
        [("provider_event_id", 1), ("provider_reference", 1)],
        unique=True, sparse=True, name="uniq_provider_event_idempotency")
    for _ in range(3):
        r = await _post_webhook(app, body, sig)
        assert r.status_code == 200
    await asyncio.sleep(0.3)  # esperar el asyncio.create_task
    n = await col(KYB_VERIFICATIONS).count_documents(
        {"provider_event_id": "evt_1"})
    assert n == 1, f"esperaba 1, obtuve {n}"


async def test_out_of_order_event_dropped(app):
    from db import col
    from kyb.models import KYB_VERIFICATIONS
    await _seed_config()
    await _seed_case_and_applicant()
    await col(KYB_VERIFICATIONS).create_index(
        [("provider_event_id", 1), ("provider_reference", 1)],
        unique=True, sparse=True, name="uniq_provider_event_idempotency")
    # Nuevo llega primero
    ev_new = json.dumps(_make_event(event_id="evt_new", ts=5000)).encode()
    r1 = await _post_webhook(app, ev_new, _sig("w3bh00k_secret", ev_new))
    assert r1.status_code == 200
    await asyncio.sleep(0.3)
    # Viejo llega después
    ev_old = json.dumps(_make_event(event_id="evt_old", ts=1000)).encode()
    r2 = await _post_webhook(app, ev_old, _sig("w3bh00k_secret", ev_old))
    assert r2.status_code == 200
    await asyncio.sleep(0.3)
    n_new = await col(KYB_VERIFICATIONS).count_documents(
        {"provider_event_id": "evt_new"})
    n_old = await col(KYB_VERIFICATIONS).count_documents(
        {"provider_event_id": "evt_old"})
    assert n_new == 1 and n_old == 0, (
        f"esperaba evt_new=1, evt_old=0; obtuve {n_new}/{n_old}")


async def test_post_approval_review_triggers_apply_transition(app):
    from db import col
    from kyb.models import KYB_CASES, KYB_VERIFICATIONS
    await _seed_config()
    # Caso YA aprobado
    await _seed_case_and_applicant(status="approved")
    await col(KYB_VERIFICATIONS).create_index(
        [("provider_event_id", 1), ("provider_reference", 1)],
        unique=True, sparse=True, name="uniq_provider_event_idempotency")
    body = json.dumps(_make_event(answer="RED")).encode()
    r = await _post_webhook(app, body, _sig("w3bh00k_secret", body))
    assert r.status_code == 200
    await asyncio.sleep(0.5)
    case = await col(KYB_CASES).find_one({"case_id": "kyb_wh_case"})
    assert case["status"] == "under_review", (
        f"apply_transition debía dejarlo under_review, got {case['status']}")
    # Auditoría de la transición existe (event=state_changed con
    # reopen_reason=provider_alert)
    from db import col as _c
    log = await _c("audit_logs").find_one({
        "action": "kyb.case.state_changed",
        "metadata.reopen_reason": "provider_alert",
        "resource_id": "kyb_wh_case"})
    assert log is not None


async def test_raw_response_ref_populated_and_recoverable(app):
    from db import col
    from kyb.models import KYB_VERIFICATIONS
    from services.storage.factory import get_storage
    await _seed_config()
    await _seed_case_and_applicant()
    await col(KYB_VERIFICATIONS).create_index(
        [("provider_event_id", 1), ("provider_reference", 1)],
        unique=True, sparse=True, name="uniq_provider_event_idempotency")
    body = json.dumps(_make_event()).encode()
    r = await _post_webhook(app, body, _sig("w3bh00k_secret", body))
    assert r.status_code == 200
    await asyncio.sleep(0.5)
    doc = await col(KYB_VERIFICATIONS).find_one(
        {"provider_event_id": "evt_1"})
    assert doc is not None
    assert doc["raw_response_ref"], "raw_response_ref debe estar poblado"
    # Recuperable via StorageBackend
    storage = get_storage()
    content, _meta = await storage.get(doc["raw_response_ref"])
    assert content == body, "el body crudo debe ser byte-idéntico"
