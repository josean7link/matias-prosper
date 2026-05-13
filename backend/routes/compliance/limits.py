"""Phase 5 — Per-client compliance limits (caps) — inline edit with audit + history."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser
from db import col, LIMITS_HISTORY, ORGANIZATIONS
from ._deps import require_compliance, require_compliance_decide

router = APIRouter(prefix="/admin/compliance/limits", tags=["admin-compliance-limits"])

CAP_KEYS = {"subscribe_daily_cap_usd", "subscribe_monthly_cap_usd",
            "redeem_daily_cap_usd",    "redeem_monthly_cap_usd"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def list_limits(_: CurrentUser = Depends(require_compliance)):
    orgs = await col(ORGANIZATIONS).find(
        {"is_deleted": False}, {"_id": 0, "org_id": 1,
         "legal_name": 1, "commercial_name": 1, "type": 1, "country": 1,
         "caps": 1, "kyb_status": 1}
    ).to_list(2000)
    items = []
    for o in orgs:
        caps = o.get("caps") or {}
        items.append({
            "org_id":  o["org_id"],
            "name":    o.get("commercial_name") or o.get("legal_name") or o["org_id"],
            "type":    o.get("type"),
            "country": o.get("country"),
            "kyb_status": o.get("kyb_status"),
            "subscribe_daily_cap_usd":   caps.get("subscribe_daily_cap_usd")   or 0,
            "subscribe_monthly_cap_usd": caps.get("subscribe_monthly_cap_usd") or 0,
            "redeem_daily_cap_usd":      caps.get("redeem_daily_cap_usd")      or 0,
            "redeem_monthly_cap_usd":    caps.get("redeem_monthly_cap_usd")    or 0,
        })
    return {"items": items, "total": len(items)}


class CapPatch(BaseModel):
    key: Literal["subscribe_daily_cap_usd", "subscribe_monthly_cap_usd",
                 "redeem_daily_cap_usd",    "redeem_monthly_cap_usd"]
    value: float = Field(..., ge=0)


@router.patch("/{org_id}")
async def patch_caps(org_id: str, body: CapPatch,
                      user: CurrentUser = Depends(require_compliance_decide)):
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id, "is_deleted": False})
    if not org:
        raise HTTPException(404, "Org not found")
    old_value = ((org.get("caps") or {}).get(body.key)) or 0
    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {f"caps.{body.key}": body.value, "updated_at": _iso_now()}})
    await col(LIMITS_HISTORY).insert_one({
        "org_id":     org_id,
        "key":        body.key,
        "old_value":  old_value,
        "new_value":  body.value,
        "changed_by": user.email,
        "changed_at": _iso_now(),
    })
    await log_action(actor=user, action="compliance.limit_updated",
                     resource_type="organization", resource_id=org_id,
                     metadata={"key": body.key, "old": old_value, "new": body.value})
    return {"ok": True, "key": body.key, "old": old_value, "new": body.value}


@router.get("/{org_id}/history")
async def history(org_id: str, limit: int = Query(50, ge=1, le=200),
                   _: CurrentUser = Depends(require_compliance)):
    rows = await col(LIMITS_HISTORY).find(
        {"org_id": org_id}, {"_id": 0}
    ).sort("changed_at", -1).to_list(limit)
    return {"items": rows, "total": len(rows)}
