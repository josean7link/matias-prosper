"""Abstract Alfred adapter — common interface for Mock + Real impls."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


class AlfredError(Exception):
    """Any failure talking to Alfred."""


@dataclass
class Quote:
    """A live quote for an on/off-ramp operation. Valid for `ttl_seconds`."""
    quote_id: str
    direction: Literal["onramp", "offramp"]
    source_currency: str
    source_amount: float
    target_currency: str
    target_amount: float
    rate: float
    fee_amount: float
    fee_currency: str
    ttl_seconds: int
    expires_at: str   # ISO 8601 UTC
    mode: Literal["mock", "sandbox", "production"]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OnrampOrderResponse:
    alfred_id: str
    checkout_url: str             # external URL to redirect user
    status: str                   # pending | confirmed | failed
    expected_usdc: float
    mode: Literal["mock", "sandbox", "production"]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OfframpOrderResponse:
    alfred_id: str
    status: str
    expected_fiat: float
    mode: Literal["mock", "sandbox", "production"]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderStatus:
    alfred_id: str
    status: str                       # pending | confirmed | completed | failed
    settled_amount: Optional[float] = None
    settled_currency: Optional[str] = None
    coelsa_id: Optional[str] = None
    tx_hash: Optional[str] = None
    failure_reason: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


class AlfredAdapter(ABC):
    """Tiny, well-typed surface so MockAlfredAdapter and RealAlfredAdapter
    can be swapped behind a single env var."""

    mode: Literal["mock", "sandbox", "production"] = "mock"

    @abstractmethod
    async def get_quote(self, *, direction: Literal["onramp", "offramp"],
                        source_currency: str, source_amount: float,
                        target_currency: str) -> Quote: ...

    @abstractmethod
    async def create_onramp_order(self, *, quote_id: str, source_currency: str,
                                  source_amount: float, user_id: str, org_id: str,
                                  callback_url: str,
                                  payment_method: str) -> OnrampOrderResponse: ...

    @abstractmethod
    async def create_offramp_order(self, *, quote_id: str, usdc_amount: float,
                                   target_currency: str,
                                   bank_account: dict[str, Any],
                                   user_id: str, org_id: str) -> OfframpOrderResponse: ...

    @abstractmethod
    async def get_order_status(self, alfred_id: str) -> OrderStatus: ...

    @abstractmethod
    def verify_webhook(self, *, payload: bytes, signature: str) -> bool: ...
