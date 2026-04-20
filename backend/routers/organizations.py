"""Auto-split from routers.py (2026-04-20). Domain: organizations."""
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
# ORGANIZATIONS (clients)
# ==========================================================================
# ============================================================================
# ORGANIZATIONS (clients)
# ============================================================================
orgs_router = APIRouter(prefix="/organizations", tags=["organizations"])


@orgs_router.get("")
async def list_orgs(
    env: Optional[str] = None,
    search: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if env:
        q["environment"] = env
    if type:
        q["type"] = type
    if status:
        q["status"] = status
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    # Non-internal users only see their own org
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    items = await col(ORGANIZATIONS).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


@orgs_router.get("/{org_id}")
async def get_org(org_id: str, user: User = Depends(get_current_user)):
    doc = await col(ORGANIZATIONS).find_one({"org_id": org_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Org not found")
    # Extras
    apps = await col(API_APPS).count_documents({"org_id": org_id})
    keys = await col(API_KEYS).count_documents({"org_id": org_id, "status": "active"})
    hooks = await col(WEBHOOK_ENDPOINTS).count_documents({"org_id": org_id, "status": "active"})
    positions_count = await col(POSITIONS).count_documents({"org_id": org_id})
    tx_count = await col(TRANSACTIONS).count_documents({"org_id": org_id})
    doc.update({
        "counts": {"apps": apps, "keys": keys, "hooks": hooks,
                   "positions": positions_count, "tx": tx_count}
    })
    return doc


class OrgCreate(BaseModel):
    name: str
    legal_name: Optional[str] = None
    type: str = "partner"
    country: Optional[str] = None
    contact_email: Optional[str] = None
    environment: str = "sandbox"


@orgs_router.post("")
async def create_org(body: OrgCreate, user: User = Depends(require_roles("super_admin", "ops"))):
    doc = {
        "org_id": f"org_{new_id()}",
        **body.model_dump(),
        "status": "active",
        "aum_usd": 0, "active_investors": 0,
        "is_demo": False,
        "created_at": now_utc().isoformat(),
    }
    await col(ORGANIZATIONS).insert_one(dict(doc))
    await _log_audit(user, "org.create", "organization", doc["org_id"])
    _strip_id(doc)
    return doc

