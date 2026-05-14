"""Phase 9 — Products + Positions + Buy/Redeem endpoints + post-onramp trigger.

Mounted under /api/v1.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ALERTS, ONRAMP_ORDERS, ORGANIZATIONS, POSITIONS, TRANSACTIONS, USERS,
)
from integrations.prosper import ProsperError, get_adapter as prosper_adapter

logger = logging.getLogger("prosper.invest")

PRODUCTS = "products"

router = APIRouter(prefix="/client", tags=["client-invest"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Default product seeds — created lazily on first read.
# ---------------------------------------------------------------------------
DEFAULT_PRODUCTS = [
    {"product_id": "liquid_v1", "name": "Prosper Liquid",
     "term_days": 0,    "apr_bps": 600,  "min_amount": 50,    "max_amount": 1_000_000,
     "status": "active",
     "description": "Sin lock — redimí cuando quieras."},
    {"product_id": "term_30",   "name": "Prosper 30d",
     "term_days": 30,   "apr_bps": 750,  "min_amount": 100,   "max_amount": 1_000_000,
     "status": "active",
     "description": "Lock de 30 días, APR 7.50%."},
    {"product_id": "term_90",   "name": "Prosper 90d",
     "term_days": 90,   "apr_bps": 900,  "min_amount": 500,   "max_amount": 5_000_000,
     "status": "active",
     "description": "Lock de 90 días, APR 9.00%."},
    {"product_id": "term_180",  "name": "Prosper 180d",
     "term_days": 180,  "apr_bps": 1100, "min_amount": 1_000, "max_amount": 10_000_000,
     "status": "active",
     "description": "Lock de 180 días, APR 11.00%."},
]


async def ensure_products() -> None:
    count = await col(PRODUCTS).count_documents({})
    if count >= len(DEFAULT_PRODUCTS):
        return
    for p in DEFAULT_PRODUCTS:
        await col(PRODUCTS).update_one(
            {"product_id": p["product_id"]},
            {"$setOnInsert": {**p, "created_at": _iso_now(),
                                "is_deleted": False}},
            upsert=True)


@router.get("/products")
async def list_products(_: CurrentUser = Depends(get_current_user)):
    await ensure_products()
    rows = await col(PRODUCTS).find(
        {"is_deleted": {"$ne": True}, "status": "active"}, {"_id": 0})\
        .sort("term_days", 1).to_list(50)
    return {"items": rows}


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
    """Returns available USDC + (when wallet exists) Prosper balance via adapter."""
    available_usdc = await _balance_for(user)
    try:
        bal = await prosper_adapter().get_user_balances(user.user_id)
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
    avail = await _balance_for(user)
    if body.amount_usdc > avail:
        raise HTTPException(400, f"Insufficient USDC ({avail:.2f})")

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
            user_reference_id=user.user_id,
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
    """Transactional buy. If ANY step fails, mark TX failed + create alert."""
    user_doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})

    # 1. Ensure wallet exists
    address = user_doc.get("stellar_address")
    if not address:
        try:
            w = await prosper_adapter().create_user_wallet(
                user_reference_id=user.user_id,
                prosper_tx_id="wallet_" + str(uuid.uuid4()))
            address = w.address
            await col(USERS).update_one(
                {"user_id": user.user_id},
                {"$set": {"stellar_address": address,
                            "updated_at": _iso_now()}})
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

    # 3. Call deposit_tokens
    try:
        resp = await prosper_adapter().deposit_tokens(
            user_reference_id=user.user_id, amount=amount, prosper_tx_id=ptx)
    except ProsperError as e:
        await col(TRANSACTIONS).update_one(
            {"tx_id": tx_doc["tx_id"]},
            {"$set": {"status": "failed", "memo": str(e),
                        "updated_at": _iso_now()}})
        await _record_failure(user, amount, str(e), step="deposit", ptx=ptx)
        return {"ok": False, "error": str(e)}

    # 4. Position
    now = datetime.now(timezone.utc)
    term_days = product.get("term_days") or 0
    maturity  = (now + timedelta(days=term_days)).isoformat() if term_days > 0 else None

    pos_id = "pos_" + secrets.token_hex(6)
    position = {
        "position_id":   pos_id,
        "org_id":        user.org_id,
        "user_id":       user.user_id,
        "product_id":    product["product_id"],
        "principal_usd": amount,
        "accrued_interest": 0.0,
        "apr_bps":       product["apr_bps"],
        "currency":      "USDC",
        "start":         _iso_now(),
        "maturity":      maturity,
        "status":        "active",
        "prosper_tx_id": ptx,
        "created_at":    _iso_now(),
        "updated_at":    _iso_now(),
        "is_deleted":    False,
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

    product_id = org_doc.get("default_product_id") or "liquid_v1"
    product = await col(PRODUCTS).find_one({"product_id": product_id, "is_deleted": {"$ne": True}})
    if not product:
        product = await col(PRODUCTS).find_one({"product_id": "liquid_v1"})
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
