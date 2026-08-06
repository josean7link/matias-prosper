"""Abstract Horizon adapter — common interface for Mock + Real.

The Deposit Watcher consumes a single cursor over a global payments stream.
This keeps the design scalable: one cursor advances regardless of how many
org wallets we are watching (the wallet-set filter happens IN the watcher,
not in N parallel streams).

`fetch_payments(cursor, limit)` returns the next page of payments after
the given cursor. Pagination uses Horizon's `paging_token`. The adapter
itself is stateless — the cursor is persisted by the watcher in Mongo.

The `Payment` shape is normalized so the watcher can stay backend-agnostic:
mock fixtures and real Horizon both produce the same dataclass.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class HorizonError(Exception):
    """Anything that goes wrong talking to Horizon (or replaying fixtures)."""


@dataclass
class Payment:
    """Normalized inbound payment observed on Stellar.

    Only the fields the watcher actually needs. `raw` keeps the source
    document verbatim so downstream debugging is possible without
    re-querying Horizon.
    """
    paging_token: str          # cursor for the NEXT fetch (Horizon order)
    tx_hash:      str          # Stellar transaction hash (64-hex)
    op_id:        str          # Horizon operation id (per-op unique)
    to:           str          # destination G-address (Stellar account)
    from_:        str          # source G-address
    asset_code:   str          # e.g. "USDC". "" for native XLM.
    asset_issuer: str          # G-address of issuer. "" for native XLM.
    amount:       str          # decimal as string — never use float for money
    memo:         Optional[str]   # tx-level memo (MEMO_TEXT/MEMO_ID/MEMO_HASH)
    memo_type:    Optional[str]   # "text" | "id" | "hash" | "return" | None
    created_at:   str          # ISO-8601 (Horizon `created_at`)
    successful:   bool         # operation successful flag
    raw:          dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentsPage:
    """A page of payments + the cursor to use for the next fetch.

    `next_cursor` MUST be persisted by the watcher. On empty pages the
    cursor is unchanged (caller passes the same value on next tick).
    """
    payments:    list[Payment]
    next_cursor: str   # the paging_token of the LAST item, or echo of input


class HorizonAdapter(ABC):
    """Public surface used by the Deposit Watcher.

    Implementations:
      * MockHorizonAdapter — replays fixtures + supports inject_payment()
      * RealHorizonAdapter — httpx against STELLAR_HORIZON_URL
    """

    mode: str = "mock"

    @abstractmethod
    async def fetch_payments(self, *, cursor: str, limit: int = 200
                              ) -> PaymentsPage:
        """Pull the next page of payments after `cursor`.

        * `cursor` is a Horizon paging_token. Empty string means "from the
          beginning" — in real mode this should be avoided in prod (cold
          start floods the cursor with historical data); the watcher
          bootstraps from a recent ledger on first run.
        * `limit` is the Horizon page size (max 200).
        """
        ...

    @abstractmethod
    async def health_check(self) -> dict:
        """Quick liveness probe. Returns {ok: bool, mode: str, …}."""
        ...
