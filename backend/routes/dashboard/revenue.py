"""/revenue — last N months of fee revenue (exact first-of-month math)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from auth import CurrentUser
from db import col, TRANSACTIONS

from ._deps import iso, require_dashboard, utc_now

router = APIRouter()


def _first_of_month_n_ago(now: datetime, n: int) -> datetime:
    """First day of the month that is `n` calendar months before `now`."""
    year = now.year
    month = now.month - n
    while month <= 0:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


@router.get("/revenue")
async def get_revenue(months: int = Query(12, ge=1, le=36),
                      _: CurrentUser = Depends(require_dashboard)):
    now = utc_now()
    start = _first_of_month_n_ago(now, months - 1)
    pipeline = [
        {"$match": {"is_deleted": False, "status": "confirmed",
                     "fee_amount": {"$gt": 0},
                     "created_at": {"$gte": iso(start)}}},
        {"$addFields": {"month": {"$substr": ["$created_at", 0, 7]}}},
        {"$group": {"_id": "$month", "revenue": {"$sum": "$fee_amount"}}},
        {"$sort": {"_id": 1}},
    ]
    rows = await col(TRANSACTIONS).aggregate(pipeline).to_list(60)
    return {"items": [{"month": r["_id"], "revenue": round(r["revenue"], 2)} for r in rows],
            "total": len(rows)}
