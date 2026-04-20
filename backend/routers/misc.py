"""Auto-split from routers.py (2026-04-20). Domain: misc."""
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
# MISC (alerts, reports, audit)
# ==========================================================================
# ============================================================================
# ALERTS / REPORTS / AUDIT
# ============================================================================
misc_router = APIRouter(tags=["misc"])


@misc_router.get("/alerts")
async def list_alerts(resolved: Optional[bool] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if resolved is not None:
        q["resolved"] = resolved
    items = await col(ALERTS).find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@misc_router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, user: User = Depends(require_roles("super_admin", "ops"))):
    r = await col(ALERTS).update_one({"alert_id": alert_id}, {"$set": {"resolved": True}})
    if r.matched_count == 0:
        raise HTTPException(404, "Alert not found")
    await _log_audit(user, "alert.resolve", "alert", alert_id)
    return {"ok": True}


@misc_router.get("/reports")
async def list_reports(kind: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if kind:
        q["kind"] = kind
    items = await col(REPORTS).find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@misc_router.get("/audit-logs")
async def list_audit(
    actor_email: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if actor_email:
        q["actor_email"] = {"$regex": actor_email, "$options": "i"}
    if action:
        q["action"] = {"$regex": action, "$options": "i"}
    if resource:
        q["resource"] = resource
    if from_date or to_date:
        created: Dict[str, Any] = {}
        if from_date:
            created["$gte"] = from_date
        if to_date:
            created["$lte"] = to_date + "T23:59:59.999Z" if len(to_date) == 10 else to_date
        q["created_at"] = created
    page = max(page, 1)
    page_size = max(1, min(page_size, 500))
    total = await col(AUDIT_LOGS).count_documents(q)
    items = await col(AUDIT_LOGS).find(q, {"_id": 0})\
        .sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "has_more": page * page_size < total}

