"""Phase 22 — Backoffice yield products + investments monitoring + dashboard.

All endpoints require `super_admin` or `finance_admin` (write) and broader
backoffice roles (read). audit-logged on every mutation.
"""
from __future__ import annotations

import csv
import io
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ALERTS, INVESTMENT_INTENTS, ORGANIZATIONS, POSITIONS, TRANSACTIONS,
)
from roles import Role

logger = logging.getLogger("prosper.admin_yield")
router = APIRouter(prefix="/admin/prosper", tags=["admin-yield"])

PRODUCTS = "products"

# Read = any backoffice role; Write = super_admin + finance_admin only.
_READ_ROLES  = {"super_admin", "admin", "finance_admin", "finance",
                  "compliance_admin", "compliance_officer", "ops"}
# Write = super_admin + finance (the canonical Role enum value; some
# deployments alias as "finance_admin" in legacy docs — accept both).
_WRITE_ROLES = {"super_admin", "finance_admin", "finance"}


def _role_str(user: CurrentUser) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def _require_read(u: CurrentUser) -> None:
    if _role_str(u) not in _READ_ROLES:
        raise HTTPException(403, f"role {_role_str(u)} cannot read yield admin")


def _require_write(u: CurrentUser) -> None:
    if _role_str(u) not in _WRITE_ROLES:
        raise HTTPException(403,
            "Only super_admin or finance_admin may mutate yield products/caps")


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# A. PRODUCTS CRUD
# ===========================================================================
class ProductIn(BaseModel):
    product_id:        str = Field(..., min_length=3, max_length=40,
                                       pattern="^[a-z0-9_]+$")
    name:              str = Field(..., min_length=2, max_length=120)
    description:       Optional[str] = ""
    accepted_asset:    str = Field("usdc",
                                       pattern="^(arsa|usdc|both)$")
    yield_asset:       str = Field("usdc",
                                       pattern="^(arsa|usdc)$")
    payout_asset:      str = Field("usdc",
                                       pattern="^(arsa|usdc)$")
    apr_bps:           int = Field(..., ge=0, le=20_000)
    term_days:         int = Field(0, ge=0, le=3_650)
    payout_schedule:   str = Field("at_maturity",
                                       pattern="^(daily|monthly|at_maturity)$")
    min_amount:        float = Field(10, ge=0)
    max_amount:        float = Field(1_000_000, ge=0)
    status:            str = Field("active",
                                       pattern="^(active|paused|archived|inactive)$")
    arsa_native_enabled: bool = False


class ProductPatch(BaseModel):
    name:              Optional[str] = None
    description:       Optional[str] = None
    accepted_asset:    Optional[str] = None
    yield_asset:       Optional[str] = None
    payout_asset:      Optional[str] = None
    apr_bps:           Optional[int] = None
    term_days:         Optional[int] = None
    payout_schedule:   Optional[str] = None
    min_amount:        Optional[float] = None
    max_amount:        Optional[float] = None
    status:            Optional[str] = None
    arsa_native_enabled: Optional[bool] = None


def _validate_coherence(doc: dict) -> None:
    """If yield_asset='arsa' it MUST be enabled. Mixing payout currencies
    without the flag is rejected to keep the user-facing UX consistent."""
    if doc.get("yield_asset") == "arsa" and not doc.get("arsa_native_enabled"):
        raise HTTPException(400,
            "yield_asset='arsa' requires arsa_native_enabled=true "
            "(ARSa-native yield path is not built yet — toggle is for future)")
    # If product accepts only ARSa, the payout asset must align with the
    # product semantics — either ARSa (native yield) or USDC (bridge).
    if doc.get("accepted_asset") == "arsa" \
            and doc.get("payout_asset") not in ("arsa", "usdc"):
        raise HTTPException(400, "payout_asset must be 'arsa' or 'usdc'")


@router.get("/products")
async def list_products(user: CurrentUser = Depends(get_current_user)):
    _require_read(user)
    rows = await col(PRODUCTS).find(
        {"is_deleted": {"$ne": True}}, {"_id": 0}).sort("apr_bps", 1) \
        .to_list(200)
    return {"items": rows, "total": len(rows)}


@router.post("/products")
async def create_product(body: ProductIn,
                            user: CurrentUser = Depends(get_current_user)):
    """CMS protocol — product catalog is fixed by the protocol.

    Per the Feb-2026 CMS migration, the operator no longer configures
    products: the contract dictates a 12-month cycle with `end` or `month`
    modality per asset (USDC/ARSa). Creation is intentionally blocked so
    no one accidentally introduces a phantom modality.
    """
    _require_write(user)
    raise HTTPException(
        status_code=403,
        detail="Product catalog is dictated by the Prosper CMS protocol "
                 "(modalities end/month × asset usdc/arsa, 12-month term). "
                 "Use the seeded catalog; manual creation is disabled.")


@router.patch("/products/{product_id}")
async def patch_product(product_id: str, body: ProductPatch,
                          user: CurrentUser = Depends(get_current_user)):
    """CMS protocol — only `status` is operator-mutable (emergency pause).

    Rates, terms, payout schedules and amount limits are fixed by the
    Prosper smart contract; the operator can only pause/archive a modality
    in case of incident. Any other field passed in the body is rejected.
    """
    _require_write(user)
    existing = await col(PRODUCTS).find_one({"product_id": product_id},
                                              {"_id": 0})
    if not existing:
        raise HTTPException(404, "product not found")
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return existing
    mutable = {"status"}
    bad = sorted(set(patch.keys()) - mutable)
    if bad:
        raise HTTPException(
            400,
            f"Fields not editable under CMS protocol: {bad}. Only "
            f"`status` (active|paused|archived) can be changed.")
    patch["updated_at"] = _iso()
    await col(PRODUCTS).update_one({"product_id": product_id},
                                      {"$set": patch})
    await log_action(actor=user, action="admin.prosper.product.status_changed",
                       resource_type="product", resource_id=product_id,
                       metadata={"new_status": patch.get("status")})
    return await col(PRODUCTS).find_one({"product_id": product_id},
                                           {"_id": 0})


# ===========================================================================
# B. CAPS per org
# ===========================================================================
class CapsIn(BaseModel):
    subscribe_daily_cap_usd:   Optional[float] = Field(None, ge=0)
    subscribe_monthly_cap_usd: Optional[float] = Field(None, ge=0)
    redeem_daily_cap_usd:      Optional[float] = Field(None, ge=0)
    redeem_monthly_cap_usd:    Optional[float] = Field(None, ge=0)
    arsa_withdraw_daily_cap_arsa:   Optional[float] = Field(None, ge=0)
    arsa_withdraw_monthly_cap_arsa: Optional[float] = Field(None, ge=0)


@router.patch("/caps/{org_id}")
async def patch_caps(org_id: str, body: CapsIn,
                       user: CurrentUser = Depends(get_current_user)):
    _require_write(user)
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id}, {"_id": 0})
    if not org:
        raise HTTPException(404, "org not found")
    before = (org.get("caps") or {}).copy()
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return {"caps": before}
    after = {**before, **patch}
    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {"caps": after, "updated_at": _iso()}})
    await log_action(actor=user, action="admin.prosper.caps.updated",
                       resource_type="organization", resource_id=org_id,
                       metadata={"before": before, "after": after,
                                  "changed": list(patch.keys())})
    return {"caps": after}


@router.get("/caps/{org_id}")
async def get_caps(org_id: str, user: CurrentUser = Depends(get_current_user)):
    _require_read(user)
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id},
                                              {"_id": 0, "caps": 1})
    if not org:
        raise HTTPException(404, "org not found")
    return {"caps": org.get("caps") or {}}


# ===========================================================================
# C. Intents monitoring + actions
# ===========================================================================
@router.get("/intents")
async def list_intents(
    user: CurrentUser = Depends(get_current_user),
    direction:     Optional[str] = Query(None, pattern="^(in|out)$"),
    step:          Optional[List[str]] = Query(None),
    org_id:        Optional[str] = None,
    end_customer_id: Optional[str] = None,
    stuck_minutes: int = Query(15, ge=0, le=10_080),
    limit:         int = Query(200, ge=1, le=1000),
):
    _require_read(user)
    q: dict = {}
    if direction:
        q["direction"]       = direction
    if step:
        q["step"]            = {"$in": step}
    if org_id:
        q["org_id"]          = org_id
    if end_customer_id:
        q["end_customer_id"] = end_customer_id
    rows = await col(INVESTMENT_INTENTS).find(q, {"_id": 0}).sort(
        "created_at", -1).limit(limit).to_list(limit)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)
                ).isoformat()
    STUCK_STEPS = {"converting", "bridging", "bridged", "subscribing",
                    "redeeming", "reconverting"}
    for r in rows:
        r["is_stuck"] = (r.get("step") in STUCK_STEPS
                            and (r.get("updated_at") or "") < cutoff)
    return {"items": rows, "total": len(rows),
             "stuck_count": sum(1 for r in rows if r.get("is_stuck")),
             "failed_count": sum(1 for r in rows
                                    if r.get("step") == "failed")}


@router.get("/intents.csv")
async def export_intents_csv(
    user: CurrentUser = Depends(get_current_user),
    direction: Optional[str] = Query(None),
    step:      Optional[List[str]] = Query(None),
    org_id:    Optional[str] = None,
):
    _require_read(user)
    q: dict = {}
    if direction:
        q["direction"] = direction
    if step:
        q["step"]      = {"$in": step}
    if org_id:
        q["org_id"]    = org_id
    rows = await col(INVESTMENT_INTENTS).find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(5000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "org_id", "end_customer_id", "direction", "source",
                  "step", "amount_arsa", "amount_usdc", "prosper_tx_id",
                  "andes_transfer_id", "position_id", "fail_reason",
                  "created_at", "updated_at"])
    for r in rows:
        w.writerow([r.get(k) for k in (
            "id", "org_id", "end_customer_id", "direction", "source", "step",
            "amount_arsa", "amount_usdc", "prosper_tx_id",
            "andes_transfer_id", "position_id", "fail_reason",
            "created_at", "updated_at")])
    await log_action(actor=user, action="admin.prosper.intents.csv_exported",
                       resource_type="investment_intent",
                       resource_id="bulk",
                       metadata={"count": len(rows)})
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition":
                  f'attachment; filename="intents_{int(datetime.now().timestamp())}.csv"'})


class IntentActionIn(BaseModel):
    action: str = Field(..., pattern="^(retry|mark_failed)$")
    reason: Optional[str] = None


@router.post("/intents/{intent_id}/action")
async def intent_action(intent_id: str, body: IntentActionIn,
                          user: CurrentUser = Depends(get_current_user)):
    """Operator actions on stuck/failed intents — `retry` re-enqueues the
    flow via the idempotent orchestrator; `mark_failed` flips the step
    to `failed` with a reason (audit-logged). NEVER transitions
    automatically — operator must opt in."""
    _require_write(user)
    intent = await col(INVESTMENT_INTENTS).find_one({"id": intent_id},
                                                      {"_id": 0})
    if not intent:
        raise HTTPException(404, "intent not found")

    if body.action == "mark_failed":
        if not body.reason:
            raise HTTPException(400, "reason required for mark_failed")
        await col(INVESTMENT_INTENTS).update_one(
            {"id": intent_id},
            {"$set": {"step": "failed",
                        "fail_reason": body.reason,
                        "failed_by": user.email,
                        "failed_at": _iso(),
                        "updated_at": _iso()}})
        await log_action(actor=user, action="admin.prosper.intent.marked_failed",
                           resource_type="investment_intent",
                           resource_id=intent_id,
                           metadata={"reason": body.reason,
                                      "previous_step": intent.get("step")})
        return {"ok": True, "action": "mark_failed"}

    # action == "retry" — log only; operator should re-POST the original
    # body. The orchestrator is idempotent by prosper_tx_id so it picks up
    # the failed step. We surface a marker so the UI can hint the user.
    await log_action(actor=user, action="admin.prosper.intent.retry_requested",
                       resource_type="investment_intent",
                       resource_id=intent_id,
                       metadata={"step": intent.get("step")})
    return {"ok": True, "action": "retry",
             "note": "Re-POST POST /api/v1/investments/intent with the same "
                      "body (idempotent by prosper_tx_id)."}


# ===========================================================================
# D. Positions + Dashboard totals
# ===========================================================================
@router.get("/positions")
async def list_positions(
    user: CurrentUser = Depends(get_current_user),
    org_id:    Optional[str] = None,
    status:    Optional[str] = None,
    asset:     Optional[str] = None,
    limit:     int = Query(500, ge=1, le=5000),
):
    _require_read(user)
    q: dict = {"is_deleted": False}
    if org_id:
        q["org_id"] = org_id
    if status:
        q["status"] = status
    if asset:
        q["asset"]  = asset
    rows = await col(POSITIONS).find(q, {"_id": 0}).sort(
        "created_at", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}


@router.get("/dashboard")
async def dashboard(user: CurrentUser = Depends(get_current_user)):
    """Phase 22 / D — Executive yield dashboard data. Returns totals broken
    down by asset (ARSa vs USDC) — they MUST stay separated per the PRD."""
    _require_read(user)
    by_asset_principal = await col(POSITIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "active"}},
        {"$group": {"_id": {"$ifNull": ["$asset", "usdc"]},
                     "principal": {"$sum": "$principal_usd"},
                     "accrued":   {"$sum": "$accrued_interest"},
                     "count":     {"$sum": 1}}},
    ]).to_list(10)
    totals = {row["_id"]: {"principal": round(row["principal"], 6),
                            "accrued":   round(row["accrued"], 6),
                            "count":     row["count"]} for row in by_asset_principal}

    intents_in_progress = await col(INVESTMENT_INTENTS).count_documents(
        {"step": {"$in": ["converting", "bridging", "bridged",
                            "subscribing", "redeeming", "reconverting"]}})
    intents_failed      = await col(INVESTMENT_INTENTS).count_documents(
        {"step": "failed"})
    stuck_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=30)
                       ).isoformat()
    intents_stuck = await col(INVESTMENT_INTENTS).count_documents(
        {"step": {"$in": ["converting", "bridging", "bridged",
                            "subscribing", "redeeming", "reconverting"]},
          "updated_at": {"$lt": stuck_cutoff}})

    # 30-day evolution (intents created per day, total principal trend)
    days_ago_30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    timeseries = await col(INVESTMENT_INTENTS).aggregate([
        {"$match": {"created_at": {"$gte": days_ago_30}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {"_id": {"day": "$day", "direction": "$direction"},
                     "n": {"$sum": 1}}},
        {"$sort": {"_id.day": 1}},
    ]).to_list(2000)

    return {
        "totals_by_asset": totals,
        "intents": {
            "in_progress": intents_in_progress,
            "stuck":       intents_stuck,
            "failed":      intents_failed,
        },
        "active_positions": sum(t["count"] for t in totals.values()),
        "timeseries": [
            {"day": r["_id"]["day"], "direction": r["_id"]["direction"],
              "n": r["n"]}
            for r in timeseries],
    }


# ===========================================================================
# E. Trustlines monitor (used by /admin/prosper/inversiones)
# ===========================================================================
@router.get("/trustlines")
async def list_trustlines(user: CurrentUser = Depends(get_current_user)):
    """Per-org trustlines snapshot. For each org with a Prosper wallet,
    returns the trustlines array; missing assets are flagged so the UI can
    surface a force-ensure button (Phase 20 endpoint)."""
    _require_read(user)
    REQUIRED = ["usdc"]   # arsa is "future" — not blocking
    rows = await col(ORGANIZATIONS).find(
        {"is_deleted": False, "prosper_wallet": {"$exists": True}},
        {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1,
          "prosper_wallet": 1}).to_list(500)
    items = []
    for org in rows:
        w = org.get("prosper_wallet") or {}
        trustlines = w.get("trustlines") or []
        established = {t.get("asset") for t in trustlines}
        missing = [a for a in REQUIRED if a not in established]
        items.append({
            "org_id":           org["org_id"],
            "name":             org.get("commercial_name")
                                     or org.get("legal_name") or org["org_id"],
            "stellar_address":  w.get("stellar_address"),
            "trustlines":       trustlines,
            "missing":          missing,
            "ok":               len(missing) == 0,
        })
    return {"items": items, "total": len(items),
             "missing_count": sum(1 for i in items if i["missing"])}


# ---------------------------------------------------------------------------
# P1-3 (Feb 2026) — CMS treasury + stakings monitor + sync widget
# ---------------------------------------------------------------------------
@router.get("/treasury")
async def get_cms_treasury(user: CurrentUser = Depends(get_current_user)):
    """Live treasury reading from the Prosper CMS partner namespace.

    Wraps `RealProsperAdapter.get_treasury()` and returns a stable shape:
        {address, balanceUSDC, balanceARSA, balanceXLM, mode, refreshed_at}
    """
    _require_read(user)
    from integrations.prosper import get_adapter, ProsperError
    try:
        t = await get_adapter().get_treasury()
    except ProsperError as e:
        raise HTTPException(502, f"CMS treasury read failed: {e}")
    import os
    return {"address":      t.get("address"),
             "balanceUSDC":  t.get("balanceUSDC"),
             "balanceARSA":  t.get("balanceARSA"),
             "balanceXLM":   t.get("balanceXLM"),
             "mode":         os.environ.get("PROSPER_MODE", "mock"),
             "refreshed_at": datetime.now(timezone.utc).isoformat()}


@router.get("/stakings")
async def list_cms_stakings(
        scope: str = Query("all", regex="^(all|ours|external)$"),
        asset: Optional[str] = Query(None, regex="^(arsa|usdc)$"),
        status: Optional[str] = Query(None,
            regex="^(active|matured|redeemed)$"),
        user: CurrentUser = Depends(get_current_user)):
    """Local view of CMS-synced stakings, grouped by ownership.

    Reads from `positions` (filled by `jobs/staking_sync.py`). Returns two
    buckets:
      - `ours`     : positions with `external != True` AND a wallet/memo/hash
      - `external` : positions flagged `external=True` (stakings observed
                       on-chain that don't match any of our provisioned
                       wallets — historical/test residue from the partner).

    Filters:
      - scope=all|ours|external
      - asset=arsa|usdc
      - status=active|matured|redeemed
    """
    _require_read(user)

    base: dict = {"wallet": {"$exists": True, "$ne": None},
                   "memo":   {"$exists": True, "$ne": None},
                   "is_deleted": {"$ne": True}}
    if asset:
        base["asset"] = asset
    if status:
        base["status"] = status

    async def _fetch(q: dict, limit: int = 200) -> list[dict]:
        rows = await col(POSITIONS).find(q, {"_id": 0}).sort(
            "updated_at", -1).to_list(limit)
        return rows

    ours: list[dict] = []
    external: list[dict] = []
    if scope in ("all", "ours"):
        ours = await _fetch({**base, "external": {"$ne": True}})
    if scope in ("all", "external"):
        external = await _fetch({**base, "external": True})

    # Group ours by org for the UI.
    by_org: dict[str, dict] = {}
    org_ids = {p["org_id"] for p in ours if p.get("org_id")}
    if org_ids:
        cursor = col(ORGANIZATIONS).find(
            {"org_id": {"$in": list(org_ids)}},
            {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1})
        async for o in cursor:
            by_org[o["org_id"]] = {
                "org_id":           o["org_id"],
                "name":             o.get("commercial_name")
                                       or o.get("legal_name") or o["org_id"],
                "positions":        [],
                "principal_arsa":   0.0,
                "principal_usdc":   0.0,
                "active_count":     0,
            }
    for p in ours:
        oid = p.get("org_id")
        if not oid:
            continue
        g = by_org.get(oid)
        if not g:
            continue
        g["positions"].append(p)
        amt = float(p.get("principal_native") or 0)
        if p.get("asset") == "arsa":
            g["principal_arsa"] += amt
        else:
            g["principal_usdc"] += amt
        if p.get("status") == "active":
            g["active_count"] += 1

    return {
        "ours": {
            "items":       ours,
            "by_org":      list(by_org.values()),
            "total":       len(ours),
        },
        "external": {
            "items": external,
            "total": len(external),
            "note":  ("Stakings observados on-chain en wallets que no son "
                       "nuestras. Residuo histórico / pruebas viejas de "
                       "Prosper (pre-integración ARSa). No requieren acción."),
        },
        "total":      len(ours) + len(external),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/staking-sync/status")
async def staking_sync_status(user: CurrentUser = Depends(get_current_user)):
    """Return the last poller run's summary + scheduler config."""
    _require_read(user)
    import os
    from jobs.staking_sync import get_last_run, is_enabled
    last = await get_last_run()
    return {
        "enabled":          is_enabled(),
        "mode":             os.environ.get("PROSPER_MODE", "mock"),
        "interval_minutes": int(os.environ.get(
            "PROSPER_STAKING_SYNC_INTERVAL_MINUTES", "5")),
        "last_run":         last,
    }


@router.post("/staking-sync/run")
async def staking_sync_run_now(user: CurrentUser = Depends(get_current_user)):
    """Trigger the staking poller on-demand. Returns the run summary."""
    _require_write(user)
    from jobs.staking_sync import run_sync_once
    summary = await run_sync_once()
    await log_action(actor=user, action="admin.prosper.staking_sync.run_now",
                       resource_type="staking_sync", resource_id="manual",
                       metadata={k: summary.get(k) for k in
                                  ("processed", "created", "updated",
                                   "external_total", "skipped", "ok")})
    return summary


# ---------------------------------------------------------------------------
# P1-1 fix · wallet reconciliation against /cms/users (super_admin only)
# ---------------------------------------------------------------------------
@router.post("/wallets/reconcile")
async def reconcile_prosper_wallets(
        org_id: Optional[str] = Query(None,
            description="Reconcile a single org. Omit to reconcile every org "
                        "that has any prosper_wallets entry."),
        user: CurrentUser = Depends(get_current_user)):
    """Re-source `organizations.prosper_wallets[].address` from `/cms/users`.

    Background: a partner-side bug in `POST /cms/cashin` (Feb 2026)
    caused the response body to echo the FIRST wallet ever created for a
    given prosperId, regardless of the `cashin` modality requested. The
    truth lives in `GET /cms/users` (one row per prosperId × modality).
    This endpoint walks every org's stored `prosper_wallets` array and
    corrects any address that drifted from the live CMS row.

    Read-only against the CMS (only GETs); writes only Mongo address
    strings on `organizations.prosper_wallets`. **Does NOT move funds.**

    Restricted to `super_admin` to keep this admin-only debug/repair tool
    behind the highest privilege gate.
    """
    if user.role not in ("super_admin", "Role.super_admin"):
        raise HTTPException(
            403, "Only super_admin may run wallet reconciliation.")

    from routes.onramp_flow import (
        reconcile_org_wallets, reconcile_all_org_wallets,
    )

    if org_id:
        result = await reconcile_org_wallets(org_id)
    else:
        result = await reconcile_all_org_wallets()

    # Audit-log every correction we applied, with before/after addresses.
    corrected_items: list[dict] = []
    if org_id:
        for change in (result.get("changes") or []):
            if change.get("action") == "address_corrected":
                corrected_items.append({"org_id":   org_id,
                                          "modality": change["modality"],
                                          "before":   change["before"],
                                          "after":    change["after"]})
    else:
        for entry in (result.get("items") or []):
            for change in (entry.get("changes") or []):
                if change.get("action") == "address_corrected":
                    corrected_items.append({
                        "org_id":   entry["org_id"],
                        "modality": change["modality"],
                        "before":   change["before"],
                        "after":    change["after"]})

    await log_action(
        actor=user,
        action="admin.prosper.wallets.reconcile",
        resource_type="prosper_wallets",
        resource_id=org_id or "all",
        metadata={
            "scope":           "single" if org_id else "all",
            "orgs_scanned":    result.get("orgs_scanned",
                                          1 if org_id else 0),
            "corrected_total": result.get("corrected_total",
                                          result.get("corrected", 0)),
            "corrections":     corrected_items,
            "ok":              result.get("ok"),
        })
    return result

