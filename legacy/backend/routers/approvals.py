"""Auto-split from routers.py (2026-04-20). Domain: approvals."""
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
# APPROVALS (two-signer)
# ==========================================================================
# ============================================================================
# APPROVAL WORKFLOW (two-signer pattern)
# ============================================================================
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])


@approvals_router.get("")
async def list_approvals(status: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    items = await col(APPROVALS).find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@approvals_router.get("/pending/count")
async def pending_count(user: User = Depends(get_current_user)):
    n = await col(APPROVALS).count_documents({"status": "pending"})
    return {"count": n}


class ApproveBody(BaseModel):
    mfa_code: Optional[str] = None  # optional MFA challenge code


@approvals_router.post("/{approval_id}/approve")
async def approve(approval_id: str, body: ApproveBody,
                  user: User = Depends(require_roles("super_admin", "ops", "finance"))):
    a = await col(APPROVALS).find_one({"approval_id": approval_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Approval not found")
    if a["status"] != "pending":
        raise HTTPException(400, f"Approval is {a['status']}, cannot approve")
    if a["requested_by"] == user.user_id:
        raise HTTPException(400, "Cannot approve your own request (four-eyes principle)")
    already = any(ap["user_id"] == user.user_id for ap in a.get("approvals", []))
    if already:
        raise HTTPException(400, "You already approved this request")

    # Optional: enforce MFA if user has it enabled
    user_doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    if user_doc and user_doc.get("mfa_enabled") and user_doc.get("mfa_secret"):
        if not body.mfa_code or not mfa_mod.verify_code(user_doc["mfa_secret"], body.mfa_code):
            raise HTTPException(401, "Valid MFA code required")

    approvals_list = a.get("approvals", []) + [{
        "user_id": user.user_id, "email": user.email,
        "at": now_utc().isoformat(),
    }]

    if len(approvals_list) >= a["required_approvals"]:
        # Execute
        try:
            result = await approvals_mod.execute_approved_action(
                a["action"], a["payload"], a["requested_by_email"]
            )
            await col(APPROVALS).update_one(
                {"approval_id": approval_id},
                {"$set": {"status": "executed", "approvals": approvals_list,
                          "executed_at": now_utc().isoformat(), "result": result}}
            )
            await _log_audit(user, f"approval.execute", "approval", approval_id,
                             metadata={"action": a["action"]})
            return {"status": "executed", "result": result}
        except Exception as e:
            await col(APPROVALS).update_one(
                {"approval_id": approval_id},
                {"$set": {"status": "failed", "approvals": approvals_list,
                          "result": {"error": str(e)}}}
            )
            raise HTTPException(500, f"Execution failed: {e}")
    else:
        await col(APPROVALS).update_one(
            {"approval_id": approval_id},
            {"$set": {"approvals": approvals_list}}
        )
        await _log_audit(user, "approval.sign", "approval", approval_id)
        return {"status": "pending", "approvals_count": len(approvals_list)}


class RejectBody(BaseModel):
    reason: Optional[str] = None


@approvals_router.post("/{approval_id}/reject")
async def reject(approval_id: str, body: RejectBody,
                 user: User = Depends(require_roles("super_admin", "ops", "finance"))):
    a = await col(APPROVALS).find_one({"approval_id": approval_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Approval not found")
    if a["status"] != "pending":
        raise HTTPException(400, f"Approval is {a['status']}")
    await col(APPROVALS).update_one(
        {"approval_id": approval_id},
        {"$set": {"status": "rejected", "rejected_by_email": user.email,
                  "rejected_reason": body.reason, "executed_at": now_utc().isoformat()}}
    )
    await _log_audit(user, "approval.reject", "approval", approval_id,
                     metadata={"reason": body.reason})
    return {"status": "rejected"}

