"""Phase 3 — Compliance officer endpoints.

Lists pending KYB applications + KYC users, with manual decision overrides.
Restricted to internal roles (super_admin, admin, compliance_officer).
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from audit import log_action
from auth import CurrentUser, requires_role
from db import col, ORGANIZATIONS, ONBOARDING_APPLICATIONS, USERS
from models import utc_now
from roles import Role

router = APIRouter(prefix="/compliance", tags=["compliance"])

_ROLES = (Role.super_admin, Role.admin, Role.compliance_officer)
require_compliance = requires_role(*_ROLES)


# ---------------------------------------------------------------------------
# /applications — list onboarding applications
# ---------------------------------------------------------------------------
@router.get("/applications")
async def list_applications(
    status: Optional[str] = Query(None, regex="^(in_review|approved|rejected)$"),
    limit: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(require_compliance),
):
    q = {"is_deleted": False}
    if status:
        q["status"] = status
    cur = col(ONBOARDING_APPLICATIONS).find(q, {"_id": 0}).sort("submitted_at", -1)
    items = await cur.to_list(limit)
    return {"items": items, "total": len(items)}


@router.get("/applications/{app_id}")
async def get_application(app_id: str, _: CurrentUser = Depends(require_compliance)):
    doc = await col(ONBOARDING_APPLICATIONS).find_one(
        {"application_id": app_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


class DecisionIn(BaseModel):
    decision: Literal["approved", "rejected", "needs_info"]
    note: Optional[str] = None


@router.post("/applications/{app_id}/decide")
async def decide_application(
    app_id: str,
    body: DecisionIn,
    user: CurrentUser = Depends(require_compliance),
):
    """Manual compliance decision — overrides AiPrise if needed."""
    doc = await col(ONBOARDING_APPLICATIONS).find_one(
        {"application_id": app_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")

    new_kyb = {
        "approved":   "approved",
        "rejected":   "rejected",
        "needs_info": "in_review",
    }[body.decision]
    new_status = {
        "approved":   "approved",
        "rejected":   "rejected",
        "needs_info": "in_review",
    }[body.decision]

    await col(ONBOARDING_APPLICATIONS).update_one(
        {"application_id": app_id},
        {"$set": {
            "kyb_status":     new_kyb,
            "status":         new_status,
            "decision":       body.decision,
            "decision_at":    utc_now(),
            "decision_by":    user.user_id,
            "decision_note":  body.note,
            "updated_at":     utc_now(),
        }},
    )
    await col(ORGANIZATIONS).update_one(
        {"org_id": doc["org_id"]},
        {"$set": {"kyb_status": new_kyb, "updated_at": utc_now()}},
    )
    await log_action(actor=user, action="compliance.kyb.decided",
                     resource_type="onboarding_application",
                     resource_id=app_id, org_id_override=doc["org_id"],
                     metadata={"decision": body.decision, "note": body.note})
    return {"ok": True, "application_id": app_id, "decision": body.decision,
            "kyb_status": new_kyb}


# ---------------------------------------------------------------------------
# /users — list users awaiting KYC
# ---------------------------------------------------------------------------
@router.get("/kyc-cases")
async def list_kyc_cases(
    status: Optional[str] = Query(None, regex="^(pending|in_review|approved|rejected)$"),
    limit: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(require_compliance),
):
    q: dict = {"is_deleted": False}
    if status:
        q["kyc_status"] = status
    else:
        q["kyc_status"] = {"$in": ["pending", "in_review", "rejected"]}
    cur = col(USERS).find(
        q,
        {"_id": 0, "user_id": 1, "email": 1, "org_id": 1, "role": 1,
         "kyc_status": 1, "kyc_decision": 1, "kyc_session_id": 1,
         "kyc_mode": 1, "updated_at": 1},
    ).sort("updated_at", -1)
    items = await cur.to_list(limit)
    return {"items": items, "total": len(items)}


class KycDecisionIn(BaseModel):
    decision: Literal["approved", "rejected", "needs_info"]
    note: Optional[str] = None


@router.post("/kyc-cases/{user_id}/decide")
async def decide_kyc(user_id: str, body: KycDecisionIn,
                     user: CurrentUser = Depends(require_compliance)):
    target = await col(USERS).find_one({"user_id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(404, "User not found")
    new_status = {
        "approved":   "approved",
        "rejected":   "rejected",
        "needs_info": "in_review",
    }[body.decision]
    await col(USERS).update_one(
        {"user_id": user_id},
        {"$set": {
            "kyc_status":      new_status,
            "kyc_decision":    body.decision,
            "kyc_decided_at":  utc_now(),
            "kyc_decided_by":  user.user_id,
            "kyc_note":        body.note,
            "updated_at":      utc_now(),
        }},
    )
    await log_action(actor=user, action="compliance.kyc.decided",
                     resource_type="user", resource_id=user_id,
                     metadata={"decision": body.decision, "note": body.note})
    return {"ok": True, "user_id": user_id, "kyc_status": new_status}


# ---------------------------------------------------------------------------
# /summary — dashboard counters for the compliance home
# ---------------------------------------------------------------------------
@router.get("/summary")
async def summary(_: CurrentUser = Depends(require_compliance)):
    pending_kyb = await col(ONBOARDING_APPLICATIONS).count_documents(
        {"status": "in_review", "is_deleted": False})
    approved_kyb = await col(ONBOARDING_APPLICATIONS).count_documents(
        {"status": "approved", "is_deleted": False})
    rejected_kyb = await col(ONBOARDING_APPLICATIONS).count_documents(
        {"status": "rejected", "is_deleted": False})
    pending_kyc = await col(USERS).count_documents(
        {"kyc_status": {"$in": ["pending", "in_review"]}, "is_deleted": False})
    return {
        "kyb": {"pending": pending_kyb, "approved": approved_kyb, "rejected": rejected_kyb},
        "kyc": {"pending": pending_kyc},
        "generated_at": utc_now(),
    }
