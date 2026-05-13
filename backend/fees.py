"""Phase 4 — fee breakdown backfill + helper.

Prosper revenue model (per spec):
  - management   = amount × 1% / 365      (daily prorated, on subscribe)
  - performance  = amount × 10% of yield  (charged at payout; in our seed
                                            approximated as 0 until payout)
  - onramp_spread  = amount × 0.5%        (only on subscribe)
  - offramp_spread = amount × 0.3%        (only on redeem)
  - other = 0
  - prosper_revenue = Σ fee_breakdown
"""
from __future__ import annotations

from db import col, TRANSACTIONS

MGMT_RATE_ANNUAL   = 0.010
PERF_RATE          = 0.10
ONRAMP_SPREAD_RATE = 0.005
OFFRAMP_SPREAD_RATE = 0.003


def fee_breakdown(amount: float, tx_type: str, accrued: float = 0.0) -> dict:
    if tx_type == "subscribe":
        mgmt = round(amount * MGMT_RATE_ANNUAL / 365, 6)
        return {
            "management":     mgmt,
            "performance":    0.0,
            "onramp_spread":  round(amount * ONRAMP_SPREAD_RATE, 2),
            "offramp_spread": 0.0,
            "other":          0.0,
        }
    if tx_type == "redeem":
        return {
            "management":     0.0,
            "performance":    round(accrued * PERF_RATE, 2),
            "onramp_spread":  0.0,
            "offramp_spread": round(amount * OFFRAMP_SPREAD_RATE, 2),
            "other":          0.0,
        }
    return {"management": 0.0, "performance": 0.0,
            "onramp_spread": 0.0, "offramp_spread": 0.0, "other": 0.0}


async def backfill_fee_breakdown() -> dict:
    """Idempotent — $set fee_breakdown + prosper_revenue on demo txs that
    don't have it yet."""
    cur = col(TRANSACTIONS).find(
        {"is_demo": True, "fee_breakdown": {"$exists": False}},
        {"_id": 0, "tx_id": 1, "amount": 1, "type": 1, "status": 1})
    updated = 0
    async for tx in cur:
        amount = float(tx.get("amount") or 0)
        fb = fee_breakdown(amount, tx.get("type", ""))
        rev = round(sum(fb.values()), 2)
        await col(TRANSACTIONS).update_one(
            {"tx_id": tx["tx_id"]},
            {"$set": {"fee_breakdown": fb, "prosper_revenue": rev}})
        updated += 1
    return {"updated": updated}
