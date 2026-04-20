"""Auto-split from routers.py (2026-04-20). Domain: compliance."""
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
# COMPLIANCE
# ==========================================================================
# ============================================================================
# COMPLIANCE
# ============================================================================
comp_router = APIRouter(prefix="/compliance", tags=["compliance"])


@comp_router.get("/queue")
async def comp_queue(user: User = Depends(get_current_user)):
    reviews = await col(COMPLIANCE).find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Attach case info
    case_ids = list({r["case_id"] for r in reviews})
    cases = await col(ONBOARDING).find({"case_id": {"$in": case_ids}}, {"_id": 0}).to_list(500)
    by_id = {c["case_id"]: c for c in cases}
    for r in reviews:
        r["case"] = by_id.get(r["case_id"])
    return {"items": reviews, "total": len(reviews)}


class CompDecision(BaseModel):
    decision: str
    comments: Optional[str] = None


@comp_router.post("/{review_id}/decide")
async def decide(review_id: str, body: CompDecision,
                 user: User = Depends(require_roles("super_admin", "compliance"))):
    r = await col(COMPLIANCE).find_one({"review_id": review_id}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Review not found")
    await col(COMPLIANCE).update_one(
        {"review_id": review_id},
        {"$set": {"decision": body.decision, "comments": body.comments, "reviewer_id": user.user_id}}
    )
    # If approved, move case to approved
    if body.decision == "approved":
        await col(ONBOARDING).update_one(
            {"case_id": r["case_id"]},
            {"$set": {"status": "approved", "progress": 100}}
        )
    elif body.decision == "rejected":
        await col(ONBOARDING).update_one(
            {"case_id": r["case_id"]},
            {"$set": {"status": "rejected", "progress": 100}}
        )
    await _log_audit(user, f"compliance.{body.decision}", "compliance_review", review_id)
    return {"ok": True}

