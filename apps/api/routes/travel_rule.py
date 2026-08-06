"""Travel Rule (FATF / UIF) screening admin endpoints.

Same shape as sanctions: queue + decision + manual-override resolution.
The activation gate (`services.activation.on_identity_approved`) requires
`travel_rule_status` to be `clear` or `na` BEFORE promoting an org to
`kyb_status=approved`.

States:
  pending  → default; gate blocks the org from operating
  clear    → VASP travel-rule data complete, customer can transact
  na       → customer below FATF threshold / not applicable → also unblocks
  flagged  → compliance issue → org rejected, user paused

Resolution:
  real_provider    → ComplyAdvantage / Notabene / Sumsub auto-cleared
  manual_decision  → compliance officer via the dedicated queue (future)
  manual_override  → super_admin / finance bypass from KYC drawer while
                     TRAVEL_RULE_PROVIDER=manual
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, requires_role
from db import col, ORGANIZATIONS, TRAVEL_RULE_SCREENINGS, USERS
from integrations.travel_rule import (
    TravelRuleResult, TravelRuleSubject, get_provider,
)
from roles import Role

logger = logging.getLogger("prosper.travel_rule")
router = APIRouter(prefix="/admin/travel-rule", tags=["admin-travel-rule"])

require_admin = requires_role(Role.super_admin, Role.admin,
                                Role.compliance_officer)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public helper (called from services.activation)
# ---------------------------------------------------------------------------
async def enqueue_screening(
    *, org_id: str,
    subject_type: Literal["individual", "business"],
    full_name: str,
    cuit: Optional[str] = None,
    country: str = "AR",
    expected_monthly_volume_usd: Optional[float] = None,
) -> dict:
    """Create or refresh a travel-rule screening row. Idempotent."""
    provider = get_provider()
    existing = await col(TRAVEL_RULE_SCREENINGS).find_one(
        {"org_id": org_id, "subject_type": subject_type}, {"_id": 0})
    result: TravelRuleResult = await provider.screen(TravelRuleSubject(
        subject_type=subject_type, org_id=org_id, full_name=full_name,
        cuit=cuit, country=country,
        expected_monthly_volume_usd=expected_monthly_volume_usd))

    iso = _now()
    if existing:
        if existing["status"] == "pending" and result.status != "pending":
            patch = {
                "status": result.status, "reason": result.reason,
                "provider": result.provider, "raw": result.raw,
                "decided_by": "system:auto", "decided_at": iso,
                "updated_at": iso, "resolution": "real_provider",
            }
            await col(TRAVEL_RULE_SCREENINGS).update_one(
                {"screening_id": existing["screening_id"]}, {"$set": patch})
            await col(ORGANIZATIONS).update_one(
                {"org_id": org_id},
                {"$set": {"travel_rule_status": result.status,
                            "updated_at": iso}})
            return {**existing, **patch}
        return existing

    row = {
        "screening_id":  "tr_" + secrets.token_hex(6),
        "org_id":        org_id,
        "subject_type":  subject_type,
        "subject_name":  full_name,
        "subject_cuit":  cuit,
        "country":       country,
        "expected_monthly_volume_usd": expected_monthly_volume_usd,
        "status":        result.status,
        "reason":        result.reason,
        "provider":      result.provider,
        "raw":           result.raw,
        "resolution":    "real_provider" if result.status != "pending" else None,
        "decided_by":    "system:auto" if result.status != "pending" else None,
        "decided_at":    iso if result.status != "pending" else None,
        "created_at":    iso,
        "updated_at":    iso,
    }
    await col(TRAVEL_RULE_SCREENINGS).insert_one(dict(row))
    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {"travel_rule_status": result.status, "updated_at": iso}})

    await log_action(actor=None,
                       action="travel_rule.screening.enqueued",
                       resource_type="travel_rule_screening",
                       resource_id=row["screening_id"],
                       org_id_override=org_id,
                       metadata={"provider": result.provider,
                                  "status": result.status,
                                  "subject_type": subject_type})
    return row


# ---------------------------------------------------------------------------
# Shared decision applier (mirror of sanctions.apply_sanctions_decision)
# ---------------------------------------------------------------------------
async def apply_travel_rule_decision(
    *, org_id: str, decision: str, reason: str,
    actor_email: str, actor_id: str, resolution: str,
) -> dict:
    """Apply a travel-rule decision to an org. `decision` ∈ (clear|na|flagged).

    `resolution`:
      real_provider | manual_decision | manual_override
    """
    if decision not in ("clear", "na", "flagged"):
        raise HTTPException(400, "decision must be one of clear|na|flagged")
    row = await col(TRAVEL_RULE_SCREENINGS).find_one({"org_id": org_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, "No travel-rule screening for this org")
    if row["status"] != "pending":
        raise HTTPException(409,
            f"Travel rule already decided (status={row['status']}). "
            f"Open a new case if circumstances changed.")

    iso = _now()
    patch = {
        "status":     decision, "reason": reason,
        "decided_by": actor_email, "decided_at": iso,
        "resolution": resolution, "updated_at": iso,
    }
    await col(TRAVEL_RULE_SCREENINGS).update_one(
        {"screening_id": row["screening_id"]}, {"$set": patch})

    org_patch: dict = {"travel_rule_status": decision, "updated_at": iso}
    if decision == "flagged":
        # Same lockout pattern as sanctions: hard reject + pause users.
        org_patch["kyb_status"] = "rejected"
        await col(USERS).update_many(
            {"org_id": org_id, "role": {"$in": ["client_admin", "client_user"]}},
            {"$set": {"status": "paused", "updated_at": iso}})
    await col(ORGANIZATIONS).update_one({"org_id": org_id}, {"$set": org_patch})

    # Re-run the activation helper — it will re-check ALL gates and only
    # promote kyb_status if identity + sanctions + travel_rule are all green.
    if decision in ("clear", "na"):
        try:
            from services.activation import on_identity_approved
            await on_identity_approved(
                org_id=org_id,
                source=f"travel_rule.{resolution}")
        except Exception as e:
            logger.exception("activation post-clear failed: %s", e)

    audit_action = f"travel_rule.{decision}"
    if resolution == "manual_override":
        audit_action = f"travel_rule.manual_override.{decision}"
    await log_action(
        actor=None, action=audit_action,
        resource_type="travel_rule_screening",
        resource_id=row["screening_id"], org_id_override=org_id,
        metadata={"decision": decision, "reason": reason,
                   "resolution": resolution,
                   "actor_id": actor_id, "actor_email": actor_email,
                   "subject_name": row.get("subject_name"),
                   "subject_cuit": row.get("subject_cuit")})
    return {"ok": True, "status": decision, "resolution": resolution}


# ---------------------------------------------------------------------------
# Admin queue + decision (mirror of sanctions endpoints)
# ---------------------------------------------------------------------------
class DecisionIn(BaseModel):
    decision: Literal["clear", "na", "flagged"]
    reason:   str = Field(min_length=2, max_length=500)


@router.get("/queue")
async def queue(
    user: CurrentUser = Depends(require_admin),
    status: Optional[Literal["pending", "clear", "na", "flagged"]] = Query("pending"),
    limit: int = Query(100, ge=1, le=500),
):
    q: dict = {} if not status else {"status": status}
    cur = col(TRAVEL_RULE_SCREENINGS).find(q, {"_id": 0}) \
                                         .sort("created_at", -1).limit(limit)
    rows = await cur.to_list(None)
    org_ids = [r["org_id"] for r in rows]
    orgs = {}
    if org_ids:
        async for o in col(ORGANIZATIONS).find(
                {"org_id": {"$in": org_ids}},
                {"_id": 0, "org_id": 1, "legal_name": 1, "country": 1,
                 "kyb_status": 1, "type": 1, "travel_rule_status": 1}):
            orgs[o["org_id"]] = o
    for r in rows:
        r["organization"] = orgs.get(r["org_id"])
    return {"items": rows, "count": len(rows)}


@router.post("/{org_id}/decision")
async def post_decision(
    org_id: str, body: DecisionIn = Body(...),
    user: CurrentUser = Depends(require_admin),
):
    return await apply_travel_rule_decision(
        org_id=org_id, decision=body.decision, reason=body.reason,
        actor_email=user.email, actor_id=user.user_id,
        resolution="manual_decision")
