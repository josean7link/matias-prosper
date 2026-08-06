"""Stellar Horizon adapter — Deposit Detection Engine (Camino A).

Public surface used by the Deposit Watcher. The adapter normalizes the
Horizon `/payments` stream so the watcher only deals with a single
`Payment` dataclass regardless of mock vs real backend.

Toggle via `HORIZON_MODE=mock|real` (default: mock). The factory is
process-cached so callers never instantiate the adapter directly.

NOTE: this is read-only — the adapter NEVER signs or submits Stellar
transactions. The Deposit Engine is strictly a detector.
"""
from .adapter import HorizonAdapter, HorizonError, Payment, PaymentsPage
from .factory import get_adapter, reset_adapter_cache

__all__ = [
    "HorizonAdapter",
    "HorizonError",
    "Payment",
    "PaymentsPage",
    "get_adapter",
    "reset_adapter_cache",
]
