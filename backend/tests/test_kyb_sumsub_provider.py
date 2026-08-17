"""Tests obligatorios del Bloque 2 — SumsubProvider.

Cobertura pedida:
  1. firma HMAC válida → (Applicant, Snapshot)
  2. firma HMAC inválida → ProviderSignatureInvalid (mensaje genérico)
  3. applicant de ambiente cruzado → ProviderEnvironmentMismatch
  4. reintento de ensure_applicant devuelve el MISMO applicant_id
  5. arranque falla si falta SUMSUB_ENVIRONMENT
  6. arranque falla en production sin credenciales productivas
  7. WARNING presente cuando app=prod + SUMSUB_ENVIRONMENT=sandbox
  8. credenciales NO aparecen en logs ni en el health check dict

Todos los tests mockean la API de Sumsub — cero llamadas reales.
Base descartable dedicada, nunca prosper_phase0.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_DB = "prosper_kyb_sumsub_tests"


@pytest.fixture(autouse=True)
async def _iso_db(monkeypatch):
    monkeypatch.setenv("DB_NAME", _DB)
    monkeypatch.setenv("SUMSUB_LEVEL_INDIVIDUAL", "basic-kyc-level")
    monkeypatch.setenv("SUMSUB_LEVEL_UBO", "basic-kyc-level")
    monkeypatch.setenv("SUMSUB_LEVEL_COMPANY", "basic-kyb-level")
    monkeypatch.setenv("KYB_PROVIDER_SUMSUB_ENABLED", "true")
    import db as _dbmod
    _dbmod._client = None
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(_DB)
    yield
    await client.drop_database(_DB)
    client.close()


async def _seed_config(env_: str, api_key="ak_test",
                        secret="s3cr3t", enabled=True):
    """Escribe una fila en kyb_provider_configs con credenciales
    encriptadas del ambiente pedido."""
    import json as _json
    from db import col
    from kyb.models import KYB_PROVIDER_CONFIGS
    from services.secret_box import encrypt
    enc = encrypt(_json.dumps({"api_key": api_key, "secret": secret}))
    await col(KYB_PROVIDER_CONFIGS).update_one(
        {"provider": "sumsub", "environment": env_},
        {"$set": {"category": "identity", "provider": "sumsub",
                    "environment": env_, "enabled": enabled,
                    "credentials_encrypted": enc,
                    "credentials_last4": api_key[-4:]}},
        upsert=True)


async def _seed_case(case_id: str, is_test_case: bool):
    from db import col
    from kyb.models import KYB_CASES
    await col(KYB_CASES).insert_one({
        "case_id": case_id, "status": "submitted",
        "is_test_case": is_test_case, "is_deleted": False})


# ------------------------------------------------------------------
# 4. Reintento de ensure_applicant devuelve el mismo applicant_id
# ------------------------------------------------------------------
async def test_ensure_applicant_idempotent_returns_same_provider_id(
        monkeypatch):
    from kyb.providers.base import SubjectRef
    from kyb.providers.sumsub import SumsubProvider

    await _seed_config("sandbox")
    await _seed_case("kyb_case_t1", is_test_case=True)

    calls = []
    async def fake_request(self, method, path, body=None):
        calls.append((method, path))
        return {"id": "sumsub_applicant_ABC"}
    monkeypatch.setattr(SumsubProvider, "_request", fake_request)

    p = SumsubProvider(environment="sandbox")
    subj = SubjectRef(case_id="kyb_case_t1", subject_type="ubo",
                       subject_id="u1")
    a1 = await p.ensure_applicant(subj, level_hint="identity")
    a2 = await p.ensure_applicant(subj, level_hint="identity")
    assert a1.provider_applicant_id == a2.provider_applicant_id \
        == "sumsub_applicant_ABC"
    # Sumsub sólo fue llamado UNA vez — el reintento se resolvió local
    assert len([c for c in calls if "applicants" in c[1]]) == 1


# ------------------------------------------------------------------
# 3. Applicant de ambiente cruzado → ProviderEnvironmentMismatch
# ------------------------------------------------------------------
async def test_ensure_applicant_refuses_cross_environment(monkeypatch):
    from kyb.providers.base import (ProviderEnvironmentMismatch,
                                     SubjectRef)
    from kyb.providers.sumsub import SumsubProvider

    await _seed_config("sandbox")
    # Caso PRODUCTIVO (is_test_case=False) + provider sandbox
    await _seed_case("kyb_case_prod", is_test_case=False)

    async def fake_request(self, method, path, body=None):
        pytest.fail("no debería haber llamado a sumsub")
    monkeypatch.setattr(SumsubProvider, "_request", fake_request)

    p = SumsubProvider(environment="sandbox")
    subj = SubjectRef(case_id="kyb_case_prod", subject_type="company")
    with pytest.raises(ProviderEnvironmentMismatch):
        await p.ensure_applicant(subj, level_hint="identity")

    # También en sentido inverso
    await _seed_config("production")
    await _seed_case("kyb_case_test", is_test_case=True)
    p2 = SumsubProvider(environment="production")
    subj2 = SubjectRef(case_id="kyb_case_test", subject_type="company")
    with pytest.raises(ProviderEnvironmentMismatch):
        await p2.ensure_applicant(subj2, level_hint="identity")


# ------------------------------------------------------------------
# 1 & 2. Firma HMAC válida / inválida
# ------------------------------------------------------------------
def _sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body,
                     hashlib.sha256).hexdigest()


async def test_validate_webhook_valid_signature_returns_snapshot(monkeypatch):
    from db import col
    from kyb.models import KYB_EXTERNAL_SUBJECTS
    from kyb.providers.base import WebhookPayload
    from kyb.providers.sumsub import SumsubProvider

    await _seed_config("sandbox", secret="w3bh00k_secret")
    await _seed_case("kyb_case_wh1", is_test_case=True)

    await col(KYB_EXTERNAL_SUBJECTS).insert_one({
        "case_id": "kyb_case_wh1", "subject_type": "ubo",
        "subject_id": "u1", "provider": "sumsub", "environment": "sandbox",
        "external_user_id": "eid_wh1",
        "provider_applicant_id": "sumsub_app_1",
        "level_name": "basic-kyc-level"})

    event = {"id": "evt_1", "applicantId": "sumsub_app_1",
              "externalUserId": "eid_wh1", "createdAtMs": 1000,
              "type": "applicantReviewed",
              "reviewResult": {"reviewAnswer": "GREEN"}}
    body = json.dumps(event).encode()
    sig = _sign_payload("w3bh00k_secret", body)

    p = SumsubProvider(environment="sandbox")
    applicant, snap = await p.validate_webhook(
        WebhookPayload(raw_body=body,
                        headers={"x-payload-digest": sig}))
    assert applicant.provider_applicant_id == "sumsub_app_1"
    assert snap.status == "completed"
    assert snap.outcome == "approved"
    assert snap.provider_event_id == "evt_1"
    assert snap.provider_event_ts == 1000
    # validate_webhook NO persiste (Bloque 3 lo hace)
    from kyb.models import KYB_VERIFICATIONS
    assert await col(KYB_VERIFICATIONS).count_documents({}) == 0


async def test_validate_webhook_invalid_signature_generic_message():
    from db import col
    from kyb.models import KYB_EXTERNAL_SUBJECTS
    from kyb.providers.base import (ProviderSignatureInvalid,
                                     WebhookPayload)
    from kyb.providers.sumsub import SumsubProvider

    await _seed_config("sandbox", secret="w3bh00k_secret")
    await col(KYB_EXTERNAL_SUBJECTS).insert_one({
        "case_id": "kyb_case_x", "subject_type": "ubo",
        "subject_id": "u1", "provider": "sumsub", "environment": "sandbox",
        "external_user_id": "eid_bad",
        "provider_applicant_id": "sumsub_app_bad"})

    event = {"id": "evt_2", "applicantId": "sumsub_app_bad",
              "externalUserId": "eid_bad"}
    body = json.dumps(event).encode()

    p = SumsubProvider(environment="sandbox")
    with pytest.raises(ProviderSignatureInvalid) as excinfo:
        await p.validate_webhook(WebhookPayload(
            raw_body=body,
            headers={"x-payload-digest": "0" * 64}))
    # Mensaje genérico: no expone firma recibida ni esperada
    msg = str(excinfo.value)
    assert msg == "invalid webhook signature"
    assert "0000" not in msg
    assert "w3bh00k" not in msg


# ------------------------------------------------------------------
# 5. Startup falla si falta SUMSUB_ENVIRONMENT
# ------------------------------------------------------------------
async def test_startup_check_fails_when_env_missing(monkeypatch):
    from kyb.providers.sumsub import sumsub_startup_check
    monkeypatch.delenv("SUMSUB_ENVIRONMENT", raising=False)
    with pytest.raises(RuntimeError) as e:
        await sumsub_startup_check()
    assert "SUMSUB_ENVIRONMENT" in str(e.value)

    monkeypatch.setenv("SUMSUB_ENVIRONMENT", "staging")
    with pytest.raises(RuntimeError) as e2:
        await sumsub_startup_check()
    assert "SUMSUB_ENVIRONMENT" in str(e2.value)


# ------------------------------------------------------------------
# 6. Startup falla en production sin credenciales productivas
# ------------------------------------------------------------------
async def test_startup_check_fails_in_prod_without_creds(monkeypatch):
    from kyb.providers.sumsub import sumsub_startup_check
    monkeypatch.setenv("SUMSUB_ENVIRONMENT", "production")
    # KYB_PROVIDER_SUMSUB_ENABLED=true (autouse fixture)
    # kyb_provider_configs vacío → no hay credenciales
    with pytest.raises(RuntimeError) as e:
        await sumsub_startup_check()
    assert "production" in str(e.value).lower()


# ------------------------------------------------------------------
# 7. WARNING cuando app=prod + SUMSUB_ENVIRONMENT=sandbox
# ------------------------------------------------------------------
async def test_startup_warning_when_app_prod_sumsub_sandbox(monkeypatch,
                                                              caplog):
    from kyb.providers.sumsub import sumsub_startup_check
    monkeypatch.setenv("SUMSUB_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("KYB_ENVIRONMENT", "production")
    await _seed_config("sandbox")
    with caplog.at_level(logging.WARNING, logger="prosper.kyb.sumsub"):
        result = await sumsub_startup_check()
    assert result["environment"] == "sandbox"
    assert result["status"] == "ok"
    assert result["warning"] is not None
    assert "sandbox" in result["warning"].lower()
    # WARNING presente en logs
    assert any("SUMSUB" in rec.message and "sandbox" in rec.message.lower()
                for rec in caplog.records)


# ------------------------------------------------------------------
# 8. Credenciales nunca en logs ni en health/startup dict
# ------------------------------------------------------------------
async def test_credentials_not_in_startup_dict_or_logs(monkeypatch, caplog):
    from kyb.providers.sumsub import sumsub_startup_check
    monkeypatch.setenv("SUMSUB_ENVIRONMENT", "sandbox")
    await _seed_config("sandbox",
                        api_key="ak_LEAK_KEY_12345",
                        secret="s3cr3t_LEAK_SECRET_XY")
    with caplog.at_level(logging.DEBUG, logger="prosper.kyb"):
        result = await sumsub_startup_check()
    # Ninguna credencial aparece en el dict del health check
    dump = json.dumps(result)
    assert "ak_LEAK_KEY_12345" not in dump
    assert "s3cr3t_LEAK_SECRET" not in dump
    assert "credentials_last4" not in dump
    # Ninguna credencial aparece en logs
    for rec in caplog.records:
        assert "ak_LEAK_KEY_12345" not in rec.getMessage()
        assert "s3cr3t_LEAK_SECRET" not in rec.getMessage()

    # Test extra: en un error de firma, tampoco filtra
    from db import col
    from kyb.models import KYB_EXTERNAL_SUBJECTS
    from kyb.providers.base import (ProviderSignatureInvalid,
                                     WebhookPayload)
    from kyb.providers.sumsub import SumsubProvider
    await col(KYB_EXTERNAL_SUBJECTS).insert_one({
        "case_id": "kyb_case_leak", "subject_type": "ubo",
        "subject_id": "u1", "provider": "sumsub", "environment": "sandbox",
        "external_user_id": "eid_leak",
        "provider_applicant_id": "sumsub_app_leak"})
    p = SumsubProvider(environment="sandbox")
    body = json.dumps({"applicantId": "sumsub_app_leak",
                        "externalUserId": "eid_leak"}).encode()
    with pytest.raises(ProviderSignatureInvalid) as e:
        await p.validate_webhook(WebhookPayload(
            raw_body=body,
            headers={"x-payload-digest": "wrongsig123"}))
    err = str(e.value)
    assert "s3cr3t_LEAK_SECRET" not in err
    assert "wrongsig123" not in err
    assert "ak_LEAK_KEY" not in err
