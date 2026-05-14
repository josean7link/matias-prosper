"""RealAlfredAdapter — talks to Alfred Pay's Penny API.

Endpoint base (sandbox): ``ALFRED_API_BASE_SANDBOX``
Endpoint base (prod):    ``ALFRED_API_BASE_PRODUCTION``

Authentication (per https://alfredpay.readme.io/reference):
    Every request includes:
        api-key:    <ALFRED_API_KEY>
        api-secret: <ALFRED_API_SECRET>
    Endpoints that act on behalf of a specific *end-user* also need a
    short-lived Bearer token returned by Alfred's KYC iframe completion
    callback — passed via ``bearer_token`` to the relevant methods.

Webhook signatures:
    Header: ``Signature: t=<unix_ts>,s=<hex_hmac_sha256>``
    Canonical:  ``f"{ts}.{raw_body}"``   (raw bytes, NOT pretty-printed)
    Algorithm:  HMAC-SHA256(secret=ALFRED_WEBHOOK_SECRET)
    Time skew:  ±5 minutes accepted (replay protection).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Literal, Optional

import httpx

from .adapter import (
    AlfredAdapter, Quote, OnrampOrderResponse, OfframpOrderResponse,
    OrderStatus, AlfredError,
)

logger = logging.getLogger("prosper.alfred")

# Maximum tolerated clock-skew on webhook timestamps
WEBHOOK_TOLERANCE_SECONDS = 300


def _base_url(mode: str) -> str:
    if mode == "production":
        return os.environ.get(
            "ALFRED_API_BASE_PRODUCTION",
            "https://penny-api-restricted.alfredpay.io/api/v1/third-party-service/penny")
    return os.environ.get(
        "ALFRED_API_BASE_SANDBOX",
        "https://penny-api-restricted-dev.alfredpay.io/api/v1/third-party-service/penny")


class RealAlfredAdapter(AlfredAdapter):
    """HTTP adapter for Alfred Pay Penny API (sandbox + production)."""

    def __init__(self, mode: Literal["sandbox", "production"]):
        self.mode = mode
        self._api_key = os.environ.get("ALFRED_API_KEY", "")
        self._api_secret = os.environ.get("ALFRED_API_SECRET", "")
        self._business_id = os.environ.get("ALFRED_BUSINESS_ID", "")
        self._base = _base_url(mode)
        if not self._api_key or not self._api_secret:
            raise AlfredError(
                "ALFRED_API_KEY / ALFRED_API_SECRET are empty — "
                "set them or switch ALFRED_MODE=mock")
        logger.info("RealAlfredAdapter ready (mode=%s, business_id=%s, base=%s)",
                     mode, self._business_id, self._base)

    # ---------------------------------------------------------------------
    # Low-level HTTP
    # ---------------------------------------------------------------------
    def _headers(self, *, bearer_token: Optional[str] = None) -> dict[str, str]:
        h = {
            "api-key":      self._api_key,
            "api-secret":   self._api_secret,
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "User-Agent":   "prosper-backend/0.2 (+https://prosper.foundation)",
        }
        if self._business_id:
            h["business-id"] = self._business_id  # not required by every endpoint
        if bearer_token:
            h["Authorization"] = f"Bearer {bearer_token}"
        return h

    async def _request(self, method: str, path: str, *,
                        json_body: dict | None = None,
                        bearer_token: Optional[str] = None) -> dict:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=30.0) as cx:
            try:
                r = await cx.request(method, url, json=json_body,
                                       headers=self._headers(bearer_token=bearer_token))
            except httpx.HTTPError as e:
                logger.exception("alfred http error %s %s", method, path)
                raise AlfredError(f"Network error talking to Alfred: {e}") from e
        # Surface Alfred's error body verbatim to the caller (truncated for logs)
        if r.status_code >= 400:
            body_preview = r.text[:500].replace("\n", " ")
            logger.warning("Alfred %s %s → %s · %s",
                            method, path, r.status_code, body_preview)
            raise AlfredError(f"Alfred {r.status_code} on {path}: {body_preview}")
        try:
            return r.json() if r.text else {}
        except ValueError as e:
            raise AlfredError(
                f"Alfred returned non-JSON for {path}: {r.text[:200]!r}") from e

    # ---------------------------------------------------------------------
    # Quotes — POST /quotes
    # ---------------------------------------------------------------------
    async def get_quote(self, *, direction, source_currency, source_amount,
                          target_currency) -> Quote:
        # Penny accepts a single direction-agnostic quote shape with from/to.
        # Quote endpoint uses `fromAmount` (NOT `amount` — that field name
        # is only valid on /onramp and /offramp). `paymentMethodType` is
        # required at the quote stage because the rate depends on the rail.
        body = {
            "fromCurrency":      source_currency,
            "toCurrency":        target_currency,
            "fromAmount":        str(source_amount),
            "chain":             os.environ.get("ALFRED_DEFAULT_CHAIN", "XLM"),
            "paymentMethodType": os.environ.get(
                "ALFRED_DEFAULT_PAYMENT_METHOD", "BANK"),
        }
        data = await self._request("POST", "/quotes", json_body=body)

        target_amount = float(data.get("toAmount") or 0)
        rate          = float(data.get("rate") or 0)
        fee_amount    = 0.0
        for fee in data.get("fees", []) or []:
            try:
                fee_amount += float(fee.get("amount", 0) or 0)
            except (TypeError, ValueError):
                pass

        return Quote(
            quote_id=str(data.get("quoteId") or ""),
            direction=direction,
            source_currency=source_currency,
            source_amount=source_amount,
            target_currency=target_currency,
            target_amount=target_amount,
            rate=rate,
            fee_amount=fee_amount,
            fee_currency=source_currency,
            ttl_seconds=180,  # Penny quotes ~ 3min by default
            expires_at=data.get("expiration") or "",
            mode=self.mode,
            raw=data,
        )

    # ---------------------------------------------------------------------
    # Onramp — POST /onramp
    # ---------------------------------------------------------------------
    async def create_onramp_order(self, *, quote_id, source_currency, source_amount,
                                    user_id, org_id, callback_url,
                                    payment_method) -> OnrampOrderResponse:
        # Optional kwargs forwarded via raw env / per-org defaults
        body = {
            "quoteId":           quote_id,
            "customerId":        os.environ.get("ALFRED_DEFAULT_CUSTOMER_ID") or user_id,
            "fromCurrency":      source_currency,
            "toCurrency":        "USDC",
            "amount":            str(source_amount),
            "chain":             os.environ.get("ALFRED_DEFAULT_CHAIN", "XLM"),
            "depositAddress":    os.environ.get("ALFRED_DEFAULT_DEPOSIT_ADDRESS", ""),
            "paymentMethodType": payment_method.upper(),
            "callbackUrl":       callback_url,
            "externalReference": f"prosper:{org_id}:{user_id}",
        }
        data = await self._request("POST", "/onramp", json_body=body)
        # Penny wraps onramp responses in {transaction, fiatPaymentInstructions}.
        tx       = data.get("transaction", data)
        instr    = data.get("fiatPaymentInstructions") or {}
        # Pin the payment instructions into raw so the route can render them.
        raw_full = {"transaction": tx, "fiatPaymentInstructions": instr}
        return OnrampOrderResponse(
            alfred_id=str(tx.get("transactionId") or tx.get("referenceId") or ""),
            checkout_url=instr.get("qrCodeImage")
                          or instr.get("qrCode")
                          or "",
            status=(tx.get("status") or "CREATED").lower(),
            expected_usdc=float(tx.get("toAmount") or 0),
            mode=self.mode,
            raw=raw_full,
        )

    # ---------------------------------------------------------------------
    # Offramp — POST /offramp
    # ---------------------------------------------------------------------
    async def create_offramp_order(self, *, quote_id, usdc_amount, target_currency,
                                     bank_account, user_id, org_id) -> OfframpOrderResponse:
        body = {
            "quoteId":       quote_id,
            "customerId":    os.environ.get("ALFRED_DEFAULT_CUSTOMER_ID") or user_id,
            "fromCurrency":  "USDC",
            "toCurrency":    target_currency,
            "amount":        str(usdc_amount),
            "chain":         os.environ.get("ALFRED_DEFAULT_CHAIN", "XLM"),
            "fiatAccountId": bank_account.get("fiat_account_id") or bank_account.get("id"),
            "originAddress": bank_account.get("origin_address", ""),
            "externalReference": f"prosper:{org_id}:{user_id}",
        }
        data = await self._request("POST", "/offramp", json_body=body)
        # Offramp Penny responses are flat (no wrapper).
        return OfframpOrderResponse(
            alfred_id=str(data.get("transactionId") or data.get("referenceId") or ""),
            status=(data.get("status") or "CREATED").lower(),
            expected_fiat=float(data.get("toAmount") or 0),
            mode=self.mode,
            raw=data,
        )

    # ---------------------------------------------------------------------
    # Status — GET /transactions/{id}   (Penny uses referenceId)
    # ---------------------------------------------------------------------
    async def get_order_status(self, alfred_id: str) -> OrderStatus:
        # Penny exposes the txn under /transactions/{referenceId} per docs.
        # Try the new path, fall back to /orders/{id} for forward-compat.
        try:
            data = await self._request("GET", f"/transactions/{alfred_id}")
        except AlfredError as primary_err:
            try:
                data = await self._request("GET", f"/orders/{alfred_id}")
            except AlfredError:
                raise primary_err

        return OrderStatus(
            alfred_id=alfred_id,
            status=(data.get("status") or "pending").lower(),
            settled_amount=_optional_float(data.get("settledAmount")
                                             or data.get("toAmount")),
            settled_currency=data.get("settledCurrency")
                              or data.get("toCurrency"),
            coelsa_id=data.get("coelsaId"),
            tx_hash=data.get("txHash") or data.get("transactionHash"),
            failure_reason=data.get("failureReason") or data.get("errorMessage"),
            raw=data,
        )

    # ---------------------------------------------------------------------
    # Health check — does a benign call so caller can verify creds
    # ---------------------------------------------------------------------
    async def health_check(self) -> dict:
        """Probe the API with a tiny no-side-effect call. Used by /v1/status."""
        try:
            # ARS minimum typically ≥ 5000 — use a value sandbox accepts.
            await self.get_quote(direction="onramp",
                                   source_currency="ARS",
                                   source_amount=35_000,
                                   target_currency="USDC")
            return {"ok": True, "mode": self.mode}
        except AlfredError as e:
            return {"ok": False, "mode": self.mode, "error": str(e)[:200]}

    # ---------------------------------------------------------------------
    # Webhook signature — header `Signature: t=<ts>,s=<hex_hmac_sha256>`
    # ---------------------------------------------------------------------
    def verify_webhook(self, *, payload: bytes, signature: str) -> bool:
        secret = os.environ.get("ALFRED_WEBHOOK_SECRET", "").encode()
        if not secret:
            logger.warning("ALFRED_WEBHOOK_SECRET empty — rejecting webhook")
            return False
        if not signature:
            return False

        # Parse `t=<ts>,s=<sig>` OR fall back to a bare hex string (older docs).
        parts: dict[str, str] = {}
        for chunk in signature.split(","):
            if "=" in chunk:
                k, _, v = chunk.partition("=")
                parts[k.strip().lower()] = v.strip()

        if "t" in parts and "s" in parts:
            try:
                ts = int(parts["t"])
            except ValueError:
                return False
            if abs(int(time.time()) - ts) > WEBHOOK_TOLERANCE_SECONDS:
                logger.warning("Alfred webhook timestamp out of tolerance: %s", ts)
                return False
            signed = f"{ts}.{payload.decode('utf-8', errors='replace')}".encode()
            expected = hmac.new(secret, signed, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, parts["s"].lower())

        # Legacy: bare hex of HMAC(raw body).
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip().lower())


def _optional_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
