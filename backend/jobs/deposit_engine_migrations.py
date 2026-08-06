"""Deposit Engine — index migrations.

Hardens `ramp_movements.external_id` from `sparse` to `sparse + unique`.
Why: the watcher inserts one row per Horizon payment using `tx_hash` as
`external_id`. Two concurrent ticks could race past an app-level
`find_one(external_id)` check and double-insert. With a unique index the
DB rejects the second write, guaranteeing idempotency.

Safety rails:
  * **Re-verify duplicates AT MIGRATION TIME** (not just at design time).
    If any exist, abort with a structured report — never coerce a unique
    index over dirty data.
  * Idempotent: running twice is a no-op.
  * Drops the old non-unique `external_id_1` index before creating the
    new one (Mongo refuses two indexes on the same key with different
    options).

Callable from:
  * `backend/tests/...` — unit tests
  * `backend/jobs/deposit_watcher.py` — startup (only when flag ON)
  * `POST /api/v1/admin/deposits/migrations/run` — manual op control
"""
from __future__ import annotations

import logging
from typing import Any

from db import RAMP_MOVEMENTS, col

logger = logging.getLogger("prosper.deposit_engine.migrations")

# Name of the new unique index. Kept distinct from the legacy
# `external_id_1` so the rollout is auditable.
UNIQUE_INDEX_NAME = "external_id_unique_sparse"


async def find_duplicate_external_ids() -> list[dict[str, Any]]:
    """Return up to 50 `external_id` values that appear in 2+ rows.

    Returns `[]` when the collection is clean. Used by `run()` to refuse
    the migration when duplicates exist.
    """
    pipeline = [
        {"$match": {"external_id": {"$nin": [None, ""]}}},
        {"$group": {"_id":  "$external_id",
                       "n":    {"$sum": 1},
                       "ids":  {"$push": "$_id"},
                       "kinds": {"$addToSet": "$kind"}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 50},
    ]
    return await col(RAMP_MOVEMENTS).aggregate(pipeline).to_list(50)


async def run(*, force: bool = False) -> dict[str, Any]:
    """Apply the unique-sparse migration. Returns a structured report.

    `force=True` is NOT a way to bypass the duplicate check — there is
    no bypass. If duplicates exist, the only path forward is operator
    cleanup. `force` only re-creates the index even if it already exists
    with the same name (used by tests).
    """
    coll = col(RAMP_MOVEMENTS)

    # 1. Re-verify duplicates RIGHT NOW. Never coerce a unique index over
    #    dirty data — that would brick subsequent writes against the
    #    existing rows.
    dupes = await find_duplicate_external_ids()
    if dupes:
        logger.error("Deposit migration aborted: %d duplicate external_id "
                       "value(s) found", len(dupes))
        return {
            "ok":            False,
            "step":          "duplicate_check",
            "duplicates":    dupes,
            "message":       "Migration aborted: clean the duplicates first.",
        }

    # 2. Inspect current indexes
    existing = await coll.index_information()
    actions: list[str] = []

    # 3. Drop the legacy non-unique index if present
    if "external_id_1" in existing:
        spec = existing["external_id_1"]
        if not spec.get("unique"):
            await coll.drop_index("external_id_1")
            actions.append("dropped:external_id_1")

    # 4. Create the new unique-sparse index (idempotent)
    if UNIQUE_INDEX_NAME in existing and not force:
        actions.append(f"exists:{UNIQUE_INDEX_NAME}")
    else:
        if UNIQUE_INDEX_NAME in existing:
            await coll.drop_index(UNIQUE_INDEX_NAME)
            actions.append(f"dropped:{UNIQUE_INDEX_NAME}")
        await coll.create_index(
            "external_id",
            unique=True, sparse=True,
            name=UNIQUE_INDEX_NAME)
        actions.append(f"created:{UNIQUE_INDEX_NAME}")

    final = await coll.index_information()
    logger.info("Deposit migration applied: actions=%s", actions)
    return {"ok": True, "actions": actions, "indexes": list(final.keys())}
