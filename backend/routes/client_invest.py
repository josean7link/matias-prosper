"""Phase 9 — Products + Positions + Buy/Redeem endpoints + post-onramp trigger.

Mounted under /api/v1.
"""
from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ALERTS, ONRAMP_ORDERS, ORGANIZATIONS, POSITIONS,
    RAMP_ACCOUNTS, RAMP_BALANCES, TRANSACTIONS, USERS,
)
from integrations.prosper import ProsperError, get_adapter as prosper_adapter
from ramp.adapters.andes import AndesAdapter
from ramp.provider import NotSupportedByProvider

logger = logging.getLogger("prosper.invest")

PRODUCTS = "products"

router = APIRouter(prefix="/client", tags=["client-invest"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Default product seeds (CMS protocol catalog).
# ---------------------------------------------------------------------------
# Per the new Prosper CMS protocol, the catalog is NOT operator-configurable
# anymore: the contract dictates a single 12-month staking cycle with two
# settlement modalities (`end` and `month`). Asset is preserved through the
# whole cycle: ARSa stays in ARSa, USDC stays in USDC (no bridge).
#
# The seeded `apr_bps` is a UI default; the canonical rate lives on the
# Stellar smart contract and is echoed back per-staking via
# /api/v1/cms/staking[].rate (see RealProsperAdapter.get_staking_records).
DEFAULT_PRODUCTS = [
    {"product_id": "usdc_end",   "name": "Prosper USDC · End",
     "term_days": 365, "apr_bps": 1700, "min_amount": 100, "max_amount": 5_000_000,
     "status": "active", "asset": "usdc", "yield_asset": "usdc",
     "payout_asset": "usdc", "payout_schedule": "at_maturity",
     "modality": "end", "term_months": 12,
     "arsa_native_enabled": False,
     "description": "USDC · cobro al vencimiento (12 meses)."},
    {"product_id": "usdc_month", "name": "Prosper USDC · Mensual",
     "term_days": 365, "apr_bps": 1700, "min_amount": 100, "max_amount": 5_000_000,
     "status": "active", "asset": "usdc", "yield_asset": "usdc",
     "payout_asset": "usdc", "payout_schedule": "monthly",
     "modality": "month", "term_months": 12,
     "arsa_native_enabled": False,
     "description": "USDC · pago mensual de intereses (12 meses)."},
    {"product_id": "arsa_end",   "name": "Prosper ARSa · End",
     "term_days": 365, "apr_bps": 1700, "min_amount": 10, "max_amount": 5_000_000_000,
     "status": "active", "asset": "arsa", "yield_asset": "arsa",
     "payout_asset": "arsa", "payout_schedule": "at_maturity",
     "modality": "end", "term_months": 12,
     "arsa_native_enabled": True,
     "description": "ARSa · cobro al vencimiento (12 meses)."},
    {"product_id": "arsa_month", "name": "Prosper ARSa · Mensual",
     "term_days": 365, "apr_bps": 1700, "min_amount": 10, "max_amount": 5_000_000_000,
     "status": "active", "asset": "arsa", "yield_asset": "arsa",
     "payout_asset": "arsa", "payout_schedule": "monthly",
     "modality": "month", "term_months": 12,
     "arsa_native_enabled": True,
     "description": "ARSa · pago mensual de intereses (12 meses)."},
]

# Legacy product ids that were invented before the CMS protocol was defined.
# We soft-archive them so anyone with an outstanding position still sees the
# product metadata, but they're hidden from the wizard + admin listings.
_LEGACY_PRODUCT_IDS = ["liquid_v1", "term_30", "term_90", "term_180"]


async def ensure_products() -> None:
    """Seed the CMS-aligned catalog and archive the legacy products.

    Idempotent: rerunning leaves existing rows untouched (only $setOnInsert).
    The legacy archival step is also idempotent — it sets status='archived'
    on the 4 invented products (Liquid/30d/90d/180d) so they fall out of the
    wizard's `status=active` filter without losing audit history.
    """
    for p in DEFAULT_PRODUCTS:
        await col(PRODUCTS).update_one(
            {"product_id": p["product_id"]},
            {"$setOnInsert": {**p, "created_at": _iso_now(),
                                "is_deleted": False}},
            upsert=True)
    # Archive legacy products (don't soft-delete — we want history readable).
    await col(PRODUCTS).update_many(
        {"product_id": {"$in": _LEGACY_PRODUCT_IDS},
         "status": {"$ne": "archived"}},
        {"$set": {"status": "archived",
                    "archived_reason": "cms_protocol_replaces_legacy_catalog",
                    "updated_at": _iso_now()}})


@router.get("/products")
async def list_products(_: CurrentUser = Depends(get_current_user)):
    await ensure_products()
    rows = await col(PRODUCTS).find(
        {"is_deleted": {"$ne": True}, "status": "active"}, {"_id": 0})\
        .sort("term_days", 1).to_list(50)
    return {"items": rows}


# ---------------------------------------------------------------------------
# P1-1 (Feb 2026) — Deposit wallets per (org, modality)
# ---------------------------------------------------------------------------
@router.get("/deposit-wallets")
async def get_deposit_wallets(
        user: CurrentUser = Depends(get_current_user)):
    """Return the client's Stellar wallets, one per CMS staking modality.

    The CMS protocol provisions one wallet per (prosperId, modality), so a
    client operating both `end` and `month` gets two distinct addresses.
    Calling this endpoint will lazily provision any missing wallet for
    approved orgs (idempotent via `ensure_org_prosper_wallet`).

    Used by `/client/cargar-usdc` to render QR codes + copyable addresses
    + the (mandatory) network safety warning.
    """
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": user.org_id, "is_deleted": False},
        {"_id": 0, "kyb_status": 1, "prosper_wallets": 1,
          "prosper_id": 1, "stellar_address": 1,
          "prosper_cashin_modality": 1, "prosper_user_id": 1})
    if not org or org.get("kyb_status") != "approved":
        raise HTTPException(403,
            "Tu KYB no está aprobado. No podés recibir transferencias todavía.")

    from routes.onramp_flow import (
        ensure_org_prosper_wallet, VALID_MODALITIES,
    )

    wallets = []
    for modality in VALID_MODALITIES:
        try:
            entry = await ensure_org_prosper_wallet(user.org_id,
                                                       modality=modality)
        except Exception as e:  # noqa: BLE001
            logger.warning("deposit-wallets: provisioning failed for "
                              "org=%s modality=%s: %s",
                              user.org_id, modality, e)
            continue
        if not entry.get("stellar_address"):
            continue
        wallets.append({
            "modality":        modality,
            "address":         entry["stellar_address"],
            "prosper_user_id": entry.get("prosper_user_id") or "",
            "created":         entry.get("created", False),
        })

    return {
        "wallets":     wallets,
        "network":     "stellar",
        "asset":       "USDC",
        "asset_issuer": "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN",
        "prosper_id":  org.get("prosper_id") or user.org_id,
        # Mandatory safety copy — surfaced verbatim by the UI so the user
        # cannot dismiss it before transferring funds.
        "safety_warning": (
            "Enviá USDC ÚNICAMENTE en la red Stellar. "
            "Cualquier transferencia desde otra red (Ethereum, Polygon, BSC, etc.) "
            "implica la PÉRDIDA TOTAL de los fondos. Los depósitos son "
            "irreversibles."),
        "fetched_at": _iso_now(),
    }



# ---------------------------------------------------------------------------
# Manual buy
# ---------------------------------------------------------------------------
class BuyIn(BaseModel):
    product_id:  str
    amount_usdc: float = Field(..., gt=0)


async def _balance_for(user: CurrentUser) -> float:
    """Compute available USDC = sum(onramp+redeem) - sum(subscribe+offramp)."""
    rows = await col(TRANSACTIONS).find(
        {"org_id": user.org_id, "is_deleted": False,
          "status": "confirmed"}, {"_id": 0, "type": 1, "amount": 1}
    ).to_list(2000)
    in_usdc  = sum(r["amount"] for r in rows if r["type"] in ("onramp", "redeem"))
    out_usdc = sum(r["amount"] for r in rows if r["type"] in ("subscribe", "offramp"))
    return max(0.0, round(in_usdc - out_usdc, 2))


@router.get("/balances")
async def get_balances(user: CurrentUser = Depends(get_current_user)):
    """Returns available USDC + (when wallet exists) Prosper balance via adapter.

    Sprint 12.4: balances are queried per-org now (one wallet per
    organization). If the org doesn't have a wallet yet, we lazily
    provision it here so /balances always returns useful data after the
    first call.
    """
    available_usdc = await _balance_for(user)
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": user.org_id, "is_deleted": False},
        {"_id": 0, "prosper_user_id": 1, "stellar_address": 1, "kyb_status": 1})
    # Only attempt provisioning + Prosper balance reads for approved orgs.
    if not org or org.get("kyb_status") != "approved":
        return {"available_usdc":   available_usdc,
                 "address":          None,
                 "balance_prosper":  None,
                 "balance_xlm":      None,
                 "mode":             prosper_adapter().mode}

    try:
        if not org.get("prosper_user_id"):
            from routes.onramp_flow import ensure_org_prosper_wallet
            await ensure_org_prosper_wallet(user.org_id)

        bal = await prosper_adapter().get_user_balances(user.org_id)
        return {
            "available_usdc":   available_usdc,
            "address":          bal.address,
            "balance_prosper":  float(bal.balance_prosper or 0),
            "balance_xlm":      float(bal.balance_xlm or 0),
            "mode":             prosper_adapter().mode,
        }
    except ProsperError as e:
        logger.warning("get_balances failed: %s", e)
        return {
            "available_usdc":   available_usdc,
            "address":          None,
            "balance_prosper":  None,
            "balance_xlm":      None,
            "mode":             prosper_adapter().mode,
            "error":            str(e),
        }


@router.post("/positions")
async def create_position(body: BuyIn, user: CurrentUser = Depends(get_current_user)):
    """Manual buy — used by /client/invest page."""
    await ensure_products()
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": user.org_id, "is_deleted": False}, {"_id": 0})
    if not org or org.get("kyb_status") != "approved" or org.get("paused"):
        raise HTTPException(403, "Operations are blocked for this organization")

    product = await col(PRODUCTS).find_one(
        {"product_id": body.product_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not product or product.get("status") != "active":
        raise HTTPException(404, "Product not found or inactive")
    if body.amount_usdc < (product.get("min_amount") or 0):
        raise HTTPException(400, f"Below min_amount {product['min_amount']}")
    if body.amount_usdc > (product.get("max_amount") or float("inf")):
        raise HTTPException(400, f"Above max_amount {product['max_amount']}")
    # Balance check is asset-aware: ARSa products consume ARSa from the
    # ramp account (CVU pesos already tokenized); USDC products consume
    # the on-platform USDC ledger. The CMS protocol keeps each asset in
    # its own lane — we never cross-check ARSa vs USDC.
    asset = (product.get("asset") or "usdc").lower()
    if asset == "arsa":
        arsa_row = await col(RAMP_BALANCES).find_one(
            {"org_id": user.org_id, "asset": "arsa"},
            {"_id": 0, "balance": 1}, sort=[("as_of", -1)])
        if not arsa_row:
            from db import RAMP_ACCOUNTS
            acc_ids = [a["id"] async for a in
                          col(RAMP_ACCOUNTS).find({"org_id": user.org_id},
                                                    {"_id": 0, "id": 1})]
            if acc_ids:
                arsa_row = await col(RAMP_BALANCES).find_one(
                    {"ramp_account_id": {"$in": acc_ids}, "asset": "arsa"},
                    {"_id": 0, "balance": 1}, sort=[("as_of", -1)])
        avail = float(arsa_row.get("balance") or 0) if arsa_row else 0.0
        if body.amount_usdc > avail:
            raise HTTPException(400, f"Saldo ARSa insuficiente ({avail:.2f})")
    else:
        avail = await _balance_for(user)
        if body.amount_usdc > avail:
            raise HTTPException(400, f"Saldo USDC insuficiente ({avail:.2f})")

    res = await _execute_buy(
        user=user, org=org, product=product, amount=body.amount_usdc,
        related_onramp_id=None, trigger="manual")
    if not res["ok"]:
        raise HTTPException(502, res.get("error") or "Buy failed")
    return res


@router.get("/positions")
async def list_positions(user: CurrentUser = Depends(get_current_user)):
    rows = await col(POSITIONS).find(
        {"org_id": user.org_id, "is_deleted": False}, {"_id": 0}
    ).sort("start", -1).to_list(500)
    return {"items": rows}


@router.get("/positions/{position_id}")
async def get_position(position_id: str,
                        user: CurrentUser = Depends(get_current_user)):
    pos = await col(POSITIONS).find_one(
        {"position_id": position_id, "org_id": user.org_id, "is_deleted": False},
        {"_id": 0})
    if not pos:
        raise HTTPException(404, "Position not found")
    txs = await col(TRANSACTIONS).find(
        {"org_id": user.org_id, "related_position_id": position_id,
          "is_deleted": False}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return {"position": pos, "events": txs}


# ---------------------------------------------------------------------------
# P1-2 (Feb 2026) — Multi-asset client dashboard summary
# ---------------------------------------------------------------------------
def _empty_aum_bucket() -> dict:
    return {"principal": 0.0, "yield_accrued": 0.0, "yield_claimed": 0.0,
             "positions": 0, "active": 0}


async def _read_stellar_balance(*, org_id: str, asset_code: str,
                                 asset_issuer: str) -> float:
    """Live read of the org's Stellar wallet balance for (code, issuer).

    Returns 0.0 if there's no provisioned wallet or Horizon is
    unreachable. Never raises — callers use this in the hot path.
    """
    if not asset_issuer:
        return 0.0
    from db import RAMP_WALLETS
    # Match the asset lane the wallet was provisioned under (case-insensitive
    # code — DB stores "arsa"/"usdc" lower-case).
    wallet = await col(RAMP_WALLETS).find_one(
        {"org_id": org_id, "asset": asset_code.lower(),
         "is_deleted": {"$ne": True}},
        {"_id": 0, "address": 1},
        sort=[("created_at", -1)])
    address = (wallet or {}).get("address")
    if not address:
        return 0.0
    from integrations.horizon import get_adapter
    balances = await get_adapter().get_account_balances(address=address)
    for b in balances:
        if (b.asset_code == asset_code
                and b.asset_issuer == asset_issuer):
            try:
                return float(b.balance)
            except (TypeError, ValueError):
                return 0.0
    return 0.0



@router.get("/dashboard-summary")
async def dashboard_summary(user: CurrentUser = Depends(get_current_user)):
    """Aggregates everything the client dashboard needs in a single call.

    CMS protocol invariant: each asset stays in its native lane. ARSa never
    converts into USDC and vice versa. KPIs are surfaced separately per
    currency — no cross-asset normalization happens here.
    """
    org_id = user.org_id

    # 1. AUM + yield by asset (sums over `positions`).
    pipeline = [
        {"$match": {"org_id": org_id, "is_deleted": False,
                      "external": {"$ne": True}}},
        {"$group": {
            "_id": {"asset": {"$ifNull": ["$asset", "usdc"]}},
            "principal":      {"$sum": {"$ifNull": ["$principal_native",
                                                       {"$ifNull": ["$principal_usd", 0]}]}},
            "yield_accrued":  {"$sum": {"$ifNull": ["$accrued_interest", 0]}},
            "yield_claimed":  {"$sum": {"$ifNull": ["$claimed_interest", 0]}},
            "positions":      {"$sum": 1},
            "active":         {"$sum": {"$cond": [
                                          {"$eq": ["$status", "active"]}, 1, 0]}},
        }},
    ]
    aum: dict[str, dict] = {"arsa": _empty_aum_bucket(),
                              "usdc": _empty_aum_bucket()}
    async for row in col(POSITIONS).aggregate(pipeline):
        asset = (row["_id"]["asset"] or "usdc").lower()
        if asset not in aum:
            continue
        aum[asset] = {
            "principal":     float(row.get("principal") or 0),
            "yield_accrued": float(row.get("yield_accrued") or 0),
            "yield_claimed": float(row.get("yield_claimed") or 0),
            "positions":     int(row.get("positions") or 0),
            "active":        int(row.get("active") or 0),
        }

    # 2. Cash balances — CMS protocol surfaces TWO ARSa sub-balances:
    #    * arsa_cvu     → digital pesos already inside the org's CVU
    #                       (pre-tokenization on the ramp side)
    #    * arsa_stellar → ARSa tokens already minted to the org's
    #                       Stellar wallet, ready to transfer to the
    #                       ARSAp contract for staking.
    #    USDC also has TWO sub-balances:
    #    * usdc_platform → free USDC on the platform's internal ledger
    #                        (legacy fiat-onramp surplus, retire-able).
    #    * usdc_stellar  → USDC at the org's Stellar deposit wallet,
    #                        ready to transfer to USDCp.
    #
    # Freshness: before reading `ramp_balances`, ask the provider for
    # the current numbers so a CVU deposit that just landed shows up
    # immediately (webhook or not). Best-effort — never blocks the
    # dashboard if the provider is slow/down.
    try:
        from services.ramp_balance_sync import refresh_ramp_balances_for_org
        await refresh_ramp_balances_for_org(org_id)
    except Exception as e:                                    # noqa: BLE001
        logger.warning("dashboard_summary balance refresh failed "
                          "org=%s: %s", org_id, e)

    available_usdc = await _balance_for(user)
    arsa_row = await col(RAMP_BALANCES).find_one(
        {"org_id": org_id, "asset": "arsa"},
        {"_id": 0, "balance": 1, "as_of": 1},
        sort=[("as_of", -1)])
    if not arsa_row:
        from db import RAMP_ACCOUNTS
        acc_ids = []
        async for a in col(RAMP_ACCOUNTS).find({"org_id": org_id},
                                                  {"_id": 0, "id": 1}):
            acc_ids.append(a["id"])
        if acc_ids:
            arsa_row = await col(RAMP_BALANCES).find_one(
                {"ramp_account_id": {"$in": acc_ids}, "asset": "arsa"},
                {"_id": 0, "balance": 1, "as_of": 1},
                sort=[("as_of", -1)])
    arsa_cvu = float(arsa_row.get("balance") or 0) if arsa_row else 0.0

    # `arsa_stellar` — live read of the org's Stellar wallet balance via
    # Horizon (`GET /accounts/{address}`). This is the second source of
    # truth: even if the provider-side ramp_balances is stale, the
    # on-chain read reflects reality. Best-effort — falls back to 0 if
    # Horizon is unreachable (mock adapter, network blocked, etc.).
    arsa_stellar = 0.0
    usdc_stellar = 0.0
    try:
        arsa_stellar = await _read_stellar_balance(
            org_id=org_id, asset_code="ARSa",
            asset_issuer=os.environ.get("ARSA_ISSUER", ""))
    except Exception as e:                                    # noqa: BLE001
        logger.warning("arsa_stellar read failed org=%s: %s", org_id, e)
    try:
        bal = await prosper_adapter().get_user_balances(org_id)
        # The adapter's `balance_prosper` is asset-agnostic — it returns the
        # USDCP/USDC balance. ARSa balance comes via the cms users endpoint
        # only if the adapter exposes it. We currently only have USDC.
        usdc_stellar = float(bal.balance_prosper or 0)
    except Exception:  # noqa: BLE001
        # Adapter not available / wallet not provisioned — surface zeros.
        pass

    # 3. Breakdown by asset × modality.
    breakdown_pipeline = [
        {"$match": {"org_id": org_id, "is_deleted": False,
                      "external": {"$ne": True}}},
        {"$group": {
            "_id":       {"asset":    {"$ifNull": ["$asset", "usdc"]},
                            "modality": {"$ifNull": ["$modality", "end"]}},
            "count":     {"$sum": 1},
            "principal": {"$sum": {"$ifNull": ["$principal_native",
                                                  {"$ifNull": ["$principal_usd", 0]}]}},
        }},
        {"$sort": {"_id.asset": 1, "_id.modality": 1}},
    ]
    breakdown: list[dict] = []
    async for row in col(POSITIONS).aggregate(breakdown_pipeline):
        breakdown.append({
            "asset":     row["_id"]["asset"],
            "modality":  row["_id"]["modality"],
            "count":     int(row["count"]),
            "principal": float(row["principal"]),
        })

    return {
        "aum":        aum,
        "cash":       {
            "usdc":         available_usdc + usdc_stellar,
            "usdc_platform": available_usdc,
            "usdc_stellar":  usdc_stellar,
            "arsa":         arsa_cvu + arsa_stellar,
            "arsa_cvu":     arsa_cvu,
            "arsa_stellar": arsa_stellar,
        },
        "breakdown":  breakdown,
        "fetched_at": _iso_now(),
    }



@router.post("/positions/{position_id}/redeem")
async def redeem_position(position_id: str,
                            user: CurrentUser = Depends(get_current_user)):
    pos = await col(POSITIONS).find_one(
        {"position_id": position_id, "org_id": user.org_id, "is_deleted": False})
    if not pos:
        raise HTTPException(404, "Position not found")
    if pos.get("status") not in ("active", "matured"):
        raise HTTPException(400, "Position is not redeemable")
    # Liquid (term_days == 0) or matured can always redeem
    product = await col(PRODUCTS).find_one({"product_id": pos.get("product_id")})
    term = (product or {}).get("term_days", 0)
    if term > 0 and pos.get("status") != "matured":
        raise HTTPException(400, "Term position has not matured yet")

    ptx = str(uuid.uuid4())
    principal = pos.get("principal_usd") or 0
    accrued   = pos.get("accrued_interest") or 0
    total     = round(principal + accrued, 2)
    try:
        resp = await prosper_adapter().withdraw_tokens(
            user_reference_id=user.org_id,
            amount=total, prosper_tx_id=ptx)
    except ProsperError as e:
        raise HTTPException(502, f"Stellar withdraw failed: {e}")

    await col(POSITIONS).update_one(
        {"position_id": position_id},
        {"$set": {"status": "redeemed", "redeemed_at": _iso_now(),
                    "updated_at": _iso_now()}})
    await col(TRANSACTIONS).insert_one({
        "tx_id":          "tx_" + secrets.token_hex(6),
        "org_id":         user.org_id,
        "prosper_tx_id":  ptx,
        "type":           "redeem",
        "amount":         total,
        "asset":          "USDC",
        "status":         "confirmed",
        "tx_hash":        resp.tx_hash,
        "ledger":         resp.ledger,
        "memo":           f"Redeem position {position_id}",
        "related_position_id": position_id,
        "metadata":       {"principal": principal, "accrued": accrued},
        "created_at":     _iso_now(),
        "updated_at":     _iso_now(),
        "is_deleted":     False,
    })
    await log_action(actor=user, action="client.position.redeem",
                      resource_type="position", resource_id=position_id,
                      metadata={"amount": total, "prosper_tx_id": ptx})
    return {"ok": True, "amount_received": total, "tx_hash": resp.tx_hash}


# ---------------------------------------------------------------------------
# Core buy executor — used by both manual buy and post-onramp trigger.
# ---------------------------------------------------------------------------
async def _execute_buy(*, user, org, product: dict, amount: float,
                        related_onramp_id: Optional[str], trigger: str) -> dict:
    """Transactional buy. If ANY step fails, mark TX failed + create alert.

    P0 (Feb 2026): wallet provisioning is per-(org, modality) — the CMS
    protocol assigns a different Stellar wallet per modality. We resolve
    the wallet from `product.modality` (default `end` for legacy products
    without an explicit modality).
    """
    # 1. Ensure the org has a Prosper wallet for THIS product's modality.
    modality = (product.get("modality") or "end").lower()
    try:
        from routes.onramp_flow import ensure_org_prosper_wallet
        wallet = await ensure_org_prosper_wallet(user.org_id, modality=modality)
        address = wallet["stellar_address"]
    except ProsperError as e:
        await _record_failure(user, amount, str(e), step="wallet")
        return {"ok": False, "error": f"wallet creation failed: {e}"}

    # 2. Build Transaction shell (subscribe, pending)
    ptx = str(uuid.uuid4())
    tx_doc = {
        "tx_id":         "tx_" + secrets.token_hex(6),
        "org_id":        user.org_id,
        "user_id":       user.user_id,
        "prosper_tx_id": ptx,
        "type":          "subscribe",
        "amount":        amount,
        "asset":         "USDC",
        "status":        "pending",
        "tx_hash":       None,
        "ledger":        None,
        "memo":          f"Buy {product['name']} ({trigger})",
        "related_onramp_id": related_onramp_id,
        "related_position_id": None,
        "metadata":      {"product_id": product["product_id"],
                          "trigger":    trigger,
                          "apr_bps":    product["apr_bps"]},
        "created_at":    _iso_now(),
        "updated_at":    _iso_now(),
        "is_deleted":    False,
    }
    await col(TRANSACTIONS).insert_one(tx_doc.copy())

    # 3. Call deposit_tokens — use the same reference we used when
    # provisioning the wallet (org_id), NOT our internal user_id. This
    # way the Prosper protocol routes the deposit to the right wallet.
    #
    # CMS protocol note (Feb 2026): deposits are NOT API-driven anymore.
    # In the CMS namespace the adapter raises a `ProsperError` here and
    # we surface a user-friendly message explaining the real flow
    # (transfer + automatic detection by the poller).
    try:
        resp = await prosper_adapter().deposit_tokens(
            user_reference_id=user.org_id, amount=amount, prosper_tx_id=ptx)
    except ProsperError as e:
        msg = str(e)
        if "not exposed" in msg.lower() or "cms partner" in msg.lower():
            is_arsa = (product.get("asset") or "usdc").lower() == "arsa"
            unit = "ARSa" if is_arsa else "USDC"
            cargar_route = "/client/onramp" if is_arsa else "/client/cargar-usdc"
            friendly = (
                f"En el protocolo Prosper CMS las inversiones se crean "
                f"automáticamente cuando transferís {unit} a tu wallet "
                f"asignada para la modalidad elegida. "
                f"Andá a {cargar_route} para ver la dirección de depósito "
                f"y las instrucciones. Una vez recibida la transferencia, "
                f"el staking aparece en /client/investments en 1–3 minutos.")
            await col(TRANSACTIONS).update_one(
                {"tx_id": tx_doc["tx_id"]},
                {"$set": {"status": "cancelled", "memo": friendly,
                            "updated_at": _iso_now()}})
            return {"ok": False, "error": friendly,
                     "code": "cms_deposit_not_api_driven"}
        await col(TRANSACTIONS).update_one(
            {"tx_id": tx_doc["tx_id"]},
            {"$set": {"status": "failed", "memo": msg,
                        "updated_at": _iso_now()}})
        await _record_failure(user, amount, msg, step="deposit", ptx=ptx)
        return {"ok": False, "error": msg}

    # 4. Position — P0 (Feb 2026) model:
    # New CMS-aligned fields (asset, modality, wallet, memo, hash, rate,
    # principal_native + principal_unit). Legacy fields (principal_usd,
    # apr_bps, currency) preserved for backwards compat — both are mirrors
    # of the new ones while the protocol's `interesesAcumulados` keeps
    # returning null (see audit Feb-09).
    # `memo` and `hash` start empty: the staking poller (jobs/staking_sync)
    # fills them when the on-chain transfer settles and /cms/staking
    # surfaces the per-staking memoStaking + hashStaking.
    now = datetime.now(timezone.utc)
    term_days = product.get("term_days") or 0
    maturity  = (now + timedelta(days=term_days)).isoformat() if term_days > 0 else None
    asset     = (product.get("asset") or "usdc").lower()
    asset_unit = "ARSa" if asset == "arsa" else "USDC"

    pos_id = "pos_" + secrets.token_hex(6)
    position = {
        "position_id":      pos_id,
        "org_id":           user.org_id,
        "user_id":          user.user_id,
        "contract_email":   (user.email or "").lower(),
        "product_id":       product["product_id"],
        # New P0 fields ------------------------------------------------------
        "asset":            asset,                   # "arsa" | "usdc"
        "modality":         modality,                # "end"  | "month"
        "wallet":           address,                 # Stellar wallet (origin)
        "memo":             None,                    # set by staking poller
        "hash":             None,                    # set by staking poller
        "rate":             product.get("apr_bps", 0) / 100,
                                                     # APR % — replaced by
                                                     # contract `rate` when
                                                     # the staking lands.
        "principal_native": amount,                  # amount in native asset
        "principal_unit":   asset_unit,              # "ARSa" | "USDC"
        # Legacy mirrors (kept until UI fully migrates) ---------------------
        "principal_usd":    amount,                  # mirror of principal_native
        "currency":         asset_unit,
        "apr_bps":          product["apr_bps"],
        # Yield bookkeeping --------------------------------------------------
        "accrued_interest": 0.0,
        "claimed_interest": 0.0,
        "contract_provides_interest": False,
                          # flipped to True by staking poller when /cms/staking
                          # starts returning `interesesAcumulados != null`; once
                          # True the daily accrual job skips this position.
        # Lifecycle ---------------------------------------------------------
        "start":            _iso_now(),
        "maturity":         maturity,
        "status":           "active",
        "prosper_tx_id":    ptx,
        "created_at":       _iso_now(),
        "updated_at":       _iso_now(),
        "is_deleted":       False,
    }
    await col(POSITIONS).insert_one(position.copy())

    # 5. Update TX
    await col(TRANSACTIONS).update_one(
        {"tx_id": tx_doc["tx_id"]},
        {"$set": {"status": "confirmed", "tx_hash": resp.tx_hash,
                    "ledger":  resp.ledger,
                    "related_position_id": pos_id,
                    "updated_at": _iso_now()}})

    await log_action(actor=user, action="client.position.create",
                      resource_type="position", resource_id=pos_id,
                      metadata={"product_id": product["product_id"],
                                  "amount":     amount,
                                  "trigger":    trigger,
                                  "prosper_tx_id": ptx})

    position.pop("_id", None)
    return {"ok": True, "position": position, "tx_hash": resp.tx_hash,
             "address": address}


async def _record_failure(user, amount: float, err: str,
                            *, step: str, ptx: Optional[str] = None) -> None:
    await col(ALERTS).insert_one({
        "alert_id":    "al_buy_" + secrets.token_hex(5),
        "type":        "operational",
        "severity":    "warning",
        "title":       f"Compra Prosper falló · step={step}",
        "description": f"User {user.email} amount=${amount}: {err}",
        "org_id":      user.org_id,
        "status":      "open",
        "context":     {"amount": amount, "step": step, "ptx": ptx,
                          "user_id": user.user_id},
        "created_at":  _iso_now(),
        "updated_at":  _iso_now(),
        "is_deleted":  False,
    })


# ---------------------------------------------------------------------------
# Post-onramp trigger — called from Alfred webhook handler.
# Idempotent: if the onramp already has a related subscribe TX, skip.
# ---------------------------------------------------------------------------
async def trigger_buy_after_onramp(onramp_doc: dict) -> dict:
    await ensure_products()
    existing = await col(TRANSACTIONS).find_one(
        {"related_onramp_id": onramp_doc["onramp_id"], "type": "subscribe"})
    if existing:
        return {"ok": True, "skipped": True, "reason": "already processed"}

    user_doc = await col(USERS).find_one({"user_id": onramp_doc["user_id"]},
                                          {"_id": 0})
    org_doc  = await col(ORGANIZATIONS).find_one({"org_id": onramp_doc["org_id"]},
                                                    {"_id": 0})
    if not user_doc or not org_doc:
        return {"ok": False, "error": "user or org missing"}

    product_id = org_doc.get("default_product_id") or "usdc_end"
    product = await col(PRODUCTS).find_one({"product_id": product_id, "is_deleted": {"$ne": True}})
    if not product:
        product = await col(PRODUCTS).find_one({"product_id": "usdc_end"})
    if not product:
        return {"ok": False, "error": "no product available"}

    # Forge a CurrentUser shim with attributes the helper needs.
    class _U:
        user_id = onramp_doc["user_id"]
        org_id  = onramp_doc["org_id"]
        email   = user_doc.get("email", "")
        role    = user_doc.get("role", "client_admin")
    amount = float(onramp_doc.get("usdc_received") or onramp_doc.get("expected_usdc") or 0)
    if amount < (product.get("min_amount") or 0):
        return {"ok": False, "skipped": True,
                 "reason": f"amount below min_amount of {product['product_id']}"}
    return await _execute_buy(user=_U(), org=org_doc, product=product,
                                amount=amount,
                                related_onramp_id=onramp_doc["onramp_id"],
                                trigger="auto_post_onramp")



# ---------------------------------------------------------------------------
# P0 (Feb 2026) — Andes outbound on-chain transfer (Invest "ahora")
# ---------------------------------------------------------------------------
# Lets a client transfer ARSa from their Andes Stellar wallet directly to
# the Prosper Treasury wallet provisioned for their org × modality. The
# staking record itself is NOT created here — the Prosper smart contract
# emits it when it observes the incoming on-chain transfer. The local
# `positions` collection gets a `pending_onchain` placeholder; the staking
# poller (`jobs/staking_sync.py`) reclaims it by matching `(wallet, asset,
# modality, principal_native)` and sets `memo`, `hash`, `status=active`.
#
# Safety invariants (per user spec Feb 2026):
#   1. Asset is restricted to ARSa here. USDC stays on the manual path.
#   2. Destination address MUST be the wallet provisioned for THIS org +
#      modality (no global treasury fallback).
#   3. Amount must be within the product's [min, max] and ≤ available ARSa.
#   4. Authorization checkbox is required on the request body; persisted
#      verbatim into the audit log so we can prove user consent.
#   5. Idempotency: cannot create a new pending_onchain for the same
#      (user_id, asset, modality) if one created < 5 min ago is still
#      pending.
#   6. Audit log entries: `client.invest.onchain.authorize` (pre-call) and
#      `client.invest.onchain.initiated` (post-call).
# ---------------------------------------------------------------------------
class InvestOnchainIn(BaseModel):
    asset:           str                # "arsa" only (USDC manual path)
    modality:        str                # "end" | "month"
    amount:          float = Field(..., gt=0)
    authorized:      bool                # MUST be True (frontend checkbox)
    confirmed_destination: str           # MUST equal the resolved wallet
    confirmed_amount:      float         # MUST equal `amount` (anti-tamper)


@router.post("/invest/onchain")
async def invest_onchain(body: InvestOnchainIn,
                          user: CurrentUser = Depends(get_current_user)):
    """Initiate on-chain ARSa transfer to the org's Prosper Treasury wallet."""
    await ensure_products()

    # ---- 1. Validate body shape -------------------------------------------
    asset    = (body.asset or "").lower()
    modality = (body.modality or "").lower()
    if asset != "arsa":
        raise HTTPException(400,
            "Por ahora sólo se soporta transferencia directa de ARSa.")
    if modality not in ("end", "month"):
        raise HTTPException(400, "Modalidad inválida (end | month)")
    if not body.authorized:
        raise HTTPException(400,
            "Falta autorización explícita del usuario.")
    if abs(body.confirmed_amount - body.amount) > 0.0001:
        raise HTTPException(400,
            "El monto confirmado no coincide con el monto a transferir.")

    # ---- 2. Org + KYB --------------------------------------------------------
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": user.org_id, "is_deleted": False}, {"_id": 0})
    if not org or org.get("kyb_status") != "approved" or org.get("paused"):
        raise HTTPException(403, "Tu organización no puede operar todavía.")

    # ---- 3. Resolve product + per-modality limits ---------------------------
    product_id = f"arsa_{modality}"
    product = await col(PRODUCTS).find_one(
        {"product_id": product_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not product or product.get("status") != "active":
        raise HTTPException(404, "Producto no disponible.")
    if body.amount < (product.get("min_amount") or 0):
        raise HTTPException(400,
            f"Mínimo: {product['min_amount']} ARSa")
    if body.amount > (product.get("max_amount") or float("inf")):
        raise HTTPException(400,
            f"Máximo: {product['max_amount']} ARSa")

    # ---- 4. Resolve destination wallet (per-org, per-modality) -------------
    from routes.onramp_flow import (ensure_org_prosper_wallet,
                                       _is_valid_stellar_address)
    try:
        wallet_meta = await ensure_org_prosper_wallet(user.org_id,
                                                          modality=modality)
    except Exception as e:  # noqa: BLE001
        # The most common failure here is the Prosper CMS returning 400
        # on `/cms/cashin` ("Error creating account on Stellar network"
        # — the partner's Stellar funding side is down). Log the raw
        # error for ops and surface a user-friendly Spanish message.
        err_text = str(e)
        logger.warning("invest_onchain: ensure_org_prosper_wallet "
                          "failed org=%s modality=%s: %s",
                          user.org_id, modality, err_text)
        if ("Error creating account on Stellar network" in err_text
                or "cms/cashin" in err_text
                or "wallet inválida" in err_text):
            raise HTTPException(503,
                "El CMS de Prosper no pudo generar la wallet destino "
                "en este momento. Ya estamos al tanto; reintentá en "
                "unos minutos.")
        raise HTTPException(502,
            f"No se pudo resolver la wallet destino: {err_text}")
    destination_address = (wallet_meta.get("stellar_address") or "").strip()
    if not destination_address:
        raise HTTPException(502,
            "La wallet de Prosper para esta modalidad aún no está provisionada.")
    if not _is_valid_stellar_address(destination_address):
        # Belt-and-suspenders: even if a legacy row slipped past the
        # provisioning guard, refuse to hand a bogus address to Andes
        # (it would 400 "Invalid address" and surface as a blank 502
        # toast to the user). Force the caller to retry.
        logger.error("invest_onchain: wallet destino inválida "
                        "org=%s modality=%s addr=%r — bloqueando envío",
                        user.org_id, modality, destination_address)
        raise HTTPException(503,
            "La wallet destino de Prosper no es válida. "
            "Reintentá en unos minutos.")
    if body.confirmed_destination.strip() != destination_address:
        raise HTTPException(400,
            "La dirección destino confirmada no coincide con la wallet asignada. "
            "Recargá la página y volvé a intentar.")

    # ---- 5. Available ARSa balance check ------------------------------------
    arsa_row = await col(RAMP_BALANCES).find_one(
        {"org_id": user.org_id, "asset": "arsa"},
        {"_id": 0, "balance": 1}, sort=[("as_of", -1)])
    if not arsa_row:
        acc_ids = [a["id"] async for a in
                      col(RAMP_ACCOUNTS).find({"org_id": user.org_id},
                                                {"_id": 0, "id": 1})]
        if acc_ids:
            arsa_row = await col(RAMP_BALANCES).find_one(
                {"ramp_account_id": {"$in": acc_ids}, "asset": "arsa"},
                {"_id": 0, "balance": 1}, sort=[("as_of", -1)])
    available_arsa = float(arsa_row.get("balance") or 0) if arsa_row else 0.0
    if body.amount > available_arsa:
        raise HTTPException(400,
            f"Saldo ARSa insuficiente ({available_arsa:.2f})")

    # ---- 6. Idempotency: bail if a recent pending exists -------------------
    five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    existing_pending = await col(POSITIONS).find_one({
        "user_id":    user.user_id,
        "org_id":     user.org_id,
        "asset":      "arsa",
        "modality":   modality,
        "status":     "pending_onchain",
        "is_deleted": False,
        "created_at": {"$gte": five_min_ago},
    }, {"_id": 0})
    if existing_pending:
        return {"ok": True, "skipped": True,
                 "reason": "Ya existe una transferencia pendiente reciente.",
                 "position_id": existing_pending["position_id"]}

    # ---- 7. Resolve Andes user_id from ramp_accounts -----------------------
    andes_acc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": user.org_id, "provider": "andeslabs"},
        {"_id": 0, "provider_user_id": 1})
    andes_user_id = (andes_acc or {}).get("provider_user_id") or ""
    if not andes_user_id:
        raise HTTPException(409,
            "No tenés una cuenta Andes activada. Completá el onboarding ARS.")

    # ---- 8. Pre-call audit log (proof of user authorization) ---------------
    await log_action(
        actor=user,
        action="client.invest.onchain.authorize",
        resource_type="invest_onchain",
        resource_id=None,
        metadata={
            "asset":          asset,
            "modality":       modality,
            "amount":         body.amount,
            "destination":    destination_address,
            "andes_user_id":  andes_user_id,
            "product_id":     product["product_id"],
            "authorized":     True,
            "authorized_at":  _iso_now(),
        })

    # ---- 9. Call Andes outbound transfer (with 425 retry) ------------------
    try:
        transfer = await AndesAdapter().initiate_onchain_transfer(
            andes_user_id=andes_user_id,
            asset="arsa",
            chain="stellar",
            to_address=destination_address,
            amount=body.amount,
        )
    except NotSupportedByProvider as e:
        # Audit the failure too — same correlation as the authorize entry
        await log_action(
            actor=user, action="client.invest.onchain.failed",
            resource_type="invest_onchain", resource_id=None,
            metadata={"error": str(e), "amount": body.amount,
                        "modality": modality, "asset": asset})
        await _record_failure(user, body.amount, str(e),
                                step="andes_transfer")
        raise HTTPException(502,
            f"La transferencia falló en Andes: {e}")

    transfer_id  = (transfer.get("transactionId")
                     or transfer.get("wallet_transaction_id") or "")
    tx_hash      = transfer.get("tx_hash") or None
    from_address = transfer.get("from_address") or ""
    transfer_status = transfer.get("status") or "Pending"

    # ---- 10. Persist pending position --------------------------------------
    pos_id = "pos_" + secrets.token_hex(6)
    now = datetime.now(timezone.utc)
    maturity = (now + timedelta(days=product.get("term_days") or 365)).isoformat()
    position = {
        "position_id":      pos_id,
        "org_id":           user.org_id,
        "user_id":          user.user_id,
        "contract_email":   (user.email or "").lower(),
        "product_id":       product["product_id"],
        "asset":            "arsa",
        "modality":         modality,
        "wallet":           destination_address,
        # memo/hash arrancan NULL — los completa el poller al reclamar
        "memo":             None,
        "hash":             None,
        "rate":             (product.get("apr_bps") or 0) / 100,
        "principal_native": body.amount,
        "principal_unit":   "ARSa",
        # Legacy mirrors
        "principal_usd":    body.amount,
        "currency":         "ARSa",
        "apr_bps":          product.get("apr_bps") or 0,
        # Yield bookkeeping
        "accrued_interest": 0.0,
        "claimed_interest": 0.0,
        "contract_provides_interest": False,
        # Lifecycle
        "start":            _iso_now(),
        "maturity":         maturity,
        "status":           "pending_onchain",
        # Andes traceability
        "andes_transfer_id": transfer_id,
        "andes_tx_hash":     tx_hash,
        "andes_from_address": from_address,
        "andes_status":      transfer_status,
        # Audit
        "created_at":       _iso_now(),
        "updated_at":       _iso_now(),
        "is_deleted":       False,
    }
    await col(POSITIONS).insert_one(position.copy())

    # ---- 11. Post-call audit log -------------------------------------------
    await log_action(
        actor=user,
        action="client.invest.onchain.initiated",
        resource_type="position",
        resource_id=pos_id,
        metadata={
            "andes_transfer_id": transfer_id,
            "amount":            body.amount,
            "asset":              "arsa",
            "modality":           modality,
            "destination":        destination_address,
            "tx_hash":            tx_hash,
        })

    position.pop("_id", None)
    return {"ok":               True,
             "position_id":      pos_id,
             "andes_transfer_id": transfer_id,
             "tx_hash":          tx_hash,
             "status":           "pending_onchain",
             "destination":      destination_address,
             "message":          ("Tu transferencia está en proceso. Vamos a "
                                    "detectar el depósito on-chain en 1-3 "
                                    "minutos y tu inversión va a aparecer "
                                    "automáticamente en /client/investments.")}
