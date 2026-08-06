"""Abstract Prosper adapter — common interface for Mock + Real."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class ProsperError(Exception):
    """Anything that goes wrong talking to the Prosper Stellar backend."""


@dataclass
class WalletResp:
    address: str
    tx_hash: str
    ledger: str
    status: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenOpResp:
    tx_hash: str
    ledger: str
    status: str
    address: Optional[str] = None
    balance: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BalancesResp:
    address: str
    balance_prosper: str
    balance_xlm: str
    raw: dict[str, Any] = field(default_factory=dict)


class ProsperAdapter(ABC):
    """Public surface used by the rest of the backend. Mock and Real both
    implement this so the only thing that changes is the env var."""

    mode: str = "mock"

    @abstractmethod
    async def create_user_wallet(self, *, user_reference_id: str,
                                  prosper_tx_id: str,
                                  modality: str = "end") -> WalletResp: ...

    @abstractmethod
    async def deposit_tokens(self, *, user_reference_id: str, amount: float,
                              prosper_tx_id: str) -> TokenOpResp: ...

    @abstractmethod
    async def withdraw_tokens(self, *, user_reference_id: str, amount: float,
                               prosper_tx_id: str) -> TokenOpResp: ...

    @abstractmethod
    async def transfer_tokens(self, *, amount: float, from_user_id: str,
                               to_user_id: str, prosper_tx_id: str,
                               metadata: dict | None = None) -> TokenOpResp: ...

    @abstractmethod
    async def get_user_balances(self, user_id: str) -> BalancesResp: ...

    @abstractmethod
    async def get_user_transactions(self, user_id: str) -> dict: ...

    @abstractmethod
    async def get_assets(self) -> dict: ...
