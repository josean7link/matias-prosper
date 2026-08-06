"""Phase 3 — Operations module endpoints.

Sub-modules:
  /admin/transactions                    list / filter / search / paginate
  /admin/transactions/{id}               single tx with lifecycle steps
  /admin/transactions/{id}/lifecycle     just the lifecycle array
  /admin/transactions/{id}/retry-step    super_admin retry
  /admin/transactions/export.csv         filtered CSV stream
  /admin/funds/state                     fund header + Stellar account balances
  /admin/funds/nav-history               passthrough to dashboard.nav_history
  /admin/operations/by-client/stats      success/fail per org + sparkline
  /admin/operations/volume-by-client     volume by org with period diff
  /admin/prosper-upstream/status         3-LED upstream health
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from auth import CurrentUser, requires_role
from db import col, ORGANIZATIONS, POSITIONS, TRANSACTIONS, NAV_SNAPSHOTS
from models import utc_now
from roles import Role

router = APIRouter(prefix="/admin", tags=["admin-operations"])

OPS_ROLES = (Role.super_admin, Role.admin, Role.finance, Role.compliance_officer)
require_ops = requires_role(*OPS_ROLES)
require_super = requires_role(Role.super_admin)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()


def _scrub(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# /admin/transactions — list with filters
# ---------------------------------------------------------------------------
@router.get("/transactions")
async def list_transactions(
    type: Optional[List[str]] = Query(None),
    status: Optional[List[str]] = Query(None),
    org_id: Optional[str]      = Query(None),
    date_from: Optional[str]   = Query(None),
    date_to:   Optional[str]   = Query(None),
    search:    Optional[str]   = Query(None),
    only_errors: bool          = Query(False),
    page:  int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(require_ops),
):
    q: dict = {"is_deleted": False}
    if type:    q["type"]   = {"$in": type}
    if status:  q["status"] = {"$in": status}
    if org_id:  q["org_id"] = org_id
    if date_from or date_to:
        date_q: dict = {}
        if date_from: date_q["$gte"] = date_from
        if date_to:   date_q["$lte"] = date_to
        q["created_at"] = date_q
    if search:
        q["$or"] = [
            {"tx_hash":       {"$regex": search, "$options": "i"}},
            {"prosper_tx_id": {"$regex": search, "$options": "i"}},
            {"tx_id":         {"$regex": search, "$options": "i"}},
            {"memo":          {"$regex": search, "$options": "i"}},
        ]
    if only_errors:
        q["$or"] = (q.get("$or") or []) + [
            {"status": "failed"},
            {"lifecycle.status": "error"},
        ]

    total = await col(TRANSACTIONS).count_documents(q)
    skip = (page - 1) * limit
    rows = await col(TRANSACTIONS).find(
        q, {"_id": 0, "lifecycle": 0}
    ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)

    # join org names
    org_ids = list({r["org_id"] for r in rows if r.get("org_id")})
    orgs = {o["org_id"]: o.get("commercial_name") or o.get("legal_name") or o["org_id"]
            async for o in col(ORGANIZATIONS).find(
                {"org_id": {"$in": org_ids}},
                {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1})}
    for r in rows:
        r["org_name"] = orgs.get(r.get("org_id"), r.get("org_id") or "—")

    return {
        "items": rows, "total": total,
        "page":  page, "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


# ---------------------------------------------------------------------------
# CSV export — same filters as list. Streams to keep memory flat.
# ---------------------------------------------------------------------------
@router.get("/transactions/export.csv")
async def export_csv(
    type: Optional[List[str]] = Query(None),
    status: Optional[List[str]] = Query(None),
    org_id: Optional[str]      = Query(None),
    date_from: Optional[str]   = Query(None),
    date_to:   Optional[str]   = Query(None),
    search: Optional[str]      = Query(None),
    only_errors: bool          = Query(False),
    _: CurrentUser = Depends(require_ops),
):
    q: dict = {"is_deleted": False}
    if type:    q["type"]   = {"$in": type}
    if status:  q["status"] = {"$in": status}
    if org_id:  q["org_id"] = org_id
    if date_from or date_to:
        date_q: dict = {}
        if date_from: date_q["$gte"] = date_from
        if date_to:   date_q["$lte"] = date_to
        q["created_at"] = date_q
    if search:
        q["$or"] = [
            {"tx_hash":       {"$regex": search, "$options": "i"}},
            {"prosper_tx_id": {"$regex": search, "$options": "i"}},
            {"memo":          {"$regex": search, "$options": "i"}},
        ]
    if only_errors:
        q["$or"] = (q.get("$or") or []) + [
            {"status": "failed"}, {"lifecycle.status": "error"},
        ]

    async def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["created_at", "tx_id", "prosper_tx_id", "type", "org_id",
                    "amount", "asset", "status", "fee_amount", "tx_hash", "memo"])
        yield buf.getvalue(); buf.seek(0); buf.truncate()

        cur = col(TRANSACTIONS).find(
            q, {"_id": 0, "lifecycle": 0}).sort("created_at", -1)
        async for r in cur:
            w.writerow([
                r.get("created_at"), r.get("tx_id"), r.get("prosper_tx_id"),
                r.get("type"), r.get("org_id"), r.get("amount"),
                r.get("asset"), r.get("status"), r.get("fee_amount"),
                r.get("tx_hash"), r.get("memo"),
            ])
            yield buf.getvalue(); buf.seek(0); buf.truncate()

    headers = {"Content-Disposition":
               f'attachment; filename="transactions_{datetime.now().strftime("%Y%m%d")}.csv"'}
    return StreamingResponse(gen(), media_type="text/csv", headers=headers)


# ---------------------------------------------------------------------------
# /admin/transactions/{tx_id} — full doc with lifecycle
# ---------------------------------------------------------------------------
@router.get("/transactions/{tx_id}/lifecycle")
async def tx_lifecycle(tx_id: str, _: CurrentUser = Depends(require_ops)):
    doc = await col(TRANSACTIONS).find_one(
        {"$or": [{"tx_id": tx_id}, {"prosper_tx_id": tx_id}],
         "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Transaction not found")
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": doc.get("org_id")},
        {"_id": 0, "commercial_name": 1, "legal_name": 1, "org_id": 1})
    return {
        "transaction": doc,
        "org": org,
        "lifecycle": doc.get("lifecycle") or [],
    }


@router.post("/transactions/{tx_id}/retry-step")
async def retry_step(tx_id: str, step_id: str = Query(...),
                     user: CurrentUser = Depends(require_super)):
    """Stub retry — flips the step from error/pending back to pending and
    appends an audit note. Real retry hooks land in Phase 4."""
    doc = await col(TRANSACTIONS).find_one(
        {"$or": [{"tx_id": tx_id}, {"prosper_tx_id": tx_id}],
         "is_deleted": False})
    if not doc:
        raise HTTPException(404, "Transaction not found")
    lifecycle = doc.get("lifecycle") or []
    updated = False
    for s in lifecycle:
        if s.get("step_id") == step_id:
            s["status"] = "pending"
            s["retry_requested_by"] = user.user_id
            s["retry_requested_at"] = _iso(datetime.now(timezone.utc))
            updated = True
            break
    if not updated:
        raise HTTPException(404, f"Step {step_id} not found")
    await col(TRANSACTIONS).update_one(
        {"tx_id": doc["tx_id"]},
        {"$set": {"lifecycle": lifecycle, "updated_at": utc_now()}})
    return {"ok": True, "step_id": step_id, "status": "pending"}


# ---------------------------------------------------------------------------
# /admin/funds/state
# ---------------------------------------------------------------------------
@router.get("/funds/state")
async def funds_state(_: CurrentUser = Depends(require_ops)):
    # current NAV from snapshots
    nav_doc = await col(NAV_SNAPSHOTS).find_one(
        {}, {"_id": 0}, sort=[("date", -1)])
    yday_doc = await col(NAV_SNAPSHOTS).find_one(
        {"date": {"$lt": (nav_doc or {}).get("date", "")}},
        {"_id": 0}, sort=[("date", -1)])
    nav = (nav_doc or {}).get("nav", 1.0)
    nav_yday = (yday_doc or {}).get("nav", nav)
    nav_delta = (nav - nav_yday) / nav_yday if nav_yday else None

    # supply / total invested
    agg = await col(POSITIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "active"}},
        {"$group": {"_id": None,
                    "principal": {"$sum": "$principal_usd"},
                    "accrued":   {"$sum": "$accrued_interest"},
                    "count":     {"$sum": 1}}},
    ]).to_list(1)
    p = agg[0] if agg else {"principal": 0, "accrued": 0, "count": 0}
    supply = p["principal"]
    invested = supply + p["accrued"]
    treasury_balance = max(0, supply * 0.08)  # 8% liquidity buffer (synthetic)

    fund = {
        "fund_id":       "fund_quiron_pymes",
        "name":          "Quirón PyMEs",
        "nav":           round(nav, 6),
        "nav_delta_24h": nav_delta,
        "supply_circulating": round(supply, 2),
        "invested_usd":  round(invested, 2),
        "treasury_usd":  round(treasury_balance, 2),
        "positions":     p["count"],
        "asset_code":    "PROS",
    }

    stellar_accounts = [
        {"label": "Issuer",    "address": "GBPROSPERISSUER2026XYZ7K9L0M1N2O3P4Q5R6S7T8U9V0WPQR",
         "balance_usd":  0, "balance_xlm": 2.5, "is_native": True},
        {"label": "Treasury",  "address": "GBPROSPERTREASURY2026ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
         "balance_usd": round(treasury_balance, 2), "balance_xlm": 14.8},
        {"label": "Reward pool", "address": "GBPROSPERREWARDS2026WSXEDCRFVTGBYHNUJMIKOLPQAZ234567",
         "balance_usd": round(p["accrued"], 2), "balance_xlm": 5.1},
        {"label": "Fees account", "address": "GBPROSPERFEES2026QAZWSXEDCRFVTGBYHNUJMIKOLP345678",
         "balance_usd": round(supply * 0.001, 2), "balance_xlm": 1.2},
    ]
    xlm_total = sum(a["balance_xlm"] for a in stellar_accounts)

    return {
        "fund": fund,
        "stellar_accounts": stellar_accounts,
        "xlm_reserve_total": round(xlm_total, 2),
        "generated_at": _iso(datetime.now(timezone.utc)),
    }


# ---------------------------------------------------------------------------
# /admin/prosper-upstream/status  — 3-LED upstream health
# ---------------------------------------------------------------------------
@router.get("/prosper-upstream/status")
async def upstream_status(_: CurrentUser = Depends(require_ops)):
    """Returns enabled / reachable / authenticated. In sandbox preview the
    Stellar egress is blocked, so reachable is False. The structure stays
    stable so the UI lights its semaphore correctly when prod opens."""
    env = os.environ.get("AIPRISE_ENVIRONMENT", "sandbox")
    enabled = True
    # Egress to horizon is blocked in the preview — return false but document
    reachable = False
    authenticated = False
    return {
        "enabled":       enabled,
        "reachable":     reachable,
        "authenticated": authenticated,
        "environment":   env,
        "upstream_url":  "https://horizon.stellar.org",
        "note":          "Preview egress to horizon.stellar.org is blocked. "
                          "Once infra opens the egress, this endpoint will "
                          "perform a real /accounts probe.",
        "checked_at":    _iso(datetime.now(timezone.utc)),
    }


# ---------------------------------------------------------------------------
# /admin/operations/by-client/stats
# ---------------------------------------------------------------------------
@router.get("/operations/by-client/stats")
async def by_client_stats(_: CurrentUser = Depends(require_ops)):
    cutoff_30d = _iso(datetime.now(timezone.utc) - timedelta(days=30))
    rows = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False}},
        {"$group": {
            "_id": "$org_id",
            "total":   {"$sum": 1},
            "ok":      {"$sum": {"$cond": [{"$eq": ["$status", "confirmed"]}, 1, 0]}},
            "failed":  {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
            "last_at": {"$max": "$created_at"},
        }},
        {"$sort": {"total": -1}},
    ]).to_list(200)

    org_ids = [r["_id"] for r in rows if r["_id"]]
    orgs = {o["org_id"]: o async for o in col(ORGANIZATIONS).find(
        {"org_id": {"$in": org_ids}},
        {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1})}

    # sparkline last 30d daily counts per org
    spark_pipeline = [
        {"$match": {"is_deleted": False,
                    "org_id": {"$in": org_ids},
                    "created_at": {"$gte": cutoff_30d}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {"_id": {"org": "$org_id", "day": "$day"}, "n": {"$sum": 1}}},
        {"$sort": {"_id.day": 1}},
    ]
    spark_rows = await col(TRANSACTIONS).aggregate(spark_pipeline).to_list(5000)
    sparkmap: dict[str, list[int]] = {}
    for r in spark_rows:
        sparkmap.setdefault(r["_id"]["org"], []).append(r["n"])

    items = []
    for r in rows:
        oid = r["_id"]
        org = orgs.get(oid, {})
        total = r["total"]
        items.append({
            "org_id":     oid,
            "org_name":   org.get("commercial_name") or org.get("legal_name") or oid,
            "total":      total,
            "ok":         r["ok"],
            "failed":     r["failed"],
            "success_pct": round((r["ok"] / total) * 100, 1) if total else 0,
            "failed_pct":  round((r["failed"] / total) * 100, 1) if total else 0,
            "last_at":    r["last_at"],
            "sparkline":  sparkmap.get(oid, []),
        })
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# /admin/operations/volume-by-client
# ---------------------------------------------------------------------------
@router.get("/operations/volume-by-client")
async def volume_by_client(_: CurrentUser = Depends(require_ops)):
    now = datetime.now(timezone.utc)
    d24  = _iso(now - timedelta(hours=24))
    d7   = _iso(now - timedelta(days=7))
    d30  = _iso(now - timedelta(days=30))
    d60  = _iso(now - timedelta(days=60))

    pipeline = [
        {"$match": {"is_deleted": False, "status": "confirmed",
                    "type": {"$in": ["subscribe", "redeem"]}}},
        {"$group": {
            "_id": "$org_id",
            "vol_total": {"$sum": "$amount"},
            "vol_24h":   {"$sum": {"$cond": [{"$gte": ["$created_at", d24]},  "$amount", 0]}},
            "vol_7d":    {"$sum": {"$cond": [{"$gte": ["$created_at", d7]},   "$amount", 0]}},
            "vol_30d":   {"$sum": {"$cond": [{"$gte": ["$created_at", d30]},  "$amount", 0]}},
            "vol_prev_30d": {"$sum": {"$cond": [
                {"$and": [{"$gte": ["$created_at", d60]}, {"$lt": ["$created_at", d30]}]},
                "$amount", 0]}},
        }},
        {"$sort": {"vol_total": -1}},
    ]
    rows = await col(TRANSACTIONS).aggregate(pipeline).to_list(200)
    org_ids = [r["_id"] for r in rows if r["_id"]]
    orgs = {o["org_id"]: o async for o in col(ORGANIZATIONS).find(
        {"org_id": {"$in": org_ids}}, {"_id": 0, "org_id": 1,
        "commercial_name": 1, "legal_name": 1})}

    total_30d = sum(r["vol_30d"] for r in rows) or 1
    items = []
    for r in rows:
        oid  = r["_id"]
        org  = orgs.get(oid, {})
        prev = r["vol_prev_30d"]
        cur  = r["vol_30d"]
        delta_pct = ((cur - prev) / prev * 100) if prev else (100.0 if cur else 0.0)
        items.append({
            "org_id":    oid,
            "org_name":  org.get("commercial_name") or org.get("legal_name") or oid,
            "vol_24h":   round(r["vol_24h"],  2),
            "vol_7d":    round(r["vol_7d"],   2),
            "vol_30d":   round(cur,           2),
            "vol_total": round(r["vol_total"],2),
            "vol_prev_30d": round(prev, 2),
            "delta_pct_30d": round(delta_pct, 2),
            "share_pct_30d": round(cur / total_30d * 100, 2),
        })
    return {"items": items, "total": len(items), "total_volume_30d": round(total_30d, 2)}
