"""Deposit Detection Engine — USDC watcher (Camino A).

Pulls a single global cursor over `GET /payments` from the Horizon
adapter every `HORIZON_POLL_INTERVAL_SECONDS`. Filters in memory by
`(to ∈ wallet_set) AND (asset_code == 'USDC') AND (asset_issuer ==
expected_issuer) AND (successful == True)`. Surviving payments are
persisted as `ramp_movements{status:pending_detected}` via
`services.deposit_engine.record_pending_detected`.

Why this scales: ONE TCP connection (or polling cursor) regardless of
how many wallets we watch. Wallet set lookup is O(1).

Cursor is persisted in `deposit_watcher_cursors` so reboots resume
from the same place. Cold-start in real mode bootstraps the cursor to
"now" via Horizon's latest ledger to avoid replaying months of history.
The mock adapter starts from "" (replay everything).

The watcher does NOT touch balances, does NOT create positions. It only
writes `ramp_movements` rows and emits observability events.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from db import (DEPOSIT_WATCHER_CURSORS, ORGANIZATIONS, col)
from integrations.horizon import get_adapter
from services.deposit_engine import (PROVIDER_STELLAR, record_pending_detected,
                                          sweep_orphans)

logger = logging.getLogger("prosper.deposit_watcher")

CURSOR_KEY = "horizon_payments_global"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def is_enabled() -> bool:
    return (os.environ.get("DEPOSIT_ENGINE_ENABLED") or "").lower() in (
        "1", "true", "yes", "on")


def poll_interval_seconds() -> int:
    try:
        return max(2, int(os.environ.get("HORIZON_POLL_INTERVAL_SECONDS")
                              or 12))
    except (TypeError, ValueError):
        return 12


def expected_usdc_issuer() -> str:
    """Issuer G-address we accept as USDC. Defaults to Circle's mainnet
    USDC issuer; can be overridden for testnet."""
    return (os.environ.get("STELLAR_USDC_ISSUER")
              or "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN"
              ).strip()


# ---------------------------------------------------------------------------
# Cursor persistence
# ---------------------------------------------------------------------------
async def _get_cursor() -> str:
    doc = await col(DEPOSIT_WATCHER_CURSORS).find_one({"key": CURSOR_KEY},
                                                          {"_id": 0,
                                                            "cursor": 1})
    return (doc or {}).get("cursor") or ""


async def _set_cursor(cursor: str) -> None:
    await col(DEPOSIT_WATCHER_CURSORS).update_one(
        {"key": CURSOR_KEY},
        {"$set": {"cursor": cursor,
                     "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True)


# ---------------------------------------------------------------------------
# Wallet set
# ---------------------------------------------------------------------------
async def _load_wallet_set() -> dict[str, dict[str, Any]]:
    """Returns `{address: {org_id, modality}}` for every provisioned
    USDC wallet. Cheap to call per tick — the result is bounded by N
    orgs × 2 modalities and lives only in memory for the tick.
    """
    out: dict[str, dict[str, Any]] = {}
    cursor = col(ORGANIZATIONS).find(
        {"prosper_wallets": {"$exists": True, "$ne": []}},
        {"_id": 0, "org_id": 1, "prosper_wallets": 1})
    async for org in cursor:
        for w in (org.get("prosper_wallets") or []):
            addr = (w.get("address") or "").strip()
            if not addr:
                continue
            out[addr] = {
                "org_id":   org.get("org_id"),
                "modality": w.get("modality"),
            }
    return out


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------
async def run_tick_once() -> dict[str, Any]:
    """Advance the cursor by one Horizon page. Returns a summary.

    This function is the unit of work. It is safe to call concurrently
    (the unique index on `external_id` enforces dedup), but the
    scheduler runs single-instance.
    """
    if not is_enabled():
        return {"skipped": True, "reason": "flag_off"}

    adapter = get_adapter()
    cursor = await _get_cursor()
    wallets = await _load_wallet_set()
    issuer = expected_usdc_issuer()

    page = await adapter.fetch_payments(cursor=cursor, limit=200)

    matched = 0
    inserted = 0
    duplicates = 0
    already = 0
    ignored = 0

    for p in page.payments:
        if not p.successful:
            ignored += 1
            continue
        if p.asset_code != "USDC":
            ignored += 1
            continue
        if p.asset_issuer != issuer:
            ignored += 1
            continue
        wmeta = wallets.get(p.to)
        if not wmeta:
            ignored += 1
            continue
        matched += 1
        res = await record_pending_detected(
            tx_hash=p.tx_hash,
            op_id=p.op_id,
            wallet=p.to,
            org_id=wmeta.get("org_id"),
            modality=wmeta.get("modality"),
            amount=p.amount,
            memo=p.memo,
            created_at_iso=p.created_at,
            from_addr=p.from_,
            paging_token=p.paging_token,
        )
        action = res.get("action")
        if action == "inserted":
            inserted += 1
        elif action == "duplicate_skipped":
            duplicates += 1
        elif action == "already_present":
            already += 1

    # Advance cursor even when the page yielded zero matches — what
    # matters is that we processed every op up to next_cursor.
    if page.next_cursor and page.next_cursor != cursor:
        await _set_cursor(page.next_cursor)

    summary = {
        "skipped":      False,
        "mode":         adapter.mode,
        "cursor_in":    cursor,
        "cursor_out":   page.next_cursor,
        "page_size":    len(page.payments),
        "wallet_count": len(wallets),
        "matched":      matched,
        "inserted":     inserted,
        "duplicates":   duplicates,
        "already":      already,
        "ignored":      ignored,
    }
    if matched:
        logger.info("deposit_watcher tick: matched=%d inserted=%d "
                       "dups=%d already=%d ignored=%d page=%d wallets=%d "
                       "cursor=%s→%s",
                       matched, inserted, duplicates, already, ignored,
                       len(page.payments), len(wallets),
                       cursor[:18] or "(start)", page.next_cursor[:18])
    return summary


async def run_orphan_sweep_once() -> dict[str, Any]:
    if not is_enabled():
        return {"skipped": True, "reason": "flag_off"}
    return await sweep_orphans()


# ---------------------------------------------------------------------------
# Scheduler wiring (consumed by server.py startup hook)
# ---------------------------------------------------------------------------
_scheduler = None


def start_scheduler() -> Optional[object]:
    """Wire the watcher + orphan sweep into APScheduler. Returns the
    scheduler instance (or None when the flag is OFF).

    Idempotent: calling twice is a no-op. The caller is expected to
    install a shutdown hook (`shutdown_scheduler`) on app shutdown.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if not is_enabled():
        logger.info("deposit_watcher: flag OFF — scheduler not started")
        return None

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    interval = poll_interval_seconds()
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(_safe_tick, "interval", seconds=interval,
                    id="deposit_watcher_tick", max_instances=1,
                    coalesce=True)
    # Orphan sweep runs less frequently — every 5 minutes is plenty.
    sched.add_job(_safe_orphan_sweep, "interval", minutes=5,
                    id="deposit_watcher_orphan_sweep", max_instances=1,
                    coalesce=True)
    sched.start()
    _scheduler = sched
    logger.info("deposit_watcher scheduler started (tick=%ds, "
                  "orphan_sweep=5m, mode=%s)", interval,
                  get_adapter().mode)
    return sched


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        _scheduler = None


async def _safe_tick() -> None:
    try:
        await run_tick_once()
    except Exception:  # noqa: BLE001
        logger.exception("deposit_watcher tick failed")


async def _safe_orphan_sweep() -> None:
    try:
        await run_orphan_sweep_once()
    except Exception:  # noqa: BLE001
        logger.exception("deposit_watcher orphan sweep failed")


# ---------------------------------------------------------------------------
# Boot helper
# ---------------------------------------------------------------------------
async def boot_apply_migration_if_enabled() -> dict[str, Any]:
    """Apply the unique-sparse migration ONCE on startup, but only when
    the flag is on. We refuse to mutate indexes when the engine is
    disabled."""
    if not is_enabled():
        return {"skipped": True, "reason": "flag_off"}
    from jobs.deposit_engine_migrations import run as run_migration
    return await run_migration()


async def health_snapshot() -> dict[str, Any]:
    """Read-only status for the admin health endpoint."""
    from services.deposit_engine import counts
    return {
        "enabled":             is_enabled(),
        "horizon_mode":        get_adapter().mode,
        "poll_interval_secs":  poll_interval_seconds(),
        "cursor":              await _get_cursor(),
        "wallet_count":        len(await _load_wallet_set()),
        "deposit_counts":      await counts(),
    }
