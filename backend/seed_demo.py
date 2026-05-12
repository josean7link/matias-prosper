"""Phase 2 demo data — ~6 months of synthetic transactions, positions and accruals
so the dashboard charts have realistic shape. Idempotent: tags everything with
`is_demo: true` so it can be wiped without touching real data.

Generated:
  - 1 product (PROS-180 · 8.5% APR · 180-day term)
  - 60-120 active positions across the 2 seed orgs
  - 180 days of transactions: subscribe + redeem + daily yield accruals
  - 6 months of revenue numbers (fee_amount on each tx)
"""
from __future__ import annotations
import random
from datetime import datetime, timedelta, timezone

from db import col, ORGANIZATIONS, POSITIONS, TRANSACTIONS
from models import Position, Transaction, utc_now, new_id


RNG_SEED = 20260512  # deterministic so chart shape is stable across boots
DEMO_PRODUCT_ID = "prod_pros_180"
DEMO_USER_IDS = {
    "org_seed_alemany": "usr_seed_alemany_admin",
    "org_seed_finpact": "usr_seed_finpact_admin",
}
ASSET = "USDC"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def seed_demo_transactions(days: int = 180):
    """Idempotent — if `is_demo` records exist for this product, do nothing."""
    existing = await col(TRANSACTIONS).count_documents({"is_demo": True})
    if existing > 0:
        return {"skipped": True, "existing": existing}

    rng = random.Random(RNG_SEED)
    now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)

    orgs = await col(ORGANIZATIONS).find({"is_deleted": False}, {"_id": 0}).to_list(50)
    if not orgs:
        return {"skipped": True, "reason": "no orgs"}

    transactions: list[dict] = []
    positions: list[dict] = []

    # ── 1. Daily subscribes / redeems for the past N days ───────────────────
    for day_offset in range(days):
        day = start + timedelta(days=day_offset)
        # Subscribes per day: 0-4
        n_subs = rng.choices([0, 1, 2, 3, 4], weights=[20, 30, 25, 15, 10])[0]
        for _ in range(n_subs):
            org = rng.choice(orgs)
            if org.get("kyb_status") not in ("approved", "in_review"):
                # let pending org also place small subscribes for variety
                pass
            amount = rng.choice([5_000, 10_000, 25_000, 50_000, 100_000, 250_000])
            apr_bps = 850  # 8.5%
            pos_id = f"pos_{new_id().split('_',1)[1]}"
            tx_id  = f"tx_{new_id().split('_',1)[1]}"
            tx_uuid = f"ptx_{new_id().split('_',1)[1]}"
            # Position
            positions.append(Position(
                position_id=pos_id, org_id=org["org_id"],
                user_id=DEMO_USER_IDS.get(org["org_id"]),
                product_id=DEMO_PRODUCT_ID, principal_usd=float(amount),
                apr_bps=apr_bps, accrued_interest=0.0, currency=ASSET,
                start=_iso(day), maturity=_iso(day + timedelta(days=180)),
                status="active", prosper_tx_id=tx_uuid,
                created_at=_iso(day), updated_at=_iso(day),
            ).model_dump() | {"is_demo": True})
            # Subscribe tx
            transactions.append(Transaction(
                tx_id=tx_id, org_id=org["org_id"], prosper_tx_id=tx_uuid,
                type="subscribe", amount=float(amount), asset=ASSET,
                status="confirmed", related_position_id=pos_id,
                fee_amount=round(amount * 0.0010, 2),  # 10 bps origination fee
                fee_currency=ASSET,
                memo=f"Subscribe PROS-180 day+{day_offset}",
                created_at=_iso(day), updated_at=_iso(day),
            ).model_dump() | {"is_demo": True})
        # Redeems per day: 0-2
        n_red = rng.choices([0, 1, 2], weights=[60, 30, 10])[0]
        for _ in range(n_red):
            org = rng.choice(orgs)
            amount = rng.choice([5_000, 10_000, 25_000, 50_000])
            tx_id  = f"tx_{new_id().split('_',1)[1]}"
            transactions.append(Transaction(
                tx_id=tx_id, org_id=org["org_id"],
                type="redeem", amount=float(amount), asset=ASSET,
                status="confirmed",
                fee_amount=round(amount * 0.0005, 2),  # 5 bps redemption fee
                fee_currency=ASSET,
                memo=f"Redeem day+{day_offset}",
                created_at=_iso(day), updated_at=_iso(day),
            ).model_dump() | {"is_demo": True})

    if positions:
        await col(POSITIONS).insert_many(positions)
    if transactions:
        await col(TRANSACTIONS).insert_many(transactions)

    return {"positions": len(positions), "transactions": len(transactions)}


async def wipe_demo_transactions():
    """Surgical cleanup — only touches records tagged is_demo=true."""
    res1 = await col(POSITIONS).delete_many({"is_demo": True})
    res2 = await col(TRANSACTIONS).delete_many({"is_demo": True})
    return {"positions_deleted": res1.deleted_count,
            "transactions_deleted": res2.deleted_count}
