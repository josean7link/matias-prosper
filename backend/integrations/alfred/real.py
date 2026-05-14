"""RealAlfredAdapter — real HTTP calls to Alfred sandbox/production.

⚠️ Until ALFRED_API_KEY is set we keep this in stub state. The shape mirrors
the mock so swapping is a one-env-var change.

Endpoints assumed (per Alfred docs — TODO: confirm when credentials arrive):
    POST  /v1/quotes
    POST  /v1/orders/onramp
    POST  /v1/orders/offramp
    GET   /v1/orders/{id}

Auth: Bearer ALFRED_API_KEY
Webhook signature: HMAC-SHA256(payload, ALFRED_WEBHOOK_SECRET) in header
                   `X-Alfred-Signature` as hex.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any, Literal

import httpx

from .adapter import (
    AlfredAdapter, Quote, OnrampOrderResponse, OfframpOrderResponse,
    OrderStatus, AlfredError,
)

logger = logging.getLogger("prosper.alfred")

SANDBOX_BASE = "https://api-sandbox.alfred.capital/v1"
PROD_BASE    = "https://api.alfred.capital/v1"


def _base_url() -> str:
    return PROD_BASE if os.environ.get("ALFRED_MODE") == "production" else SANDBOX_BASE


def _api_key() -> str:
    return os.environ.get("ALFRED_API_KEY", "")


class RealAlfredAdapter(AlfredAdapter):
    """Real HTTP adapter — used when ALFRED_MODE in (sandbox, production)."""

    def __init__(self, mode: Literal["sandbox", "production"]):
        self.mode = mode
        if not _api_key():
            raise AlfredError(
                "ALFRED_API_KEY is empty — set it or switch ALFRED_MODE=mock")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type":  "application/json",
            "User-Agent":    "prosper-backend/0.1",
        }

    async def _request(self, method: str, path: str,
                       json_body: dict | None = None) -> dict:
        url = f"{_base_url()}{path}"
        async with httpx.AsyncClient(timeout=20.0) as cx:
            try:
                r = await cx.request(method, url, headers=self._headers(),
                                      json=json_body)
            except httpx.HTTPError as e:
                logger.exception("alfred http error %s %s", method, path)
                raise AlfredError(f"Network error talking to Alfred: {e}") from e
        if r.status_code >= 400:
            raise AlfredError(f"Alfred {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except ValueError as e:
            raise AlfredError("Alfred returned non-JSON response") from e

    async def get_quote(self, *, direction, source_currency, source_amount,
                        target_currency) -> Quote:
        data = await self._request("POST", "/quotes", {
            "direction": direction,
            "source_currency": source_currency,
            "source_amount": source_amount,
            "target_currency": target_currency,
        })
        return Quote(
            quote_id=data["quote_id"],
            direction=direction,
            source_currency=source_currency,
            source_amount=source_amount,
            target_currency=target_currency,
            target_amount=data["target_amount"],
            rate=data["rate"],
            fee_amount=data.get("fee_amount", 0),
            fee_currency=data.get("fee_currency", target_currency),
            ttl_seconds=data.get("ttl_seconds", 60),
            expires_at=data["expires_at"],
            mode=self.mode,
            raw=data,
        )

    async def create_onramp_order(self, *, quote_id, source_currency, source_amount,
                                  user_id, org_id, callback_url, payment_method) -> OnrampOrderResponse:
        data = await self._request("POST", "/orders/onramp", {
            "quote_id": quote_id,
            "source_currency": source_currency,
            "source_amount":   source_amount,
            "external_user_id": user_id,
            "external_org_id":  org_id,
            "callback_url":     callback_url,
            "payment_method":   payment_method,
        })
        return OnrampOrderResponse(
            alfred_id=data["order_id"],
            checkout_url=data["checkout_url"],
            status=data.get("status", "pending"),
            expected_usdc=data.get("expected_usdc", 0),
            mode=self.mode,
            raw=data,
        )

    async def create_offramp_order(self, *, quote_id, usdc_amount, target_currency,
                                   bank_account, user_id, org_id) -> OfframpOrderResponse:
        data = await self._request("POST", "/orders/offramp", {
            "quote_id": quote_id,
            "usdc_amount": usdc_amount,
            "target_currency": target_currency,
            "bank_account": bank_account,
            "external_user_id": user_id,
            "external_org_id":  org_id,
        })
        return OfframpOrderResponse(
            alfred_id=data["order_id"],
            status=data.get("status", "pending"),
            expected_fiat=data.get("expected_fiat", 0),
            mode=self.mode,
            raw=data,
        )

    async def get_order_status(self, alfred_id: str) -> OrderStatus:
        data = await self._request("GET", f"/orders/{alfred_id}")
        return OrderStatus(
            alfred_id=alfred_id,
            status=data.get("status", "pending"),
            settled_amount=data.get("settled_amount"),
            settled_currency=data.get("settled_currency"),
            coelsa_id=data.get("coelsa_id"),
            tx_hash=data.get("tx_hash"),
            failure_reason=data.get("failure_reason"),
            raw=data,
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> bool:
        secret = os.environ.get("ALFRED_WEBHOOK_SECRET", "").encode()
        if not secret:
            logger.warning("ALFRED_WEBHOOK_SECRET empty — rejecting webhook")
            return False
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, (signature or "").lower())
