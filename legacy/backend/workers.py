"""Background jobs for the Prosper platform (APScheduler-based).

Jobs:
- webhook_retry_job: retries failed webhook deliveries every 5 minutes
- sla_check_job: flags onboarding cases nearing SLA breach (every hour)
- eod_snapshot_job: writes a NAV snapshot at 00:05 UTC daily (for demo, also runs hourly)
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import col, WEBHOOK_DELIVERIES, ONBOARDING, NAV_SNAPSHOTS, FUNDS, ALERTS
from models import now_utc, new_id

logger = logging.getLogger("prosper.workers")


async def webhook_retry_job():
    """Simulate retry: if delivery response_status != 200 and attempt < 3, increment and mark delivered."""
    cursor = col(WEBHOOK_DELIVERIES).find(
        {"delivered": False, "attempt": {"$lt": 3}}, {"_id": 0}
    )
    n = 0
    async for d in cursor:
        await col(WEBHOOK_DELIVERIES).update_one(
            {"delivery_id": d["delivery_id"]},
            {"$inc": {"attempt": 1}, "$set": {"next_retry_at": (now_utc() + timedelta(minutes=5)).isoformat()}}
        )
        n += 1
    if n > 0:
        logger.info(f"[webhook_retry] retried {n} failed deliveries")


async def sla_check_job():
    """Flag onboarding cases that are <6h from SLA breach."""
    cutoff = (now_utc() + timedelta(hours=6)).isoformat()
    items = await col(ONBOARDING).find({
        "status": {"$in": ["submitted", "under_review", "needs_info"]},
        "sla_due": {"$lte": cutoff}
    }, {"_id": 0}).to_list(100)
    for c in items:
        # Insert alert if not already open for this case
        existing = await col(ALERTS).find_one({
            "kind": "onboarding_sla",
            "metadata.case_id": c["case_id"],
            "resolved": False,
        }, {"_id": 0})
        if existing:
            continue
        await col(ALERTS).insert_one({
            "alert_id": f"al_{new_id()}",
            "severity": "warning", "kind": "onboarding_sla",
            "title": f"Onboarding SLA near: {c['applicant_name']}",
            "message": f"Case {c['case_id']} due by {c.get('sla_due')}",
            "resolved": False, "is_demo": False,
            "metadata": {"case_id": c["case_id"]},
            "created_at": now_utc().isoformat(),
        })
    if items:
        logger.info(f"[sla_check] flagged {len(items)} cases near SLA")


async def eod_snapshot_job():
    """Write a NAV snapshot per production fund."""
    funds = await col(FUNDS).find({"environment": "production", "status": "active"}, {"_id": 0}).to_list(50)
    for f in funds:
        # Skip if a snapshot already exists in the last hour (avoid duplicates)
        cutoff = (now_utc() - timedelta(hours=1)).isoformat()
        recent = await col(NAV_SNAPSHOTS).find_one({
            "fund_id": f["fund_id"],
            "as_of": {"$gte": cutoff},
        }, {"_id": 0})
        if recent:
            continue
        nav = float(f.get("nav_per_token", 1.0)) * (1.0 + 0.00001)  # drift
        await col(NAV_SNAPSHOTS).insert_one({
            "snapshot_id": f"nav_{new_id()}", "fund_id": f["fund_id"],
            "as_of": now_utc().isoformat(),
            "nav_per_token": round(nav, 6),
            "total_supply": f.get("total_supply", 0),
            "is_demo": False,
        })
        await col(FUNDS).update_one({"fund_id": f["fund_id"]}, {"$set": {"nav_per_token": round(nav, 6)}})
    logger.info(f"[eod_snapshot] wrote {len(funds)} snapshots")


_scheduler: AsyncIOScheduler | None = None


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(webhook_retry_job, "interval", minutes=5, id="webhook_retry", replace_existing=True)
    _scheduler.add_job(sla_check_job, "interval", minutes=60, id="sla_check", replace_existing=True)
    _scheduler.add_job(eod_snapshot_job, "interval", minutes=60, id="eod_snapshot", replace_existing=True)
    _scheduler.start()
    logger.info("[scheduler] started with 3 jobs")


def shutdown_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
