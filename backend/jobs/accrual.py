"""Phase 9 — Daily accrual + maturity worker.

Uses APScheduler (already in deps for ops?). If not available, the scheduler
silently no-ops and exposes a `run_once()` for manual invocation / tests.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from db import col, POSITIONS

logger = logging.getLogger("prosper.accrual")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_accrual_once() -> dict[str, Any]:
    """Apply 1-day accrual to every active position. Idempotent within a day
    via the `last_accrued_date` marker.

    P0 guard (Feb 2026): positions where the CMS contract started returning
    `interesesAcumulados != null` (flagged on the doc as
    `contract_provides_interest=True`) are SKIPPED — the contract is now the
    authoritative source for accrued interest, the local APR calc would
    double-count.
    """
    today = _iso_now()[:10]
    updated = 0
    matured = 0
    skipped = 0
    deferred = 0
    cursor = col(POSITIONS).find({"status": "active", "is_deleted": False})
    async for pos in cursor:
        if pos.get("contract_provides_interest"):
            deferred += 1
            continue
        if pos.get("last_accrued_date") == today:
            skipped += 1
            continue
        # Prefer the new `principal_native` field but fall back to legacy
        # `principal_usd` for positions created pre-P0.
        principal = float(pos.get("principal_native")
                            or pos.get("principal_usd") or 0)
        apr_bps   = int(pos.get("apr_bps") or 0)
        daily     = round(principal * (apr_bps / 10_000) / 365, 6)
        new_accr  = round((pos.get("accrued_interest") or 0) + daily, 6)
        set_doc: dict[str, Any] = {
            "accrued_interest":   new_accr,
            "last_accrued_date":  today,
            "updated_at":         _iso_now(),
        }
        # Maturity check
        mat = pos.get("maturity")
        if mat and mat <= _iso_now():
            set_doc["status"] = "matured"
            set_doc["matured_at"] = _iso_now()
            matured += 1
        await col(POSITIONS).update_one({"position_id": pos["position_id"]},
                                          {"$set": set_doc})
        updated += 1
    logger.info("accrual run: updated=%d matured=%d skipped=%d deferred=%d",
                updated, matured, skipped, deferred)
    return {"updated": updated, "matured": matured,
             "skipped": skipped, "deferred_to_contract": deferred}


_scheduler = None


def start_scheduler() -> None:
    """Start the APScheduler in-process. Tolerates the lib being missing.

    Schedules two jobs:
      • `daily-accrual` — 00:00 UTC, local APR accrual (skips positions
        where the contract already provides accrued interest).
      • `staking-sync` — every N minutes, reconciles `/cms/staking` into
        local positions. Toggle via `PROSPER_STAKING_SYNC_ENABLED`.
    """
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
        from apscheduler.triggers.cron import CronTrigger             # type: ignore
        from apscheduler.triggers.interval import IntervalTrigger     # type: ignore
    except ImportError:
        logger.warning("APScheduler not installed — accrual cron disabled")
        return
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(run_accrual_once, CronTrigger(hour=0, minute=0),
                   id="daily-accrual",
                   replace_existing=True)

    # Staking sync (P0-3, Feb 2026)
    from jobs.staking_sync import is_enabled as sync_enabled, run_sync_once
    if sync_enabled():
        import os
        interval_min = int(os.environ.get(
            "PROSPER_STAKING_SYNC_INTERVAL_MINUTES", "5"))
        sched.add_job(run_sync_once,
                       IntervalTrigger(minutes=interval_min),
                       id="staking-sync",
                       replace_existing=True,
                       next_run_time=datetime.now(timezone.utc))
        logger.info("Staking sync scheduler enabled "
                       "(interval=%dm)", interval_min)
    else:
        logger.info("Staking sync scheduler DISABLED "
                       "(PROSPER_STAKING_SYNC_ENABLED unset/false)")

    sched.start()
    _scheduler = sched
    logger.info("Accrual + staking-sync schedulers started")
