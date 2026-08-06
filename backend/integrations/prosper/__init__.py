"""Prosper Stellar protocol integration package.

Two adapter implementations behind a `ProsperAdapter` interface:
  - MockProsperAdapter: deterministic, in-process, fast — default when
                        PROSPER_MODE=mock OR when no credentials.
  - RealProsperAdapter: real HTTP calls to the Prosper Stellar backend.

Switch with `PROSPER_MODE=mock|development|production`.

Env vars:
    PROSPER_MODE
    PROSPER_API_BASE
    PROSPER_API_USER
    PROSPER_API_PASS
"""
from .adapter import (
    ProsperAdapter, ProsperError, WalletResp, TokenOpResp, BalancesResp,
)
from .factory import get_adapter, current_mode

__all__ = [
    "ProsperAdapter", "ProsperError", "WalletResp", "TokenOpResp", "BalancesResp",
    "get_adapter", "current_mode",
]
