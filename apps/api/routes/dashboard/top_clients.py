"""/top-clients — top N orgs by AUM."""
from fastapi import APIRouter, Depends, Query

from auth import CurrentUser
from db import col, ORGANIZATIONS, POSITIONS

from ._deps import require_dashboard

router = APIRouter()


@router.get("/top-clients")
async def get_top_clients(limit: int = Query(10, ge=1, le=50),
                          _: CurrentUser = Depends(require_dashboard)):
    pipeline = [
        {"$match": {"is_deleted": False, "status": "active"}},
        {"$group": {"_id": "$org_id",
                     "aum": {"$sum": {"$add": ["$principal_usd", "$accrued_interest"]}},
                     "positions_count": {"$sum": 1}}},
        {"$sort": {"aum": -1}},
        {"$limit": limit},
    ]
    rows = await col(POSITIONS).aggregate(pipeline).to_list(limit)
    org_ids = [r["_id"] for r in rows if r["_id"]]
    org_lookup = {o["org_id"]: o async for o in
                  col(ORGANIZATIONS).find({"org_id": {"$in": org_ids}}, {"_id": 0})}
    items = []
    for r in rows:
        org = org_lookup.get(r["_id"]) or {}
        items.append({
            "org_id": r["_id"],
            "name": org.get("commercial_name") or org.get("legal_name") or r["_id"],
            "aum": round(r["aum"], 2),
            "positions_count": r["positions_count"],
        })
    return {"items": items, "total": len(items)}
