"""Auto-split from routers.py (2026-04-20). Domain: mfa."""
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
# MFA (TOTP)
# ==========================================================================
# ============================================================================
# MFA TOTP
# ============================================================================
mfa_router = APIRouter(prefix="/auth/mfa", tags=["mfa"])


@mfa_router.post("/enable")
async def mfa_enable(user: User = Depends(get_current_user)):
    """Returns secret + QR code. User must verify with /mfa/verify to actually enable."""
    secret = mfa_mod.generate_secret()
    uri = mfa_mod.provisioning_uri(user.email, secret)
    qr = mfa_mod.qr_png_base64(uri)
    # Stash pending secret on user doc (not yet enabled)
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_secret_pending": secret}}
    )
    return {"secret": secret, "provisioning_uri": uri, "qr_code_data_url": qr}


class MfaVerifyBody(BaseModel):
    code: str


@mfa_router.post("/verify")
async def mfa_verify(body: MfaVerifyBody, user: User = Depends(get_current_user)):
    doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    secret = doc.get("mfa_secret_pending") or doc.get("mfa_secret")
    if not secret:
        raise HTTPException(400, "No MFA setup pending. Call /mfa/enable first.")
    if not mfa_mod.verify_code(secret, body.code):
        raise HTTPException(401, "Invalid code")
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_enabled": True, "mfa_secret": secret},
         "$unset": {"mfa_secret_pending": ""}}
    )
    await _log_audit(user, "mfa.enabled", "user", user.user_id)
    return {"ok": True, "mfa_enabled": True}


@mfa_router.post("/disable")
async def mfa_disable(body: MfaVerifyBody, user: User = Depends(get_current_user)):
    doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc.get("mfa_enabled"):
        return {"ok": True}
    if not mfa_mod.verify_code(doc.get("mfa_secret", ""), body.code):
        raise HTTPException(401, "Invalid code")
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_enabled": False},
         "$unset": {"mfa_secret": "", "mfa_secret_pending": ""}}
    )
    await _log_audit(user, "mfa.disabled", "user", user.user_id)
