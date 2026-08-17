"""Tests del canal AiPrise KYB corporativo — log-and-drop.

El módulo KYB nuevo es dueño exclusivo de `organizations.kyb_status`.
`_apply_kyb_decision` fue neutralizado: registra el evento en
`webhook_kyb_dropped_events` + emite audit `aiprise.kyb.dropped_for_corporate`,
y NO escribe `organizations.kyb_status`, `onboarding_applications`,
`kyb_status` de app, wallets, ramp o users.

Corre en base scratch `prosper_aiprise_kyb_dropped_tests` (drop en teardown).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SCRATCH_DB = "prosper_aiprise_kyb_dropped_tests"
_ORIG_DB_NAME = os.environ.get("DB_NAME")
_ORIG_SECRET = os.environ.get("AIPRISE_WEBHOOK_SECRET")

# Fijamos secret ANTES del import del router para que `webhook_secret()`
# lo lea del env.
os.environ["AIPRISE_WEBHOOK_SECRET"] = "test-secret-for-hmac"

import db as db_module                                            # noqa: E402
from routes.webhooks_aiprise import router as aiprise_router      # noqa: E402


def _sign(body: bytes, secret: str = "test-secret-for-hmac") -> str:
    return hmac.new(secret.encode(), body,
                    hashlib.sha256).hexdigest()


@pytest_asyncio.fixture()
async def _scratch():
    """Base scratch dedicada. Instala un onboarding_application + org
    corporativa y devuelve la DB + un TestClient con solo el router de
    AiPrise montado."""
    os.environ["DB_NAME"] = _SCRATCH_DB
    db_module._client = None
    admin = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await admin.drop_database(_SCRATCH_DB)
    d = db_module.db()

    await d["organizations"].insert_one({
        "org_id": "org_test_corp", "type": "fintech",
        "kyb_status": "in_review", "legal_name": "Corp Test S.A.",
        "is_deleted": False})
    await d["organizations"].insert_one({
        "org_id": "org_test_personal", "type": "personal",
        "kyb_status": "pending", "legal_name": "Juan Personal",
        "is_deleted": False})
    await d["onboarding_applications"].insert_one({
        "application_id": "app_test_corp",
        "org_id": "org_test_corp",
        "aiprise_session_id": "aiprise_session_abc123",
        "status": "in_review",
        "kyb_status": "in_review",
        "is_deleted": False,
        "legal_name": "Corp Test S.A."})
    await d["users"].insert_one({
        "user_id": "usr_test_personal",
        "email": "juan@personal.example",
        "org_id": "org_test_personal",
        "kyc_status": "pending",
        "kyc_session_id": "aiprise_kyc_session_xyz",
        "role": "client_user",
        "status": "invited",
        "is_deleted": False})

    # Montamos una app mínima con solo el router bajo /api/v1
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(aiprise_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                  base_url="http://test") as client:
        try:
            yield d, client
        finally:
            await admin.drop_database(_SCRATCH_DB)
            admin.close()
            if _ORIG_DB_NAME is not None:
                os.environ["DB_NAME"] = _ORIG_DB_NAME
            else:
                os.environ.pop("DB_NAME", None)
            db_module._client = None


# ------------------------------------------------------------------------
# T1 — KYB corporativo con firma válida: se registra, NO muta kyb_status.
# ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_corporate_kyb_valid_hmac_is_dropped_and_registered(_scratch):
    d, client = _scratch
    body = json.dumps({
        "verification_session_id": "aiprise_session_abc123",
        "decision": "approved",
        "extra_metadata": {"score": 0.99}}).encode()
    sig = _sign(body)

    r = await client.post("/api/v1/webhooks/aiprise/kyb", content=body,
                    headers={"Content-Type": "application/json",
                             "X-HMAC-Signature": sig})

    # Mismo status code que la versión previa (200)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["dropped"] is True
    assert j["application_id"] == "app_test_corp"
    assert j["reason"] == "corporate_kyb_dropped_new_module_owns_state"

    # kyb_status de la org NO fue tocado
    org = await d["organizations"].find_one({"org_id": "org_test_corp"})
    assert org["kyb_status"] == "in_review"  # sin cambios
    assert "updated_at" not in org           # no se tocó el doc

    # onboarding_application NO fue tocado tampoco
    app = await d["onboarding_applications"].find_one(
        {"application_id": "app_test_corp"})
    assert app["kyb_status"] == "in_review"
    assert app["status"] == "in_review"
    assert "decision_raw" not in app
    assert "decision" not in app

    # Ningún user activado
    n_active = await d["users"].count_documents(
        {"org_id": "org_test_corp", "status": "active"})
    assert n_active == 0

    # Registro en webhook_kyb_dropped_events
    reg = await d["webhook_kyb_dropped_events"].find_one(
        {"session_id": "aiprise_session_abc123"})
    assert reg is not None
    assert reg["provider"] == "aiprise"
    assert reg["org_id"] == "org_test_corp"
    assert reg["application_id"] == "app_test_corp"
    assert reg["decision_incoming"] == "approved"
    assert reg["kyb_status_would_be"] == "approved"
    assert reg["kyb_status_current"] == "in_review"
    assert reg["org_type"] == "fintech"
    assert reg["payload"]["extra_metadata"]["score"] == 0.99  # payload íntegro
    assert reg["reason"] == "corporate_kyb_dropped_new_module_owns_state"
    assert reg["received_at"]  # timestamp presente

    # audit_logs: 1 entrada aiprise.kyb.dropped_for_corporate
    n_audit = await d["audit_logs"].count_documents(
        {"action": "aiprise.kyb.dropped_for_corporate"})
    assert n_audit == 1
    audit = await d["audit_logs"].find_one(
        {"action": "aiprise.kyb.dropped_for_corporate"})
    assert audit["resource_type"] == "onboarding_application"
    assert audit["resource_id"] == "app_test_corp"
    assert audit["org_id"] == "org_test_corp"
    assert audit["metadata"]["decision"] == "approved"
    assert audit["metadata"]["kyb_status_current"] == "in_review"

    # webhook_events: registro previo (aceptado por HMAC)
    n_we = await d["webhook_events"].count_documents(
        {"provider": "aiprise", "kind": "kyb", "status": "accepted"})
    assert n_we == 1

    # kyb.decided (el action del canal viejo) NO se emite
    assert await d["audit_logs"].count_documents(
        {"action": "kyb.decided"}) == 0


# ------------------------------------------------------------------------
# T2 — KYB corporativo con firma inválida: se rechaza, NO se registra
#      en la colección de dropped, sí queda registro de firma inválida
#      en webhook_events (comportamiento previo intacto).
# ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_corporate_kyb_invalid_hmac_is_rejected(_scratch):
    d, client = _scratch
    body = json.dumps({
        "verification_session_id": "aiprise_session_abc123",
        "decision": "approved"}).encode()

    r = await client.post("/api/v1/webhooks/aiprise/kyb", content=body,
                    headers={"Content-Type": "application/json",
                             "X-HMAC-Signature": "sha256=bogus_signature"})

    assert r.status_code == 401

    # NO se registra en la colección de dropped
    assert await d["webhook_kyb_dropped_events"].count_documents({}) == 0

    # NO se emite audit del drop
    assert await d["audit_logs"].count_documents(
        {"action": "aiprise.kyb.dropped_for_corporate"}) == 0

    # webhook_events: SÍ hay registro forense de la firma rechazada
    rej = await d["webhook_events"].find_one(
        {"provider": "aiprise", "kind": "kyb",
         "status": "rejected_signature"})
    assert rej is not None

    # kyb_status intacto
    org = await d["organizations"].find_one({"org_id": "org_test_corp"})
    assert org["kyb_status"] == "in_review"


# ------------------------------------------------------------------------
# T3 — El flujo de KYC personal no cambió: sigue log-and-drop pre-existente,
#      no toca kyb_status, no crea entrada en webhook_kyb_dropped_events.
# ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_personal_kyc_flow_unchanged(_scratch):
    d, client = _scratch
    body = json.dumps({
        "verification_session_id": "aiprise_kyc_session_xyz",
        "decision": "approved",
        "client_reference_id": "usr_test_personal"}).encode()
    sig = _sign(body)

    r = await client.post("/api/v1/webhooks/aiprise/kyc", content=body,
                    headers={"Content-Type": "application/json",
                             "X-HMAC-Signature": sig})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    # El path personal ya devolvía `dropped: True` con reason específica
    assert j.get("dropped") is True
    assert j["reason"] == "personal_org_uses_andes_only"

    # audit_logs: entrada aiprise.kyc.dropped_for_personal (patrón viejo,
    # intacto)
    n_kyc_drop = await d["audit_logs"].count_documents(
        {"action": "aiprise.kyc.dropped_for_personal"})
    assert n_kyc_drop == 1

    # kyb_status del org personal no cambió (era pending)
    org = await d["organizations"].find_one({"org_id": "org_test_personal"})
    assert org["kyb_status"] == "pending"

    # users.kyc_status tampoco (el drop del KYC personal no lo modifica)
    u = await d["users"].find_one({"user_id": "usr_test_personal"})
    assert u["kyc_status"] == "pending"
    assert u["status"] == "invited"

    # NO se creó una entrada en webhook_kyb_dropped_events (esa es solo
    # para el canal KYB corporativo)
    assert await d["webhook_kyb_dropped_events"].count_documents({}) == 0

    # NO se emitió audit del drop KYB (canal ortogonal)
    assert await d["audit_logs"].count_documents(
        {"action": "aiprise.kyb.dropped_for_corporate"}) == 0


# ------------------------------------------------------------------------
# T4 — Complemento: session_id inexistente sigue devolviendo 404 (mismo
#      comportamiento de antes de la neutralización).
# ------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_corporate_kyb_unknown_session_still_returns_404(_scratch):
    d, client = _scratch
    body = json.dumps({
        "verification_session_id": "aiprise_session_UNKNOWN",
        "decision": "approved"}).encode()
    sig = _sign(body)

    r = await client.post("/api/v1/webhooks/aiprise/kyb", content=body,
                    headers={"Content-Type": "application/json",
                             "X-HMAC-Signature": sig})
    assert r.status_code == 404

    # Sin session no hay drop registrable — nada en la colección
    assert await d["webhook_kyb_dropped_events"].count_documents({}) == 0
    # Nada de audit del drop
    assert await d["audit_logs"].count_documents(
        {"action": "aiprise.kyb.dropped_for_corporate"}) == 0


# Restaurar env al final del módulo (por si otros tests corren después)
def teardown_module(_mod):
    if _ORIG_SECRET is not None:
        os.environ["AIPRISE_WEBHOOK_SECRET"] = _ORIG_SECRET
    else:
        os.environ.pop("AIPRISE_WEBHOOK_SECRET", None)
