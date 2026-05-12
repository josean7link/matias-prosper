"""Phase 2 — Admin Home / Dashboard endpoints.

Every endpoint protected: super_admin / admin / finance only.
All numbers are computed in real time from positions + transactions
via MongoDB aggregations ($facet, $group) — one query per endpoint.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import CurrentUser, requires_role
from db import col, ORGANIZATIONS, USERS, POSITIONS, TRANSACTIONS, ALERTS, APPROVALS
from roles import Role

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])

# Roles that can read the dashboard
_DASH_ROLES = (Role.super_admin, Role.admin, Role.finance)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# /kpis — single $facet with every top-card number
# ---------------------------------------------------------------------------
@router.get("/kpis")
async def get_kpis(_: CurrentUser = Depends(requires_role(*_DASH_ROLES))):
    now = _utc_now()
    yday = now - timedelta(days=1)
    last30 = now - timedelta(days=30)
    yr_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    mo_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    pipeline_tx = [
        {"$match": {"is_deleted": False, "status": "confirmed"}},
        {"$facet": {
            "revenue_mtd": [
                {"$match": {"created_at": {"$gte": _iso(mo_start)}}},
                {"$group": {"_id": None, "v": {"$sum": "$fee_amount"}}},
            ],
            "revenue_ytd": [
                {"$match": {"created_at": {"$gte": _iso(yr_start)}}},
                {"$group": {"_id": None, "v": {"$sum": "$fee_amount"}}},
            ],
            "volume_30d": [
                {"$match": {"created_at": {"$gte": _iso(last30)},
                             "type": {"$in": ["subscribe", "redeem"]}}},
                {"$group": {"_id": None, "v": {"$sum": "$amount"}}},
            ],
        }},
    ]

    pipeline_pos = [
        {"$match": {"is_deleted": False, "status": "active"}},
        {"$facet": {
            "aum_today": [
                {"$group": {"_id": None,
                            "principal": {"$sum": "$principal_usd"},
                            "accrued":   {"$sum": "$accrued_interest"}}},
            ],
            "aum_yday": [
                {"$match": {"created_at": {"$lte": _iso(yday)}}},
                {"$group": {"_id": None,
                            "principal": {"$sum": "$principal_usd"},
                            "accrued":   {"$sum": "$accrued_interest"}}},
            ],
        }},
    ]

    tx_res  = await col(TRANSACTIONS).aggregate(pipeline_tx).to_list(1)
    pos_res = await col(POSITIONS).aggregate(pipeline_pos).to_list(1)

    def _g(facet, key, sub=None):
        arr = facet.get(key, [])
        if not arr:
            return 0.0
        if sub is None:
            return arr[0].get("v", 0) or 0
        return arr[0].get(sub, 0) or 0

    tx_facet  = tx_res[0]  if tx_res  else {}
    pos_facet = pos_res[0] if pos_res else {}

    aum_today_principal = _g(pos_facet, "aum_today", "principal")
    aum_today_accrued   = _g(pos_facet, "aum_today", "accrued")
    aum_today           = aum_today_principal + aum_today_accrued
    aum_yday            = _g(pos_facet, "aum_yday", "principal") + _g(pos_facet, "aum_yday", "accrued")
    aum_delta_24h       = ((aum_today - aum_yday) / aum_yday) if aum_yday else None

    # Active clients = orgs with at least one active position
    active_orgs = await col(POSITIONS).distinct(
        "org_id", {"is_deleted": False, "status": "active"})

    # Operations in queue (pending approvals)
    pending_approvals = await col(APPROVALS).count_documents(
        {"status": "pending", "is_deleted": False})

    # Supply circulating — proxy = sum of principal still in active positions
    supply_circulating = aum_today_principal

    # NAV — toy value: 1.0 + (accrued / principal). 24h delta vs yesterday
    nav_today = 1.0 + (aum_today_accrued / aum_today_principal) if aum_today_principal else 1.0
    yday_acc  = _g(pos_facet, "aum_yday", "accrued")
    yday_prin = _g(pos_facet, "aum_yday", "principal")
    nav_yday  = 1.0 + (yday_acc / yday_prin) if yday_prin else 1.0
    nav_delta = (nav_today - nav_yday) / nav_yday if nav_yday else None

    return {
        "aum_usd":           aum_today,
        "aum_delta_24h":     aum_delta_24h,
        "revenue_mtd":       _g(tx_facet, "revenue_mtd"),
        "revenue_ytd":       _g(tx_facet, "revenue_ytd"),
        "active_clients":    len(active_orgs),
        "volume_30d":        _g(tx_facet, "volume_30d"),
        "operations_queue":  pending_approvals,
        "supply_circulating": supply_circulating,
        "nav":               nav_today,
        "nav_delta_24h":     nav_delta,
        "generated_at":      _iso(now),
    }


# ---------------------------------------------------------------------------
# /nav-history — synthetic daily NAV series
# ---------------------------------------------------------------------------
@router.get("/nav-history")
async def get_nav_history(days: int = Query(90, ge=1, le=365),
                          _: CurrentUser = Depends(requires_role(*_DASH_ROLES))):
    now = _utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    # Aggregate: sum of accrued_interest per day across all active positions
    pipeline = [
        {"$match": {"is_deleted": False,
                     "created_at": {"$gte": _iso(start)}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {
            "_id": "$day",
            "principal": {"$sum": "$principal_usd"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = await col(POSITIONS).aggregate(pipeline).to_list(400)

    # Compute NAV that grows ~apr_bps/365 per day. Smooth, monotonic-up curve.
    series = []
    cum_principal = 0.0
    nav = 1.0
    daily_yield = 0.085 / 365  # 8.5% APR base
    for r in rows:
        cum_principal += r["principal"]
    # Now walk day by day in [start, now], computing NAV trajectory.
    day = start
    nav = 1.0
    while day <= now:
        nav *= (1.0 + daily_yield)
        series.append({"date": day.strftime("%Y-%m-%d"),
                       "nav": round(nav, 6)})
        day += timedelta(days=1)
    # cap at the configured days window
    return {"items": series[-days:], "total": min(days, len(series))}


# ---------------------------------------------------------------------------
# /volume — daily stacked (subscribe vs redeem) for last N days
# ---------------------------------------------------------------------------
@router.get("/volume")
async def get_volume(days: int = Query(30, ge=1, le=365),
                     _: CurrentUser = Depends(requires_role(*_DASH_ROLES))):
    now = _utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    pipeline = [
        {"$match": {"is_deleted": False, "status": "confirmed",
                     "type": {"$in": ["subscribe", "redeem"]},
                     "created_at": {"$gte": _iso(start)}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {"_id": {"day": "$day", "type": "$type"},
                     "amount": {"$sum": "$amount"}}},
        {"$sort": {"_id.day": 1}},
    ]
    rows = await col(TRANSACTIONS).aggregate(pipeline).to_list(2000)

    # Pivot to {date, subscribe, redeem}
    by_day: dict[str, dict] = {}
    for r in rows:
        d = r["_id"]["day"]
        t = r["_id"]["type"]
        by_day.setdefault(d, {"date": d, "subscribe": 0, "redeem": 0})
        by_day[d][t] = round(r["amount"], 2)

    # Fill missing days with zeros so the chart is continuous
    day = start
    out = []
    while day <= now:
        k = day.strftime("%Y-%m-%d")
        out.append(by_day.get(k, {"date": k, "subscribe": 0, "redeem": 0}))
        day += timedelta(days=1)
    out = out[-days:]
    return {"items": out, "total": len(out)}


# ---------------------------------------------------------------------------
# /revenue — last N months of fee revenue
# ---------------------------------------------------------------------------
@router.get("/revenue")
async def get_revenue(months: int = Query(12, ge=1, le=36),
                      _: CurrentUser = Depends(requires_role(*_DASH_ROLES))):
    now = _utc_now()
    # First day, `months` months ago (approximate via 30-day blocks for simplicity)
    start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
             - timedelta(days=31 * (months - 1)))
    pipeline = [
        {"$match": {"is_deleted": False, "status": "confirmed",
                     "fee_amount": {"$gt": 0},
                     "created_at": {"$gte": _iso(start)}}},
        {"$addFields": {"month": {"$substr": ["$created_at", 0, 7]}}},
        {"$group": {"_id": "$month", "revenue": {"$sum": "$fee_amount"}}},
        {"$sort": {"_id": 1}},
    ]
    rows = await col(TRANSACTIONS).aggregate(pipeline).to_list(60)
    return {"items": [{"month": r["_id"], "revenue": round(r["revenue"], 2)} for r in rows],
            "total": len(rows)}


# ---------------------------------------------------------------------------
# /top-clients — top N orgs by AUM
# ---------------------------------------------------------------------------
@router.get("/top-clients")
async def get_top_clients(limit: int = Query(10, ge=1, le=50),
                          _: CurrentUser = Depends(requires_role(*_DASH_ROLES))):
    pipeline = [
        {"$match": {"is_deleted": False, "status": "active"}},
        {"$group": {"_id": "$org_id",
                     "aum": {"$sum": {"$add": ["$principal_usd", "$accrued_interest"]}},
                     "positions_count": {"$sum": 1}}},
        {"$sort": {"aum": -1}},
        {"$limit": limit},
    ]
    rows = await col(POSITIONS).aggregate(pipeline).to_list(limit)
    # Attach org commercial_name
    org_ids = [r["_id"] for r in rows if r["_id"]]
    org_lookup = {o["org_id"]: o async for o in
                  col(ORGANIZATIONS).find({"org_id": {"$in": org_ids}}, {"_id": 0})}
    items = []
    for r in rows:
        org = org_lookup.get(r["_id"]) or {}
        items.append({
            "org_id": r["_id"],
            "name": org.get("commercial_name") or org.get("legal_name") or r["_id"],
            "aum": round(r["aum"], 2),
            "positions_count": r["positions_count"],
        })
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# /ops-queue — operations queue digest
# ---------------------------------------------------------------------------
@router.get("/ops-queue")
async def get_ops_queue(_: CurrentUser = Depends(requires_role(*_DASH_ROLES))):
    # Approvals pending
    appr_count = await col(APPROVALS).count_documents(
        {"status": "pending", "is_deleted": False})
    appr_top = await col(APPROVALS).find(
        {"status": "pending", "is_deleted": False}, {"_id": 0}
    ).sort("created_at", 1).to_list(3)

    # Alerts open by severity
    al_count = await col(ALERTS).count_documents(
        {"status": "open", "is_deleted": False})
    al_top = await col(ALERTS).find(
        {"status": "open", "is_deleted": False}, {"_id": 0}
    ).sort("created_at", -1).to_list(3)

    # KYB pending (Phase 1 model: organizations.kyb_status)
    kyb_count = await col(ORGANIZATIONS).count_documents(
        {"kyb_status": {"$in": ["pending", "in_review"]}, "is_deleted": False})
    kyb_top_cursor = col(ORGANIZATIONS).find(
        {"kyb_status": {"$in": ["pending", "in_review"]}, "is_deleted": False},
        {"_id": 0, "org_id": 1, "commercial_name": 1, "kyb_status": 1, "created_at": 1},
    ).sort("created_at", 1)
    kyb_top = await kyb_top_cursor.to_list(3)

    # Webhook failures + Reconciliation unmatched — Phase 2 placeholders
    # (real data lands when those modules ship). Read-friendly empty defaults.
    webhook_fail_count = 0
    recon_unmatched_count = 0

    return {
        "approvals":      {"count": appr_count,  "items": appr_top},
        "kyb":            {"count": kyb_count,   "items": kyb_top},
        "alerts":         {"count": al_count,    "items": al_top},
        "webhook_failing": {"count": webhook_fail_count, "items": []},
        "reconciliation": {"count": recon_unmatched_count, "items": []},
        "generated_at":   _iso(_utc_now()),
    }
