"""Admin endpoints — Deposit Detection Engine (PR2).

Read-only health + orphan list + manual reconciliation. Gated by the
admin role guard (same pattern as other `/api/v1/admin/*` routes).

Endpoints:
  * GET    /api/v1/admin/deposits/health          → engine status snapshot
  * GET    /api/v1/admin/deposits/orphans         → list orphan_detected rows
  * GET    /api/v1/admin/deposits/pending         → list pending_detected rows
  * POST   /api/v1/admin/deposits/{mid}/reconcile → bind a movement to a
                                                       position (operator-driven,
                                                       for unresolved ambiguity)
  * POST   /api/v1/admin/deposits/tick            → force a single watcher tick
                                                       (debugging only)
  * POST   /api/v1/admin/deposits/migrations/run  → apply unique-sparse migration
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from auth import CurrentUser, requires_role
from db import POSITIONS, RAMP_MOVEMENTS, col
from jobs.deposit_watcher import (health_snapshot, run_tick_once)
from services.deposit_engine import (list_orphans, list_pending,
                                          PROVIDER_STELLAR,
                                          S_PENDING_DETECTED, S_SUCCESS,
                                          S_ORPHAN_DETECTED)

logger = logging.getLogger("prosper.routes.admin_deposits")
router = APIRouter(prefix="/admin/deposits",
                    tags=["admin · deposits"])

_ADMIN_ROLES = ("super_admin", "ops_admin", "compliance_officer", "finance")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/health")
async def deposits_health(
    _user: CurrentUser = Depends(requires_role(*_ADMIN_ROLES))):
    """Snapshot of the engine — cursor, wallet count, status counts."""
    return await health_snapshot()


@router.get("/orphans")
async def deposits_orphans(
    limit: int = 50,
    _user: CurrentUser = Depends(requires_role(*_ADMIN_ROLES))):
    """USDC deposits that landed on-chain but never matched a /cms/staking
    record within the orphan timeout window."""
    limit = max(1, min(int(limit or 50), 200))
    return {"items": await list_orphans(limit), "count_limit": limit}


@router.get("/pending")
async def deposits_pending(
    limit: int = 50,
    _user: CurrentUser = Depends(requires_role(*_ADMIN_ROLES))):
    """USDC deposits detected on-chain but not yet reconciled with CMS.
    Most rows here are normal (CMS will process them shortly). Rows
    older than the orphan timeout become `orphan_detected`."""
    limit = max(1, min(int(limit or 50), 200))
    return {"items": await list_pending(limit), "count_limit": limit}


@router.post("/{movement_id}/reconcile")
async def deposits_reconcile_manual(
    movement_id: str,
    position_id: str,
    user: CurrentUser = Depends(requires_role(*_ADMIN_ROLES))):
    """Operator-driven binding of a `pending_detected` or `orphan_detected`
    movement to an existing position. Used when automatic reconciliation
    was skipped due to ambiguity. NEVER touches the position's principal
    or balance — only adds the cross-reference.
    """
    mov = await col(RAMP_MOVEMENTS).find_one(
        {"movement_id": movement_id, "asset": "usdc",
         "provider":   PROVIDER_STELLAR}, {"_id": 0})
    if not mov:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                              detail="movement_not_found")
    if mov.get("status") not in (S_PENDING_DETECTED, S_ORPHAN_DETECTED):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                              detail=f"cannot_reconcile_status_{mov.get('status')}")

    pos = await col(POSITIONS).find_one(
        {"position_id": position_id, "is_deleted": {"$ne": True}},
        {"_id": 0, "position_id": 1, "org_id": 1})
    if not pos:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                              detail="position_not_found")

    await col(RAMP_MOVEMENTS).update_one(
        {"movement_id": movement_id},
        {"$set": {
            "status":                 S_SUCCESS,
            "reconciled_position_id": position_id,
            "reconciled_via":         "manual",
            "reconciled_by":          user.user_id,
            "reconciled_at":          _now(),
            "updated_at":             _now(),
        }})
    logger.info("admin manually reconciled deposit %s → position %s "
                  "(by user %s)", movement_id, position_id, user.user_id)
    return {"ok": True, "movement_id": movement_id,
             "position_id": position_id}


@router.post("/tick")
async def deposits_force_tick(
    _user: CurrentUser = Depends(requires_role("super_admin", "ops_admin"))):
    """Debug-only: force a single watcher tick. Idempotent."""
    return await run_tick_once()


@router.post("/migrations/run")
async def deposits_run_migration(
    _user: CurrentUser = Depends(requires_role("super_admin"))):
    """Apply the unique-sparse migration on `ramp_movements.external_id`.
    Refuses to run if duplicates exist. Callable independently of the
    engine flag so operators can prep prod before flipping it on."""
    from jobs.deposit_engine_migrations import run as run_migration
    return await run_migration()
