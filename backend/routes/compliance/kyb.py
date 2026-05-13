"""Phase 5 — KYB queue + checklist + decision."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser
from db import col, KYB_CASES
from ._deps import require_compliance, require_compliance_decide

router = APIRouter(prefix="/admin/compliance/kyb", tags=["admin-compliance-kyb"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sla_color(hours: float) -> str:
    if hours <= 12: return "red"
    if hours <= 24: return "amber"
    return "green"


@router.get("/queue")
async def kyb_queue(
    status: Optional[List[str]] = Query(None),
    _: CurrentUser = Depends(require_compliance),
):
    q: dict = {"is_deleted": False}
    if status: q["status"] = {"$in": status}
    items = await col(KYB_CASES).find(q, {"_id": 0}).sort("applied_at", -1).to_list(200)
    now = datetime.now(timezone.utc)
    for it in items:
        try:
            applied = datetime.fromisoformat(it["applied_at"])
            it["sla_hours_left"] = round(max(0, 48 - (now - applied).total_seconds() / 3600), 1)
        except Exception:
            it["sla_hours_left"] = 0
        it["sla_color"] = _sla_color(it["sla_hours_left"])
        items_checked = sum(1 for c in (it.get("checklist") or []) if c.get("checked"))
        it["checklist_progress"] = {"checked": items_checked,
                                     "total": len(it.get("checklist") or []),
                                     "ready_to_approve": items_checked == 8}
    return {"items": items, "total": len(items)}


@router.get("/{case_id}")
async def kyb_detail(case_id: str, _: CurrentUser = Depends(require_compliance)):
    doc = await col(KYB_CASES).find_one({"case_id": case_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    items_checked = sum(1 for c in (doc.get("checklist") or []) if c.get("checked"))
    doc["checklist_progress"] = {"checked": items_checked,
                                  "total": len(doc.get("checklist") or []),
                                  "ready_to_approve": items_checked == 8}
    return doc


class ChecklistPatch(BaseModel):
    key: str
    checked: bool


@router.patch("/{case_id}/checklist")
async def kyb_patch_checklist(case_id: str, body: ChecklistPatch,
                               user: CurrentUser = Depends(require_compliance_decide)):
    doc = await col(KYB_CASES).find_one({"case_id": case_id, "is_deleted": False})
    if not doc:
        raise HTTPException(404, "Not found")
    cl = doc.get("checklist") or []
    found = False
    for c in cl:
        if c.get("key") == body.key:
            c["checked"]   = bool(body.checked)
            c["checked_by"] = user.email if body.checked else None
            c["checked_at"] = _iso_now() if body.checked else None
            found = True
    if not found:
        raise HTTPException(404, "Checklist item not found")
    entry = {"ts": _iso_now(), "by": user.email,
             "what": f"checklist.{'check' if body.checked else 'uncheck'}",
             "meta": {"key": body.key}}
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"checklist": cl, "updated_at": _iso_now()},
         "$push": {"timeline": entry}})
    await log_action(actor=user, action="compliance.kyb.checklist_patched",
                     resource_type="kyb_case", resource_id=case_id,
                     metadata={"key": body.key, "checked": body.checked})
    items_checked = sum(1 for c in cl if c.get("checked"))
    return {"ok": True, "checklist_progress": {
        "checked": items_checked, "total": len(cl),
        "ready_to_approve": items_checked == 8}}


class KybDecision(BaseModel):
    action: Literal["approve", "reject", "request_info"]
    reason: str = Field(..., min_length=20, max_length=2000)


@router.post("/{case_id}/decision")
async def kyb_decide(case_id: str, body: KybDecision,
                      user: CurrentUser = Depends(require_compliance_decide)):
    doc = await col(KYB_CASES).find_one({"case_id": case_id, "is_deleted": False})
    if not doc:
        raise HTTPException(404, "Not found")
    if body.action == "approve":
        # Enforce checklist
        items_checked = sum(1 for c in (doc.get("checklist") or []) if c.get("checked"))
        if items_checked != 8:
            raise HTTPException(400, "Checklist incomplete — cannot approve")
    new_status = {"approve": "approved", "reject": "rejected",
                   "request_info": "needs_info"}[body.action]
    entry = {"ts": _iso_now(), "by": user.email,
             "what": f"decision.{body.action}", "meta": {"reason": body.reason}}
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"status": new_status, "decision": body.action,
                   "decision_reason": body.reason, "decided_by": user.user_id,
                   "decided_at": _iso_now(), "updated_at": _iso_now()},
         "$push": {"timeline": entry}})
    await log_action(actor=user, action=f"compliance.kyb.{body.action}",
                     resource_type="kyb_case", resource_id=case_id,
                     metadata={"reason": body.reason})
    return {"ok": True, "case_id": case_id, "status": new_status}
