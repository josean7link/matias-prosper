"""Auto-split from routers.py (2026-04-20). Domain: onboarding."""
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
# ONBOARDING
# ==========================================================================
# ============================================================================
# ONBOARDING
# ============================================================================
ob_router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@ob_router.get("")
async def list_cases(
    status: Optional[str] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if search:
        q["applicant_name"] = {"$regex": search, "$options": "i"}
    items = await col(ONBOARDING).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


@ob_router.get("/{case_id}")
async def get_case(case_id: str, user: User = Depends(get_current_user)):
    c = await col(ONBOARDING).find_one({"case_id": case_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Case not found")
    review = await col(COMPLIANCE).find_one({"case_id": case_id}, {"_id": 0})
    return {"case": c, "compliance": review}


class CaseUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    progress: Optional[int] = None


@ob_router.patch("/{case_id}")
async def update_case(case_id: str, body: CaseUpdate,
                      user: User = Depends(require_roles("super_admin", "ops", "compliance"))):
    patch: Dict[str, Any] = {"updated_at": now_utc().isoformat()}
    for k, v in body.model_dump(exclude_none=True).items():
        patch[k] = v
    r = await col(ONBOARDING).update_one({"case_id": case_id}, {"$set": patch})
    if r.matched_count == 0:
        raise HTTPException(404, "Case not found")
    await _log_audit(user, f"onboarding.{body.status or 'update'}", "onboarding_case", case_id)
    doc = await col(ONBOARDING).find_one({"case_id": case_id}, {"_id": 0})
    return doc



# ---- Onboarding create (missing) ----
class OnboardingCreate(BaseModel):
    applicant_name: str
    applicant_email: str
    applicant_type: str = "individual"
    country: Optional[str] = None
    org_id: Optional[str] = None
    notes: Optional[str] = None


@ob_router.post("")
async def create_onboarding(body: OnboardingCreate,
                            user: User = Depends(require_roles("super_admin", "ops", "compliance", "client_admin"))):
    now = now_utc()
    case_id = f"case_{new_id()}"
    doc = {
        "case_id": case_id, "org_id": body.org_id or user.org_id,
        "applicant_name": body.applicant_name,
        "applicant_email": body.applicant_email,
        "applicant_type": body.applicant_type,
        "country": body.country,
        "status": "submitted",
        "progress": 20,
        "sla_due": (now + timedelta(hours=48)).isoformat(),
        "risk_score": None, "notes": body.notes, "is_demo": False,
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
    }
    await col(ONBOARDING).insert_one(dict(doc))
    # Also create an empty compliance review
    await col(COMPLIANCE).insert_one({
        "review_id": f"rev_{new_id()}", "case_id": case_id,
        "kyc_status": "pending", "aml_check": "pending",
        "sanctions_check": "pending", "pep_check": "pending", "travel_rule": "pending",
        "decision": "pending", "is_demo": False, "created_at": now.isoformat(),
    })
    await _log_audit(user, "onboarding.create", "onboarding_case", case_id)
    _strip_id(doc)
    return doc
