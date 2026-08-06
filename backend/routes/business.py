"""Phase 4 — Business module endpoints (master client list, revenue,
yield-per-client). Internal roles only: super_admin / admin / finance.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from auth import CurrentUser, requires_role
from db import col, ORGANIZATIONS, POSITIONS, TRANSACTIONS
from roles import Role

router = APIRouter(prefix="/admin/business", tags=["admin-business"])

BIZ_ROLES = (Role.super_admin, Role.admin, Role.finance)
require_business = requires_role(*BIZ_ROLES)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# /clients — master list with all metrics + 30d sparkline
# ---------------------------------------------------------------------------
@router.get("/clients")
async def list_clients(
    org_type: Optional[List[str]] = Query(None, alias="type"),
    status:   Optional[List[str]] = Query(None),
    tier:     Optional[List[str]] = Query(None),
    date_from: Optional[str]      = Query(None),
    parent_org_id: Optional[str]  = Query(
        None,
        description="Phase 23: 'none' filters to N1 only; otherwise an org_id "
                    "to list its N2 children."),
    _: CurrentUser = Depends(require_business),
):
    cutoff_30d = _iso(datetime.now(timezone.utc) - timedelta(days=30))

    # Pre-fetch organizations
    q: dict = {"is_deleted": False}
    if org_type: q["type"] = {"$in": org_type}
    if status:
        # caller uses 'active' | 'paused' | 'churned'. Map to kyb_status approved
        # filter for now; without churn tracking we treat all as `active`.
        if "active" in status and len(status) == 1:
            q["kyb_status"] = "approved"
    if parent_org_id == "none":
        q["parent_org_id"] = None
    elif parent_org_id:
        q["parent_org_id"] = parent_org_id
    orgs = await col(ORGANIZATIONS).find(q, {"_id": 0}).to_list(500)

    # 1) aggregate per org: volume, revenue, first_subscribe_at
    org_ids = [o["org_id"] for o in orgs]
    if not org_ids:
        return {"items": [], "total": 0}

    agg_rows = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "confirmed",
                     "org_id": {"$in": org_ids}}},
        {"$group": {
            "_id": "$org_id",
            "volume_total":   {"$sum": "$amount"},
            "revenue_total":  {"$sum": {"$ifNull": ["$prosper_revenue", 0]}},
            "first_subscribe_at": {"$min": {"$cond": [
                {"$eq": ["$type", "subscribe"]}, "$created_at", None]}},
        }},
    ]).to_list(500)
    agg_map = {r["_id"]: r for r in agg_rows}

    # 2) sparkline: daily counts last 30d
    spark_rows = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "org_id": {"$in": org_ids},
                     "created_at": {"$gte": cutoff_30d}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {"_id": {"org": "$org_id", "day": "$day"},
                     "v": {"$sum": "$amount"}}},
        {"$sort": {"_id.day": 1}},
    ]).to_list(5000)
    spark_map: dict[str, list[float]] = {}
    for r in spark_rows:
        spark_map.setdefault(r["_id"]["org"], []).append(round(r["v"], 0))

    # 3) APR effective (weighted by principal) — last 30d
    apr_rows = await col(POSITIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "active",
                    "org_id": {"$in": org_ids}}},
        {"$group": {"_id": "$org_id",
                    "weighted_apr_num": {"$sum": {"$multiply": ["$principal_usd", "$apr_bps"]}},
                    "principal":        {"$sum": "$principal_usd"},
                    "accrued":          {"$sum": "$accrued_interest"}}},
    ]).to_list(500)
    apr_map = {r["_id"]: r for r in apr_rows}

    items = []
    # Phase 23 — collect parent commercial_names to expose in the Parent col
    parent_ids = {o.get("parent_org_id") for o in orgs if o.get("parent_org_id")}
    parent_map: dict[str, str] = {}
    if parent_ids:
        parents = await col(ORGANIZATIONS).find(
            {"org_id": {"$in": list(parent_ids)}, "is_deleted": False},
            {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1},
        ).to_list(500)
        parent_map = {p["org_id"]: (p.get("commercial_name")
                                      or p.get("legal_name") or p["org_id"])
                       for p in parents}

    for o in orgs:
        oid = o["org_id"]
        a = agg_map.get(oid, {})
        p = apr_map.get(oid, {})
        principal = p.get("principal") or 0
        weighted_apr_bps = (p.get("weighted_apr_num") / principal) if principal else 0
        accrued = p.get("accrued") or 0
        accrued_pct = (accrued / principal * 100) if principal else 0
        items.append({
            "org_id":        oid,
            "name":          o.get("commercial_name") or o.get("legal_name") or oid,
            "type":          o.get("type"),
            "status":        "active" if o.get("kyb_status") == "approved" else "paused",
            "tier":          o.get("tier") or "T1",
            "volume_total":  round(a.get("volume_total") or 0, 2),
            "revenue_total": round(a.get("revenue_total") or 0, 2),
            "started_at":    a.get("first_subscribe_at"),
            "apr_effective_bps": round(weighted_apr_bps),
            "apr_effective_pct": round(weighted_apr_bps / 100, 2),
            "yield_30d_pct":    round(accrued_pct, 2),
            "sparkline":     spark_map.get(oid, []),
            # Phase 23 — N1/N2 hierarchy surface
            "parent_org_id": o.get("parent_org_id"),
            "parent_name":   parent_map.get(o.get("parent_org_id") or "", None),
            "level":         o.get("level") or 1,
        })

    if tier:
        items = [i for i in items if i["tier"] in tier]
    if status:
        items = [i for i in items if i["status"] in status]
    if date_from:
        items = [i for i in items if (i["started_at"] or "") >= date_from]
    items.sort(key=lambda r: r["volume_total"], reverse=True)
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# CSV export of clients
# ---------------------------------------------------------------------------
@router.get("/clients/export.csv")
async def export_clients_csv(
    org_type: Optional[List[str]] = Query(None, alias="type"),
    status:   Optional[List[str]] = Query(None),
    tier:     Optional[List[str]] = Query(None),
    user: CurrentUser = Depends(require_business),
):
    data = await list_clients(org_type=org_type, status=status, tier=tier,
                              date_from=None, _=user)
    items = data["items"]

    async def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["org_id", "name", "type", "status", "tier",
                    "volume_total_usd", "revenue_total_usd",
                    "started_at", "apr_effective_pct", "yield_30d_pct"])
        yield buf.getvalue(); buf.seek(0); buf.truncate()
        for r in items:
            w.writerow([r["org_id"], r["name"], r["type"], r["status"],
                        r["tier"], r["volume_total"], r["revenue_total"],
                        r["started_at"], r["apr_effective_pct"], r["yield_30d_pct"]])
            yield buf.getvalue(); buf.seek(0); buf.truncate()

    return StreamingResponse(gen(), media_type="text/csv", headers={
        "Content-Disposition":
        f'attachment; filename="clients_{datetime.now().strftime("%Y%m%d")}.csv"'})


# ---------------------------------------------------------------------------
# /revenue/summary
# ---------------------------------------------------------------------------
@router.get("/revenue/summary")
async def revenue_summary(_: CurrentUser = Depends(require_business)):
    now = datetime.now(timezone.utc)
    mo_start  = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    yr_start  = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    prev_mo_end = mo_start - timedelta(seconds=1)
    prev_mo_start = datetime(prev_mo_end.year, prev_mo_end.month, 1, tzinfo=timezone.utc)
    prev_yr_start = datetime(now.year - 1, 1, 1, tzinfo=timezone.utc)
    prev_yr_end   = datetime(now.year - 1, now.month, now.day, tzinfo=timezone.utc)

    facet = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "confirmed"}},
        {"$facet": {
            "all":     [{"$group": {"_id": None, "v": {"$sum": "$prosper_revenue"}}}],
            "mtd":     [{"$match": {"created_at": {"$gte": _iso(mo_start)}}},
                        {"$group": {"_id": None, "v": {"$sum": "$prosper_revenue"}}}],
            "prev_mo": [{"$match": {"created_at": {"$gte": _iso(prev_mo_start),
                                                    "$lt":  _iso(mo_start)}}},
                        {"$group": {"_id": None, "v": {"$sum": "$prosper_revenue"}}}],
            "ytd":     [{"$match": {"created_at": {"$gte": _iso(yr_start)}}},
                        {"$group": {"_id": None, "v": {"$sum": "$prosper_revenue"}}}],
            "prev_yr": [{"$match": {"created_at": {"$gte": _iso(prev_yr_start),
                                                    "$lt":  _iso(prev_yr_end)}}},
                        {"$group": {"_id": None, "v": {"$sum": "$prosper_revenue"}}}],
        }},
    ]).to_list(1)

    def pick(f, k):
        arr = f.get(k, [])
        return round(arr[0].get("v", 0), 2) if arr else 0

    f = facet[0] if facet else {}
    rev_all = pick(f, "all")
    rev_mtd = pick(f, "mtd"); rev_prev_mo = pick(f, "prev_mo")
    rev_ytd = pick(f, "ytd"); rev_prev_yr = pick(f, "prev_yr")
    return {
        "revenue_total":   rev_all,
        "revenue_mtd":     rev_mtd,
        "revenue_prev_mo": rev_prev_mo,
        "mom_delta_pct":   round(((rev_mtd - rev_prev_mo) / rev_prev_mo * 100), 2) if rev_prev_mo else None,
        "revenue_ytd":     rev_ytd,
        "revenue_prev_yr": rev_prev_yr,
        "yoy_delta_pct":   round(((rev_ytd - rev_prev_yr) / rev_prev_yr * 100), 2) if rev_prev_yr else None,
        "generated_at":    _iso(now),
    }


# ---------------------------------------------------------------------------
# /revenue/breakdown — donut by concept + optional period filter
# ---------------------------------------------------------------------------
@router.get("/revenue/breakdown")
async def revenue_breakdown(period: str = Query("all", regex="^(mtd|ytd|all)$"),
                             _: CurrentUser = Depends(require_business)):
    now = datetime.now(timezone.utc)
    match: dict = {"is_deleted": False, "status": "confirmed"}
    if period == "mtd":
        match["created_at"] = {"$gte": _iso(datetime(now.year, now.month, 1, tzinfo=timezone.utc))}
    elif period == "ytd":
        match["created_at"] = {"$gte": _iso(datetime(now.year, 1, 1, tzinfo=timezone.utc))}

    agg = await col(TRANSACTIONS).aggregate([
        {"$match": match},
        {"$group": {
            "_id": None,
            "management":     {"$sum": "$fee_breakdown.management"},
            "performance":    {"$sum": "$fee_breakdown.performance"},
            "onramp_spread":  {"$sum": "$fee_breakdown.onramp_spread"},
            "offramp_spread": {"$sum": "$fee_breakdown.offramp_spread"},
            "other":          {"$sum": "$fee_breakdown.other"},
        }},
    ]).to_list(1)
    raw = agg[0] if agg else {}
    items = [
        {"concept": "management",     "amount": round(raw.get("management", 0), 2)},
        {"concept": "performance",    "amount": round(raw.get("performance", 0), 2)},
        {"concept": "onramp_spread",  "amount": round(raw.get("onramp_spread", 0), 2)},
        {"concept": "offramp_spread", "amount": round(raw.get("offramp_spread", 0), 2)},
        {"concept": "other",          "amount": round(raw.get("other", 0), 2)},
    ]
    total = sum(i["amount"] for i in items)
    for i in items:
        i["share_pct"] = round((i["amount"] / total * 100), 2) if total else 0
    return {"items": items, "total": round(total, 2), "period": period}


# ---------------------------------------------------------------------------
# /revenue/by-month — last N months stacked by concept
# ---------------------------------------------------------------------------
@router.get("/revenue/by-month")
async def revenue_by_month(months: int = Query(12, ge=1, le=36),
                            _: CurrentUser = Depends(require_business)):
    now = datetime.now(timezone.utc)
    # naive go-back-N-months
    y, m = now.year, now.month - months + 1
    while m <= 0: m += 12; y -= 1
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    rows = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "confirmed",
                     "created_at": {"$gte": _iso(start)}}},
        {"$addFields": {"month": {"$substr": ["$created_at", 0, 7]}}},
        {"$group": {
            "_id": "$month",
            "management":     {"$sum": "$fee_breakdown.management"},
            "performance":    {"$sum": "$fee_breakdown.performance"},
            "onramp_spread":  {"$sum": "$fee_breakdown.onramp_spread"},
            "offramp_spread": {"$sum": "$fee_breakdown.offramp_spread"},
            "other":          {"$sum": "$fee_breakdown.other"},
            "total":          {"$sum": "$prosper_revenue"},
        }},
        {"$sort": {"_id": 1}},
    ]).to_list(60)
    items = [{
        "month":          r["_id"],
        "management":     round(r["management"], 2),
        "performance":    round(r["performance"], 2),
        "onramp_spread":  round(r["onramp_spread"], 2),
        "offramp_spread": round(r["offramp_spread"], 2),
        "other":          round(r["other"], 2),
        "total":          round(r["total"], 2),
    } for r in rows]
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# /revenue/by-client
# ---------------------------------------------------------------------------
@router.get("/revenue/by-client")
async def revenue_by_client(limit: int = Query(10, ge=1, le=100),
                             _: CurrentUser = Depends(require_business)):
    rows = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "confirmed"}},
        {"$group": {"_id": "$org_id",
                    "revenue": {"$sum": "$prosper_revenue"}}},
        {"$sort": {"revenue": -1}},
        {"$limit": limit},
    ]).to_list(limit)
    org_ids = [r["_id"] for r in rows if r["_id"]]
    orgs = {o["org_id"]: o async for o in col(ORGANIZATIONS).find(
        {"org_id": {"$in": org_ids}},
        {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1})}
    items = [{
        "org_id":  r["_id"],
        "name":    orgs.get(r["_id"], {}).get("commercial_name")
                   or orgs.get(r["_id"], {}).get("legal_name") or r["_id"],
        "revenue": round(r["revenue"], 2),
    } for r in rows]
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# /yield/by-client
# ---------------------------------------------------------------------------
@router.get("/yield/by-client")
async def yield_by_client(_: CurrentUser = Depends(require_business)):
    rows = await col(POSITIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "active"}},
        {"$group": {
            "_id": "$org_id",
            "weighted_apr_num": {"$sum": {"$multiply": ["$principal_usd", "$apr_bps"]}},
            "principal":        {"$sum": "$principal_usd"},
            "accrued":          {"$sum": "$accrued_interest"},
            "earliest_maturity": {"$min": "$maturity"},
            "positions":        {"$sum": 1},
        }},
        {"$sort": {"principal": -1}},
    ]).to_list(500)
    org_ids = [r["_id"] for r in rows if r["_id"]]
    orgs = {o["org_id"]: o async for o in col(ORGANIZATIONS).find(
        {"org_id": {"$in": org_ids}},
        {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1})}

    # platform-wide APR for benchmark delta
    total_principal = sum(r["principal"] for r in rows) or 1
    platform_apr_bps = sum(r["weighted_apr_num"] for r in rows) / total_principal

    # Per-client implicit Prosper revenue (last 30d, from fee_breakdown)
    cutoff_30d = _iso(datetime.now(timezone.utc) - timedelta(days=30))
    rev_rows = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "confirmed",
                    "org_id": {"$in": org_ids},
                    "created_at": {"$gte": cutoff_30d}}},
        {"$group": {
            "_id": "$org_id",
            "implicit_mgmt":  {"$sum": {"$ifNull": ["$fee_breakdown.management", 0]}},
            "implicit_perf":  {"$sum": {"$ifNull": ["$fee_breakdown.performance", 0]}},
            "implicit_spreads": {"$sum": {"$add": [
                {"$ifNull": ["$fee_breakdown.onramp_spread", 0]},
                {"$ifNull": ["$fee_breakdown.offramp_spread", 0]},
            ]}},
            "implicit_total": {"$sum": {"$ifNull": ["$prosper_revenue", 0]}},
        }},
    ]).to_list(500)
    rev_map = {r["_id"]: r for r in rev_rows}

    items = []
    for r in rows:
        oid = r["_id"]
        principal = r["principal"] or 0
        apr_bps = (r["weighted_apr_num"] / principal) if principal else 0
        accrued = r["accrued"] or 0
        # accrued last 30d ~= accrued × 30/180  (sloppy but fine for demo)
        accrued_30d = round(accrued * 30 / 180, 2)
        rev = rev_map.get(oid, {})

        # Implicit Prosper fees on top of the APR shown to the client:
        #   gross_fund_apr = (net_apr + mgmt_drag) / (1 - perf_share)
        # where mgmt_drag = 100 bps (1% annual) and perf_share = 10%.
        mgmt_drag_bps = 100
        perf_share    = 0.10
        gross_apr_bps = (apr_bps + mgmt_drag_bps) / (1 - perf_share) if apr_bps else 0
        implicit_total_bps = max(0, gross_apr_bps - apr_bps)

        items.append({
            "org_id":   oid,
            "name":     orgs.get(oid, {}).get("commercial_name")
                        or orgs.get(oid, {}).get("legal_name") or oid,
            "positions": r["positions"],
            "principal_usd": round(principal, 2),
            "apr_bps":      round(apr_bps),
            "apr_pct":      round(apr_bps / 100, 2),
            "gross_apr_bps": round(gross_apr_bps),
            "gross_apr_pct": round(gross_apr_bps / 100, 2),
            "implicit_total_bps": round(implicit_total_bps),
            "implicit_total_pct": round(implicit_total_bps / 100, 2),
            "implicit_mgmt_30d_usd":   round(rev.get("implicit_mgmt", 0) or 0, 2),
            "implicit_perf_30d_usd":   round(rev.get("implicit_perf", 0) or 0, 2),
            "implicit_spread_30d_usd": round(rev.get("implicit_spreads", 0) or 0, 2),
            "implicit_total_30d_usd":  round(rev.get("implicit_total", 0) or 0, 2),
            "accrued_30d":  accrued_30d,
            "accrued_total": round(accrued, 2),
            "next_payout_at": r["earliest_maturity"],
            "next_payout_usd": round(principal * apr_bps / 10_000 * 180 / 365, 2),
            "benchmark_delta_bps": round(apr_bps - platform_apr_bps),
        })
    return {"items": items, "total": len(items),
            "platform_apr_bps": round(platform_apr_bps),
            "platform_apr_pct": round(platform_apr_bps / 100, 2)}


# ---------------------------------------------------------------------------
# /cohorts — group clients by their first_subscribe month and track retention
# ---------------------------------------------------------------------------
@router.get("/cohorts")
async def cohorts(
    months: int = Query(12, ge=1, le=36),
    _: CurrentUser = Depends(require_business),
):
    """Returns one row per cohort month (YYYY-MM). For each cohort:
       - new clients (first_subscribe in that month)
       - active_now (at least one tx in the last 60d)
       - churned (no tx in the last 60d)
       - cumulative volume + revenue brought in by the cohort
    """
    now    = datetime.now(timezone.utc)
    active_cutoff_iso = _iso(now - timedelta(days=60))

    # 1) compute first_subscribe_at per org + activity flags + totals
    org_rows = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "confirmed", "type": "subscribe"}},
        {"$group": {
            "_id": "$org_id",
            "first_subscribe_at": {"$min": "$created_at"},
            "last_tx_at":         {"$max": "$created_at"},
            "volume_total":       {"$sum": "$amount"},
            "revenue_total":      {"$sum": {"$ifNull": ["$prosper_revenue", 0]}},
        }},
    ]).to_list(2000)

    # 2) group by cohort month
    cohorts: dict[str, dict] = {}
    for o in org_rows:
        first = o.get("first_subscribe_at") or ""
        if len(first) < 7:
            continue
        month = first[:7]  # YYYY-MM
        c = cohorts.setdefault(month, {
            "cohort_month": month,
            "new_clients":  0,
            "active_now":   0,
            "churned":      0,
            "volume_total": 0.0,
            "revenue_total": 0.0,
            "org_ids":       [],
        })
        c["new_clients"]  += 1
        c["volume_total"] += float(o.get("volume_total")  or 0)
        c["revenue_total"] += float(o.get("revenue_total") or 0)
        c["org_ids"].append(o["_id"])
        if (o.get("last_tx_at") or "") >= active_cutoff_iso:
            c["active_now"] += 1
        else:
            c["churned"] += 1

    # 3) filter to last N months and order chronologically
    y, m = now.year, now.month - months + 1
    while m <= 0:
        m += 12; y -= 1
    start_month = f"{y:04d}-{m:02d}"
    items = []
    for k in sorted(cohorts.keys()):
        if k < start_month:
            continue
        c = cohorts[k]
        retention_pct = round((c["active_now"] / c["new_clients"]) * 100, 1) \
                         if c["new_clients"] else 0
        items.append({
            "cohort_month":   c["cohort_month"],
            "new_clients":    c["new_clients"],
            "active_now":     c["active_now"],
            "churned":        c["churned"],
            "retention_pct":  retention_pct,
            "volume_total":   round(c["volume_total"], 2),
            "revenue_total":  round(c["revenue_total"], 2),
            "avg_revenue_per_client": round(
                c["revenue_total"] / c["new_clients"], 2) if c["new_clients"] else 0,
        })

    total_new      = sum(i["new_clients"]   for i in items)
    total_active   = sum(i["active_now"]    for i in items)
    total_churned  = sum(i["churned"]       for i in items)
    total_volume   = sum(i["volume_total"]  for i in items)
    total_revenue  = sum(i["revenue_total"] for i in items)
    return {
        "items":  items,
        "total":  len(items),
        "totals": {
            "new_clients":  total_new,
            "active_now":   total_active,
            "churned":      total_churned,
            "volume_total": round(total_volume, 2),
            "revenue_total": round(total_revenue, 2),
            "retention_pct": round((total_active / total_new) * 100, 1) if total_new else 0,
        },
    }
