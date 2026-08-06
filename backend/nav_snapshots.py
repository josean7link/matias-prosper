"""NAV snapshots — daily series read by /admin/dashboard/nav-history.

The collection is populated from `seed_demo.backfill_nav_snapshots` and can be
extended daily by a scheduled job (Phase 6+). Each doc is `{date, nav,
principal, accrued, created_at}` keyed by `date` (UTC `YYYY-MM-DD`).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from db import col, NAV_SNAPSHOTS, POSITIONS


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def backfill_nav_snapshots(days: int = 180, rng_seed: int = 20260512) -> dict:
    """Idempotent — if any snapshot already exists, no-op.

    For each day in [today-days+1, today] we compute principal = Σ active
    positions whose start ≤ day. NAV grows as NAV_t = NAV_{t-1} * (1 + r_t)
    where r_t = blended_apr / 365 plus a tiny ±0.5bp noise so the line isn't
    suspiciously perfect.
    """
    existing = await col(NAV_SNAPSHOTS).estimated_document_count()
    if existing > 0:
        return {"skipped": True, "existing": existing}

    rng = random.Random(rng_seed)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)

    # Pull active positions once
    cur = col(POSITIONS).find(
        {"is_deleted": False, "status": "active"},
        {"_id": 0, "principal_usd": 1, "apr_bps": 1, "created_at": 1},
    )
    positions = await cur.to_list(20_000)

    def parse_day(iso_s: str) -> datetime:
        return datetime.fromisoformat(iso_s.replace("Z", "+00:00")).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )

    pos_pairs = [(parse_day(p["created_at"]), float(p["principal_usd"]),
                  float(p.get("apr_bps", 850))) for p in positions]

    nav = 1.0
    docs: list[dict] = []
    day = start
    while day <= today:
        active = [(prin, apr) for (sd, prin, apr) in pos_pairs if sd <= day]
        if active:
            total_prin = sum(p for p, _ in active)
            weighted_apr = sum(p * a for p, a in active) / total_prin / 10_000
        else:
            total_prin = 0.0
            weighted_apr = 0.085
        daily = weighted_apr / 365.0
        # ±0.5bp noise = ±5e-5 day-over-day
        noise = rng.uniform(-5e-5, 5e-5)
        nav = nav * (1.0 + daily + noise)
        accrued = total_prin * (nav - 1.0)
        docs.append({
            "date":       day.strftime("%Y-%m-%d"),
            "nav":        round(nav, 6),
            "principal":  round(total_prin, 2),
            "accrued":    round(accrued, 2),
            "created_at": _iso(day),
        })
        day += timedelta(days=1)

    if docs:
        await col(NAV_SNAPSHOTS).insert_many(docs)
        await col(NAV_SNAPSHOTS).create_index("date", unique=True)
    return {"snapshots": len(docs)}


async def wipe_nav_snapshots() -> dict:
    res = await col(NAV_SNAPSHOTS).delete_many({})
    return {"deleted": res.deleted_count}
