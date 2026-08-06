"""Phase 04 — Portfolio snapshot (cache-aware).

The snapshot endpoint feeds the 20s client polling. Its single job is to
return everything the dashboard/withdraw/positions/activity screens need
to display balances + recent movements + "deposit in transit" markers
WITHOUT hitting Horizon or running heavy aggregations on every request.

Architecture:
  * Cache: Redis SETEX with TTL=12s per `user_id`. Effective rate-limit:
    Horizon receives at most 1 call every 12s per user.
  * Source of truth UNCHANGED — we read the SAME on-chain/off-chain
    sources the existing /dashboard-summary uses; we just memoize the
    expensive bits.

Critical seam between Motor 02 (deposit engine) and Phase 04 (snapshot):

  balance.{asset}.stellar = max(0, horizon_balance - pending_detected_sum)

This eliminates the double-counting window. Without subtraction, a
freshly-arrived USDC payment would appear BOTH in `pending_detected`
(from `ramp_movements{status:pending_detected}`) AND in `stellar` (from
Horizon's live wallet read). With subtraction:

  T0  arrival      → horizon=100, pending=100 → stellar=0,   pending=100
  T1  engine flips → horizon=100, pending=0   → stellar=100, pending=0
       (or if staking moved funds out of wallet:)
       horizon=0, pending=0 → stellar=0, pending=0 + position=100

In both transitions the user sees exactly one home for every dollar.
Tested explicitly in `test_portfolio_snapshot.py`.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from db import (POSITIONS, RAMP_ACCOUNTS, RAMP_BALANCES, RAMP_MOVEMENTS,
                    col)
from integrations.prosper.factory import get_adapter as get_prosper_adapter

logger = logging.getLogger("prosper.portfolio_snapshot")

CACHE_TTL_SECONDS = 12
_CACHE_KEY_PREFIX = "prosper:portfolio:snapshot:"
_RECENT_MOVEMENTS_LIMIT = 10


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_key(user_id: str) -> str:
    return f"{_CACHE_KEY_PREFIX}{user_id}"


async def _redis_client():
    """Get the singleton Redis client from server.py. Returns None if
    Redis is not available (tests, dev without Redis) — caller must
    handle that gracefully (cache disabled, every request rebuilds)."""
    try:
        from server import redis_client
        return redis_client
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def get_or_build(user) -> dict[str, Any]:
    """Cache-first snapshot. Returns dict with `snapshot_source` field."""
    rc = await _redis_client()
    key = _cache_key(user.user_id)

    if rc is not None:
        try:
            cached = await rc.get(key)
            if cached:
                doc = json.loads(cached)
                doc["snapshot_source"] = "cache"
                return doc
        except Exception:  # noqa: BLE001
            logger.exception("snapshot: redis GET failed — falling through")

    doc = await build_snapshot(user)
    doc["snapshot_source"] = "fresh"

    if rc is not None:
        try:
            await rc.setex(key, CACHE_TTL_SECONDS, json.dumps(doc))
        except Exception:  # noqa: BLE001
            logger.exception("snapshot: redis SETEX failed — proceeding without cache")

    return doc


async def invalidate(user_id: str) -> None:
    """Force a refresh on next call. Currently unused — kept for the
    future SSE pump (Phase 2) which will invalidate on deposit.credited."""
    rc = await _redis_client()
    if rc is None:
        return
    try:
        await rc.delete(_cache_key(user_id))
    except Exception:  # noqa: BLE001
        logger.exception("snapshot: redis DEL failed")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
async def build_snapshot(user) -> dict[str, Any]:
    """Construct the snapshot fresh. ~5-10ms for DB-only paths, +Horizon
    latency when the USDC adapter fires."""
    org_id = user.org_id

    # 1. pending_detected by asset — visible separately, NEVER added to
    #    the operable balance. Used in two places: the card "Depósito
    #    en camino" AND subtracted from the raw on-chain balance below
    #    so the same dollar isn't shown twice.
    pending_arsa, pending_usdc = await _sum_pending_detected(org_id)

    # 2. Raw balances from current sources of truth.
    horizon_usdc, horizon_ts = await _read_usdc_horizon(org_id)
    arsa_cvu, arsa_ts = await _read_arsa_off_chain(org_id)

    # 3. Subtract pending from raw → "stellar" = operable, NOT in transit.
    #    `max(0, …)` guards against ordering races (engine flips to
    #    Success in the same instant a new deposit arrives — Horizon
    #    lags the watcher's view by milliseconds).
    usdc_stellar_operable = max(0.0, horizon_usdc - pending_usdc)
    arsa_cvu_operable     = max(0.0, arsa_cvu - pending_arsa)

    # 4. Recent movements + cursor — for the "Activity" surface + new
    #    movement detection on the client.
    recent, cursor = await _recent_movements(org_id)

    return {
        "balances": {
            "arsa": {
                "cvu":              arsa_cvu_operable,
                "stellar":          0.0,             # not used for ARSa today
                "total":            arsa_cvu_operable,
                "pending_detected": pending_arsa,
                "as_of":            arsa_ts,
            },
            "usdc": {
                "platform":         0.0,             # legacy lane — kept zero
                "stellar":          usdc_stellar_operable,
                "total":            usdc_stellar_operable,
                "pending_detected": pending_usdc,
                "as_of":            horizon_ts,
            },
        },
        "recent_movements":     recent,
        "last_movement_cursor": cursor,
        "fetched_at":           _iso_now(),
    }


# ---------------------------------------------------------------------------
# Source readers
# ---------------------------------------------------------------------------
async def _sum_pending_detected(org_id: str) -> tuple[float, float]:
    """Sum `ramp_movements{status:pending_detected}` per asset."""
    pipeline = [
        {"$match": {"org_id": org_id, "status": "pending_detected",
                      "kind":    "deposit"}},
        {"$group": {"_id":   {"asset": "$asset"},
                       "total": {"$sum": {"$toDouble": "$amount"}}}},
    ]
    arsa = 0.0
    usdc = 0.0
    async for row in col(RAMP_MOVEMENTS).aggregate(pipeline):
        asset = (row["_id"].get("asset") or "").lower()
        amt = float(row.get("total") or 0)
        if asset == "arsa":
            arsa += amt
        elif asset == "usdc":
            usdc += amt
    return arsa, usdc


async def _read_usdc_horizon(org_id: str) -> tuple[float, str]:
    """USDC balance from Stellar via the Prosper adapter."""
    try:
        bal = await get_prosper_adapter().get_user_balances(org_id)
        return float(bal.balance_prosper or 0), _iso_now()
    except Exception:  # noqa: BLE001
        # Adapter unavailable / wallet not provisioned → safe zero.
        return 0.0, _iso_now()


async def _read_arsa_off_chain(org_id: str) -> tuple[float, str]:
    """ARSa CVU balance from `ramp_balances` (webhook-driven, no Horizon hit)."""
    row = await col(RAMP_BALANCES).find_one(
        {"org_id": org_id, "asset": "arsa"},
        {"_id": 0, "balance": 1, "as_of": 1},
        sort=[("as_of", -1)])
    if not row:
        # Fallback: look up via ramp_account ids (legacy data shape).
        acc_ids = []
        async for a in col(RAMP_ACCOUNTS).find({"org_id": org_id},
                                                  {"_id": 0, "id": 1}):
            acc_ids.append(a["id"])
        if acc_ids:
            row = await col(RAMP_BALANCES).find_one(
                {"ramp_account_id": {"$in": acc_ids}, "asset": "arsa"},
                {"_id": 0, "balance": 1, "as_of": 1},
                sort=[("as_of", -1)])
    if not row:
        return 0.0, _iso_now()
    return float(row.get("balance") or 0), str(row.get("as_of") or _iso_now())


async def _recent_movements(org_id: str
                              ) -> tuple[list[dict[str, Any]], str | None]:
    """Top N most recent ramp_movements + a monotonic cursor.

    Cursor is the `created_at` of the most recent row. The client treats
    a strictly-greater value as "new movement detected".
    """
    rows = await col(RAMP_MOVEMENTS).find(
        {"org_id": org_id},
        {"_id":         0, "movement_id":  1, "id": 1, "kind":   1,
         "asset":       1, "amount":       1, "status": 1, "memo": 1,
         "created_at":  1, "external_id":  1, "occurred_at": 1,
         "provider":    1},
    ).sort("created_at", -1).limit(_RECENT_MOVEMENTS_LIMIT).to_list(
        _RECENT_MOVEMENTS_LIMIT)

    # Normalize the id field (mixed across collections).
    for r in rows:
        if "movement_id" not in r and "id" in r:
            r["movement_id"] = r.pop("id")
    cursor = rows[0].get("created_at") if rows else None
    return rows, cursor
