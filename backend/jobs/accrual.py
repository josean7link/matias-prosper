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
    via the `last_accrued_date` marker."""
    today = _iso_now()[:10]
    updated = 0
    matured = 0
    skipped = 0
    cursor = col(POSITIONS).find({"status": "active", "is_deleted": False})
    async for pos in cursor:
        if pos.get("last_accrued_date") == today:
            skipped += 1
            continue
        principal = float(pos.get("principal_usd") or 0)
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
    logger.info("accrual run: updated=%d matured=%d skipped=%d",
                updated, matured, skipped)
    return {"updated": updated, "matured": matured, "skipped": skipped}


_scheduler = None


def start_scheduler() -> None:
    """Start the APScheduler in-process. Tolerates the lib being missing."""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
        from apscheduler.triggers.cron import CronTrigger             # type: ignore
    except ImportError:
        logger.warning("APScheduler not installed — accrual cron disabled")
        return
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(run_accrual_once, CronTrigger(hour=0, minute=0),
                   id="daily-accrual",
                   replace_existing=True)
    sched.start()
    _scheduler = sched
    logger.info("Accrual scheduler started (cron 0 0 * * *)")
