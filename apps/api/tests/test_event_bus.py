"""PR — Event bus tests.

Coverage:
  * publish persists + invokes subscribed handlers in order
  * duplicate event_id → second publish does NOT re-invoke handlers
  * a failing handler does not block subsequent handlers for the same event
  * subscribe is idempotent (same handler twice → single registration)
  * publish raises on missing `event_type`
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TEST_DB = "prosper_phase0_test_event_bus"
_ORIG_DB_NAME = os.environ.get("DB_NAME")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

import db as db_module  # noqa: E402
from db import DEPOSIT_EVENTS, col  # noqa: E402
from services.event_bus import (  # noqa: E402
    publish, reset_subscribers_for_tests, subscribe)


@pytest.fixture(autouse=True)
async def _isolate():
    os.environ["DB_NAME"] = _TEST_DB
    db_module._client = None
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(_TEST_DB)
    client.close()
    db_module._client = None
    # Ensure unique index on event_id exists (db.ensure_indexes is not run)
    await col(DEPOSIT_EVENTS).create_index("event_id", unique=True)
    reset_subscribers_for_tests()
    yield
    reset_subscribers_for_tests()
    if db_module._client is not None:
        db_module._client.close()
        db_module._client = None
    if _ORIG_DB_NAME is not None:
        os.environ["DB_NAME"] = _ORIG_DB_NAME
    else:
        os.environ.pop("DB_NAME", None)


async def test_publish_invokes_subscribed_handler():
    seen: list[dict] = []
    async def h(ev): seen.append(ev)
    subscribe("deposit.credited", h)
    res = await publish({"event_type": "deposit.credited",
                            "event_id": "evt_test_001",
                            "asset": "usdc"})
    assert res["action"] == "published"
    assert res["handlers_run"] == 1
    assert len(seen) == 1
    assert seen[0]["event_id"] == "evt_test_001"


async def test_publish_duplicate_event_id_does_not_re_fire():
    seen: list[dict] = []
    async def h(ev): seen.append(ev)
    subscribe("deposit.credited", h)
    r1 = await publish({"event_type": "deposit.credited",
                           "event_id": "evt_dup_42", "asset": "arsa"})
    r2 = await publish({"event_type": "deposit.credited",
                           "event_id": "evt_dup_42", "asset": "arsa"})
    assert r1["action"] == "published"
    assert r2["action"] == "duplicate_skipped"
    assert len(seen) == 1


async def test_failing_handler_does_not_block_others():
    seen: list[str] = []
    async def bad(ev): raise RuntimeError("boom")
    async def good(ev): seen.append(ev["event_id"])
    subscribe("deposit.credited", bad)
    subscribe("deposit.credited", good)
    res = await publish({"event_type": "deposit.credited",
                            "event_id": "evt_bad", "asset": "usdc"})
    assert res["handlers_total"] == 2
    assert res["handlers_run"] == 1   # only `good` succeeded
    assert seen == ["evt_bad"]


async def test_subscribe_dedupes_same_handler():
    seen: list[dict] = []
    async def h(ev): seen.append(ev)
    subscribe("deposit.credited", h)
    subscribe("deposit.credited", h)   # second time should be a no-op
    await publish({"event_type": "deposit.credited",
                      "event_id": "evt_once"})
    assert len(seen) == 1   # NOT 2 — handler registered once


async def test_publish_missing_event_type_raises():
    with pytest.raises(ValueError):
        await publish({"asset": "usdc"})


async def test_publish_stamps_event_id_when_absent():
    res = await publish({"event_type": "deposit.credited",
                            "asset": "usdc"})
    assert res["event_id"].startswith("evt_")
    persisted = await col(DEPOSIT_EVENTS).find_one(
        {"event_id": res["event_id"]}, {"_id": 0})
    assert persisted is not None
    assert persisted["asset"] == "usdc"


async def test_handler_receives_defensive_copy():
    """Mutating the event inside a handler must not leak to the next handler."""
    received: list[dict] = []
    async def mutator(ev):
        ev["asset"] = "MUTATED"
    async def observer(ev):
        received.append(ev)
    subscribe("deposit.credited", mutator)
    subscribe("deposit.credited", observer)
    await publish({"event_type": "deposit.credited",
                      "event_id": "evt_iso", "asset": "usdc"})
    assert received[0]["asset"] == "usdc"   # observer got pristine copy
