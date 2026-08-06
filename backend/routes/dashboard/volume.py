"""/volume — daily stacked subscribe vs redeem for last N days."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Query

from auth import CurrentUser
from db import col, TRANSACTIONS

from ._deps import iso, require_dashboard, utc_now

router = APIRouter()


@router.get("/volume")
async def get_volume(days: int = Query(30, ge=1, le=365),
                     _: CurrentUser = Depends(require_dashboard)):
    now = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    pipeline = [
        {"$match": {"is_deleted": False, "status": "confirmed",
                     "type": {"$in": ["subscribe", "redeem"]},
                     "created_at": {"$gte": iso(start)}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {"_id": {"day": "$day", "type": "$type"},
                     "amount": {"$sum": "$amount"}}},
        {"$sort": {"_id.day": 1}},
    ]
    rows = await col(TRANSACTIONS).aggregate(pipeline).to_list(2000)

    by_day: dict[str, dict] = {}
    for r in rows:
        d = r["_id"]["day"]
        t = r["_id"]["type"]
        by_day.setdefault(d, {"date": d, "subscribe": 0, "redeem": 0})
        by_day[d][t] = round(r["amount"], 2)

    day = start
    out = []
    while day <= now:
        k = day.strftime("%Y-%m-%d")
        out.append(by_day.get(k, {"date": k, "subscribe": 0, "redeem": 0}))
        day += timedelta(days=1)
    out = out[-days:]
    return {"items": out, "total": len(out)}
