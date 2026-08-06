"""/recent-activity — last N confirmed transactions across all orgs."""
from fastapi import APIRouter, Depends, Query

from auth import CurrentUser
from db import col, ORGANIZATIONS, TRANSACTIONS

from ._deps import require_dashboard

router = APIRouter()


@router.get("/recent-activity")
async def get_recent_activity(limit: int = Query(8, ge=1, le=50),
                              _: CurrentUser = Depends(require_dashboard)):
    txs = await col(TRANSACTIONS).find(
        {"is_deleted": False, "status": "confirmed"},
        {"_id": 0, "tx_id": 1, "org_id": 1, "type": 1, "amount": 1,
         "asset": 1, "prosper_tx_id": 1, "tx_hash": 1, "fee_amount": 1,
         "created_at": 1, "memo": 1},
    ).sort("created_at", -1).to_list(limit)

    org_ids = list({t["org_id"] for t in txs if t.get("org_id")})
    org_lookup: dict[str, str] = {}
    if org_ids:
        async for o in col(ORGANIZATIONS).find(
            {"org_id": {"$in": org_ids}}, {"_id": 0, "org_id": 1, "commercial_name": 1, "legal_name": 1}
        ):
            org_lookup[o["org_id"]] = o.get("commercial_name") or o.get("legal_name") or o["org_id"]

    items = []
    for t in txs:
        items.append({
            "tx_id":         t.get("tx_id"),
            "org_id":        t.get("org_id"),
            "org_name":      org_lookup.get(t.get("org_id", ""), t.get("org_id") or "—"),
            "type":          t.get("type"),
            "amount":        t.get("amount"),
            "asset":         t.get("asset", "USDC"),
            "fee_amount":    t.get("fee_amount", 0),
            "prosper_tx_id": t.get("prosper_tx_id"),
            "tx_hash":       t.get("tx_hash"),
            "created_at":    t.get("created_at"),
            "memo":          t.get("memo"),
        })
    return {"items": items, "total": len(items)}
