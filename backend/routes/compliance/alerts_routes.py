"""Phase 5 — Centralised alerts feed (kyt + operational + compliance + technical)."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from audit import log_action
from auth import CurrentUser
from db import col, ALERTS, ORGANIZATIONS, USERS
from ._deps import require_compliance, require_compliance_decide

router = APIRouter(prefix="/admin/alerts", tags=["admin-alerts"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def list_alerts(
    severity: Optional[List[str]] = Query(None),
    type:     Optional[List[str]] = Query(None, alias="type"),
    status:   Optional[List[str]] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    _: CurrentUser = Depends(require_compliance),
):
    q: dict = {"is_deleted": False}
    if severity: q["severity"] = {"$in": severity}
    if type:     q["type"]     = {"$in": type}
    if status:   q["status"]   = {"$in": status}
    items = await col(ALERTS).find(q, {"_id": 0})\
              .sort("created_at", -1).to_list(limit)
    org_ids = list({i.get("org_id") for i in items if i.get("org_id")})
    orgs = {o["org_id"]: o async for o in col(ORGANIZATIONS).find(
        {"org_id": {"$in": org_ids}},
        {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1})}
    for it in items:
        o = orgs.get(it.get("org_id") or "")
        it["org_name"] = (o.get("commercial_name") or o.get("legal_name")) if o else None
    return {"items": items, "total": len(items)}


@router.get("/summary")
async def alerts_summary(_: CurrentUser = Depends(require_compliance)):
    """Bell-icon count + latest 5 critical-open."""
    open_critical_count = await col(ALERTS).count_documents(
        {"is_deleted": False, "status": "open", "severity": "critical"})
    open_count = await col(ALERTS).count_documents(
        {"is_deleted": False, "status": "open"})
    latest = await col(ALERTS).find(
        {"is_deleted": False, "status": "open"}, {"_id": 0}
    ).sort("created_at", -1).to_list(5)
    return {"open_count": open_count,
             "open_critical_count": open_critical_count,
             "latest": latest}


class AlertPatch(BaseModel):
    status: Optional[Literal["open", "acknowledged", "resolved"]] = None
    assigned_to: Optional[str] = None
    note: Optional[str] = None


@router.patch("/{alert_id}")
async def patch_alert(alert_id: str, body: AlertPatch,
                       user: CurrentUser = Depends(require_compliance_decide)):
    existing = await col(ALERTS).find_one({"alert_id": alert_id, "is_deleted": False})
    if not existing:
        raise HTTPException(404, "Alert not found")
    upd = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    upd["updated_at"] = _iso_now()
    await col(ALERTS).update_one({"alert_id": alert_id}, {"$set": upd})
    await log_action(actor=user, action="compliance.alert_patched",
                     resource_type="alert", resource_id=alert_id, metadata=upd)
    return {"ok": True}


class BulkPatch(BaseModel):
    alert_ids: List[str]
    status: Optional[Literal["acknowledged", "resolved"]] = "acknowledged"
    assigned_to: Optional[str] = None


@router.post("/bulk")
async def bulk_patch(body: BulkPatch,
                      user: CurrentUser = Depends(require_compliance_decide)):
    upd = {"status": body.status, "updated_at": _iso_now()}
    if body.assigned_to:
        upd["assigned_to"] = body.assigned_to
    res = await col(ALERTS).update_many(
        {"alert_id": {"$in": body.alert_ids}}, {"$set": upd})
    await log_action(actor=user, action="compliance.alerts_bulk_patched",
                     resource_type="alert", resource_id=f"{len(body.alert_ids)} alerts",
                     metadata={"count": res.modified_count, **upd})
    return {"ok": True, "modified": res.modified_count}
