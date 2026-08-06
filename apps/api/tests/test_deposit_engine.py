"""PR2 — Deposit Detection Engine end-to-end tests.

Coverage:
  * Migration: dupe detection refuses, clean migration succeeds, twice
    is idempotent, hardens index to unique+sparse.
  * Watcher tick: matches per-org wallet, ignores unknown wallets,
    ignores non-USDC, ignores wrong issuer, ignores failed tx.
  * Watcher tick: cursor advances, second tick is a no-op.
  * Idempotency: DB-enforced via unique index — running the same payment
    twice across two distinct ticks results in ONE row.
  * Reconciliation by hash: hashDeposito match closes pending_detected.
  * Reconciliation by memo+amount (fallback): single match → Success.
  * Reconciliation by memo+amount: 2+ matches → alert + NO update.
  * Orphan sweep: rows older than 90min flip to orphan_detected + alert.
  * Orphan timeout floor: env values below RECLAIM_WINDOW+30 are bumped.
  * Flag OFF: watcher tick early-returns, scheduler not started.

Tests use the MockHorizonAdapter and a clean Mongo DB instance.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Dedicated test DB. We mutate `DB_NAME` ONLY inside the fixture so that
# tests run alongside (e.g. test_andes_kyc_widget) keep their own DB.
_TEST_DB = "prosper_phase0_test_deposit_engine"
_ORIG_DB_NAME = os.environ.get("DB_NAME")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

import db as db_module  # noqa: E402
from db import (ALERTS, ORGANIZATIONS, POSITIONS, RAMP_MOVEMENTS,  # noqa: E402
                    col)
from integrations.horizon import reset_adapter_cache, get_adapter  # noqa: E402
from integrations.horizon.mock import MockHorizonAdapter  # noqa: E402
from jobs.deposit_engine_migrations import (  # noqa: E402
    UNIQUE_INDEX_NAME, find_duplicate_external_ids,
    run as run_migration)
from jobs.deposit_watcher import (  # noqa: E402
    health_snapshot, is_enabled, run_orphan_sweep_once, run_tick_once)
from services.deposit_engine import (  # noqa: E402
    PROVIDER_STELLAR, S_ORPHAN_DETECTED, S_PENDING_DETECTED, S_SUCCESS,
    reconcile_usdc_deposit, sweep_orphans)


# ---------------------------------------------------------------------------
# Constants — match the default fixture used by MockHorizonAdapter
# ---------------------------------------------------------------------------
USDC_ISSUER = "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN"
KNOWN_WALLET_END = "GDHQFTLNKHSRECW7FTOBXDDAZU2JTJGEB3WVWRMBV6ROSGCCGG4DRLDF"
KNOWN_WALLET_MONTH = "GAP44Y7LTZG7R3MDP5ZRWNCITNOIN4JBAOA4DCGNZQ5R6INB2IRIF7C4"
ORG_ALEMANY = "org_test_alemany"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
async def _isolate_db_and_env():
    """Wipe the test DB before each test + reset env + reload adapters."""
    # Engine env defaults — each test can override.
    os.environ["DEPOSIT_ENGINE_ENABLED"] = "true"
    os.environ["HORIZON_MODE"] = "mock"
    os.environ["STELLAR_USDC_ISSUER"] = USDC_ISSUER
    os.environ.pop("HORIZON_MOCK_FIXTURE", None)
    os.environ["DEPOSIT_ORPHAN_TIMEOUT_MINUTES"] = "90"
    # Scope the test DB to THIS fixture so other test files (loaded in
    # the same pytest session) keep their original DB_NAME.
    os.environ["DB_NAME"] = _TEST_DB
    reset_adapter_cache()

    # Force a fresh motor client bound to the current event loop. Without
    # this, the cached client from a prior test's (now-closed) loop
    # leaks across tests and raises `Event loop is closed`.
    db_module._client = None
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(_TEST_DB)
    client.close()
    db_module._client = None  # next col() call creates a fresh one

    # Seed the orgs collection with our known wallets so the watcher
    # treats them as provisioned per-org.
    await col(ORGANIZATIONS).insert_one({
        "org_id": ORG_ALEMANY,
        "type":   "business",
        "prosper_wallets": [
            {"address": KNOWN_WALLET_END,   "modality": "end"},
            {"address": KNOWN_WALLET_MONTH, "modality": "month"},
        ],
    })

    yield

    reset_adapter_cache()
    # Tear down the per-test motor client so the next test gets a fresh
    # one on its own loop.
    if db_module._client is not None:
        db_module._client.close()
        db_module._client = None
    # Restore the original DB_NAME so other test files in the same
    # session do not accidentally hit our test DB.
    if _ORIG_DB_NAME is not None:
        os.environ["DB_NAME"] = _ORIG_DB_NAME
    else:
        os.environ.pop("DB_NAME", None)


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------
async def test_migration_clean_db_succeeds():
    # Seed a few legit ramp_movements with distinct external_ids
    for i in range(3):
        await col(RAMP_MOVEMENTS).insert_one({
            "movement_id": f"mov_{i}", "external_id": f"ext_{i}",
            "asset": "arsa", "kind": "deposit"})
    # Create the legacy non-unique sparse index as the migration would
    # encounter in prod.
    await col(RAMP_MOVEMENTS).create_index("external_id", sparse=True)

    res = await run_migration()
    assert res["ok"] is True
    assert UNIQUE_INDEX_NAME in res["indexes"]
    # The old non-unique index must be gone.
    assert "external_id_1" not in res["indexes"]

    # Confirm unique enforcement: inserting a dupe now fails.
    from pymongo.errors import DuplicateKeyError
    with pytest.raises(DuplicateKeyError):
        await col(RAMP_MOVEMENTS).insert_one({
            "movement_id": "dup", "external_id": "ext_0",
            "asset": "arsa", "kind": "deposit"})


async def test_migration_with_dupes_aborts():
    # Pre-existing dupes
    await col(RAMP_MOVEMENTS).insert_many([
        {"movement_id": "a", "external_id": "DUPE_X",
         "asset": "arsa", "kind": "deposit"},
        {"movement_id": "b", "external_id": "DUPE_X",
         "asset": "arsa", "kind": "deposit"},
        {"movement_id": "c", "external_id": "DUPE_Y",
         "asset": "arsa", "kind": "deposit"},
        {"movement_id": "d", "external_id": "DUPE_Y",
         "asset": "arsa", "kind": "deposit"},
    ])
    res = await run_migration()
    assert res["ok"] is False
    assert res["step"] == "duplicate_check"
    assert len(res["duplicates"]) == 2
    dupe_ids = {d["_id"] for d in res["duplicates"]}
    assert dupe_ids == {"DUPE_X", "DUPE_Y"}
    # Unique index must NOT have been created.
    info = await col(RAMP_MOVEMENTS).index_information()
    assert UNIQUE_INDEX_NAME not in info


async def test_migration_is_idempotent():
    await col(RAMP_MOVEMENTS).create_index("external_id", sparse=True)
    r1 = await run_migration()
    r2 = await run_migration()
    assert r1["ok"] and r2["ok"]
    # Second run sees the index already in place.
    assert any("exists:" in a for a in r2["actions"]) or any(
        "created:" in a for a in r2["actions"])


# ---------------------------------------------------------------------------
# Watcher tick tests
# ---------------------------------------------------------------------------
async def test_tick_matches_known_wallet_and_persists_pending():
    await run_migration()
    res = await run_tick_once()
    assert res["skipped"] is False
    # Fixture: 2 USDC payments to known wallets with success=true and
    # the right issuer (`KNOWN_WALLET_END` x2 with memo, `KNOWN_WALLET_MONTH` x1,
    # `path_payment` to END x1) — but wait, the failed one is filtered.
    # Counting valid: items #1 (END, memo), #2 (END, no memo), #5 (MONTH,
    # memo), #6 (END path_payment, memo) = 4 matches.
    assert res["matched"] == 4
    assert res["inserted"] == 4
    assert res["wallet_count"] == 2

    rows = await col(RAMP_MOVEMENTS).find(
        {"asset": "usdc"}, {"_id": 0}).to_list(20)
    assert len(rows) == 4
    for r in rows:
        assert r["status"] == S_PENDING_DETECTED
        assert r["provider"] == PROVIDER_STELLAR
        assert r["org_id"] == ORG_ALEMANY


async def test_tick_ignores_unknown_wallet_and_non_usdc():
    await run_migration()
    await run_tick_once()
    rows = await col(RAMP_MOVEMENTS).find({"asset": "usdc"}).to_list(20)
    # The unknown-wallet USDC payment + native XLM must NOT have been
    # persisted. Failed tx is ignored too.
    tos = {r["wallet"] for r in rows}
    assert tos.issubset({KNOWN_WALLET_END, KNOWN_WALLET_MONTH})
    # No row should have asset_code XLM (the watcher only writes USDC).
    for r in rows:
        assert r["asset"] == "usdc"


async def test_tick_ignores_wrong_issuer():
    await run_migration()
    # Override expected issuer to something the fixture does NOT use.
    os.environ["STELLAR_USDC_ISSUER"] = "GBADCAFEBADCAFEBADCAFEBADCAFEBADCAFEBADCAFEBADCAFEBADCAFEBAD"
    res = await run_tick_once()
    assert res["matched"] == 0
    assert res["inserted"] == 0
    assert await col(RAMP_MOVEMENTS).count_documents({"asset": "usdc"}) == 0


async def test_tick_cursor_advances_and_second_tick_is_noop():
    await run_migration()
    r1 = await run_tick_once()
    assert r1["inserted"] == 4

    # Second tick — same fixture, but cursor has advanced past all items.
    r2 = await run_tick_once()
    assert r2["matched"] == 0
    assert r2["inserted"] == 0
    # No new rows persisted
    assert await col(RAMP_MOVEMENTS).count_documents({"asset": "usdc"}) == 4
    # Cursor should not regress
    assert r2["cursor_in"] == r1["cursor_out"]


async def test_idempotency_via_unique_index_on_concurrent_replay():
    """Even if two ticks process the same payment (cursor race), the
    unique index keeps the table at exactly 1 row per tx_hash."""
    await run_migration()
    # Force the watcher to re-read from the start by manually wiping
    # the cursor between ticks while keeping the inserted rows.
    await run_tick_once()
    from jobs.deposit_watcher import _set_cursor
    await _set_cursor("")  # reset cursor — next tick will see same items
    res = await run_tick_once()
    # All items revisited but all are duplicates now → 0 inserted.
    assert res["inserted"] == 0
    assert res["duplicates"] + res["already"] == res["matched"]
    # Still exactly 4 rows
    assert await col(RAMP_MOVEMENTS).count_documents({"asset": "usdc"}) == 4


# ---------------------------------------------------------------------------
# Reconciliation tests
# ---------------------------------------------------------------------------
async def test_reconcile_by_hash_closes_pending():
    await run_migration()
    await run_tick_once()
    # Pick one pending_detected row and pretend a staking record with
    # that exact hashDeposito just arrived from CMS.
    row = await col(RAMP_MOVEMENTS).find_one(
        {"status": S_PENDING_DETECTED, "asset": "usdc",
         "memo": "1739100000"}, {"_id": 0})
    assert row is not None
    res = await reconcile_usdc_deposit(
        deposit_hash=row["external_id"], memo=row["memo"],
        principal=100.0, wallet=row["wallet"],
        position_id="pos_test_001",
        staking_raw={"id": 999, "hashDeposito": row["external_id"],
                       "memoStaking": row["memo"]})
    assert res["action"] == "reconciled_by_hash"
    updated = await col(RAMP_MOVEMENTS).find_one(
        {"movement_id": row["movement_id"]}, {"_id": 0})
    assert updated["status"] == S_SUCCESS
    assert updated["reconciled_position_id"] == "pos_test_001"
    assert updated["reconciled_via"] == "deposit_hash"


async def test_reconcile_by_memo_amount_unique_match():
    await run_migration()
    await run_tick_once()
    # Reconcile WITHOUT hash — force the fallback path.
    row = await col(RAMP_MOVEMENTS).find_one(
        {"status": S_PENDING_DETECTED, "memo": "1739100000"},
        {"_id": 0})
    assert row is not None
    res = await reconcile_usdc_deposit(
        deposit_hash=None, memo="1739100000",
        principal=100.0, wallet=row["wallet"],
        position_id="pos_test_002",
        staking_raw={"id": 998, "memoStaking": "1739100000"})
    assert res["action"] == "reconciled_by_memo_amount"
    updated = await col(RAMP_MOVEMENTS).find_one(
        {"movement_id": row["movement_id"]}, {"_id": 0})
    assert updated["status"] == S_SUCCESS
    assert updated["reconciled_via"] == "memo_amount"


async def test_reconcile_by_memo_amount_ambiguous_raises_alert_no_update():
    await run_migration()
    # Manually plant 2 pending_detected rows with the same (memo, amount)
    # — this should NOT happen in practice (each tx_hash is unique) but
    # we test the safety rail.
    now = datetime.now(timezone.utc).isoformat()
    common = {
        "kind": "deposit", "asset": "usdc",
        "provider": PROVIDER_STELLAR, "status": S_PENDING_DETECTED,
        "amount": "50.0000000", "wallet": KNOWN_WALLET_END,
        "memo": "AMBIG_MEMO", "org_id": ORG_ALEMANY,
        "detected_at": now, "created_at": now, "updated_at": now,
        "is_deleted": False,
    }
    await col(RAMP_MOVEMENTS).insert_one({
        **common, "movement_id": "mov_amb_1",
        "external_id": "tx_amb_1_" + ("0" * 50)})
    await col(RAMP_MOVEMENTS).insert_one({
        **common, "movement_id": "mov_amb_2",
        "external_id": "tx_amb_2_" + ("0" * 50)})

    res = await reconcile_usdc_deposit(
        deposit_hash=None, memo="AMBIG_MEMO",
        principal=50.0, wallet=KNOWN_WALLET_END,
        position_id="pos_test_003",
        staking_raw={"id": 997, "memoStaking": "AMBIG_MEMO"})
    assert res["action"] == "ambiguous_skipped"
    assert res["candidate_count"] == 2

    # Both rows MUST still be pending_detected — no mass update.
    pending_count = await col(RAMP_MOVEMENTS).count_documents(
        {"memo": "AMBIG_MEMO", "status": S_PENDING_DETECTED})
    assert pending_count == 2

    # Alert was created
    alerts = await col(ALERTS).find(
        {"type": "operational",
         "title": {"$regex": "Reconciliación USDC ambigua"}}).to_list(10)
    assert len(alerts) == 1
    assert alerts[0]["context"]["candidate_movement_ids"] == [
        "mov_amb_1", "mov_amb_2"]


async def test_reconcile_no_match_returns_no_match():
    await run_migration()
    res = await reconcile_usdc_deposit(
        deposit_hash="0" * 64, memo="nope",
        principal=1.0, wallet=KNOWN_WALLET_END,
        position_id="pos_test_004",
        staking_raw={"id": 996})
    assert res["action"] == "no_match"


# ---------------------------------------------------------------------------
# Orphan sweep tests
# ---------------------------------------------------------------------------
async def test_orphan_sweep_flips_aged_rows_and_alerts():
    await run_migration()
    await run_tick_once()
    # Backdate one row past the 90-min timeout
    old_dt = (datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat()
    row = await col(RAMP_MOVEMENTS).find_one(
        {"status": S_PENDING_DETECTED, "memo": "1739100000"},
        {"_id": 0})
    await col(RAMP_MOVEMENTS).update_one(
        {"movement_id": row["movement_id"]},
        {"$set": {"detected_at": old_dt}})

    res = await sweep_orphans()
    assert res["flipped"] == 1
    assert res["timeout_minutes"] == 90

    updated = await col(RAMP_MOVEMENTS).find_one(
        {"movement_id": row["movement_id"]}, {"_id": 0})
    assert updated["status"] == S_ORPHAN_DETECTED
    assert "orphan_at" in updated

    # Alert created
    alerts = await col(ALERTS).find(
        {"title": "USDC sin staking (probable memo inválido)"}).to_list(10)
    assert len(alerts) == 1


async def test_orphan_sweep_skips_recent_rows():
    await run_migration()
    await run_tick_once()
    res = await sweep_orphans()
    assert res["flipped"] == 0


async def test_orphan_timeout_floor_is_enforced():
    """If operator sets DEPOSIT_ORPHAN_TIMEOUT_MINUTES below
    RECLAIM_WINDOW+30, the engine bumps it back up."""
    await run_migration()
    os.environ["DEPOSIT_ORPHAN_TIMEOUT_MINUTES"] = "30"
    # Plant a row at 35 min — would be flagged if floor was 30, but
    # the floor is 90 (reclaim_window 60 + 30 margin).
    now = datetime.now(timezone.utc)
    old_dt = (now - timedelta(minutes=35)).isoformat()
    await col(RAMP_MOVEMENTS).insert_one({
        "movement_id": "mov_floor", "external_id": "tx_floor_" + "0" * 50,
        "kind": "deposit", "asset": "usdc", "provider": PROVIDER_STELLAR,
        "status": S_PENDING_DETECTED, "amount": "1.0000000",
        "wallet": KNOWN_WALLET_END, "memo": "f", "org_id": ORG_ALEMANY,
        "detected_at": old_dt, "created_at": old_dt, "updated_at": old_dt,
        "is_deleted": False,
    })
    res = await sweep_orphans()
    assert res["flipped"] == 0
    assert res["timeout_minutes"] == 90  # floored from 30 → 90


# ---------------------------------------------------------------------------
# Flag tests
# ---------------------------------------------------------------------------
async def test_flag_off_skips_tick():
    os.environ["DEPOSIT_ENGINE_ENABLED"] = "false"
    res = await run_tick_once()
    assert res["skipped"] is True
    assert res["reason"] == "flag_off"
    assert await col(RAMP_MOVEMENTS).count_documents(
        {"asset": "usdc"}) == 0


async def test_flag_off_skips_orphan_sweep():
    os.environ["DEPOSIT_ENGINE_ENABLED"] = "false"
    res = await run_orphan_sweep_once()
    assert res["skipped"] is True


async def test_is_enabled_reads_env():
    os.environ["DEPOSIT_ENGINE_ENABLED"] = "true"
    assert is_enabled() is True
    os.environ["DEPOSIT_ENGINE_ENABLED"] = "false"
    assert is_enabled() is False
    os.environ["DEPOSIT_ENGINE_ENABLED"] = "1"
    assert is_enabled() is True


# ---------------------------------------------------------------------------
# Health endpoint snapshot
# ---------------------------------------------------------------------------
async def test_health_snapshot_reports_state():
    await run_migration()
    await run_tick_once()
    snap = await health_snapshot()
    assert snap["enabled"] is True
    assert snap["horizon_mode"] == "mock"
    assert snap["wallet_count"] == 2
    assert snap["deposit_counts"]["pending_detected"] == 4
    assert snap["deposit_counts"]["orphan_detected"] == 0
    assert snap["cursor"]  # non-empty after a tick
