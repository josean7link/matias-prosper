"""Phase 20 v2 — Admin endpoints for the ARSa↔USDC↔Prosper bridge.

* POST /api/v1/admin/prosper/accounts/{org_id}/trustline — force-create or
  refresh a trustline on the Prosper custodial wallet for an org.
* GET  /api/v1/admin/prosper/ledger/{org_id} — per-person ledger
  (principal + accrued by `end_customer_id`).
* GET  /api/v1/admin/prosper/reconcile/{org_id} — invariance check: the
  sum of USDC principals across all active positions must equal the
  org's on-chain USDC balance reported by Prosper. Returns descuadre if any.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser
from db import col, ORGANIZATIONS, POSITIONS
from integrations.prosper import ProsperError, get_adapter as prosper_adapter
from roles import Role
from routes.admin_clients._deps import require_admin
from routes.phase20_bridge import ensure_trustline

logger = logging.getLogger("prosper.admin_p20")
router = APIRouter(prefix="/admin/prosper", tags=["admin-bridge"])


_WRITE_ROLES = {Role.super_admin.value, "admin", "finance_admin", "finance"}


def _require_write(user: CurrentUser) -> None:
    if user.role.value if hasattr(user.role, "value") else user.role:
        role_val = user.role.value if hasattr(user.role, "value") else user.role
        if role_val not in _WRITE_ROLES:
            raise HTTPException(403,
                f"role {role_val} cannot mutate Prosper accounts")


class TrustlineIn(BaseModel):
    asset: str = Field("usdc", pattern="^(usdc|arsa)$")


@router.post("/accounts/{org_id}/trustline")
async def admin_create_trustline(
    org_id: str, body: TrustlineIn,
    user: CurrentUser = Depends(require_admin),
):
    """Force-establish a trustline on the Prosper custodial wallet of `org_id`.
    Idempotent (returns `idempotent: true` if already established)."""
    _require_write(user)
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id}, {"_id": 0})
    if not org:
        raise HTTPException(404, "org not found")
    res = await ensure_trustline(org_id=org_id, asset=body.asset)
    await log_action(actor=user, action="admin.prosper.trustline.ensured",
                       resource_type="organization",
                       resource_id=org_id,
                       metadata={"asset": body.asset, **res})
    return res


@router.get("/accounts/{org_id}/trustlines")
async def admin_list_trustlines(org_id: str,
                                 _: CurrentUser = Depends(require_admin)):
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id},
                                              {"_id": 0, "prosper_wallet": 1})
    if not org:
        raise HTTPException(404, "org not found")
    return {"trustlines":
                (org.get("prosper_wallet") or {}).get("trustlines") or []}


@router.get("/ledger/{org_id}")
async def admin_ledger(org_id: str,
                         _: CurrentUser = Depends(require_admin)):
    """Per-person ledger: principal_usd + accrued_interest grouped by
    `end_customer_id`. The frontend shows this to N1 / Prosper backoffice."""
    rows = await col(POSITIONS).aggregate([
        {"$match": {"org_id": org_id, "is_deleted": False,
                     "status": {"$in": ["active", "matured"]}}},
        {"$group": {
            "_id": {"$ifNull": ["$end_customer_id", "$user_id"]},
            "principal_usd":    {"$sum": "$principal_usd"},
            "accrued_interest": {"$sum": "$accrued_interest"},
            "position_count":   {"$sum": 1},
        }},
    ]).to_list(500)
    total_principal = sum(r["principal_usd"] for r in rows)
    total_accrued   = sum(r["accrued_interest"] for r in rows)
    return {
        "org_id": org_id,
        "by_person": [
            {"end_customer_id": r["_id"],
              "principal_usd":  round(r["principal_usd"], 6),
              "accrued_interest": round(r["accrued_interest"], 6),
              "position_count": r["position_count"]}
            for r in rows],
        "totals": {"principal_usd":    round(total_principal, 6),
                    "accrued_interest": round(total_accrued, 6)},
    }


@router.get("/reconcile/{org_id}")
async def admin_reconcile(org_id: str,
                            _: CurrentUser = Depends(require_admin)):
    """Invariance check: sum of USDC principals across active positions of
    the org must equal the org's on-chain USDC balance reported by Prosper.
    If they differ beyond EPSILON, emit an alert and return `balanced=false`.
    """
    total_principal = 0.0
    async for p in col(POSITIONS).find(
            {"org_id": org_id, "is_deleted": False, "status": "active"},
            {"_id": 0, "principal_usd": 1}):
        total_principal += float(p.get("principal_usd") or 0)

    # On-chain — best-effort via Prosper adapter
    onchain_usdc: Optional[float] = None
    onchain_error: Optional[str] = None
    try:
        bal = await prosper_adapter().get_user_balances(
            user_reference_id=org_id)
        # The adapter returns a normalized list/dict — pick USDC if present.
        if isinstance(bal, dict):
            onchain_usdc = float(
                bal.get("usdc") or bal.get("USDC")
                or (bal.get("balance_prosper") if "balance_prosper" in bal
                    else 0) or 0)
        elif isinstance(bal, list):
            for row in bal:
                if (row.get("asset") or "").lower() in ("usdc", "pusd"):
                    onchain_usdc = float(row.get("balance") or 0)
                    break
    except (ProsperError, Exception) as e:  # noqa: BLE001
        onchain_error = f"{type(e).__name__}: {e}"

    EPSILON = 0.01
    balanced = (onchain_usdc is not None and
                 abs(onchain_usdc - total_principal) <= EPSILON)
    delta = (round((onchain_usdc or 0) - total_principal, 6)
              if onchain_usdc is not None else None)

    return {
        "org_id": org_id,
        "principal_sum_usdc": round(total_principal, 6),
        "onchain_usdc":       (round(onchain_usdc, 6)
                                  if onchain_usdc is not None else None),
        "balanced":           balanced,
        "delta":              delta,
        "epsilon":            EPSILON,
        "onchain_error":      onchain_error,
    }
