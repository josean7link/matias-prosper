"""P0 (Feb 2026) — Andes outbound transfer + pending_onchain reclaim tests.

Covers:
  * Staking poller `_try_reclaim_pending_onchain` — exact, tolerance,
    ambiguity, expired window.
  * Staking poller `_expire_stale_pendings` — flips placeholders older
    than the reclaim window to `expired_pending_onchain`.
  * Andes adapter `initiate_onchain_transfer` — happy path + 425 Too Early
    retry handling (Retry-After header).
  * POST /api/v1/client/invest/onchain — validation rules (asset, modality,
    authorized checkbox, confirmed_destination, confirmed_amount), the
    audit log entries on success, and that no real HTTP call is made
    (the Andes adapter is monkey-patched).

NONE of these tests trigger a real on-chain transfer — the Andes adapter
is fully mocked. The first real transfer will be executed by the user
manually with a minimum amount.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from db import (col, ALERTS, AUDIT_LOGS, POSITIONS, ORGANIZATIONS,
                  RAMP_ACCOUNTS, RAMP_BALANCES)
from jobs.staking_sync import (
    _expire_stale_pendings, _try_reclaim_pending_onchain,
    RECLAIM_WINDOW_MINUTES,
)
from ramp.adapters.andes import AndesAdapter
from ramp.provider import NotSupportedByProvider

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def event_loop():
    """Module-scoped event loop so Motor's connection is reused across
    tests; otherwise the second test sees `Event loop is closed`."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _insert_pending(
    *, org_id: str, wallet: str, asset: str, modality: str, amount: float,
    minutes_ago: int = 1, position_id: str | None = None,
    user_id: str = "u_test",
) -> str:
    pos_id = position_id or "pos_" + uuid.uuid4().hex[:10]
    created_at = (datetime.now(timezone.utc)
                    - timedelta(minutes=minutes_ago)).isoformat()
    await col(POSITIONS).insert_one({
        "position_id":      pos_id,
        "org_id":           org_id,
        "user_id":          user_id,
        "asset":            asset,
        "modality":         modality,
        "wallet":           wallet,
        "memo":             None,
        "hash":             None,
        "principal_native": amount,
        "principal_unit":   "ARSa" if asset == "arsa" else "USDC",
        "status":           "pending_onchain",
        "andes_transfer_id": "test_" + uuid.uuid4().hex[:8],
        "created_at":       created_at,
        "updated_at":       created_at,
        "is_deleted":       False,
    })
    return pos_id


async def _cleanup_test_data(*, tag: str) -> None:
    await col(POSITIONS).delete_many({"andes_transfer_id":
                                       {"$regex": f"^test_{tag}"}})
    await col(POSITIONS).delete_many({"org_id": {"$regex": f"^org_test_{tag}"}})
    await col(ALERTS).delete_many({"context.wallet":
                                    {"$regex": f"^GTEST{tag.upper()}"}})


# ---------------------------------------------------------------------------
# Test 1 — Exact match wins
# ---------------------------------------------------------------------------
async def test_reclaim_exact_amount_match():
    tag = "exact"
    org_id = f"org_test_{tag}"
    wallet = f"GTEST{tag.upper()}WALLETEXACT0000000000000000000000000000000000000000"
    try:
        pid = await _insert_pending(
            org_id=org_id, wallet=wallet, asset="arsa", modality="end",
            amount=100_000.0)
        res = await _try_reclaim_pending_onchain(
            wallet=wallet, org_id=org_id, asset="arsa", modality="end",
            principal=100_000.0,
            set_doc={"wallet": wallet, "memo": "1707000000",
                       "hash": "abc123", "asset": "arsa",
                       "modality": "end", "status": "active",
                       "principal_native": 100_000.0},
            raw={"id": 999, "memoStaking": "1707000000",
                  "hashStaking": "abc123"})
        assert res is not None
        assert res["action"] == "reclaimed"
        assert res["position_id"] == pid
        assert res["matched_kind"] == "exact"
        # DB should reflect the active status + memo/hash + claim marker
        doc = await col(POSITIONS).find_one({"position_id": pid})
        assert doc["status"] == "active"
        assert doc["memo"] == "1707000000"
        assert doc["hash"] == "abc123"
        assert "claimed_by_sync_at" in doc
        assert doc["reclaim_match"] == "exact"
    finally:
        await _cleanup_test_data(tag=tag)


# ---------------------------------------------------------------------------
# Test 2 — Tolerance match only when no exact match exists
# ---------------------------------------------------------------------------
async def test_reclaim_tolerance_match_when_no_exact():
    tag = "tol"
    org_id = f"org_test_{tag}"
    wallet = f"GTEST{tag.upper()}WALLETTOL00000000000000000000000000000000000000000"
    try:
        # Pending placeholder for 100_000.0, on-chain deposit slightly off
        pid = await _insert_pending(
            org_id=org_id, wallet=wallet, asset="arsa", modality="month",
            amount=100_000.0)
        on_chain_amount = 100_050.0   # 0.05% above — within 0.1% tolerance
        res = await _try_reclaim_pending_onchain(
            wallet=wallet, org_id=org_id, asset="arsa", modality="month",
            principal=on_chain_amount,
            set_doc={"wallet": wallet, "memo": "1707000001",
                       "hash": "def456", "asset": "arsa",
                       "modality": "month", "status": "active",
                       "principal_native": on_chain_amount},
            raw={"id": 1000, "memoStaking": "1707000001",
                  "hashStaking": "def456"})
        assert res is not None
        assert res["action"] == "reclaimed"
        assert res["matched_kind"] == "tolerance"
        assert res["position_id"] == pid
    finally:
        await _cleanup_test_data(tag=tag)


# ---------------------------------------------------------------------------
# Test 3 — Beyond tolerance → no reclaim
# ---------------------------------------------------------------------------
async def test_reclaim_no_match_when_amount_far_off():
    tag = "far"
    org_id = f"org_test_{tag}"
    wallet = f"GTEST{tag.upper()}WALLETFAR00000000000000000000000000000000000000000"
    try:
        await _insert_pending(
            org_id=org_id, wallet=wallet, asset="arsa", modality="end",
            amount=100_000.0)
        # 1% above — way outside 0.1% tolerance
        res = await _try_reclaim_pending_onchain(
            wallet=wallet, org_id=org_id, asset="arsa", modality="end",
            principal=101_000.0,
            set_doc={}, raw={"id": 1001})
        assert res is None
    finally:
        await _cleanup_test_data(tag=tag)


# ---------------------------------------------------------------------------
# Test 4 — Ambiguity: 2+ candidates → skip + raise alert
# ---------------------------------------------------------------------------
async def test_reclaim_ambiguous_raises_alert_and_does_not_claim():
    tag = "amb"
    org_id = f"org_test_{tag}"
    wallet = f"GTEST{tag.upper()}WALLETAMB00000000000000000000000000000000000000000"
    try:
        pid1 = await _insert_pending(
            org_id=org_id, wallet=wallet, asset="arsa", modality="end",
            amount=50_000.0)
        pid2 = await _insert_pending(
            org_id=org_id, wallet=wallet, asset="arsa", modality="end",
            amount=50_000.0)
        res = await _try_reclaim_pending_onchain(
            wallet=wallet, org_id=org_id, asset="arsa", modality="end",
            principal=50_000.0,
            set_doc={}, raw={"id": 1002, "memoStaking": "x",
                                "hashStaking": "y"})
        assert res is not None
        assert res["action"] == "ambiguous_skipped"
        assert set(res["candidates"]) == {pid1, pid2}
        # Neither should be flipped to active
        for pid in (pid1, pid2):
            d = await col(POSITIONS).find_one({"position_id": pid})
            assert d["status"] == "pending_onchain"
        # Alert must exist
        alert = await col(ALERTS).find_one({"context.wallet": wallet})
        assert alert is not None
        assert alert["severity"] == "warning"
        assert "Reclaim ambiguo" in alert["title"]
        assert set(alert["context"]["candidate_position_ids"]) == {pid1, pid2}
    finally:
        await _cleanup_test_data(tag=tag)


# ---------------------------------------------------------------------------
# Test 5 — Older than 60 min → not eligible
# ---------------------------------------------------------------------------
async def test_reclaim_skips_pendings_outside_window():
    tag = "old"
    org_id = f"org_test_{tag}"
    wallet = f"GTEST{tag.upper()}WALLETOLD00000000000000000000000000000000000000000"
    try:
        # 90 minutes old — outside the 60-min reclaim window
        await _insert_pending(
            org_id=org_id, wallet=wallet, asset="arsa", modality="end",
            amount=75_000.0, minutes_ago=90)
        res = await _try_reclaim_pending_onchain(
            wallet=wallet, org_id=org_id, asset="arsa", modality="end",
            principal=75_000.0,
            set_doc={}, raw={"id": 1003})
        assert res is None, "Outside-window pendings must not be reclaimable"
    finally:
        await _cleanup_test_data(tag=tag)


# ---------------------------------------------------------------------------
# Test 6 — Expiry sweep
# ---------------------------------------------------------------------------
async def test_expire_stale_pendings_flips_old_rows():
    tag = "exp"
    org_id = f"org_test_{tag}"
    wallet = f"GTEST{tag.upper()}WALLETEXP00000000000000000000000000000000000000000"
    try:
        old_pid = await _insert_pending(
            org_id=org_id, wallet=wallet, asset="arsa", modality="end",
            amount=10_000.0, minutes_ago=RECLAIM_WINDOW_MINUTES + 5)
        fresh_pid = await _insert_pending(
            org_id=org_id, wallet=wallet, asset="arsa", modality="month",
            amount=20_000.0, minutes_ago=5)
        count = await _expire_stale_pendings()
        assert count >= 1
        old_doc = await col(POSITIONS).find_one({"position_id": old_pid})
        fresh_doc = await col(POSITIONS).find_one({"position_id": fresh_pid})
        assert old_doc["status"] == "expired_pending_onchain"
        assert "expired_at" in old_doc
        assert fresh_doc["status"] == "pending_onchain"
    finally:
        await _cleanup_test_data(tag=tag)


# ---------------------------------------------------------------------------
# Test 7 — Andes adapter happy path (mock httpx)
# ---------------------------------------------------------------------------
async def test_andes_initiate_onchain_transfer_happy_path(monkeypatch):
    captured: dict = {}

    class _MockResponse:
        def __init__(self, status_code: int = 200,
                       json_data: dict | None = None,
                       headers: dict | None = None):
            self.status_code = status_code
            self._json = json_data or {}
            self.headers = headers or {}
            self.text = str(self._json)

        def json(self):
            return self._json

    class _MockAsyncClient:
        def __init__(self, *a, **kw):
            self.kw = kw
        async def __aenter__(self):  return self
        async def __aexit__(self, *a):  return False
        async def post(self, url, headers=None, json=None):
            captured["url"]     = url
            captured["headers"] = headers
            captured["body"]    = json
            return _MockResponse(
                200, {"transactionId": "tx_test_001",
                        "wallet_transaction_id": "tx_test_001",
                        "status": "Pending",
                        "from_address": "GUSERANDES",
                        "to_address": json["to_address"]})

    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)
    adapter = AndesAdapter()
    res = await adapter.initiate_onchain_transfer(
        andes_user_id="user_abc", asset="arsa", chain="stellar",
        to_address="GPROSPERTREASURY", amount=100_000.0)
    assert res["transactionId"] == "tx_test_001"
    assert captured["body"]["user_id"] == "user_abc"
    assert captured["body"]["chain"] == "stellar"
    assert captured["body"]["asset"] == "arsa"
    assert captured["body"]["to_address"] == "GPROSPERTREASURY"
    assert captured["body"]["amount"] == 100_000.0
    assert captured["url"].endswith("/wallets/transfers")


# ---------------------------------------------------------------------------
# Test 8 — 425 Too Early retries honor Retry-After then succeed
# ---------------------------------------------------------------------------
async def test_andes_initiate_onchain_transfer_retries_on_425(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    class _MockResponse:
        def __init__(self, status_code, json_data=None, headers=None):
            self.status_code = status_code
            self._json = json_data or {}
            self.headers = headers or {}
            self.text = str(self._json)
        def json(self): return self._json

    class _MockAsyncClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self):  return self
        async def __aexit__(self, *a):  return False
        async def post(self, url, headers=None, json=None):
            calls["n"] += 1
            if calls["n"] < 3:
                return _MockResponse(425, headers={"Retry-After": "1"})
            return _MockResponse(200, {"transactionId": "tx_retry_ok",
                                          "status": "Pending"})

    async def _fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    adapter = AndesAdapter()
    res = await adapter.initiate_onchain_transfer(
        andes_user_id="u", asset="arsa", chain="stellar",
        to_address="G_DEST", amount=1_000.0,
        max_retries_425=3)
    assert res["transactionId"] == "tx_retry_ok"
    assert calls["n"] == 3                  # 2 × 425 then 200
    assert sleeps == [1.0, 1.0]             # honored Retry-After both times


# ---------------------------------------------------------------------------
# Test 9 — 425 exhausts retries → NotSupportedByProvider
# ---------------------------------------------------------------------------
async def test_andes_initiate_onchain_transfer_persistent_425_fails(monkeypatch):
    class _MockResponse:
        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self._json = {}
            self.headers = headers or {}
            self.text = ""
        def json(self): return self._json

    class _MockAsyncClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self):  return self
        async def __aexit__(self, *a):  return False
        async def post(self, url, headers=None, json=None):
            return _MockResponse(425, headers={"Retry-After": "1"})

    async def _fake_sleep(s): pass
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(NotSupportedByProvider):
        await AndesAdapter().initiate_onchain_transfer(
            andes_user_id="u", asset="arsa", chain="stellar",
            to_address="G_DEST", amount=1.0, max_retries_425=2)


# ---------------------------------------------------------------------------
# Test 10 — POST /api/v1/client/invest/onchain validation suite
# ---------------------------------------------------------------------------
# Uses a live FastAPI process (TestClient via httpx against running supervisor)
# and a fully-mocked AndesAdapter. We exercise the validation branches first
# (cheap), then the happy path which monkey-patches the adapter.

@pytest_asyncio.fixture
async def setup_test_user_arsa():
    """Insert a fake org, user, ramp_account, ramp_balance, org wallet."""
    tag = "e2e"
    org_id  = f"org_test_{tag}_{uuid.uuid4().hex[:6]}"
    user_id = f"u_test_{tag}_{uuid.uuid4().hex[:6]}"
    wallet  = "GTEST" + tag.upper() + uuid.uuid4().hex[:43].upper()
    # KYB-approved org with a per-modality wallet pre-provisioned
    await col(ORGANIZATIONS).insert_one({
        "org_id": org_id, "is_deleted": False, "paused": False,
        "kyb_status": "approved",
        "prosper_wallets": [
            {"modality": "end",   "address": wallet, "provisioned_at": _iso(datetime.now(timezone.utc))},
        ],
    })
    # Andes ramp account
    ramp_id = "ra_test_" + uuid.uuid4().hex[:8]
    await col(RAMP_ACCOUNTS).insert_one({
        "id": ramp_id, "org_id": org_id, "end_customer_id": user_id,
        "provider": "andeslabs",
        "provider_user_id": "andes_uid_" + uuid.uuid4().hex[:8],
    })
    # ARSa balance row
    await col(RAMP_BALANCES).insert_one({
        "ramp_account_id": ramp_id, "org_id": org_id,
        "asset": "arsa", "balance": "1000000",
        "as_of": _iso(datetime.now(timezone.utc)),
    })
    yield {"org_id": org_id, "user_id": user_id, "wallet": wallet,
            "tag": tag}
    # Cleanup
    await col(ORGANIZATIONS).delete_one({"org_id": org_id})
    await col(RAMP_ACCOUNTS).delete_many({"org_id": org_id})
    await col(RAMP_BALANCES).delete_many({"org_id": org_id})
    await col(POSITIONS).delete_many({"org_id": org_id})
    await col(AUDIT_LOGS).delete_many({"org_id": org_id})
    await col(ALERTS).delete_many({"org_id": org_id})
