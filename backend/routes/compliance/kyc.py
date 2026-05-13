"""Phase 5 — KYC queue + decision endpoints."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser
from db import col, KYC_CASES, USERS
from ._deps import require_compliance, require_compliance_decide

router = APIRouter(prefix="/admin/compliance/kyc", tags=["admin-compliance-kyc"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sla_color(hours: float) -> str:
    if hours <= 12: return "red"
    if hours <= 24: return "amber"
    return "green"


@router.get("/queue")
async def kyc_queue(
    status: Optional[List[str]] = Query(None),
    provider: Optional[List[str]] = Query(None),
    _: CurrentUser = Depends(require_compliance),
):
    q: dict = {"is_deleted": False}
    if status:   q["status"]   = {"$in": status}
    if provider: q["provider"] = {"$in": provider}
    items = await col(KYC_CASES).find(q, {"_id": 0}).sort("applied_at", -1).to_list(200)
    # Update sla_hours_left dynamically (24h sla)
    now = datetime.now(timezone.utc)
    for it in items:
        try:
            applied = datetime.fromisoformat(it["applied_at"])
            it["sla_hours_left"] = round(max(0, 24 - (now - applied).total_seconds() / 3600), 1)
        except Exception:
            it["sla_hours_left"] = 0
        it["sla_color"] = _sla_color(it["sla_hours_left"])
    return {"items": items, "total": len(items)}


@router.get("/{case_id}")
async def kyc_detail(case_id: str, _: CurrentUser = Depends(require_compliance)):
    doc = await col(KYC_CASES).find_one({"case_id": case_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    try:
        applied = datetime.fromisoformat(doc["applied_at"])
        doc["sla_hours_left"] = round(max(0, 24 - (datetime.now(timezone.utc) - applied).total_seconds() / 3600), 1)
        doc["sla_color"] = _sla_color(doc["sla_hours_left"])
    except Exception:
        pass
    return doc


class KycDecision(BaseModel):
    action: Literal["approve", "reject", "request_info"]
    reason: str = Field(..., min_length=20, max_length=2000)


@router.post("/{case_id}/decision")
async def kyc_decide(case_id: str, body: KycDecision,
                     user: CurrentUser = Depends(require_compliance_decide)):
    doc = await col(KYC_CASES).find_one({"case_id": case_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    new_status = {"approve": "approved", "reject": "rejected",
                   "request_info": "needs_info"}[body.action]
    entry = {"ts": _iso_now(), "by": user.email,
             "what": f"decision.{body.action}", "meta": {"reason": body.reason}}
    await col(KYC_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"status": new_status, "decision": body.action,
                   "decision_reason": body.reason, "decided_by": user.user_id,
                   "decided_at": _iso_now(), "updated_at": _iso_now()},
         "$push": {"timeline": entry}},
    )
    # Mirror to USERS.kyc_status when there's an email-linked user
    email = doc.get("email")
    if email:
        await col(USERS).update_one(
            {"email": email},
            {"$set": {"kyc_status": new_status, "updated_at": _iso_now()}})
    await log_action(actor=user, action=f"compliance.kyc.{body.action}",
                     resource_type="kyc_case", resource_id=case_id,
                     metadata={"reason": body.reason})
    return {"ok": True, "case_id": case_id, "status": new_status}
