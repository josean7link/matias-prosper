"""Sanctions / PEP screening admin endpoints.

Workflow:

  1. After Andes emits `fiat.account.created`, `_handle_fiat_account_created`
     calls `enqueue_screening(org_id, …)` which inserts a SANCTIONS_SCREENINGS
     row in `pending` and (in manual mode) leaves it for compliance to
     resolve from the admin UI. The org's `sanctions_status` is set to
     `pending` so the client gate keeps them out of the portal.

  2. Super_admin / compliance officer hits this router:
       GET  /api/v1/admin/sanctions/queue?status=pending
       POST /api/v1/admin/sanctions/{org_id}/decision  {decision, reason}

  3. POST decision flips `organizations.sanctions_status` and:
       - clear  → if Andes already approved (CVU emitted), activate the
                  org+client_admin (mirror of `_handle_fiat_account_created`
                  post-Andes activation).
       - flagged → set kyb_status=rejected, deactivate users. Compliance
                   contacts the client.

  4. All decisions are written to audit_logs with the actor email.

Adapter pattern: real providers (ComplyAdvantage, Truora …) implement
`SanctionsProvider.screen()`; once they auto-return `clear/flagged`, the
queue empties on its own and this admin UI becomes the exception path.
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
from db import col, ORGANIZATIONS, SANCTIONS_SCREENINGS, USERS
from integrations.sanctions import (
    ScreeningResult, ScreeningSubject, get_provider,
)
from roles import Role

logger = logging.getLogger("prosper.sanctions")
router = APIRouter(prefix="/admin/sanctions", tags=["admin-sanctions"])

require_admin = requires_role(Role.super_admin, Role.admin,
                                Role.compliance_officer)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public helper (called from ramp_webhook + onboarding)
# ---------------------------------------------------------------------------
async def enqueue_screening(
    *, org_id: str,
    subject_type: Literal["individual", "business"],
    full_name: str,
    cuit: Optional[str] = None,
    birthdate: Optional[str] = None,
    country: str = "AR",
) -> dict:
    """Create or refresh a screening row and (if provider supports it) execute
    a synchronous screen call. Always returns the persisted row.

    Idempotent: re-calling on an existing (org_id, subject_type) row reuses
    it. The org's `sanctions_status` is mirrored from the row's status.
    """
    provider = get_provider()
    existing = await col(SANCTIONS_SCREENINGS).find_one(
        {"org_id": org_id, "subject_type": subject_type}, {"_id": 0})
    result: ScreeningResult = await provider.screen(ScreeningSubject(
        subject_type=subject_type, org_id=org_id, full_name=full_name,
        cuit=cuit, birthdate=birthdate, country=country))

    iso = _now()
    if existing:
        # Only auto-overwrite if the new result is conclusive (clear/flagged)
        # AND the existing status is still pending. Once a human (or a real
        # provider) decided, we never silently overwrite.
        if existing["status"] == "pending" and result.status != "pending":
            patch = {
                "status": result.status,
                "reason": result.reason,
                "provider": result.provider,
                "raw": result.raw,
                "decided_by": "system:auto",
                "decided_at": iso,
                "updated_at": iso,
            }
            await col(SANCTIONS_SCREENINGS).update_one(
                {"screening_id": existing["screening_id"]}, {"$set": patch})
            await col(ORGANIZATIONS).update_one(
                {"org_id": org_id},
                {"$set": {"sanctions_status": result.status,
                            "updated_at": iso}})
            return {**existing, **patch}
        return existing

    row = {
        "screening_id":  "scr_" + secrets.token_hex(6),
        "org_id":        org_id,
        "subject_type":  subject_type,
        "subject_name":  full_name,
        "subject_cuit":  cuit,
        "subject_birthdate": birthdate,
        "country":       country,
        "status":        result.status,
        "reason":        result.reason,
        "provider":      result.provider,
        "raw":           result.raw,
        "decided_by":    "system:auto" if result.status != "pending" else None,
        "decided_at":    iso if result.status != "pending" else None,
        "created_at":    iso,
        "updated_at":    iso,
    }
    await col(SANCTIONS_SCREENINGS).insert_one(dict(row))
    # Mirror into org for the activation gate
    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {"sanctions_status": result.status, "updated_at": iso}})

    await log_action(actor=None,
                       action="sanctions.screening.enqueued",
                       resource_type="sanctions_screening",
                       resource_id=row["screening_id"],
                       org_id_override=org_id,
                       metadata={"provider": result.provider,
                                  "status": result.status,
                                  "subject_type": subject_type})
    return row


# ---------------------------------------------------------------------------
# Admin queue + decision
# ---------------------------------------------------------------------------
class DecisionIn(BaseModel):
    decision: Literal["clear", "flagged"]
    reason:   str = Field(min_length=2, max_length=500)


@router.get("/queue")
async def queue(
    user: CurrentUser = Depends(require_admin),
    status: Optional[Literal["pending", "clear", "flagged"]] = Query("pending"),
    limit: int = Query(100, ge=1, le=500),
):
    q: dict = {} if not status else {"status": status}
    cur = col(SANCTIONS_SCREENINGS).find(q, {"_id": 0}) \
                                       .sort("created_at", -1) \
                                       .limit(limit)
    rows = await cur.to_list(None)

    # Join with the org so the UI can show legal_name + country
    org_ids = [r["org_id"] for r in rows]
    orgs = {}
    if org_ids:
        async for o in col(ORGANIZATIONS).find(
                {"org_id": {"$in": org_ids}},
                {"_id": 0, "org_id": 1, "legal_name": 1, "country": 1,
                 "kyb_status": 1, "type": 1, "sanctions_status": 1}):
            orgs[o["org_id"]] = o

    for r in rows:
        r["organization"] = orgs.get(r["org_id"])
    return {"items": rows, "count": len(rows)}


@router.get("/{org_id}")
async def get_one(org_id: str, user: CurrentUser = Depends(require_admin)):
    row = await col(SANCTIONS_SCREENINGS).find_one({"org_id": org_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, "No screening for this org")
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id}, {"_id": 0})
    return {"screening": row, "organization": org}


# ---------------------------------------------------------------------------
# Shared decision applier (used by both `/decision` and KYC manual-override)
# ---------------------------------------------------------------------------
async def apply_sanctions_decision(
    *, org_id: str, decision: str, reason: str,
    actor_email: str, actor_id: str,
    resolution: str,
) -> dict:
    """Apply a sanctions/PEP decision to an org.

    `resolution` tracks HOW the decision was made — used to distinguish a
    real provider auto-decision vs a compliance officer's call vs an
    admin's manual override while no real provider is connected:

        resolution = 'real_provider'    # ComplyAdvantage/Truora auto-cleared
                     'manual_decision'  # compliance officer via sanctions queue
                     'manual_override'  # super_admin/finance bypass from KYC drawer
                                        #   while SANCTIONS_PROVIDER=manual
    """
    row = await col(SANCTIONS_SCREENINGS).find_one({"org_id": org_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, "No screening for this org")
    if row["status"] != "pending":
        raise HTTPException(409,
            f"Screening already decided (status={row['status']}). "
            f"Open a new case if circumstances changed.")

    iso = _now()
    patch = {
        "status":     decision,
        "reason":     reason,
        "decided_by": actor_email,
        "decided_at": iso,
        "resolution": resolution,
        "updated_at": iso,
    }
    await col(SANCTIONS_SCREENINGS).update_one(
        {"screening_id": row["screening_id"]}, {"$set": patch})

    # Mirror to org gate
    org_patch: dict = {"sanctions_status": decision, "updated_at": iso}
    if decision == "flagged":
        org_patch["kyb_status"] = "rejected"
        await col(USERS).update_many(
            {"org_id": org_id, "role": {"$in": ["client_admin", "client_user"]}},
            {"$set": {"status": "paused", "updated_at": iso}})
    await col(ORGANIZATIONS).update_one({"org_id": org_id}, {"$set": org_patch})

    # If clear → delegate to the unified activation helper. It re-checks
    # the Andes gate (CVU emitted + andes_kyc_status=approved) and only
    # promotes kyb_status when BOTH gates green.
    if decision == "clear":
        try:
            from services.activation import on_identity_approved
            await on_identity_approved(
                org_id=org_id,
                source=f"sanctions.{resolution}")
        except Exception as e:
            logger.exception("activation post-clear failed: %s", e)

    # Audit log — the resolution + reason are persisted forever
    audit_action = f"sanctions.{decision}"
    if resolution == "manual_override":
        audit_action = f"sanctions.manual_override.{decision}"
    await log_action(
        actor=None,  # passed explicitly below
        action=audit_action,
        resource_type="sanctions_screening",
        resource_id=row["screening_id"],
        org_id_override=org_id,
        metadata={
            "decision":   decision,
            "reason":     reason,
            "resolution": resolution,
            "actor_id":   actor_id,
            "actor_email": actor_email,
            "subject_name": row.get("subject_name"),
            "subject_cuit": row.get("subject_cuit"),
        })
    return {"ok": True, "status": decision, "resolution": resolution}


@router.post("/{org_id}/decision")
async def post_decision(
    org_id: str,
    body: DecisionIn = Body(...),
    user: CurrentUser = Depends(require_admin),
):
    return await apply_sanctions_decision(
        org_id=org_id, decision=body.decision, reason=body.reason,
        actor_email=user.email, actor_id=user.user_id,
        resolution="manual_decision")
