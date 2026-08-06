"""Phase 15 — Internal webhook receiver for Andes.

The Node `andes-gateway` verifies the ES256 signature and then forwards the
already-verified payload to this endpoint:

    POST /api/v1/internal/ramp/webhook
    X-Internal-Token: <GATEWAY_INTERNAL_TOKEN>
    Body: {
        event_type: str,
        delivery_id: str,
        payload:    { type, data: {...} },
        signature_valid: true,
        headers:    {...passthrough...}
    }

Contract:
  * Idempotent by `delivery_id` (unique index on ramp_webhook_events).
  * Always persists the event in `ramp_webhook_events` (success-or-fail).
  * Dispatches per event type; handler exceptions → 5xx so Andes retries.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from audit import log_action
from db import (
    ALERTS, col, RAMP_ACCOUNTS, RAMP_BALANCES, RAMP_FIAT_ACCOUNTS,
    RAMP_MOVEMENTS, RAMP_WALLETS, RAMP_WEBHOOK_EVENTS, SANCTIONS_SCREENINGS,
)

logger = logging.getLogger("prosper.ramp.webhook")

router = APIRouter(prefix="/internal/ramp", tags=["ramp-internal"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gateway_token() -> str:
    return os.environ.get("GATEWAY_INTERNAL_TOKEN",
                            "dev-internal-token-change-me")


class WebhookIn(BaseModel):
    event_type: str = Field(..., min_length=3)
    delivery_id: str = Field(..., min_length=3)
    payload: dict[str, Any]
    signature_valid: bool = True
    headers: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Receiver
# ---------------------------------------------------------------------------
@router.post("/webhook")
async def receive_webhook(body: WebhookIn,
                            request: Request,
                            x_internal_token: Optional[str] = Header(
                                None, alias="X-Internal-Token")):
    if x_internal_token != _gateway_token():
        raise HTTPException(401, "invalid internal token")
    if not body.signature_valid:
        raise HTTPException(401, "webhook signature was not verified upstream")

    # 1) Idempotency — `ramp_webhook_events.delivery_id` has a unique index
    existing = await col(RAMP_WEBHOOK_EVENTS).find_one(
        {"delivery_id": body.delivery_id}, {"_id": 0, "delivery_id": 1, "event_type": 1})
    if existing:
        logger.info("webhook delivery_id=%s already processed (type=%s) — skipping",
                       body.delivery_id, existing.get("event_type"))
        return {"ok": True, "duplicate": True, "delivery_id": body.delivery_id}

    # 2) Persist BEFORE dispatch so even handler crashes leave a trail
    doc = {
        "delivery_id":     body.delivery_id,
        "event_type":      body.event_type,
        "payload":         body.payload,
        "headers":         body.headers,
        "signature_valid": True,
        "provider":        "andeslabs",
        "processed":       False,
        "received_at":     _now_iso(),
    }
    try:
        await col(RAMP_WEBHOOK_EVENTS).insert_one(dict(doc))
    except Exception as e:  # race with concurrent delivery — still idempotent
        logger.warning("webhook persist race for delivery_id=%s: %s",
                          body.delivery_id, e)
        return {"ok": True, "duplicate": True, "delivery_id": body.delivery_id}

    # 3) Dispatch
    try:
        await _dispatch(body)
    except Exception as e:  # noqa: BLE001
        logger.exception("webhook handler failed for type=%s delivery=%s: %s",
                            body.event_type, body.delivery_id, e)
        await col(RAMP_WEBHOOK_EVENTS).update_one(
            {"delivery_id": body.delivery_id},
            {"$set": {"processed": False, "error": str(e)[:500],
                       "updated_at": _now_iso()}})
        # Returning 5xx so Andes retries the delivery.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"handler error: {e}")

    await col(RAMP_WEBHOOK_EVENTS).update_one(
        {"delivery_id": body.delivery_id},
        {"$set": {"processed": True, "processed_at": _now_iso()}})
    return {"ok": True, "delivery_id": body.delivery_id,
              "event_type": body.event_type}


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------
async def _dispatch(evt: WebhookIn) -> None:
    handlers = {
        "wallet.active":                   _handle_wallet_active,
        "fiat.account.created":            _handle_fiat_account_created,
        "fiat.deposit.success":            _handle_deposit_success,
        "fiat.deposit.failed":             _handle_deposit_failed,
        "fiat.withdrawal.success":         _handle_withdrawal_success,
        "fiat.withdrawal.failed":          _handle_withdrawal_failed,
        "crypto.transfer.success":         _handle_crypto_transfer,
        "crypto.transfer.failed":          _handle_crypto_transfer,
        "international.offramp.success":   _handle_intl_offramp,
        "international.offramp.failed":    _handle_intl_offramp,
    }
    fn = handlers.get(evt.event_type)
    if not fn:
        logger.info("ramp webhook ignored (type=%s)", evt.event_type)
        return
    await fn(evt)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def _data(evt: WebhookIn) -> dict[str, Any]:
    return (evt.payload or {}).get("data") or {}


async def _account_for_user(provider_user_id: str) -> Optional[dict]:
    if not provider_user_id:
        return None
    return await col(RAMP_ACCOUNTS).find_one(
        {"provider_user_id": provider_user_id}, {"_id": 0})


async def _handle_deposit_success(evt: WebhookIn) -> None:
    d = _data(evt)
    user_id = str(d.get("userId") or d.get("user_id") or "")
    amount  = str(d.get("amount") or "0")
    asset   = (d.get("asset") or "arsa").lower()
    chain   = (d.get("chain") or "stellar").lower()
    ext_id  = str(d.get("transactionId") or d.get("mint_receipt_hash")
                   or "ext_" + secrets.token_hex(4))

    acc = await _account_for_user(user_id)
    if not acc:
        logger.warning("deposit.success for unknown provider_user_id=%s — "
                          "persisting orphan movement", user_id)

    org_id = (acc or {}).get("org_id", "")
    ramp_account_id = (acc or {}).get("id", "")
    prosper_tx_id = "prosper_dep_" + secrets.token_hex(6)

    # Phase 18 — Stellar wallets are `pending` until `wallet.active` arrives.
    # Defensive: if a deposit arrives BEFORE the wallet is active, hold the
    # movement (status='Pending', `held_for_wallet_activation=True`) and skip
    # the balance bump. The `wallet.active` handler will release it.
    wallet = await col(RAMP_WALLETS).find_one(
        {"provider_user_id": user_id, "asset": asset, "chain": chain},
        {"_id": 0, "status": 1})
    wallet_pending = bool(wallet and (wallet.get("status") == "pending"))

    # Idempotency by external_id within ramp_movements
    if await col(RAMP_MOVEMENTS).find_one(
            {"external_id": ext_id, "kind": "deposit"},
            {"_id": 0, "external_id": 1}):
        logger.info("deposit.success duplicate (ext_id=%s) — skipping", ext_id)
        return

    mv = {
        "id":               "mv_" + secrets.token_hex(6),
        "org_id":           org_id,
        "ramp_account_id":  ramp_account_id,
        "provider":         "andeslabs",
        "provider_user_id": user_id,
        "external_id":      ext_id,
        "kind":             "deposit",
        "asset":            asset,
        "chain":            chain,
        "amount":           amount,
        "status":           "Pending" if wallet_pending else "Success",
        "held_for_wallet_activation": wallet_pending,
        "destination_cvu":  None,
        "destination_name": None,
        "prosper_tx_id":    prosper_tx_id,
        "occurred_at":      d.get("timestamp") or _now_iso(),
        "raw":              d,
        "delivery_id":      evt.delivery_id,
        "created_at":       _now_iso(),
        "updated_at":       _now_iso(),
    }
    await col(RAMP_MOVEMENTS).insert_one(dict(mv))

    if wallet_pending:
        logger.warning("deposit.success held — wallet %s/%s/%s still pending "
                          "activation (mv=%s)", user_id, asset, chain, mv["id"])
        return  # Skip balance update; wallet.active will release

    # Refresh cached balance (best-effort)
    if ramp_account_id:
        prev = await col(RAMP_BALANCES).find_one(
            {"ramp_account_id": ramp_account_id, "asset": asset, "chain": chain},
            {"_id": 0, "balance": 1})
        new_bal = str(float(prev.get("balance") or 0) + float(amount or 0)
                       ) if prev else amount
        await col(RAMP_BALANCES).update_one(
            {"ramp_account_id": ramp_account_id, "asset": asset, "chain": chain},
            {"$set": {"balance": new_bal, "as_of": _now_iso()}},
            upsert=True)

    await log_action(actor=None, action="ramp.deposit.success",
                              resource_type="ramp_movement",
                              resource_id=mv["id"],
                              metadata={"org_id": org_id, "amount": amount,
                                          "asset": asset, "ext_id": ext_id,
                                          "delivery_id": evt.delivery_id})

    # Phase 03 — Publish `deposit.credited` for notifications + future
    # consumers. Only fires for actually-credited deposits (status=Success).
    # Held deposits return earlier and are released via _handle_wallet_active,
    # which has its own publish call. Soft-fail.
    try:
        from services.event_bus import publish as _publish
        await _publish({
            "event_type":  "deposit.credited",
            "version":     1,
            "event_id":    f"evt_dep_arsa_{ext_id}",
            "asset":       "arsa",
            "deposit_id":  ext_id,
            "tx_hash":     d.get("hash") or d.get("transactionHash"),
            "org_id":      org_id,
            "user_id":     None,
            "amount":      amount,
            "currency":    "ARSa",
            "ref":         d.get("reference") or d.get("memo"),
            "occurred_at": mv["occurred_at"],
            "detected_at": _now_iso(),
            "source":      "andes_webhook",
            "metadata": {
                "chain":             chain,
                "ramp_account_id":   ramp_account_id,
                "provider_user_id":  user_id,
                "prosper_tx_id":     prosper_tx_id,
                "delivery_id":       evt.delivery_id,
            },
        })
    except Exception:
        logger.exception("ramp.deposit.success: publish failed "
                            "(non-blocking) ext_id=%s", ext_id)


# ---------------------------------------------------------------------------
# Phase 18 — wallet.active + fiat.account.created
# ---------------------------------------------------------------------------
async def _handle_wallet_active(evt: WebhookIn) -> None:
    """Stellar wallets are created pending. When provisioning finishes, Andes
    emits `wallet.active`. We flip our ramp_wallets row, release any deposits
    that arrived while the wallet was still pending, and audit-log."""
    d = _data(evt)
    user_id = str(d.get("userId") or d.get("user_id") or "")
    asset   = (d.get("asset") or "arsa").lower()
    chain   = (d.get("chain") or "stellar").lower()
    activated_at = str(d.get("activated_at") or d.get("activatedAt") or _now_iso())

    if not user_id:
        logger.warning("wallet.active without user_id (delivery=%s) — skipping",
                          evt.delivery_id)
        return

    res = await col(RAMP_WALLETS).update_one(
        {"provider_user_id": user_id, "asset": asset, "chain": chain},
        {"$set": {"status": "active", "activated_at": activated_at,
                    "updated_at": _now_iso()}})

    if res.matched_count == 0:
        # The wallet may not be in our DB yet (race with create). Upsert a
        # placeholder so the next get_balances / detail call sees status=active.
        addr = str(d.get("address") or "")
        if addr:
            await col(RAMP_WALLETS).update_one(
                {"provider_user_id": user_id, "asset": asset, "chain": chain},
                {"$set": {"provider_user_id": user_id, "asset": asset,
                            "chain": chain, "address": addr,
                            "status": "active", "activated_at": activated_at,
                            "provider": "andeslabs",
                            "updated_at": _now_iso()},
                  "$setOnInsert": {"created_at": _now_iso()}},
                upsert=True)

    # Find the parent ramp_account
    acc = await _account_for_user(user_id)
    ramp_account_id = (acc or {}).get("id", "")
    org_id          = (acc or {}).get("org_id", "")

    # Release any held deposits → mark Success + bump balance
    held_cursor = col(RAMP_MOVEMENTS).find(
        {"provider_user_id": user_id, "kind": "deposit", "asset": asset,
          "chain": chain, "held_for_wallet_activation": True},
        {"_id": 0, "id": 1, "amount": 1, "external_id": 1})
    released_total = 0.0
    released_ids: list[str] = []
    released_movements: list[dict] = []
    async for held in held_cursor:
        amt = float(held.get("amount") or 0)
        released_total += amt
        released_ids.append(held["id"])
        released_movements.append(held)
        await col(RAMP_MOVEMENTS).update_one(
            {"id": held["id"]},
            {"$set": {"status": "Success",
                        "held_for_wallet_activation": False,
                        "released_at": _now_iso(),
                        "updated_at": _now_iso()}})

    if ramp_account_id and released_total > 0:
        prev = await col(RAMP_BALANCES).find_one(
            {"ramp_account_id": ramp_account_id, "asset": asset, "chain": chain},
            {"_id": 0, "balance": 1})
        new_bal = float(prev.get("balance") or 0) + released_total if prev \
                    else released_total
        await col(RAMP_BALANCES).update_one(
            {"ramp_account_id": ramp_account_id, "asset": asset, "chain": chain},
            {"$set": {"balance": str(new_bal), "as_of": _now_iso()}},
            upsert=True)

    logger.info("wallet.active: user=%s asset=%s chain=%s released=%d (%s ARSa)",
                  user_id, asset, chain, len(released_ids), released_total)

    await log_action(actor=None, action="ramp.wallet.active",
                              resource_type="ramp_wallet",
                              resource_id=user_id,
                              metadata={"org_id": org_id,
                                          "asset": asset, "chain": chain,
                                          "released_deposits": released_ids,
                                          "released_amount": released_total,
                                          "delivery_id": evt.delivery_id})

    # Phase 03 — Publish `deposit.credited` for each previously-held
    # deposit that just got released. ARSa rail. Soft-fail per movement.
    if released_movements:
        try:
            from services.event_bus import publish as _publish
            for rm in released_movements:
                try:
                    await _publish({
                        "event_type":  "deposit.credited",
                        "version":     1,
                        "event_id":    f"evt_dep_arsa_{rm['external_id']}",
                        "asset":       "arsa",
                        "deposit_id":  rm["external_id"],
                        "tx_hash":     None,
                        "org_id":      org_id,
                        "user_id":     None,
                        "amount":      rm.get("amount"),
                        "currency":    "ARSa",
                        "ref":         None,
                        "occurred_at": rm.get("occurred_at") or _now_iso(),
                        "detected_at": _now_iso(),
                        "source":      "andes_webhook",
                        "metadata": {
                            "chain":             chain,
                            "ramp_account_id":   ramp_account_id,
                            "provider_user_id":  user_id,
                            "released":          True,
                            "delivery_id":       evt.delivery_id,
                        },
                    })
                except Exception:
                    logger.exception("wallet.active publish failed for "
                                        "released ext_id=%s",
                                        rm.get("external_id"))
        except Exception:
            logger.exception("wallet.active publish loop failed "
                                "(non-blocking)")


async def _handle_fiat_account_created(evt: WebhookIn) -> None:
    """When Andes finishes provisioning the CVU it emits fiat.account.created.
    We refresh the cvu/alias/status on our ramp_accounts + ramp_fiat_accounts.
    """
    d = _data(evt)
    user_id = str(d.get("userId") or d.get("user_id") or "")
    cvu     = d.get("cvu")
    alias   = d.get("alias")
    fid     = str(d.get("fiat_account_id") or d.get("fiatAccountId") or "")
    onb     = d.get("onboarding_status") or d.get("onboardingStatus") or "approved"

    if not user_id:
        logger.warning("fiat.account.created without user_id (delivery=%s)",
                          evt.delivery_id)
        return

    acc = await _account_for_user(user_id)
    if not acc:
        logger.warning("fiat.account.created for unknown user_id=%s", user_id)
        return

    await col(RAMP_ACCOUNTS).update_one(
        {"id": acc["id"]},
        {"$set": {
            "cvu": cvu, "alias": alias,
            "cvu_status": "completed" if cvu else "pending",
            "onboarding_status": onb,
            "onboarding_message": None,
            "updated_at": _now_iso(),
        }})
    if fid:
        await col(RAMP_FIAT_ACCOUNTS).update_one(
            {"org_id": acc["org_id"], "fiat_account_id": fid},
            {"$set": {"cvu": cvu, "alias": alias,
                        "onboarding_status": onb,
                        "updated_at": _now_iso()}},
            upsert=False)
    logger.info("fiat.account.created: user=%s cvu=%s alias=%s", user_id,
                  cvu, alias)

    # Phase 22+ (orden b · andes-direct) — delegamos al helper unificado
    # `services.activation.on_identity_approved` que implementa la política
    # de dos gates (identidad + sanctions). Es idempotente, así que es
    # seguro llamarlo tanto desde acá (path asíncrono) como desde el
    # endpoint de upload de kyc-docs (path sincrónico cuando Andes
    # responde "approved" en la misma request).
    if cvu and onb in ("approved", "completed"):
        from services.activation import on_identity_approved
        await on_identity_approved(
            org_id=acc["org_id"],
            andes_user_id=user_id,
            cvu=cvu,
            alias=alias,
            source="fiat.account.created",
        )


async def _handle_deposit_failed(evt: WebhookIn) -> None:
    d = _data(evt)
    user_id = str(d.get("userId") or d.get("user_id") or "")
    acc = await _account_for_user(user_id)
    org_id = (acc or {}).get("org_id", "")
    ext_id = str(d.get("transactionId") or "ext_" + secrets.token_hex(4))
    reason = str(d.get("reason") or d.get("message") or "unknown")

    mv = {
        "id":              "mv_" + secrets.token_hex(6),
        "org_id":          org_id,
        "ramp_account_id": (acc or {}).get("id", ""),
        "provider":        "andeslabs",
        "provider_user_id": user_id,
        "external_id":     ext_id,
        "kind":            "deposit",
        "asset":           (d.get("asset") or "arsa").lower(),
        "chain":           (d.get("chain") or "stellar").lower(),
        "amount":          str(d.get("amount") or "0"),
        "status":          "Failed",
        "fail_reason":     reason,
        "raw":             d,
        "delivery_id":     evt.delivery_id,
        "created_at":      _now_iso(),
        "updated_at":      _now_iso(),
    }
    await col(RAMP_MOVEMENTS).insert_one(dict(mv))

    await col(ALERTS).insert_one({
        "alert_id":   "alrt_" + secrets.token_hex(6),
        "org_id":     org_id or None,
        "severity":   "medium",
        "category":   "ramp.deposit.failed",
        "title":      "Depósito ARSa fallido",
        "body":       f"Andes rechazó un depósito (ext_id={ext_id}): {reason}",
        "metadata":   {"ext_id": ext_id, "user_id": user_id},
        "status":     "open",
        "created_at": _now_iso(),
    })


async def _handle_withdrawal_success(evt: WebhookIn) -> None:
    d = _data(evt)
    ext_id = str(d.get("transactionId") or "")
    if not ext_id:
        logger.warning("withdrawal.success without transactionId — skipping")
        return
    res = await col(RAMP_MOVEMENTS).update_one(
        {"external_id": ext_id, "kind": "withdrawal"},
        {"$set": {"status": "Success",
                    "fail_reason": None,
                    "settled_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "raw.settle": d}})
    if res.matched_count == 0:
        logger.warning("withdrawal.success for unknown ext_id=%s", ext_id)
    await log_action(actor=None, action="ramp.withdrawal.success",
                              resource_type="ramp_movement",
                              resource_id=ext_id,
                              metadata={"delivery_id": evt.delivery_id})


async def _handle_withdrawal_failed(evt: WebhookIn) -> None:
    d = _data(evt)
    ext_id = str(d.get("transactionId") or "")
    reason = str(d.get("reason") or d.get("message") or "unknown")
    if not ext_id:
        return
    mv = await col(RAMP_MOVEMENTS).find_one_and_update(
        {"external_id": ext_id, "kind": "withdrawal"},
        {"$set": {"status": "Failed",
                    "fail_reason": reason,
                    "updated_at": _now_iso()}},
        projection={"_id": 0, "id": 1, "org_id": 1, "amount": 1,
                      "ramp_account_id": 1, "provider_user_id": 1, "asset": 1,
                      "chain": 1},
        return_document=False)

    # CRITICAL — refund the wallet balance on the gateway side too, because
    # we pre-debited at submission time. Best-effort: just adjust our cached
    # ramp_balances row so the UI shows the right number.
    if mv:
        prev = await col(RAMP_BALANCES).find_one(
            {"ramp_account_id": mv["ramp_account_id"],
              "asset": mv["asset"], "chain": mv["chain"]},
            {"_id": 0, "balance": 1})
        new_bal = str(float(prev.get("balance") or 0) + float(mv.get("amount") or 0)
                       ) if prev else mv.get("amount") or "0"
        await col(RAMP_BALANCES).update_one(
            {"ramp_account_id": mv["ramp_account_id"],
              "asset": mv["asset"], "chain": mv["chain"]},
            {"$set": {"balance": new_bal, "as_of": _now_iso()}},
            upsert=True)

    await col(ALERTS).insert_one({
        "alert_id":   "alrt_" + secrets.token_hex(6),
        "org_id":     (mv or {}).get("org_id") or None,
        "severity":   "high",
        "category":   "ramp.withdrawal.failed",
        "title":      "Retiro ARSa fallido",
        "body":       f"Andes rechazó un retiro (ext_id={ext_id}): {reason}",
        "metadata":   {"ext_id": ext_id},
        "status":     "open",
        "created_at": _now_iso(),
    })


async def _handle_crypto_transfer(evt: WebhookIn) -> None:
    """Phase 15.2 — crypto transfer settlement.
    Updates ramp_movements(kind='transfer', external_id=transactionId) and
    refunds the cached balance if the transfer failed (we pre-debited at
    submission).
    """
    d = _data(evt)
    ext_id = str(d.get("transactionId") or d.get("wallet_transaction_id") or "")
    status = d.get("status")
    new_status = "Success" if evt.event_type.endswith(".success") else "Failed"
    if status:
        new_status = status if status in ("Success", "Failed") else new_status

    if not ext_id:
        logger.warning("crypto.transfer.* without transactionId (delivery=%s)",
                          evt.delivery_id)
        return

    update: dict[str, Any] = {
        "status":      new_status,
        "updated_at":  _now_iso(),
        "raw.settle":  d,
    }
    if new_status == "Success":
        update["tx_hash"]   = d.get("tx_hash") or d.get("hash")
        update["settled_at"] = _now_iso()
    else:
        update["fail_reason"] = d.get("reason") or d.get("message") or "unknown"

    mv = await col(RAMP_MOVEMENTS).find_one_and_update(
        {"external_id": ext_id, "kind": "transfer"},
        {"$set": update},
        projection={"_id": 0, "id": 1, "org_id": 1, "amount": 1,
                      "ramp_account_id": 1, "asset": 1, "chain": 1},
        return_document=False)

    # On failure: refund the pre-debited balance
    if mv and new_status == "Failed":
        prev = await col(RAMP_BALANCES).find_one(
            {"ramp_account_id": mv["ramp_account_id"],
              "asset": mv["asset"], "chain": mv["chain"]},
            {"_id": 0, "balance": 1})
        amount = float(mv.get("amount") or 0)
        new_bal = str(float((prev or {}).get("balance") or 0) + amount)
        await col(RAMP_BALANCES).update_one(
            {"ramp_account_id": mv["ramp_account_id"],
              "asset": mv["asset"], "chain": mv["chain"]},
            {"$set": {"balance": new_bal, "as_of": _now_iso()}},
            upsert=True)
        await col(ALERTS).insert_one({
            "alert_id":   "alrt_" + secrets.token_hex(6),
            "org_id":     mv.get("org_id") or None,
            "severity":   "medium",
            "category":   "ramp.transfer.failed",
            "title":      "Transferencia cripto fallida",
            "body":       f"Andes reportó transferencia fallida (ext_id={ext_id})",
            "metadata":   {"ext_id": ext_id},
            "status":     "open",
            "created_at": _now_iso(),
        })

    await log_action(actor=None, action=f"ramp.transfer.{new_status.lower()}",
                              resource_type="ramp_movement",
                              resource_id=ext_id,
                              metadata={"delivery_id": evt.delivery_id})


async def _handle_intl_offramp(evt: WebhookIn) -> None:
    """Phase 15.2 — international off-ramp settlement.
    Looks up the ramp_movements(kind='intl_offramp') by external_id and
    transitions status to Success/Failed. On Failed, refunds the (frozen)
    ARSa caps and emits an alert.
    """
    d = _data(evt)
    ext_id = str(d.get("transactionId") or d.get("id") or "")
    new_status = "Success" if evt.event_type.endswith(".success") else "Failed"

    if not ext_id:
        logger.warning("international.offramp.* without external_id (delivery=%s)",
                          evt.delivery_id)
        return

    update: dict[str, Any] = {
        "status":     new_status,
        "updated_at": _now_iso(),
        "raw.settle": d,
    }
    if new_status == "Success":
        update["settled_at"] = _now_iso()
        if d.get("to_amount"):
            update["to_amount"] = d.get("to_amount")
    else:
        update["fail_reason"] = d.get("reason") or d.get("message") or "unknown"

    mv = await col(RAMP_MOVEMENTS).find_one_and_update(
        {"external_id": ext_id, "kind": "intl_offramp"},
        {"$set": update},
        projection={"_id": 0, "id": 1, "org_id": 1, "country": 1},
        return_document=False)

    if mv and new_status == "Failed":
        await col(ALERTS).insert_one({
            "alert_id":   "alrt_" + secrets.token_hex(6),
            "org_id":     mv.get("org_id") or None,
            "severity":   "high",
            "category":   "ramp.intl_offramp.failed",
            "title":      "Off-ramp internacional fallido",
            "body":       f"Andes rechazó el off-ramp {mv.get('country','?')} "
                          f"(ext_id={ext_id})",
            "metadata":   {"ext_id": ext_id, "country": mv.get("country")},
            "status":     "open",
            "created_at": _now_iso(),
        })

    await log_action(actor=None,
                              action=f"ramp.intl_offramp.{new_status.lower()}",
                              resource_type="ramp_movement",
                              resource_id=ext_id,
                              metadata={"delivery_id": evt.delivery_id})
