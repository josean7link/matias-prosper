"""Auto-split from routers.py (2026-04-20). Domain: users."""
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
# USERS (platform admin view)
# ==========================================================================
# ============================================================================
# USERS / ADMIN
# ============================================================================
users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("")
async def list_users(user: User = Depends(get_current_user)):
    items = await col(USERS).find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


class RoleUpdate(BaseModel):
    platform_role: str
    org_id: Optional[str] = None


@users_router.patch("/{user_id}")
async def update_user(user_id: str, body: RoleUpdate,
                      user: User = Depends(require_roles("super_admin"))):
    await col(USERS).update_one({"user_id": user_id}, {"$set": body.model_dump(exclude_none=True)})
    await _log_audit(user, "user.role_update", "user", user_id, metadata=body.model_dump())
    return {"ok": True}




# ---- Org user invite (missing) ----
class OrgUserInvite(BaseModel):
    email: str
    name: str
    role: str = "client_user"
    org_id: str


@users_router.post("/invite")
async def invite_org_user(body: OrgUserInvite,
                          user: User = Depends(require_roles("super_admin", "ops", "client_admin"))):
    if not user.is_internal and body.org_id != user.org_id:
        raise HTTPException(403, "Cannot invite users for another org")
    existing = await col(ORG_USERS).find_one({"email": body.email.lower(), "org_id": body.org_id}, {"_id": 0})
    if existing:
        raise HTTPException(409, "User already invited")
    doc = {
        "org_user_id": f"ou_{new_id()}",
        "org_id": body.org_id, "user_id": None,
        "email": body.email.lower(), "name": body.name,
        "role": body.role, "status": "invited",
        "created_at": now_utc().isoformat(),
    }
    await col(ORG_USERS).insert_one(dict(doc))
    await _log_audit(user, "user.invite", "org_user", doc["org_user_id"],
                     metadata={"email": body.email, "role": body.role})
    _strip_id(doc)
    return doc


@users_router.get("/org-members")
async def list_org_members(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    elif not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    items = await col(ORG_USERS).find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}
