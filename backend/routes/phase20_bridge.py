"""Phase 20 v2 — ARSa <-> USDC <-> Prosper bridge orchestrator.

End-user enters and exits in ARSa (pesos). The Prosper yield protocol
operates internally in USDC. Andes performs the ARSa <-> USDC swap
(MOCKED today; replace with the real Andes swap endpoint when available).

Two flows live here:

  CASH IN  (direction='in') — POST /api/v1/investments/intent
    ARSa  --convert (mock)-->  USDC
    USDC  --bridge (transfer Andes wallet → Prosper deposit address)-->
    USDC  --subscribe (asset='usdc', amount=usdc_out, attributed to person)-->
    POSITION active.

  CASH OUT (direction='out') — POST /api/v1/investments/intent
    POSITION  --redeem (principal + accrued, asset='usdc')-->
    USDC      --bridge (transfer Prosper → Andes wallet)-->
    USDC      --reconvert (mock USDC → ARSa)-->
    ARSa      available in Andes wallet for offramp (Phase 15.1).

Both flows are idempotent by `prosper_tx_id`. The intent doc is the single
source of truth; every step transition is audit-logged. Failures stop the
flow with `step=failed` + `fail_reason` + an operational alert; retrying
hits the same intent and only replays the failed step.

NOTE: this module does NOT modify the Prosper protocol or the yield accrual
job. It only wires the conversion + bridging + attribution on top of the
existing `_execute_buy` and `prosper_adapter().withdraw_tokens` primitives.
"""
from __future__ import annotations

import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ALERTS, INVESTMENT_INTENTS, ORGANIZATIONS, POSITIONS,
    RAMP_ACCOUNTS, RAMP_BALANCES, RAMP_WALLETS, TRANSACTIONS,
)
from integrations.prosper import ProsperError, get_adapter as prosper_adapter

PRODUCTS = "products"

logger = logging.getLogger("prosper.bridge")
router = APIRouter(prefix="/investments", tags=["bridge"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gateway() -> tuple[str, str]:
    url = os.environ.get("ANDES_GATEWAY_URL", "http://localhost:8090").rstrip("/")
    tok = os.environ.get("GATEWAY_INTERNAL_TOKEN",
                          "dev-internal-token-change-me")
    return url, tok


async def _gw(method: str, path: str, *,
                  json_body: Optional[dict] = None) -> dict:
    url, tok = _gateway()
    async with httpx.AsyncClient(timeout=20.0) as cli:
        r = await cli.request(method, f"{url}{path}", json=json_body,
                                  headers={"X-Internal-Token": tok})
    if r.status_code >= 400:
        raise HTTPException(r.status_code,
                              f"gateway {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return {}


def _prosper_deposit_address() -> str:
    """The Stellar account that receives USDC for subscribes. Configured
    via PROSPER_DEPOSIT_ADDRESS (live development uses Prosper's hot wallet)."""
    addr = os.environ.get("PROSPER_DEPOSIT_ADDRESS", "").strip()
    if not addr:
        # Mock-friendly default (won't be used in prod since the env is set).
        return "GCCHGZRZ4QTI4WRWRKHXAUD7SKCSUHRXOXG66EZLAW4FSMRPDHRLNE77"
    return addr


def _usdc_asset() -> str:
    """Currently 'usdc'. Future: 'arsa' when ARSA_NATIVE_YIELD_ENABLED=true."""
    return "usdc"


async def _resolve_ramp_account(org_id: str,
                                  end_customer_id: Optional[str]) -> dict:
    """Find the Andes ramp account for this org. The on-chain account is
    ONE per org (per PRD: 'la cuenta on-chain es una por org — el
    end_customer_id atribuye contablemente, no enruta wallets'). If an
    explicit ecid matches, prefer it; else fall back to the org's primary
    ramp account."""
    if end_customer_id:
        acc = await col(RAMP_ACCOUNTS).find_one(
            {"org_id": org_id, "end_customer_id": end_customer_id},
            {"_id": 0})
        if acc:
            return acc
    acc = await col(RAMP_ACCOUNTS).find_one({"org_id": org_id}, {"_id": 0})
    if not acc:
        raise HTTPException(404,
            "Ramp account not found — provision the Andes account first "
            "(POST /v1/ramp/accounts)")
    return acc


async def _arsa_balance(ramp_account_id: str, chain: str = "stellar") -> float:
    row = await col(RAMP_BALANCES).find_one(
        {"ramp_account_id": ramp_account_id, "asset": "arsa", "chain": chain},
        {"_id": 0, "balance": 1})
    return float((row or {}).get("balance") or 0)


async def _alert(*, severity: str, title: str, description: str,
                  org_id: str, context: dict) -> None:
    await col(ALERTS).insert_one({
        "alert_id":    "al_p20_" + secrets.token_hex(5),
        "type":        "operational",
        "severity":    severity,
        "title":       title,
        "description": description,
        "org_id":      org_id,
        "status":      "open",
        "context":     context,
        "created_at":  _iso(),
        "updated_at":  _iso(),
        "is_deleted":  False,
    })


async def _patch_intent(intent_id: str, **patch) -> dict:
    patch["updated_at"] = _iso()
    await col(INVESTMENT_INTENTS).update_one({"id": intent_id},
                                                {"$set": patch})
    return await col(INVESTMENT_INTENTS).find_one({"id": intent_id},
                                                     {"_id": 0})


# ---------------------------------------------------------------------------
# Trustlines (Phase 20 / B)
# ---------------------------------------------------------------------------
async def ensure_trustline(*, org_id: str, asset: str) -> dict:
    """Idempotently mark a trustline as established for the org's Prosper
    wallet. For USDC-Stellar the Prosper custodial account already trusts
    the Circle issuer (it's the receiving address); we mirror that here.

    For real protocol enforcement Prosper signs the trustline tx — this
    helper records the state and is the single integration point for when
    the protocol exposes a `trustlines.create(issuer, code)` API.
    """
    asset = asset.lower()
    issuer_key = {"usdc": "USDC_STELLAR_ISSUER",
                   "arsa": "ARSA_ISSUER"}.get(asset)
    if not issuer_key:
        raise HTTPException(400, f"unsupported asset {asset}")
    issuer = os.environ.get(issuer_key, "")

    org = await col(ORGANIZATIONS).find_one({"org_id": org_id}, {"_id": 0})
    if not org:
        raise HTTPException(404, "org not found")
    wallet = (org.get("prosper_wallet") or {})
    trustlines = list(wallet.get("trustlines") or [])
    if any(t.get("asset") == asset and t.get("issuer") == issuer
              for t in trustlines):
        return {"established": True, "idempotent": True,
                 "asset": asset, "issuer": issuer}
    trustlines.append({"asset": asset, "issuer": issuer,
                         "established_at": _iso(),
                         "method": "custodial_recorded"})
    wallet["trustlines"] = trustlines
    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {"prosper_wallet": wallet, "updated_at": _iso()}})
    return {"established": True, "idempotent": False,
             "asset": asset, "issuer": issuer}


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class IntentCreate(BaseModel):
    direction:   str = Field(..., pattern="^(in|out)$")
    # IN args
    product_id:   Optional[str] = None
    amount_arsa:  Optional[float] = Field(None, gt=0)
    source:       Optional[str] = Field("arsa",
                                          pattern="^(arsa|usdc_stellar)$")
    amount_usdc:  Optional[float] = Field(None, gt=0)   # only when source=usdc_stellar
    # OUT args
    position_id:  Optional[str] = None
    end_customer_id: Optional[str] = None


# ---------------------------------------------------------------------------
# CASH IN orchestrator
# ---------------------------------------------------------------------------
async def _cash_in(user: CurrentUser, body: IntentCreate) -> dict:
    if body.source == "arsa" and not body.amount_arsa:
        raise HTTPException(400, "amount_arsa required when source=arsa")
    if body.source == "usdc_stellar" and not body.amount_usdc:
        raise HTTPException(400, "amount_usdc required when source=usdc_stellar")
    if not body.product_id:
        raise HTTPException(400, "product_id required")

    product = await col(PRODUCTS).find_one(
        {"product_id": body.product_id, "is_deleted": {"$ne": True}},
        {"_id": 0})
    if not product or product.get("status") != "active":
        raise HTTPException(404, "product not found or inactive")
    # P0 (Feb 2026): the `yield_asset != usdc` guard is gone — both
    # ARSa-native and USDC-native products are valid, and the bridge
    # itself is deprecated (see route handler above). This function
    # remains for historical intent inspection only.

    # Idempotency anchor
    prosper_tx_id = "prosper_in_" + secrets.token_hex(8)
    intent_id     = "inv_" + secrets.token_hex(6)

    org = await col(ORGANIZATIONS).find_one({"org_id": user.org_id},
                                              {"_id": 0})
    if not org or org.get("kyb_status") != "approved" or org.get("paused"):
        raise HTTPException(403, "Operations are blocked for this organization")

    end_customer_id = body.end_customer_id or user.user_id
    ramp = await _resolve_ramp_account(user.org_id, end_customer_id) \
                if body.end_customer_id else \
                await _resolve_ramp_account(user.org_id, None)

    intent = {
        "id":              intent_id,
        "org_id":          user.org_id,
        "owner_user_id":   user.user_id,
        "end_customer_id": end_customer_id,
        "direction":       "in",
        "source":          body.source or "arsa",
        "amount_arsa":     body.amount_arsa,
        "amount_usdc":     body.amount_usdc,
        "product_id":      body.product_id,
        "step":            "created",
        "conversion":      None,
        "andes_transfer_id": None,
        "prosper_tx_id":   prosper_tx_id,
        "position_id":     None,
        "fail_reason":     None,
        "created_at":      _iso(),
        "updated_at":      _iso(),
    }
    await col(INVESTMENT_INTENTS).insert_one(dict(intent))
    await log_action(actor=user, action="bridge.intent.created",
                       resource_type="investment_intent",
                       resource_id=intent_id,
                       metadata={"direction": "in",
                                  "source": intent["source"],
                                  "prosper_tx_id": prosper_tx_id})

    # Step 1 — convert ARSa → USDC (skip if source=usdc_stellar)
    usdc_amount = float(body.amount_usdc or 0)
    if intent["source"] == "arsa":
        arsa_in = float(body.amount_arsa)
        # ARSa balance check on the Andes wallet
        bal = await _arsa_balance(ramp["id"])
        if bal < arsa_in:
            await _patch_intent(intent_id, step="failed",
                                 fail_reason=f"insufficient ARSa: have {bal}, "
                                              f"need {arsa_in}")
            raise HTTPException(400,
                f"insufficient ARSa balance: have {bal}, need {arsa_in}")

        await _patch_intent(intent_id, step="converting")
        try:
            quote = await _gw("POST", "/convert/arsa-usdc",
                                  json_body={"amount_arsa": arsa_in})
        except HTTPException as e:
            await _patch_intent(intent_id, step="failed",
                                 fail_reason=f"convert failed: {e.detail}")
            await _alert(severity="warning",
                          title="Phase 20 · convert ARSa→USDC failed",
                          description=str(e.detail),
                          org_id=user.org_id,
                          context={"intent_id": intent_id})
            raise

        usdc_amount = float(quote["usdc_out"])
        conversion = {"arsa_in": str(arsa_in),
                       "usdc_out": str(usdc_amount),
                       "rate": quote["rate"],
                       "rate_source": quote["rate_source"],
                       "quoted_at": quote["quoted_at"],
                       "expires_at": quote["expires_at"],
                       "quote_id": quote.get("quote_id")}
        await _patch_intent(intent_id, conversion=conversion)

    # Validate min USDC
    min_usdc = float(os.environ.get("INVEST_MIN_USDC", "10") or 10)
    if usdc_amount < min_usdc:
        await _patch_intent(intent_id, step="failed",
                             fail_reason=f"usdc_amount {usdc_amount} below "
                                          f"INVEST_MIN_USDC {min_usdc}")
        raise HTTPException(400,
            f"USDC amount {usdc_amount} below minimum {min_usdc}")

    # Step 2 — ensure trustlines (USDC)
    try:
        await ensure_trustline(org_id=user.org_id, asset="usdc")
    except HTTPException as e:
        await _patch_intent(intent_id, step="failed",
                             fail_reason=f"trustline failed: {e.detail}")
        raise

    # Step 3 — bridge: transfer USDC from Andes wallet → Prosper deposit address
    # MOCK: post a synthetic transfer via the gateway. The gateway auto-fires
    # crypto.transfer.success after ~1s; the webhook handler matches by
    # andes_transfer_id and advances the intent.
    await _patch_intent(intent_id, step="bridging")
    try:
        # The transfer source wallet is the user's USDC wallet on Andes. The
        # Andes mock doesn't have a USDC wallet so we synthesize the transfer
        # via /dev/fire-webhook in a moment. In real mode this would be
        # `wallets/transfers` against the user's Andes USDC wallet.
        url, tok = _gateway()
        fire_url = f"{url}/dev/fire-webhook"
        transfer_id = "tx_" + secrets.token_hex(8)
        await _patch_intent(intent_id, andes_transfer_id=transfer_id)
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(fire_url, headers={"X-Internal-Token": tok},
                                  json={"type": "crypto.transfer.success",
                                          "data": {
                                              "transactionId": transfer_id,
                                              "userId":  ramp["provider_user_id"],
                                              "chain":   "stellar",
                                              "asset":   "usdc",
                                              "to_address": _prosper_deposit_address(),
                                              "amount":  str(usdc_amount),
                                              "tx_hash": "0x" + secrets.token_hex(32),
                                              "status":  "Success",
                                              "memo":    prosper_tx_id,
                                          }})
            if r.status_code >= 400:
                raise HTTPException(502, f"bridge fire-webhook: {r.text[:200]}")
    except HTTPException as e:
        await _patch_intent(intent_id, step="failed",
                             fail_reason=f"bridge failed: {e.detail}")
        await _alert(severity="warning",
                      title="Phase 20 · bridge USDC→Prosper failed",
                      description=str(e.detail),
                      org_id=user.org_id,
                      context={"intent_id": intent_id,
                                "prosper_tx_id": prosper_tx_id})
        raise

    # Webhook handler will set step=bridged + call _subscribe_after_bridge.
    # For deterministic E2E and to avoid waiting on the async webhook in
    # sync HTTP flows, we proactively complete the subscribe step here too
    # — guarded by an idempotency check against the intent step.
    intent_after_bridge = await col(INVESTMENT_INTENTS).find_one(
        {"id": intent_id}, {"_id": 0})
    if intent_after_bridge and intent_after_bridge.get("step") in (
            "bridging", "bridged"):
        await _patch_intent(intent_id, step="bridged")
        try:
            await _subscribe_for_intent(intent_id, usdc_amount, product,
                                          end_customer_id, prosper_tx_id)
        except HTTPException:
            raise

    final = await col(INVESTMENT_INTENTS).find_one({"id": intent_id},
                                                      {"_id": 0})
    return final or intent


async def _subscribe_for_intent(intent_id: str, usdc_amount: float,
                                  product: dict, end_customer_id: str,
                                  prosper_tx_id: str) -> None:
    """Subscribe step of the IN flow. Calls Prosper deposit_tokens, creates
    a Position attributed to `end_customer_id`, flips intent step→active."""
    intent = await col(INVESTMENT_INTENTS).find_one({"id": intent_id},
                                                      {"_id": 0})
    if not intent:
        raise HTTPException(404, "intent not found")
    if intent.get("step") == "active":
        return  # idempotent
    await _patch_intent(intent_id, step="subscribing")

    org_id = intent["org_id"]
    # Provision Prosper wallet (idempotent)
    from routes.onramp_flow import ensure_org_prosper_wallet
    try:
        await ensure_org_prosper_wallet(org_id)
    except ProsperError as e:
        await _patch_intent(intent_id, step="failed",
                             fail_reason=f"wallet provision failed: {e}")
        await _alert(severity="warning",
                      title="Phase 20 · Prosper wallet failed",
                      description=str(e),
                      org_id=org_id,
                      context={"intent_id": intent_id})
        raise HTTPException(502, f"wallet provision failed: {e}")

    # Caps validation
    caps = ((await col(ORGANIZATIONS).find_one({"org_id": org_id},
                                                 {"_id": 0})) or {}).get(
        "caps", {}) or {}
    daily = caps.get("subscribe_daily_cap_usd")
    if daily and usdc_amount > float(daily):
        await _patch_intent(intent_id, step="failed",
                             fail_reason=f"amount {usdc_amount} exceeds "
                                          f"daily cap {daily}")
        raise HTTPException(400, f"subscribe daily cap exceeded: {daily}")

    # Deposit tokens
    # ----------------------------------------------------------------------
    # PHASE 20 v2 — `PROSPER_DEPOSIT_MODE` toggle.
    #   * "mock" (default in dev): we SIMULATE a successful deposit_tokens
    #     locally — the protocol is NOT called. The position is created and
    #     accrual runs against `principal_usd` as usual.
    #   * "real": we call `prosper_adapter().deposit_tokens()` which (today)
    #     raises ProsperError "handled by Alfred onramp webhooks". When the
    #     Prosper team confirms the live `deposit_tokens` endpoint, flip
    #     `PROSPER_DEPOSIT_MODE=real` and remove this branch.
    # TODO(prosper-team): confirm the real `deposit_tokens` method (direct
    #   call vs Alfred-mediated). Until then, the deposit step stays MOCK
    #   so the rest of the circuit (convert + bridge USDC + position +
    #   accrual + redeem path) can run real end-to-end.
    deposit_mode = (os.environ.get("PROSPER_DEPOSIT_MODE") or "mock").lower()
    if deposit_mode == "mock":
        # Synthesize a successful TokenOpResp shape locally.
        from integrations.prosper.adapter import TokenOpResp
        resp = TokenOpResp(
            tx_hash=f"MOCK_DEPOSIT_{secrets.token_hex(16).upper()}",
            ledger=0,
            raw={"mocked": True,
                 "reason": "PROSPER_DEPOSIT_MODE=mock — pending real "
                            "deposit_tokens method confirmation with Prosper team",
                 "prosper_tx_id": prosper_tx_id,
                 "amount_usdc": usdc_amount})
        logger.warning(
            "[PHASE20] deposit MOCKED (PROSPER_DEPOSIT_MODE=mock). "
            "Protocol NOT contacted. tx_id=%s amount=%s", prosper_tx_id, usdc_amount)
    else:
        try:
            resp = await prosper_adapter().deposit_tokens(
                user_reference_id=org_id, amount=usdc_amount,
                prosper_tx_id=prosper_tx_id)
        except ProsperError as e:
            await _patch_intent(intent_id, step="failed",
                                 fail_reason=f"deposit_tokens failed: {e}")
            await _alert(severity="warning",
                          title="Phase 20 · Prosper deposit_tokens failed",
                          description=str(e),
                          org_id=org_id,
                          context={"intent_id": intent_id,
                                    "prosper_tx_id": prosper_tx_id})
            raise HTTPException(502, f"subscribe failed: {e}")

    # Position (attributed to end_customer_id)
    term_days = product.get("term_days") or 0
    now_iso   = _iso()
    maturity  = None
    if term_days > 0:
        from datetime import timedelta as _td
        maturity = (datetime.now(timezone.utc) + _td(days=term_days)
                       ).isoformat()
    pos_id = "pos_" + secrets.token_hex(6)
    position = {
        "position_id":      pos_id,
        "org_id":           org_id,
        "user_id":          intent["owner_user_id"],
        "end_customer_id":  end_customer_id,
        "product_id":       product["product_id"],
        "asset":            _usdc_asset(),
        "currency":         "USDC",       # backwards compat
        "display_currency": "ARSa",
        "principal_usd":    usdc_amount,
        "accrued_interest": 0.0,
        "apr_bps":          product["apr_bps"],
        "start":            now_iso,
        "maturity":         maturity,
        "status":           "active",
        "prosper_tx_id":    prosper_tx_id,
        "created_at":       now_iso,
        "updated_at":       now_iso,
        "is_deleted":       False,
    }
    await col(POSITIONS).insert_one(position.copy())

    # Subscribe TX row (transactions table — keeps existing dashboards green)
    await col(TRANSACTIONS).insert_one({
        "tx_id":                "tx_" + secrets.token_hex(6),
        "org_id":               org_id,
        "user_id":              intent["owner_user_id"],
        "prosper_tx_id":        prosper_tx_id,
        "type":                 "subscribe",
        "amount":               usdc_amount,
        "asset":                "USDC",
        "status":               "confirmed",
        "tx_hash":              resp.tx_hash,
        "ledger":               resp.ledger,
        "memo":                 f"Bridge subscribe ({end_customer_id})",
        "related_position_id":  pos_id,
        "metadata": {"product_id": product["product_id"],
                       "trigger": "phase20_bridge",
                       "apr_bps":  product["apr_bps"],
                       "intent_id": intent_id,
                       "end_customer_id": end_customer_id},
        "created_at":           now_iso,
        "updated_at":           now_iso,
        "is_deleted":           False,
    })
    await _patch_intent(intent_id, step="active", position_id=pos_id)


# ---------------------------------------------------------------------------
# CASH OUT orchestrator
# ---------------------------------------------------------------------------
async def _cash_out(user: CurrentUser, body: IntentCreate) -> dict:
    if not body.position_id:
        raise HTTPException(400, "position_id required for cash-out")

    pos = await col(POSITIONS).find_one(
        {"position_id": body.position_id, "org_id": user.org_id,
          "is_deleted": False}, {"_id": 0})
    if not pos:
        raise HTTPException(404, "position not found")
    if pos.get("status") not in ("active", "matured"):
        raise HTTPException(400, "position is not redeemable")

    product = await col(PRODUCTS).find_one(
        {"product_id": pos.get("product_id")}, {"_id": 0})
    term = (product or {}).get("term_days", 0)
    if term > 0 and pos.get("status") != "matured":
        raise HTTPException(400, "Term position has not matured yet")

    end_customer_id = pos.get("end_customer_id") or pos.get("user_id")
    principal = float(pos.get("principal_usd") or 0)
    accrued   = float(pos.get("accrued_interest") or 0)
    usdc_total = round(principal + accrued, 6)

    prosper_tx_id = "prosper_out_" + secrets.token_hex(8)
    intent_id     = "inv_" + secrets.token_hex(6)
    intent = {
        "id":               intent_id,
        "org_id":           user.org_id,
        "owner_user_id":    user.user_id,
        "end_customer_id":  end_customer_id,
        "direction":        "out",
        "amount_usdc":      usdc_total,
        "position_id":      body.position_id,
        "product_id":       pos.get("product_id"),
        "step":             "redeeming",
        "prosper_tx_id":    prosper_tx_id,
        "andes_transfer_id": None,
        "fail_reason":      None,
        "created_at":       _iso(),
        "updated_at":       _iso(),
    }
    await col(INVESTMENT_INTENTS).insert_one(dict(intent))
    await log_action(actor=user, action="bridge.intent.created",
                       resource_type="investment_intent",
                       resource_id=intent_id,
                       metadata={"direction": "out",
                                  "position_id": body.position_id,
                                  "amount_usdc": usdc_total,
                                  "prosper_tx_id": prosper_tx_id})

    # Step 1 — redeem USDC via Prosper
    try:
        resp = await prosper_adapter().withdraw_tokens(
            user_reference_id=user.org_id,
            amount=usdc_total, prosper_tx_id=prosper_tx_id)
    except ProsperError as e:
        await _patch_intent(intent_id, step="failed",
                             fail_reason=f"redeem failed: {e}")
        await _alert(severity="warning",
                      title="Phase 20 · redeem failed",
                      description=str(e),
                      org_id=user.org_id,
                      context={"intent_id": intent_id,
                                "position_id": body.position_id})
        raise HTTPException(502, f"redeem failed: {e}")

    # Position closed
    await col(POSITIONS).update_one(
        {"position_id": body.position_id},
        {"$set": {"status": "redeemed",
                    "redeemed_at": _iso(),
                    "redeemed_total_usd": usdc_total,
                    "updated_at": _iso()}})
    await col(TRANSACTIONS).insert_one({
        "tx_id":               "tx_" + secrets.token_hex(6),
        "org_id":              user.org_id,
        "user_id":             user.user_id,
        "prosper_tx_id":       prosper_tx_id,
        "type":                "redeem",
        "amount":              usdc_total,
        "asset":               "USDC",
        "status":              "confirmed",
        "tx_hash":             resp.tx_hash,
        "ledger":              resp.ledger,
        "memo":                f"Bridge redeem ({end_customer_id})",
        "related_position_id": body.position_id,
        "metadata":            {"intent_id": intent_id,
                                  "principal": principal,
                                  "accrued":   accrued,
                                  "end_customer_id": end_customer_id},
        "created_at":          _iso(),
        "updated_at":          _iso(),
        "is_deleted":          False,
    })

    # Step 2 — bridge USDC back to Andes wallet
    await _patch_intent(intent_id, step="reconverting")
    try:
        quote = await _gw("POST", "/convert/usdc-arsa",
                              json_body={"amount_usdc": usdc_total})
    except HTTPException as e:
        await _patch_intent(intent_id, step="failed",
                             fail_reason=f"reconvert failed: {e.detail}")
        await _alert(severity="warning",
                      title="Phase 20 · reconvert USDC→ARSa failed",
                      description=str(e.detail),
                      org_id=user.org_id,
                      context={"intent_id": intent_id})
        raise

    arsa_out = float(quote["arsa_out"])
    conversion = {"usdc_in": str(usdc_total),
                   "arsa_out": str(arsa_out),
                   "rate": quote["rate"],
                   "rate_source": quote["rate_source"],
                   "quoted_at": quote["quoted_at"],
                   "expires_at": quote["expires_at"],
                   "quote_id": quote.get("quote_id")}

    # Credit the ARSa balance in the Andes wallet (mock; in real flow Andes
    # would receive USDC, swap, and credit ARSa via its own ledger). Some
    # rows store balance as string — read+write to stay tolerant.
    ramp = await _resolve_ramp_account(user.org_id, end_customer_id)
    existing = await col(RAMP_BALANCES).find_one(
        {"ramp_account_id": ramp["id"], "asset": "arsa", "chain": "stellar"},
        {"_id": 0, "balance": 1})
    prev = float((existing or {}).get("balance") or 0)
    new_bal = round(prev + arsa_out, 6)
    await col(RAMP_BALANCES).update_one(
        {"ramp_account_id": ramp["id"], "asset": "arsa", "chain": "stellar"},
        {"$set": {"balance": new_bal, "updated_at": _iso(),
                    "ramp_account_id": ramp["id"], "asset": "arsa",
                    "chain": "stellar"}}, upsert=True)

    await _patch_intent(intent_id, step="paid_out",
                         conversion=conversion,
                         amount_arsa=arsa_out)
    return await col(INVESTMENT_INTENTS).find_one({"id": intent_id},
                                                     {"_id": 0})


# ---------------------------------------------------------------------------
# Public routes — DEPRECATED (P0-4, Feb 2026)
# ---------------------------------------------------------------------------
# The Phase 20 bridge (ARSa→USDC→Prosper) has been retired with the CMS
# protocol migration. ARSa now stakes natively in ARSa and USDC natively
# in USDC — no asset conversion happens inside the platform.
#
# All POST endpoints below return **410 Gone**. Read endpoints stay open so
# clients can inspect the historical intent records (some of which may
# still be active until manually settled by the operator).
# ---------------------------------------------------------------------------
_BRIDGE_GONE_DETAIL = (
    "The ARSa→USDC→Prosper bridge has been retired (Feb 2026). "
    "Use the native flows instead: ARSa stakes via the ARSAp contract "
    "(POST /api/v1/client/positions with product_id=arsa_end|arsa_month) "
    "and USDC stakes via the USDCp contract by transferring USDC to your "
    "assigned Stellar wallet for the chosen modality.")


@router.post("/intent")
async def create_intent(body: IntentCreate,
                          user: CurrentUser = Depends(get_current_user)):
    """DEPRECATED — returns 410 Gone. See _BRIDGE_GONE_DETAIL."""
    _ = body, user  # silence unused-argument linters
    raise HTTPException(status_code=410, detail=_BRIDGE_GONE_DETAIL)


@router.get("/intent/{intent_id}")
async def get_intent(intent_id: str,
                       user: CurrentUser = Depends(get_current_user)):
    """Read-only — kept open so the operator can inspect historical intents."""
    intent = await col(INVESTMENT_INTENTS).find_one(
        {"id": intent_id, "org_id": user.org_id}, {"_id": 0})
    if not intent:
        raise HTTPException(404, "intent not found")
    intent["_deprecated"] = True
    return intent


@router.get("/intents")
async def list_intents(direction: Optional[str] = None,
                          step: Optional[str] = None,
                          user: CurrentUser = Depends(get_current_user)):
    """Read-only — kept open for historical visibility."""
    q: dict = {"org_id": user.org_id}
    if direction:
        q["direction"] = direction
    if step:
        q["step"] = step
    rows = await col(INVESTMENT_INTENTS).find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(200)
    return {"items": rows, "total": len(rows),
             "deprecated": True,
             "deprecation_notice": _BRIDGE_GONE_DETAIL}
