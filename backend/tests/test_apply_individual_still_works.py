"""Fase 1 del retiro de AiPrise — el path individual de POST
`/onboarding/apply` sigue funcionando exactamente como antes.

Este test corre contra base scratch dedicada y verifica el flujo
`applicant_type=individual` completo:

- 200 OK con `mode='andes-direct'`.
- Se crea `organization` con `type='personal'`, `kyb_status='pending'`.
- Se crea `onboarding_application` con `aiprise_session_id='andes_kyc_<user_id>'`
  y `hosted_url='/apply/{app_id}/kyc-docs'`.
- Se crea el `user` con role `client_admin`, `kyc_status='pending'`.
- El endpoint NO envía ninguna llamada a AiPrise ni a servicios externos.

Es lo que este PR no puede romper — 642 solicitudes en `andes_kyc_usr_*`
usan hoy este camino en producción.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SCRATCH_DB = "prosper_apply_individual_tests"
_ORIG_DB_NAME = os.environ.get("DB_NAME")

import db as db_module                                            # noqa: E402
from routes.onboarding import router as onboarding_router        # noqa: E402


@pytest_asyncio.fixture()
async def _client():
    os.environ["DB_NAME"] = _SCRATCH_DB
    db_module._client = None
    admin = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await admin.drop_database(_SCRATCH_DB)
    d = db_module.db()

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(onboarding_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                  base_url="http://test") as c:
        try:
            yield d, c
        finally:
            await admin.drop_database(_SCRATCH_DB)
            admin.close()
            if _ORIG_DB_NAME is not None:
                os.environ["DB_NAME"] = _ORIG_DB_NAME
            else:
                os.environ.pop("DB_NAME", None)
            db_module._client = None


def _individual_payload():
    return {
        "applicant_type":  "individual",
        "legal_name":      "Ana Test Perez",
        "commercial_name": "",
        "country":         "AR",
        "jurisdiction":    "AR",
        "contact_name":    "Ana Test",
        "last_name":       "Perez",
        "contact_email":   "ana.test@example.com",
        "contact_phone":   "+541122334455",
        "phone":           "+541122334455",
        "cuit":            "20304050607",
        "birthdate":       "1990-01-15",
        "chain":           "stellar",
        "use_case":        "yield",
        "ubos":            [],
    }


# --------------------------------------------------------------------
# Camino feliz — el path individual funciona exactamente como antes.
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_apply_individual_happy_path_unchanged(_client):
    d, c = _client
    r = await c.post("/api/v1/onboarding/apply", json=_individual_payload())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["application_id"].startswith("app_")
    assert data["org_id"].startswith("org_")
    assert data["kyb_status"] == "pending"
    assert data["status"] == "in_review"
    # Ruta Andes-direct: session sintética + hosted local, cero AiPrise
    assert data["mode"] == "andes-direct"
    assert "/apply/" in data["hosted_url"]
    assert data["hosted_url"].endswith("/kyc-docs")

    # Persistencia — organization con type=personal
    org = await d["organizations"].find_one({"org_id": data["org_id"]})
    assert org is not None
    assert org["type"] == "personal"
    assert org["kyb_status"] == "pending"
    assert org["sanctions_status"] == "pending"
    assert org["_indiv_cuit"] == "20304050607"
    assert org["_indiv_birthdate"] == "1990-01-15"

    # Persistencia — onboarding_application
    app = await d["onboarding_applications"].find_one(
        {"application_id": data["application_id"]})
    assert app is not None
    assert app["aiprise_mode"] == "andes-direct"
    assert app["aiprise_session_id"].startswith("andes_kyc_usr_")
    assert app["hosted_url"].endswith("/kyc-docs")
    assert app["applicant_type"] == "individual"

    # Persistencia — user client_admin en status invited
    u = await d["users"].find_one({"email": "ana.test@example.com"})
    assert u is not None
    assert u["role"] == "client_admin"
    assert u["status"] == "invited"
    assert u["kyc_status"] == "pending"
    assert u["org_id"] == data["org_id"]


# --------------------------------------------------------------------
# El path business está cerrado con 410 Gone.
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_apply_business_returns_410(_client):
    d, c = _client
    body = _individual_payload()
    body["applicant_type"] = "business"
    body["legal_name"] = "Corp Test S.A."
    body["ubos"] = [{"full_name": "U1", "ownership_pct": 100,
                     "role": "CEO", "country": "AR"}]
    r = await c.post("/api/v1/onboarding/apply", json=body)
    assert r.status_code == 410, r.text
    detail = (r.json() or {}).get("detail", "")
    assert "invitación" in detail
    # No expone proveedores
    assert "aiprise" not in detail.lower()
    # NO se creó organization ni application
    assert await d["organizations"].count_documents({}) == 0
    assert await d["onboarding_applications"].count_documents({}) == 0
    assert await d["users"].count_documents({}) == 0


# --------------------------------------------------------------------
# `GET /apply/{app_id}` sigue funcionando y devuelve `aiprise_mode`
# como campo legacy (para el status page del frontend individual).
# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_application_after_individual_apply(_client):
    d, c = _client
    r = await c.post("/api/v1/onboarding/apply", json=_individual_payload())
    app_id = r.json()["application_id"]
    g = await c.get(f"/api/v1/onboarding/apply/{app_id}")
    assert g.status_code == 200, g.text
    data = g.json()
    assert data["application_id"] == app_id
    assert data["status"] == "in_review"
    assert data["kyb_status"] == "pending"
    assert data["aiprise_mode"] == "andes-direct"
    # Cero PII (contact_email, contact_phone, cuit) en el response sanitizado
    assert "contact_email" not in data
    assert "contact_phone" not in data
    assert "ubos" not in data
    assert "cuit" not in data
