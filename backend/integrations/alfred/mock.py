"""MockAlfredAdapter — deterministic, fast, realistic responses.

Used while real Alfred credentials are pending. Behaviour:
  * Hardcoded FX table (ARS/USD/CLP).
  * 80 bps total fee (0.35% Alfred + 0.45% Prosper) baked into output.
  * Quotes valid for 60 seconds.
  * Webhook HMAC is verified with ALFRED_WEBHOOK_SECRET (so we can still test
    the signature path).
  * Polling `get_order_status` returns 'pending' until a deterministic time
    offset, then flips to 'confirmed' (for onramp) or 'completed' (offramp).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from .adapter import (
    AlfredAdapter, Quote, OnrampOrderResponse, OfframpOrderResponse,
    OrderStatus, AlfredError,
)

# Hardcoded FX rates (sandbox levels — chosen so ARS 100k ≈ 96.6 USDC after fees,
# matching the FASE 8 DoD example).
_RATES = {
    "ARS": 1030.00,   # 1 USD = 1030 ARS
    "USD": 1.00,
    "USDC": 1.00,
    "CLP":   950.00,
    "BRL":     5.10,
    "MXN":    17.30,
    "EUR":     0.92,
}

# 80bps total fee (Alfred 35bps + Prosper 45bps)
_FEE_BPS = 80


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _rate(src: str, dst: str) -> float:
    if src not in _RATES or dst not in _RATES:
        raise AlfredError(f"Unsupported currency pair {src}/{dst}")
    # express as: 1 unit of src -> X units of dst
    # _RATES values are: 1 USD = X local
    src_per_usd = _RATES[src]
    dst_per_usd = _RATES[dst]
    return dst_per_usd / src_per_usd


# In-memory order book (reset on process restart — adequate for mock).
_ORDERS: dict[str, dict[str, Any]] = {}


class MockAlfredAdapter(AlfredAdapter):
    """Stateless except for the in-process order book."""

    mode: Literal["mock", "sandbox", "production"] = "mock"

    async def get_quote(self, *, direction, source_currency, source_amount,
                        target_currency) -> Quote:
        if source_amount <= 0:
            raise AlfredError("source_amount must be > 0")

        src = source_currency.upper()
        dst = target_currency.upper()
        rate = _rate(src, dst)
        gross = source_amount * rate
        fee = round(gross * _FEE_BPS / 10_000, 2)
        target = round(gross - fee, 2)

        ttl = 60
        now = _now()
        return Quote(
            quote_id="qt_mock_" + secrets.token_hex(6),
            direction=direction,
            source_currency=src,
            source_amount=round(source_amount, 2),
            target_currency=dst,
            target_amount=target,
            rate=round(rate, 6),
            fee_amount=fee,
            fee_currency=dst,
            ttl_seconds=ttl,
            expires_at=_iso(now + timedelta(seconds=ttl)),
            mode="mock",
            raw={"fee_bps": _FEE_BPS, "provider": "alfred-mock"},
        )

    async def create_onramp_order(self, *, quote_id, source_currency, source_amount,
                                  user_id, org_id, callback_url, payment_method) -> OnrampOrderResponse:
        # Simulate Alfred-side validation
        if source_amount <= 0:
            raise AlfredError("source_amount must be > 0")

        alfred_id = "alf_on_" + secrets.token_hex(8)
        src = source_currency.upper()
        rate = _rate(src, "USDC")
        gross = source_amount * rate
        fee = round(gross * _FEE_BPS / 10_000, 2)
        expected = round(gross - fee, 2)

        _ORDERS[alfred_id] = {
            "alfred_id":   alfred_id,
            "direction":   "onramp",
            "status":      "pending",
            "source_currency": src,
            "source_amount":   round(source_amount, 2),
            "expected_usdc":   expected,
            "callback_url":    callback_url,
            "payment_method":  payment_method,
            "org_id":          org_id,
            "user_id":         user_id,
            "created_at":      _iso(_now()),
            # Settle after 8 seconds in mock (real Alfred is ~5-30 min).
            "_settle_at":      _now() + timedelta(seconds=8),
            "coelsa_id":       "coelsa_" + secrets.token_hex(6),
            "tx_hash":         "stellar_" + secrets.token_hex(10),
        }

        base = os.environ.get("APP_URL", "http://localhost:3000")
        checkout_url = f"{base}/api/v1/alfred/mock-checkout/{alfred_id}"

        return OnrampOrderResponse(
            alfred_id=alfred_id,
            checkout_url=checkout_url,
            status="pending",
            expected_usdc=expected,
            mode="mock",
            raw=_ORDERS[alfred_id].copy(),
        )

    async def create_offramp_order(self, *, quote_id, usdc_amount, target_currency,
                                   bank_account, user_id, org_id) -> OfframpOrderResponse:
        if usdc_amount <= 0:
            raise AlfredError("usdc_amount must be > 0")
        if not bank_account or not bank_account.get("holder_name"):
            raise AlfredError("bank_account.holder_name is required")

        alfred_id = "alf_off_" + secrets.token_hex(8)
        dst = target_currency.upper()
        rate = _rate("USDC", dst)
        gross = usdc_amount * rate
        fee = round(gross * _FEE_BPS / 10_000, 2)
        expected = round(gross - fee, 2)

        _ORDERS[alfred_id] = {
            "alfred_id":     alfred_id,
            "direction":     "offramp",
            "status":        "pending",
            "target_currency": dst,
            "usdc_amount":   round(usdc_amount, 2),
            "expected_fiat": expected,
            "bank_account":  bank_account,
            "org_id":        org_id,
            "user_id":       user_id,
            "created_at":    _iso(_now()),
            # Offramp settles after 12 seconds in mock.
            "_settle_at":    _now() + timedelta(seconds=12),
            "coelsa_id":     "coelsa_" + secrets.token_hex(6),
        }

        return OfframpOrderResponse(
            alfred_id=alfred_id,
            status="pending",
            expected_fiat=expected,
            mode="mock",
            raw=_ORDERS[alfred_id].copy(),
        )

    async def get_order_status(self, alfred_id: str) -> OrderStatus:
        order = _ORDERS.get(alfred_id)
        if not order:
            raise AlfredError(f"Unknown alfred order {alfred_id}")

        # Auto-progress if past _settle_at
        if order["status"] == "pending" and _now() >= order["_settle_at"]:
            order["status"] = "confirmed" if order["direction"] == "onramp" else "completed"

        if order["direction"] == "onramp":
            return OrderStatus(
                alfred_id=alfred_id,
                status=order["status"],
                settled_amount=order["expected_usdc"] if order["status"] == "confirmed" else None,
                settled_currency="USDC" if order["status"] == "confirmed" else None,
                coelsa_id=order["coelsa_id"] if order["status"] == "confirmed" else None,
                tx_hash=order.get("tx_hash") if order["status"] == "confirmed" else None,
                raw=order,
            )
        else:
            return OrderStatus(
                alfred_id=alfred_id,
                status=order["status"],
                settled_amount=order["expected_fiat"] if order["status"] == "completed" else None,
                settled_currency=order["target_currency"] if order["status"] == "completed" else None,
                coelsa_id=order["coelsa_id"] if order["status"] == "completed" else None,
                raw=order,
            )

    def verify_webhook(self, *, payload: bytes, signature: str) -> bool:
        secret = os.environ.get("ALFRED_WEBHOOK_SECRET", "mock_secret_change_me").encode()
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, (signature or "").lower())


def settle_now(alfred_id: str, *, force_failure: bool = False) -> dict:
    """Test helper — fast-forward an order to settled. Used by mock-checkout
    page and by automated tests."""
    order = _ORDERS.get(alfred_id)
    if not order:
        raise AlfredError(f"Unknown alfred order {alfred_id}")
    if force_failure:
        order["status"] = "failed"
    elif order["direction"] == "onramp":
        order["status"] = "confirmed"
    else:
        order["status"] = "completed"
    order["_settle_at"] = _now() - timedelta(seconds=1)
    return order
