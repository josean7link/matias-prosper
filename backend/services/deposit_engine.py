"""Deposit Engine — state machine helpers.

These are the only writers/readers of `ramp_movements` rows owned by the
Deposit Engine. The watcher (`jobs/deposit_watcher.py`) and the
reconciliation hook in `jobs/staking_sync.py` call into here.

State machine (USDC deposits via Horizon watcher):

    pending_detected  ──── hash match  ────▶  Success
       │                  (external_id =
       │                   hashDeposito)
       │
       ├──── memo+amount unique match ────▶  Success
       │     (fallback, see reconcile_*)
       │
       │     >ORPHAN_TIMEOUT_MIN min
       └──── without any match  ──────────▶  orphan_detected
                                              (operational alert,
                                               manual resolution)

Invariants:
  * The watcher NEVER touches balance fields.
  * The watcher NEVER creates positions — only ramp_movements.
  * Idempotency is DB-enforced by `external_id_unique_sparse` (see
    `deposit_engine_migrations.run`).
  * Orphan timeout MUST be `> RECLAIM_WINDOW_MINUTES` of staking_sync
    so legitimate deposits in-flight to staking are not mis-flagged.

Why we use `provider='stellar'` on every row written here: it gives a
structural discriminator against ARSa rows (which carry Andes-issued
`external_id` strings like `tx_…`, `dep_…`). Even though their key
spaces don't overlap today, a provider tag is cheap insurance.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pymongo.errors import DuplicateKeyError

from db import ALERTS, RAMP_MOVEMENTS, col

logger = logging.getLogger("prosper.deposit_engine")

PROVIDER_STELLAR  = "stellar"
PROVIDER_ANDESLABS = "andeslabs"

# Status constants — keep them centralized so callers don't typo strings.
S_PENDING_DETECTED = "pending_detected"
S_SUCCESS           = "Success"           # match the casing used elsewhere
S_ORPHAN_DETECTED   = "orphan_detected"

# Source of `RECLAIM_WINDOW_MINUTES`: lazy-imported in code to avoid a
# circular dependency with `staking_sync`. The orphan timeout MUST stay
# strictly greater than that window.
DEFAULT_ORPHAN_TIMEOUT_MINUTES = 90


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _orphan_timeout_minutes() -> int:
    """Read the orphan timeout from env, with a hard floor of
    RECLAIM_WINDOW_MINUTES + 30 to prevent operators from misconfiguring
    a window that would flag in-flight deposits as orphans."""
    try:
        configured = int(
            os.environ.get("DEPOSIT_ORPHAN_TIMEOUT_MINUTES",
                              DEFAULT_ORPHAN_TIMEOUT_MINUTES))
    except (TypeError, ValueError):
        configured = DEFAULT_ORPHAN_TIMEOUT_MINUTES

    # Lazy import to avoid cycles.
    try:
        from jobs.staking_sync import RECLAIM_WINDOW_MINUTES
        floor = RECLAIM_WINDOW_MINUTES + 30
    except Exception:  # noqa: BLE001
        floor = 90

    if configured < floor:
        logger.warning("DEPOSIT_ORPHAN_TIMEOUT_MINUTES=%d is below "
                          "reclaim_window+30 (=%d). Bumping to %d.",
                          configured, floor, floor)
        return floor
    return configured


# ---------------------------------------------------------------------------
# Watcher writer
# ---------------------------------------------------------------------------
async def record_pending_detected(*, tx_hash: str, op_id: str,
                                       wallet: str, org_id: str,
                                       modality: Optional[str],
                                       amount: str, memo: Optional[str],
                                       created_at_iso: str,
                                       from_addr: str,
                                       paging_token: str) -> dict[str, Any]:
    """Persist a freshly-observed USDC payment as `pending_detected`.

    Returns:
      * `{"action": "inserted", ...}` on first observation
      * `{"action": "duplicate_skipped", ...}` if the DB rejected the
        write because the unique index caught a race
      * `{"action": "already_present", ...}` if the row already exists
        in a non-pending state (already reconciled in a previous tick)
    """
    if not tx_hash:
        return {"action": "skipped", "reason": "missing_tx_hash"}

    coll = col(RAMP_MOVEMENTS)
    doc = {
        "movement_id":      "mov_dep_" + secrets.token_hex(6),
        "org_id":           org_id,
        "kind":             "deposit",
        "asset":            "usdc",
        "provider":         PROVIDER_STELLAR,
        "status":           S_PENDING_DETECTED,
        "amount":           amount,
        "wallet":           wallet,
        "modality":         modality,
        "memo":             memo,
        "external_id":      tx_hash,
        "horizon_op_id":    op_id,
        "horizon_paging_token": paging_token,
        "from_address":     from_addr,
        "on_chain_at":      created_at_iso,
        "detected_at":      _iso_now(),
        "created_at":       _iso_now(),
        "updated_at":       _iso_now(),
        "is_deleted":       False,
    }
    try:
        await coll.insert_one(doc)
        return {"action":      "inserted",
                 "movement_id": doc["movement_id"],
                 "external_id": tx_hash}
    except DuplicateKeyError:
        # Either a concurrent tick beat us to it, or the row is already
        # reconciled from a previous run. Both are fine.
        existing = await coll.find_one({"external_id": tx_hash},
                                            {"_id": 0, "movement_id": 1,
                                              "status": 1})
        if existing and existing.get("status") != S_PENDING_DETECTED:
            return {"action":      "already_present",
                     "movement_id": existing.get("movement_id"),
                     "status":      existing.get("status")}
        return {"action":      "duplicate_skipped",
                 "movement_id": (existing or {}).get("movement_id"),
                 "external_id": tx_hash}


# ---------------------------------------------------------------------------
# Reconciliation (called from staking_sync._upsert_position)
# ---------------------------------------------------------------------------
async def reconcile_usdc_deposit(*, deposit_hash: Optional[str],
                                       memo: Optional[str],
                                       principal: Optional[float],
                                       wallet: Optional[str],
                                       position_id: str,
                                       staking_raw: dict) -> dict[str, Any]:
    """Close a `pending_detected` row tied to a fresh staking record.

    Verified against live CMS (see PR2 audit): `hashDeposito` from
    `/cms/staking` IS the same value as the Stellar tx hash observed by
    the watcher. Hash match is the **primary** path, not a fallback.

    Memo+amount is a fallback for hashDeposito="N/A" or null cases.
    When the fallback matches 2+ pending rows, we DO NOT reconcile —
    we raise an alert and leave the rows in `pending_detected`. Never
    a mass UPDATE.
    """
    coll = col(RAMP_MOVEMENTS)
    update = {
        "$set": {
            "status":                 S_SUCCESS,
            "reconciled_position_id": position_id,
            "reconciled_via":         None,   # filled below
            "reconciled_at":          _iso_now(),
            "updated_at":             _iso_now(),
        }
    }

    # ---- Primary path: external_id == hashDeposito --------------------
    if deposit_hash and deposit_hash != "N/A":
        update["$set"]["reconciled_via"] = "deposit_hash"
        result = await coll.update_one(
            {"external_id": deposit_hash,
              "status":      S_PENDING_DETECTED,
              "asset":       "usdc",
              "provider":    PROVIDER_STELLAR},
            update)
        if result.modified_count:
            logger.info("deposit_engine: reconciled pending_detected via "
                          "hash=%s → position=%s", deposit_hash[:10],
                          position_id)
            # Phase 03 — publish deposit.credited event so subscribers
            # (notifications, future refresh) can react. We MUST read
            # back the row to get org_id/amount/etc.
            await _publish_credited_for_movement(
                external_id=deposit_hash, position_id=position_id,
                staking_raw=staking_raw)
            return {"action": "reconciled_by_hash",
                     "external_id": deposit_hash,
                     "position_id": position_id}

    # ---- Fallback: (memo + principal) — UNIQUE match required ---------
    if memo and principal is not None and wallet:
        amount_str = _format_amount(principal)
        candidates = await coll.find(
            {"status":   S_PENDING_DETECTED,
              "asset":    "usdc",
              "provider": PROVIDER_STELLAR,
              "memo":     str(memo),
              "amount":   amount_str,
              "wallet":   wallet},
            {"_id": 0, "movement_id": 1,
              "external_id": 1}).limit(5).to_list(5)

        if len(candidates) == 1:
            update["$set"]["reconciled_via"] = "memo_amount"
            await coll.update_one(
                {"movement_id": candidates[0]["movement_id"]}, update)
            logger.info("deposit_engine: reconciled pending_detected via "
                          "memo+amount → mov=%s position=%s",
                          candidates[0]["movement_id"], position_id)
            await _publish_credited_for_movement(
                movement_id=candidates[0]["movement_id"],
                position_id=position_id,
                staking_raw=staking_raw)
            return {"action": "reconciled_by_memo_amount",
                     "movement_id": candidates[0]["movement_id"],
                     "position_id": position_id}

        if len(candidates) > 1:
            # AMBIGUITY: do NOT touch any row. Alert + leave in pending.
            await _alert_ambiguous_deposit_reconcile(
                wallet=wallet, memo=str(memo), amount=amount_str,
                position_id=position_id, staking_raw=staking_raw,
                candidate_ids=[c["movement_id"] for c in candidates])
            return {"action": "ambiguous_skipped",
                     "candidate_count": len(candidates),
                     "candidate_movement_ids":
                         [c["movement_id"] for c in candidates]}

    return {"action": "no_match"}


def _format_amount(principal: float) -> str:
    """Stellar amounts are always rendered with 7 decimals in Horizon.
    The watcher stores `payment.amount` verbatim from Horizon (string),
    so to match it from a CMS-side float we replicate that format."""
    return f"{float(principal):.7f}"


async def _publish_credited_for_movement(*,
                                              external_id: str | None = None,
                                              movement_id: str | None = None,
                                              position_id: str,
                                              staking_raw: dict
                                              ) -> None:
    """Phase 03 — publish a `deposit.credited` event for a USDC movement
    that just transitioned `pending_detected → Success`.

    Soft-fail. The reconciliation itself is the source of truth for
    accounting; the event is observability + notifications. A failed
    publish must never roll back the reconciliation.
    """
    try:
        coll = col(RAMP_MOVEMENTS)
        query = ({"external_id": external_id} if external_id
                    else {"movement_id": movement_id})
        mv = await coll.find_one(query, {"_id": 0})
        if not mv:
            logger.warning("deposit_engine: publish skipped — movement not "
                              "found for query=%s", query)
            return
        from services.event_bus import publish
        await publish({
            "event_type":  "deposit.credited",
            "version":     1,
            "event_id":    f"evt_dep_usdc_{mv['external_id']}",
            "asset":       "usdc",
            "deposit_id":  mv["external_id"],
            "tx_hash":     mv["external_id"],
            "org_id":      mv.get("org_id"),
            "user_id":     None,
            "amount":      mv.get("amount"),
            "currency":    "USDC",
            "ref":         mv.get("memo"),
            "occurred_at": mv.get("on_chain_at") or mv.get("detected_at"),
            "detected_at": mv.get("detected_at"),
            "source":      "stellar_watcher",
            "metadata": {
                "wallet":      mv.get("wallet"),
                "modality":    mv.get("modality"),
                "position_id": position_id,
                "from_address": mv.get("from_address"),
                "staking_id":  staking_raw.get("id"),
            },
        })
    except Exception:  # noqa: BLE001
        logger.exception("deposit_engine: deposit.credited publish failed "
                            "(non-blocking) for position=%s", position_id)



async def _alert_ambiguous_deposit_reconcile(*, wallet: str, memo: str,
                                                  amount: str,
                                                  position_id: str,
                                                  staking_raw: dict,
                                                  candidate_ids: list[str]
                                                  ) -> None:
    """Raise an operational alert when 2+ pending deposits could match
    the same staking by (memo, amount). Operator must resolve."""
    await col(ALERTS).insert_one({
        "alert_id":    "al_dep_amb_" + secrets.token_hex(5),
        "type":        "operational",
        "severity":    "warning",
        "title":       "Reconciliación USDC ambigua · staking sin atribución",
        "description": (
            f"Llegó un staking USDC contra {wallet[:10]}… con memo={memo} "
            f"amount={amount} pero hay {len(candidate_ids)} pending_detected "
            f"que matchean. Sin hashDeposito el matcheo es ambiguo. "
            f"Resolvé manualmente cuál ramp_movements pertenece a este "
            f"staking (position={position_id})."),
        "status":      "open",
        "context": {
            "wallet":          wallet,
            "memo":            memo,
            "amount":          amount,
            "position_id":     position_id,
            "staking_id":      staking_raw.get("id"),
            "staking_hash":    staking_raw.get("hashStaking"),
            "hash_deposito":   staking_raw.get("hashDeposito"),
            "candidate_movement_ids": candidate_ids,
        },
        "created_at":  _iso_now(),
        "updated_at":  _iso_now(),
        "is_deleted":  False,
    })


# ---------------------------------------------------------------------------
# Orphan sweep
# ---------------------------------------------------------------------------
async def sweep_orphans() -> dict[str, Any]:
    """Flip `pending_detected` rows older than the orphan timeout to
    `orphan_detected` and raise alerts.

    The timeout is **always >= RECLAIM_WINDOW_MINUTES + 30** — enforced
    by `_orphan_timeout_minutes()`. This guarantees we never flag a
    deposit that the staking_sync reclaim path could still resolve.
    """
    timeout = _orphan_timeout_minutes()
    cutoff = (datetime.now(timezone.utc)
                - timedelta(minutes=timeout)).isoformat()

    coll = col(RAMP_MOVEMENTS)
    rows = await coll.find(
        {"status":     S_PENDING_DETECTED,
         "asset":      "usdc",
         "provider":   PROVIDER_STELLAR,
         "detected_at": {"$lt": cutoff}},
        {"_id": 0}).to_list(500)

    if not rows:
        return {"flipped": 0, "timeout_minutes": timeout}

    flipped = 0
    for row in rows:
        result = await coll.update_one(
            {"movement_id": row["movement_id"],
              "status":      S_PENDING_DETECTED},
            {"$set": {"status":     S_ORPHAN_DETECTED,
                         "orphan_at":  _iso_now(),
                         "updated_at": _iso_now()}})
        if not result.modified_count:
            continue  # raced with reconciliation — that's fine
        flipped += 1
        await col(ALERTS).insert_one({
            "alert_id":    "al_dep_orphan_" + secrets.token_hex(5),
            "type":        "operational",
            "severity":    "warning",
            "title":       "USDC sin staking (probable memo inválido)",
            "description": (
                f"Un depósito USDC de {row.get('amount')} a {row.get('wallet','')[:10]}… "
                f"sigue sin matchear con /cms/staking después de {timeout} min. "
                f"Probable memo inválido o transferencia sin contractar. "
                f"NO se acreditó ningún balance — el saldo on-chain ya es "
                f"verdad por Horizon. Verificá con el cliente."),
            "org_id":      row.get("org_id"),
            "status":      "open",
            "context": {
                "movement_id":  row["movement_id"],
                "wallet":       row.get("wallet"),
                "memo":         row.get("memo"),
                "amount":       row.get("amount"),
                "tx_hash":      row.get("external_id"),
                "on_chain_at":  row.get("on_chain_at"),
                "detected_at":  row.get("detected_at"),
            },
            "created_at":  _iso_now(),
            "updated_at":  _iso_now(),
            "is_deleted":  False,
        })
    logger.info("deposit_engine: swept %d orphan(s) past %dmin timeout",
                  flipped, timeout)
    return {"flipped": flipped, "timeout_minutes": timeout,
             "rows_inspected": len(rows)}


# ---------------------------------------------------------------------------
# Read helpers (admin endpoints)
# ---------------------------------------------------------------------------
async def list_orphans(limit: int = 50) -> list[dict[str, Any]]:
    return await col(RAMP_MOVEMENTS).find(
        {"status": S_ORPHAN_DETECTED, "asset": "usdc"},
        {"_id": 0}).sort("orphan_at", -1).limit(limit).to_list(limit)


async def list_pending(limit: int = 50) -> list[dict[str, Any]]:
    return await col(RAMP_MOVEMENTS).find(
        {"status": S_PENDING_DETECTED, "asset": "usdc"},
        {"_id": 0}).sort("detected_at", -1).limit(limit).to_list(limit)


async def counts() -> dict[str, int]:
    coll = col(RAMP_MOVEMENTS)
    return {
        "pending_detected": await coll.count_documents(
            {"status": S_PENDING_DETECTED, "asset": "usdc"}),
        "orphan_detected":  await coll.count_documents(
            {"status": S_ORPHAN_DETECTED, "asset": "usdc"}),
        "success_reconciled": await coll.count_documents(
            {"status": S_SUCCESS, "asset": "usdc",
              "provider": PROVIDER_STELLAR,
              "reconciled_position_id": {"$exists": True}}),
    }
