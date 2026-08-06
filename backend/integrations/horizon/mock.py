"""MockHorizonAdapter — fixture-driven payments replay for dev/preview.

Why a mock at all? Stellar Horizon is reachable from prod but blocked
from our preview/CI containers. The Deposit Engine must be testable
end-to-end without external network, so this adapter:

  * Loads a JSON fixture (`tests/fixtures/horizon_payments.json`) at
    boot. Each entry is a Horizon-shaped payment op.
  * Returns pages from the in-memory list ordered by `paging_token`
    (lexicographic — matches Horizon's monotonic 64-bit token).
  * Supports `inject_payment(...)` so tests (and the dev shell) can
    feed new payments at runtime without touching the file.

The cursor handling is identical to real Horizon: pass `""` to start
from the beginning, otherwise items with `paging_token > cursor` are
returned. The last item's paging_token becomes the next cursor.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

from .adapter import HorizonAdapter, HorizonError, Payment, PaymentsPage

logger = logging.getLogger("prosper.horizon.mock")

# Fixture path resolution — env override first, then default location in
# the repo. Tests can point this at any file.
_DEFAULT_FIXTURE = (Path(__file__).resolve().parents[2]
                      / "tests" / "fixtures" / "horizon_payments.json")


def _fixture_path() -> Path:
    raw = os.environ.get("HORIZON_MOCK_FIXTURE")
    return Path(raw) if raw else _DEFAULT_FIXTURE


class MockHorizonAdapter(HorizonAdapter):
    """In-memory Horizon replay. Thread-safe across asyncio tasks."""

    mode = "mock"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payments: list[Payment] = []
        self._load_fixture()

    # -- Fixture loading -------------------------------------------------
    def _load_fixture(self) -> None:
        path = _fixture_path()
        if not path.exists():
            logger.warning("MockHorizonAdapter: fixture not found at %s — "
                              "starting with empty payment stream", path)
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise HorizonError(
                f"MockHorizonAdapter: malformed fixture {path}: {e}") from e
        items = data if isinstance(data, list) else data.get("payments") or []
        for raw in items:
            try:
                self._payments.append(_normalize(raw))
            except Exception as e:  # noqa: BLE001
                logger.warning("MockHorizonAdapter: skipping malformed entry "
                                  "(%s): %r", e, raw)
        # Stable sort by paging_token — same order Horizon would emit.
        self._payments.sort(key=lambda p: p.paging_token)
        logger.info("MockHorizonAdapter: loaded %d payments from %s",
                       len(self._payments), path)

    # -- Test helper -----------------------------------------------------
    def inject_payment(self, raw: dict[str, Any]) -> Payment:
        """Append a payment at runtime (tests, dev shell). Returns the
        normalized record so the caller can assert against it."""
        p = _normalize(raw)
        with self._lock:
            self._payments.append(p)
            self._payments.sort(key=lambda x: x.paging_token)
        return p

    def clear(self) -> None:
        """Drop the in-memory stream. Test-only."""
        with self._lock:
            self._payments.clear()

    # -- HorizonAdapter --------------------------------------------------
    async def fetch_payments(self, *, cursor: str, limit: int = 200
                              ) -> PaymentsPage:
        limit = max(1, min(int(limit or 200), 200))
        with self._lock:
            if not cursor:
                page = list(self._payments[:limit])
            else:
                page = [p for p in self._payments
                          if p.paging_token > cursor][:limit]
        next_cursor = page[-1].paging_token if page else cursor
        return PaymentsPage(payments=page, next_cursor=next_cursor)

    async def health_check(self) -> dict:
        return {"ok": True, "mode": "mock",
                 "fixture": str(_fixture_path()),
                 "payments_loaded": len(self._payments)}


# ---------------------------------------------------------------------------
# Normalization — accepts both Horizon-shaped JSON and a leaner test shape.
# ---------------------------------------------------------------------------
def _normalize(raw: dict[str, Any]) -> Payment:
    """Build a Payment from either:
      * Horizon `payment` op shape (production-like)
      * Lean test shape `{paging_token, tx_hash, to, from, asset_code,
        asset_issuer, amount, memo, memo_type}`
    """
    if not isinstance(raw, dict):
        raise HorizonError(f"payment must be a dict, got {type(raw)}")

    # Horizon's payment op uses `type` to discriminate. We accept
    # `payment` and `path_payment_strict_*`. Anything else is rejected
    # so the fixture stays honest.
    op_type = raw.get("type") or "payment"
    if op_type not in ("payment", "path_payment_strict_send",
                          "path_payment_strict_receive"):
        raise HorizonError(f"unsupported op type: {op_type!r}")

    paging_token = str(raw.get("paging_token") or raw.get("id") or "")
    op_id = str(raw.get("id") or raw.get("op_id") or paging_token)
    tx_hash = str(raw.get("transaction_hash") or raw.get("tx_hash") or "")
    to_addr = str(raw.get("to") or raw.get("to_account") or "")
    from_addr = str(raw.get("from") or raw.get("from_") or raw.get("from_account") or "")
    asset_type = raw.get("asset_type") or ("native" if not raw.get("asset_code") else "")
    if asset_type == "native":
        asset_code = ""
        asset_issuer = ""
    else:
        asset_code = str(raw.get("asset_code") or "")
        asset_issuer = str(raw.get("asset_issuer") or "")
    # path_payment_strict_receive uses asset_received_*, but Horizon
    # surfaces both `asset_*` and `*_amount` on the same op. We pick the
    # destination-side amount when present.
    amount = str(raw.get("amount") or raw.get("to_amount") or "0")
    memo = raw.get("transaction", {}).get("memo") if isinstance(
        raw.get("transaction"), dict) else raw.get("memo")
    memo_type = raw.get("transaction", {}).get("memo_type") if isinstance(
        raw.get("transaction"), dict) else raw.get("memo_type")
    created_at = str(raw.get("created_at") or "")
    successful = bool(raw.get("transaction_successful")
                          if "transaction_successful" in raw
                          else raw.get("successful", True))

    if not (paging_token and tx_hash and to_addr):
        raise HorizonError(
            f"payment missing required keys (paging_token={paging_token!r}, "
            f"tx_hash={tx_hash!r}, to={to_addr!r})")

    return Payment(
        paging_token=paging_token,
        tx_hash=tx_hash,
        op_id=op_id,
        to=to_addr,
        from_=from_addr,
        asset_code=asset_code,
        asset_issuer=asset_issuer,
        amount=amount,
        memo=(str(memo) if memo is not None else None),
        memo_type=(str(memo_type) if memo_type else None),
        created_at=created_at,
        successful=successful,
        raw=raw,
    )


# Test surface for `factory.reset_adapter_cache()` to recreate from disk.
def _new_for_tests(fixture_override: Optional[str] = None) -> "MockHorizonAdapter":
    if fixture_override:
        os.environ["HORIZON_MOCK_FIXTURE"] = fixture_override
    return MockHorizonAdapter()
