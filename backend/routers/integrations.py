"""Auto-split from routers.py (2026-04-20). Domain: integrations."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request, UploadFile, File, Form, Header
from pydantic import BaseModel
import hashlib
import secrets
import uuid

from db import (
    col, ORGANIZATIONS, ONBOARDING, COMPLIANCE, FUNDS, PRODUCTS, NAV_SNAPSHOTS,
    TREASURY, POSITIONS, TRANSACTIONS, RECONCILIATION, API_APPS, API_KEYS,
    WEBHOOK_ENDPOINTS, WEBHOOK_DELIVERIES, ALERTS, REPORTS, AUDIT_LOGS,
    END_CUSTOMERS, ORG_USERS, USERS, SESSIONS, APPROVALS, IDEMPOTENCY, DOCUMENTS
)
from models import (
    User, Organization, OnboardingCase, ComplianceReview, Fund, Product,
    NavSnapshot, Position, TreasuryAccount, Transaction, ReconciliationRecord,
    ApiApp, ApiKey, WebhookEndpoint, WebhookDelivery, Alert, Report, AuditLog,
    EndCustomer, OrgUser, now_utc, new_id
)
from auth import (
    get_current_user, require_roles, exchange_session, upsert_user,
    create_session, delete_session,
)
import prosper_client
import seed as seed_module
import approvals as approvals_mod
import mfa as mfa_mod
import webhook_signing
import storage as storage_mod
from ._helpers import _strip_id, _log_audit, _user_scope, _apply_scope


# ==========================================================================
# INTEGRATIONS (API apps, keys, webhooks)
# ==========================================================================
# ============================================================================
# API APPS / KEYS / WEBHOOKS
# ============================================================================
int_router = APIRouter(prefix="/integrations", tags=["integrations"])


@int_router.get("/apps")
async def list_apps(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    items = await col(API_APPS).find(q, {"_id": 0}).to_list(200)
    return {"items": items, "total": len(items)}


class AppCreate(BaseModel):
    org_id: str
    name: str
    description: Optional[str] = None
    environment: str = "sandbox"


@int_router.post("/apps")
async def create_app(body: AppCreate, user: User = Depends(require_roles("super_admin", "ops", "client_admin"))):
    doc = {
        "app_id": f"app_{new_id()}", **body.model_dump(),
        "status": "active", "is_demo": False,
        "created_at": now_utc().isoformat(),
    }
    await col(API_APPS).insert_one(dict(doc))
    await _log_audit(user, "app.create", "api_app", doc["app_id"])
    _strip_id(doc)
    return doc


@int_router.get("/keys")
async def list_keys(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    items = await col(API_KEYS).find(q, {"_id": 0}).to_list(200)
    return {"items": items, "total": len(items)}


class KeyCreate(BaseModel):
    app_id: str
    org_id: str
    label: str
    scopes: List[str] = []
    environment: str = "sandbox"


@int_router.post("/keys")
async def create_key(body: KeyCreate, user: User = Depends(require_roles("super_admin", "ops", "client_admin", "developer"))):
    raw = f"pk_{body.environment[:4]}_{secrets.token_urlsafe(32)}"
    doc = {
        "key_id": f"key_{new_id()}", **body.model_dump(),
        "key_prefix": raw[:16] + "...",
        "key_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "status": "active", "last_used_at": None,
        "is_demo": False, "created_at": now_utc().isoformat(),
    }
    await col(API_KEYS).insert_one(dict(doc))
    await _log_audit(user, "apikey.create", "api_key", doc["key_id"])
    # Return the raw key ONCE (never stored in plaintext)
    _strip_id(doc)
    return {"api_key_plaintext": raw, **doc}


@int_router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, user: User = Depends(require_roles("super_admin", "ops", "client_admin"))):
    r = await col(API_KEYS).update_one({"key_id": key_id}, {"$set": {"status": "revoked"}})
    if r.matched_count == 0:
        raise HTTPException(404, "Key not found")
    await _log_audit(user, "apikey.revoke", "api_key", key_id)
    return {"ok": True}


@int_router.get("/webhooks")
async def list_webhooks(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    # NEVER return the stored `secret` field
    items = await col(WEBHOOK_ENDPOINTS).find(q, {"_id": 0, "secret": 0}).to_list(200)
    return {"items": items, "total": len(items)}


class HookCreate(BaseModel):
    app_id: str
    org_id: str
    url: str
    events: List[str] = []
    environment: str = "sandbox"


@int_router.post("/webhooks")
async def create_webhook(body: HookCreate, user: User = Depends(require_roles("super_admin", "ops", "client_admin", "developer"))):
    full_secret = webhook_signing.generate_secret()
    doc = {
        "endpoint_id": f"hook_{new_id()}", **body.model_dump(),
        "secret": full_secret,  # stored (for signing). Returned ONCE on creation.
        "secret_prefix": full_secret[:14] + "…",
        "status": "active", "is_demo": False,
        "created_at": now_utc().isoformat(),
    }
    await col(WEBHOOK_ENDPOINTS).insert_one(dict(doc))
    await _log_audit(user, "webhook.create", "webhook_endpoint", doc["endpoint_id"])
    _strip_id(doc)
    # Return plaintext secret once
    response = {**doc, "webhook_secret_plaintext": full_secret,
                "signing_instructions": "Verify X-Prosper-Signature: t=<timestamp>,v1=<hmac-sha256(secret, t+'.'+body)>"}
    # Never return stored secret in future list calls
    response.pop("secret", None)
    return response


@int_router.get("/webhooks/{endpoint_id}/deliveries")
async def webhook_deliveries(endpoint_id: str, user: User = Depends(get_current_user)):
    items = await col(WEBHOOK_DELIVERIES).find(
        {"endpoint_id": endpoint_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}

