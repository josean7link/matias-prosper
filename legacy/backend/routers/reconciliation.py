"""Auto-split from routers.py (2026-04-20). Domain: reconciliation."""
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
# RECONCILIATION
# ==========================================================================
# ============================================================================
# RECONCILIATION
# ============================================================================
recon_router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@recon_router.get("")
async def list_recon(
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    items = await col(RECONCILIATION).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Join tx by prosper_tx_id
    p_ids = [r["prosper_tx_id"] for r in items]
    tx_map = {}
    if p_ids:
        async for t in col(TRANSACTIONS).find({"prosper_tx_id": {"$in": p_ids}}, {"_id": 0}):
            tx_map[t["prosper_tx_id"]] = t
    for r in items:
        r["tx"] = tx_map.get(r["prosper_tx_id"])
    return {"items": items, "total": len(items)}


@recon_router.post("/{recon_id}/resolve")
async def resolve_recon(recon_id: str, user: User = Depends(require_roles("super_admin", "ops", "finance"))):
    r = await col(RECONCILIATION).update_one(
        {"recon_id": recon_id},
        {"$set": {"status": "resolved", "discrepancy": None}}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Record not found")
    await _log_audit(user, "recon.resolve", "reconciliation", recon_id)
    return {"ok": True}

