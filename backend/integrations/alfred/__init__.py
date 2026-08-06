"""Alfred onramp/offramp integration package.

Two adapter implementations behind a single `AlfredAdapter` interface:
  - MockAlfredAdapter:   deterministic, fast — used when ALFRED_MODE=mock
                          (default while credentials are pending).
  - RealAlfredAdapter:   real HTTP calls — used when ALFRED_MODE=sandbox
                          or ALFRED_MODE=production.

Switch the active adapter with `ALFRED_MODE` in the backend env.

Public helpers:
    get_adapter()        -> AlfredAdapter
    log_call(name, ...)  -> persists every call to `alfred_calls_log`
"""
from .adapter import (
    AlfredAdapter, Quote, OnrampOrderResponse, OfframpOrderResponse,
    OrderStatus, AlfredError,
)
from .factory import get_adapter, current_mode, verify_webhook

__all__ = [
    "AlfredAdapter", "Quote", "OnrampOrderResponse", "OfframpOrderResponse",
    "OrderStatus", "AlfredError", "get_adapter", "current_mode", "verify_webhook",
]
