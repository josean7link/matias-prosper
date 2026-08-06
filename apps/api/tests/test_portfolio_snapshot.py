"""Phase 04 — Portfolio snapshot tests.

Coverage:
  * Scope by user/org — A doesn't see B's data.
  * Cache hit/miss via Redis (TTL 12s).
  * `last_movement_cursor` advances on new movements.
  * pending_detected separated per asset (rail separation).
  * **CRITICAL** — pending_detected → Success transition: no double-count
    and no limbo.
  * Rails separated in response: ARSa never appears in USDC dict.
  * Horizon call is cached (1 fetch covers N requests in TTL).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TEST_DB = "prosper_phase0_test_portfolio_snapshot"
_ORIG_DB_NAME = os.environ.get("DB_NAME")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

import db as db_module  # noqa: E402
from db import (ORGANIZATIONS, RAMP_ACCOUNTS, RAMP_BALANCES,  # noqa: E402
                    RAMP_MOVEMENTS, USERS, col)
from services.portfolio_snapshot import (CACHE_TTL_SECONDS,  # noqa: E402
                                              build_snapshot, get_or_build,
                                              invalidate)

ORG_A = "org_snap_a"
ORG_B = "org_snap_b"
USR_A = "usr_snap_a"
USR_B = "usr_snap_b"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeUser:
    """A minimal CurrentUser stand-in for the service layer."""
    def __init__(self, user_id: str, org_id: str):
        self.user_id = user_id
        self.org_id  = org_id


class _FakeRedis:
    """In-memory Redis impl supporting just the methods used by the service."""
    def __init__(self):
        self.store: dict[str, tuple[float, str]] = {}   # key → (expires_at, value)

    async def get(self, k):
        v = self.store.get(k)
        if not v:
            return None
        expires_at, val = v
        if time.time() > expires_at:
            del self.store[k]
            return None
        return val

    async def setex(self, k, ttl, v):
        self.store[k] = (time.time() + ttl, v)

    async def delete(self, k):
        self.store.pop(k, None)


@pytest.fixture(autouse=True)
async def _isolate(monkeypatch):
    os.environ["DB_NAME"] = _TEST_DB
    db_module._client = None

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(_TEST_DB)
    client.close()
    db_module._client = None

    # Seed orgs + users
    await col(ORGANIZATIONS).insert_many([
        {"org_id": ORG_A, "type": "business", "is_deleted": False},
        {"org_id": ORG_B, "type": "business", "is_deleted": False},
    ])
    await col(USERS).insert_many([
        {"user_id": USR_A, "org_id": ORG_A, "role": "client_admin",
          "email": "a@x.test", "is_deleted": False},
        {"user_id": USR_B, "org_id": ORG_B, "role": "client_admin",
          "email": "b@x.test", "is_deleted": False},
    ])

    # ramp_balances: ARSa 50000 in org A.
    await col(RAMP_BALANCES).insert_one({
        "org_id": ORG_A, "asset": "arsa", "balance": 50000.0,
        "as_of": _now()})

    # Fake Redis client used by the snapshot service.
    fake_redis = _FakeRedis()

    async def _fake_redis_client():
        return fake_redis

    monkeypatch.setattr(
        "services.portfolio_snapshot._redis_client", _fake_redis_client)

    # Fake Prosper adapter — controllable USDC balance.
    class _FakeAdapter:
        usdc_balance = 0.0
        call_count = 0
        async def get_user_balances(self, org_id):
            _FakeAdapter.call_count += 1
            class _Bal:
                balance_prosper = _FakeAdapter.usdc_balance
            return _Bal()
    fake_adapter = _FakeAdapter()
    monkeypatch.setattr(
        "services.portfolio_snapshot.get_prosper_adapter",
        lambda: fake_adapter)

    # Attach to the fixture so tests can mutate
    yield {"redis": fake_redis, "adapter": _FakeAdapter}

    if db_module._client is not None:
        db_module._client.close()
        db_module._client = None
    if _ORIG_DB_NAME is not None:
        os.environ["DB_NAME"] = _ORIG_DB_NAME
    else:
        os.environ.pop("DB_NAME", None)


# ---------------------------------------------------------------------------
# Basic snapshot shape + scope
# ---------------------------------------------------------------------------
async def test_snapshot_returns_expected_shape(_isolate):
    snap = await build_snapshot(_FakeUser(USR_A, ORG_A))
    assert set(snap["balances"].keys()) == {"arsa", "usdc"}
    for asset in ("arsa", "usdc"):
        b = snap["balances"][asset]
        assert "total" in b and "pending_detected" in b and "as_of" in b
    assert "recent_movements" in snap
    assert "last_movement_cursor" in snap
    assert "fetched_at" in snap


async def test_scope_by_org_user_a_does_not_see_b(_isolate):
    # Plant a movement on org B and assert org A doesn't see it.
    await col(RAMP_MOVEMENTS).insert_one({
        "id": "mov_b", "org_id": ORG_B, "kind": "deposit", "asset": "arsa",
        "status": "Success", "amount": "999",
        "created_at": _now()})
    snap_a = await build_snapshot(_FakeUser(USR_A, ORG_A))
    assert snap_a["recent_movements"] == []


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------
async def test_cache_hit_within_ttl(_isolate):
    s1 = await get_or_build(_FakeUser(USR_A, ORG_A))
    assert s1["snapshot_source"] == "fresh"
    s2 = await get_or_build(_FakeUser(USR_A, ORG_A))
    assert s2["snapshot_source"] == "cache"
    # The Horizon adapter should have been called exactly ONCE.
    assert _isolate["adapter"].call_count == 1


async def test_cache_miss_after_invalidate(_isolate):
    await get_or_build(_FakeUser(USR_A, ORG_A))
    await invalidate(USR_A)
    s2 = await get_or_build(_FakeUser(USR_A, ORG_A))
    assert s2["snapshot_source"] == "fresh"
    assert _isolate["adapter"].call_count == 2


async def test_cache_is_per_user(_isolate):
    """User A's cache entry MUST NOT serve user B's request."""
    await get_or_build(_FakeUser(USR_A, ORG_A))
    sb = await get_or_build(_FakeUser(USR_B, ORG_B))
    assert sb["snapshot_source"] == "fresh"   # B got fresh, not A's cache
    # Two distinct cache keys
    assert len(_isolate["redis"].store) == 2


# ---------------------------------------------------------------------------
# Recent movements + cursor
# ---------------------------------------------------------------------------
async def test_recent_movements_and_cursor_advance(_isolate):
    await col(RAMP_MOVEMENTS).insert_one({
        "id": "mov_old", "org_id": ORG_A, "kind": "deposit",
        "asset": "arsa", "status": "Success", "amount": "100",
        "created_at": "2026-01-01T00:00:00+00:00"})
    s1 = await build_snapshot(_FakeUser(USR_A, ORG_A))
    cur1 = s1["last_movement_cursor"]
    assert cur1 == "2026-01-01T00:00:00+00:00"

    # Insert a newer movement.
    await col(RAMP_MOVEMENTS).insert_one({
        "id": "mov_new", "org_id": ORG_A, "kind": "deposit",
        "asset": "arsa", "status": "Success", "amount": "200",
        "created_at": "2026-02-01T00:00:00+00:00"})
    s2 = await build_snapshot(_FakeUser(USR_A, ORG_A))
    assert s2["last_movement_cursor"] == "2026-02-01T00:00:00+00:00"
    assert s2["last_movement_cursor"] > cur1


# ---------------------------------------------------------------------------
# pending_detected — rails separated, NOT summed into operable balance
# ---------------------------------------------------------------------------
async def test_pending_detected_per_asset_rails_separated(_isolate):
    await col(RAMP_MOVEMENTS).insert_many([
        {"id": "p1", "org_id": ORG_A, "kind": "deposit", "asset": "usdc",
          "status": "pending_detected", "amount": "30.0000000",
          "created_at": _now()},
        {"id": "p2", "org_id": ORG_A, "kind": "deposit", "asset": "usdc",
          "status": "pending_detected", "amount": "20.0000000",
          "created_at": _now()},
    ])
    snap = await build_snapshot(_FakeUser(USR_A, ORG_A))
    assert snap["balances"]["usdc"]["pending_detected"] == 50.0
    # ARSa untouched.
    assert snap["balances"]["arsa"]["pending_detected"] == 0.0


# ---------------------------------------------------------------------------
# THE CRITICAL SEAM TEST — pending_detected → Success transition
# ---------------------------------------------------------------------------
async def test_pending_to_success_transition_no_double_count_no_limbo(_isolate):
    """The user's mainnet-critical seam: a deposit must show up in
    EXACTLY ONE place at all times.

      Scenario 1 (deposit lands, engine has not yet reconciled):
        horizon_usdc = 100   (the watcher saw it because Horizon shows it)
        ramp_movements.pending_detected = 100
        → balance.usdc.stellar = max(0, 100-100) = 0  (NOT operable yet)
        → balance.usdc.pending_detected = 100         (in transit card)

      Scenario 2 (engine reconciles to Success, USDC still in wallet):
        horizon_usdc = 100
        ramp_movements.pending_detected = 0  (flipped to Success)
        → balance.usdc.stellar = 100  (now operable)
        → balance.usdc.pending_detected = 0

      Scenario 3 (engine reconciles AND staking moved USDC into the
      contract — concurrent path):
        horizon_usdc = 0
        ramp_movements.pending_detected = 0
        → balance.usdc.stellar = 0, pending_detected = 0
        (the principal lives in `positions`, not in balances)

    All three are exercised here in sequence — the same deposit
    transitioning through every state.
    """
    _isolate["adapter"].usdc_balance = 100.0   # Horizon sees the deposit
    await col(RAMP_MOVEMENTS).insert_one({
        "id": "mov_seam", "org_id": ORG_A, "kind": "deposit",
        "asset": "usdc", "status": "pending_detected",
        "external_id": "a" * 64, "amount": "100.0000000",
        "created_at": _now()})

    # --- Scenario 1 ---
    s1 = await build_snapshot(_FakeUser(USR_A, ORG_A))
    assert s1["balances"]["usdc"]["stellar"]          == 0.0,   "double-count!"
    assert s1["balances"]["usdc"]["pending_detected"] == 100.0
    assert s1["balances"]["usdc"]["total"]            == 0.0
    sum_visible_1 = (s1["balances"]["usdc"]["stellar"]
                       + s1["balances"]["usdc"]["pending_detected"])
    assert sum_visible_1 == 100.0   # entire deposit visible exactly once

    # --- Scenario 2: engine reconciles, USDC remains in wallet ---
    await col(RAMP_MOVEMENTS).update_one(
        {"id": "mov_seam"},
        {"$set": {"status": "Success",
                     "reconciled_position_id": "pos_seam_001",
                     "reconciled_at": _now()}})
    s2 = await build_snapshot(_FakeUser(USR_A, ORG_A))
    assert s2["balances"]["usdc"]["stellar"]          == 100.0
    assert s2["balances"]["usdc"]["pending_detected"] == 0.0
    sum_visible_2 = (s2["balances"]["usdc"]["stellar"]
                       + s2["balances"]["usdc"]["pending_detected"])
    assert sum_visible_2 == 100.0   # again — visible exactly once

    # --- Scenario 3: USDC moved out of wallet into contract ---
    _isolate["adapter"].usdc_balance = 0.0
    s3 = await build_snapshot(_FakeUser(USR_A, ORG_A))
    assert s3["balances"]["usdc"]["stellar"]          == 0.0
    assert s3["balances"]["usdc"]["pending_detected"] == 0.0
    # Now the principal is in `positions` — out of scope for snapshot
    # but tracked by /dashboard-summary AUM lane. NO LIMBO: the snapshot
    # honestly reports zero in transit + zero in wallet.


async def test_pending_subtraction_floors_at_zero(_isolate):
    """If Horizon reports less than `pending_detected` (e.g. Horizon
    lagging the watcher), `stellar` MUST NOT go negative."""
    _isolate["adapter"].usdc_balance = 5.0
    await col(RAMP_MOVEMENTS).insert_one({
        "id": "lag", "org_id": ORG_A, "kind": "deposit", "asset": "usdc",
        "status": "pending_detected", "amount": "10.0000000",
        "created_at": _now()})
    snap = await build_snapshot(_FakeUser(USR_A, ORG_A))
    assert snap["balances"]["usdc"]["stellar"] == 0.0  # NOT -5


# ---------------------------------------------------------------------------
# Rails separated in response: an ARSa balance NEVER bleeds into USDC.
# ---------------------------------------------------------------------------
async def test_arsa_never_appears_in_usdc_dict(_isolate):
    snap = await build_snapshot(_FakeUser(USR_A, ORG_A))
    # ARSa CVU is 50000 (seeded), USDC is zero.
    assert snap["balances"]["arsa"]["total"] == 50000.0
    assert snap["balances"]["usdc"]["total"] == 0.0
    # The keys for each rail are non-overlapping in semantics; we check
    # that the rail-typed fields are sane.
    assert "cvu" in snap["balances"]["arsa"]
    assert "platform" in snap["balances"]["usdc"]


# ---------------------------------------------------------------------------
# Horizon adapter NOT called when cache hot
# ---------------------------------------------------------------------------
async def test_repeated_polls_within_ttl_do_not_hit_horizon(_isolate):
    for _ in range(5):
        await get_or_build(_FakeUser(USR_A, ORG_A))
    assert _isolate["adapter"].call_count == 1   # one fresh build, then cache
