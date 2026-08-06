"""Phase 5 — KYT (Transaction Monitoring) rules + alerts + on-chain screening."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional, List, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from audit import log_action
from auth import CurrentUser
from db import col, KYT_ALERTS, KYT_RULES, ORGANIZATIONS, TRANSACTIONS, WATCHLIST
from integrations.trm_labs import screen_wallet
from ._deps import require_compliance, require_compliance_decide

router = APIRouter(prefix="/admin/compliance/kyt", tags=["admin-compliance-kyt"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Rules ----------
@router.get("/rules")
async def list_rules(_: CurrentUser = Depends(require_compliance)):
    items = await col(KYT_RULES).find({}, {"_id": 0}).to_list(100)
    return {"items": items, "total": len(items)}


class RuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    param_value: Optional[Union[float, int, str]] = None
    severity: Optional[Literal["info", "warning", "critical"]] = None


@router.patch("/rules/{rule_id}")
async def update_rule(rule_id: str, body: RuleUpdate,
                       user: CurrentUser = Depends(require_compliance_decide)):
    existing = await col(KYT_RULES).find_one({"rule_id": rule_id})
    if not existing:
        raise HTTPException(404, "Rule not found")
    upd = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    upd["updated_at"] = _iso_now()
    await col(KYT_RULES).update_one({"rule_id": rule_id}, {"$set": upd})
    await log_action(actor=user, action="compliance.kyt.rule_updated",
                     resource_type="kyt_rule", resource_id=rule_id,
                     metadata=upd)
    return {"ok": True}


# ---------- Alerts ----------
@router.get("/alerts")
async def list_kyt_alerts(
    severity: Optional[List[str]] = Query(None),
    status:   Optional[List[str]] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    _: CurrentUser = Depends(require_compliance),
):
    q: dict = {"is_deleted": False}
    if severity: q["severity"] = {"$in": severity}
    if status:   q["status"]   = {"$in": status}
    items = await col(KYT_ALERTS).find(q, {"_id": 0})\
              .sort("created_at", -1).to_list(limit)
    # Enrich with org name
    org_ids = list({i.get("org_id") for i in items if i.get("org_id")})
    orgs = {o["org_id"]: o async for o in col(ORGANIZATIONS).find(
        {"org_id": {"$in": org_ids}},
        {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1})}
    for it in items:
        o = orgs.get(it.get("org_id") or "")
        it["org_name"] = (o.get("commercial_name") or o.get("legal_name")) if o else None
    return {"items": items, "total": len(items)}


# ---------- Watchlist + on-chain screening ----------
@router.get("/watchlist")
async def list_watchlist(_: CurrentUser = Depends(require_compliance)):
    items = await col(WATCHLIST).find({"is_deleted": False}, {"_id": 0})\
              .sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


class WatchlistAdd(BaseModel):
    kind: Literal["wallet", "client"]
    value: str
    reason: str


@router.post("/watchlist")
async def add_watchlist(body: WatchlistAdd,
                         user: CurrentUser = Depends(require_compliance_decide)):
    doc = {
        "entry_id":   f"wl_{datetime.now(timezone.utc).timestamp():.0f}",
        "kind":       body.kind, "value": body.value.strip(),
        "reason":     body.reason, "added_by": user.email,
        "created_at": _iso_now(), "is_deleted": False,
    }
    await col(WATCHLIST).insert_one(doc.copy())
    await log_action(actor=user, action="compliance.kyt.watchlist_added",
                     resource_type="watchlist_entry",
                     resource_id=doc["entry_id"], metadata=body.model_dump())
    doc.pop("_id", None)
    return {"ok": True, "entry": doc}


class ScreenIn(BaseModel):
    address: str


@router.post("/screen-wallet")
async def screen_wallet_endpoint(body: ScreenIn,
                                  _: CurrentUser = Depends(require_compliance)):
    address = body.address.strip()
    if not address:
        raise HTTPException(400, "Empty address")
    # Internal watchlist first
    wl_hit = await col(WATCHLIST).find_one(
        {"kind": "wallet", "value": address, "is_deleted": False}, {"_id": 0})
    # External TRM Labs check (stub when key missing)
    trm = await screen_wallet(address)
    return {"address": address,
             "internal_watchlist_hit": bool(wl_hit),
             "internal_entry":         wl_hit,
             "external":               trm}


# ---------- Travel rule ----------
@router.get("/travel-rule")
async def travel_rule(_: CurrentUser = Depends(require_compliance),
                       limit: int = Query(100, ge=1, le=500)):
    txs = await col(TRANSACTIONS).find(
        {"is_deleted": False, "amount": {"$gte": 1000}, "status": "confirmed"},
        {"_id": 0, "tx_id": 1, "prosper_tx_id": 1, "org_id": 1, "amount": 1,
         "created_at": 1, "type": 1, "counterparty_verified": 1,
         "counterparty_name": 1}
    ).sort("created_at", -1).to_list(limit)
    for t in txs:
        t["travel_rule_status"] = "verified" if t.get("counterparty_verified") else "missing"
    return {"items": txs, "total": len(txs)}
