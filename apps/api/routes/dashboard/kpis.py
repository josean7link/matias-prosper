"""/kpis — single `$facet` returning every top-card number."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from auth import CurrentUser
from db import col, POSITIONS, TRANSACTIONS, APPROVALS

from ._deps import iso, require_dashboard, utc_now

router = APIRouter()


@router.get("/kpis")
async def get_kpis(_: CurrentUser = Depends(require_dashboard)):
    now = utc_now()
    yday = now - timedelta(days=1)
    last30 = now - timedelta(days=30)
    yr_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    mo_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    pipeline_tx = [
        {"$match": {"is_deleted": False, "status": "confirmed"}},
        {"$facet": {
            "revenue_mtd": [
                {"$match": {"created_at": {"$gte": iso(mo_start)}}},
                {"$group": {"_id": None, "v": {"$sum": "$fee_amount"}}},
            ],
            "revenue_ytd": [
                {"$match": {"created_at": {"$gte": iso(yr_start)}}},
                {"$group": {"_id": None, "v": {"$sum": "$fee_amount"}}},
            ],
            "volume_30d": [
                {"$match": {"created_at": {"$gte": iso(last30)},
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
                {"$match": {"created_at": {"$lte": iso(yday)}}},
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

    active_orgs = await col(POSITIONS).distinct(
        "org_id", {"is_deleted": False, "status": "active"})
    pending_approvals = await col(APPROVALS).count_documents(
        {"status": "pending", "is_deleted": False})

    supply_circulating = aum_today_principal
    nav_today = 1.0 + (aum_today_accrued / aum_today_principal) if aum_today_principal else 1.0
    yday_acc  = _g(pos_facet, "aum_yday", "accrued")
    yday_prin = _g(pos_facet, "aum_yday", "principal")
    nav_yday  = 1.0 + (yday_acc / yday_prin) if yday_prin else 1.0
    nav_delta = (nav_today - nav_yday) / nav_yday if nav_yday else None

    return {
        "aum_usd":            aum_today,
        "aum_delta_24h":      aum_delta_24h,
        "revenue_mtd":        _g(tx_facet, "revenue_mtd"),
        "revenue_ytd":        _g(tx_facet, "revenue_ytd"),
        "active_clients":     len(active_orgs),
        "volume_30d":         _g(tx_facet, "volume_30d"),
        "operations_queue":   pending_approvals,
        "supply_circulating": supply_circulating,
        "nav":                nav_today,
        "nav_delta_24h":      nav_delta,
        "generated_at":       iso(now),
    }
