"""Auto-split from routers.py (2026-04-20). Domain: auth."""
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
# AUTH
# ==========================================================================

# ============================================================================
# AUTH
# ============================================================================
auth_router = APIRouter(prefix="/auth", tags=["auth"])


class SessionRequest(BaseModel):
    session_id: str


@auth_router.post("/session")
async def create_session_endpoint(body: SessionRequest, response: Response):
    data = await exchange_session(body.session_id)
    user = await upsert_user(data)
    session_token = data["session_token"]
    await create_session(user.user_id, session_token)
    response.set_cookie(
        "session_token", session_token,
        httponly=True, secure=True, samesite="none",
        path="/", max_age=7 * 24 * 3600,
    )
    await _log_audit(user, "user.login", "user", user.user_id)
    return {"user": user.model_dump(mode="json"), "session_token": session_token}


@auth_router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return user.model_dump(mode="json")


@auth_router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token") or ""
    if token:
        await delete_session(token)
    response.delete_cookie("session_token", path="/")
    return {"ok": True}

