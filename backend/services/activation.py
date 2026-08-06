"""Two-gate activation policy for individual onboarding (orden b · andes-direct).

A client becomes "operative" only when BOTH gates are green:

    gate 1 — IDENTITY (Andes KYC)
        org.andes_kyc_status = "approved"
        ramp_account.cvu      not null
        ramp_account.onboarding_status in ("approved", "completed")

    gate 2 — SANCTIONS / PEP
        org.sanctions_status  = "clear"

`org.kyb_status` ("approved") = full activation = BOTH gates green.

A client whose identity has been approved by Andes but whose sanctions
screening is still `pending` (or `flagged`) sits in `kyb_status="pending"`
with `andes_kyc_status="approved"` and is NOT operative. The frontend
client-gate banner already understands this triple-state.

This module is the ONLY place that performs the activation transition.
Called from:

  * `routes/onboarding.upload_kyc_docs_individual`  — when Andes returns
    `onboarding_status=approved` synchronously in the multipart upload.
  * `routes/ramp_webhook._handle_fiat_account_created` — when Andes sends
    the webhook later (or always, for the async path).

Both call sites converge on this helper so the race condition described in
the diagnostic is gone: there is one activation policy, executed in one
place, and it is idempotent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from db import (
    col, ORGANIZATIONS, RAMP_ACCOUNTS, SANCTIONS_SCREENINGS,
    TRAVEL_RULE_SCREENINGS, USERS,
)

logger = logging.getLogger("prosper.activation")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def on_identity_approved(
    *,
    org_id: str,
    andes_user_id: Optional[str] = None,
    cvu: Optional[str] = None,
    alias: Optional[str] = None,
    fiat_account_id: Optional[str] = None,
    source: str = "unknown",
) -> dict:
    """Idempotent identity-gate transition.

    1. Mark `org.andes_kyc_status='approved'` (without touching `kyb_status`).
    2. If CVU/alias provided, persist them on the org's `ramp_account` and
       bump `cvu_status='completed'` / `onboarding_status='approved'`.
    3. Enqueue a sanctions/PEP screening (idempotent — re-using an
       existing row if one exists).
    4. If the screening is already `clear` (e.g. real provider auto-cleared
       OR a compliance officer already decided clear before the webhook
       arrived), promote the org to `kyb_status='approved'` and activate
       the client_admin user. Otherwise leave kyb_status untouched — the
       sanctions decision endpoint will run the same activation when the
       human (or real provider) marks the screening `clear`.

    Returns the current state so callers can include it in their response.
    """
    org_doc = await col(ORGANIZATIONS).find_one(
        {"org_id": org_id}, {"_id": 0}) or {}
    if not org_doc:
        logger.warning("activation: org %s not found", org_id)
        return {"ok": False, "reason": "org_not_found"}

    if org_doc.get("type") != "personal":
        # Business/KYB activation is governed by the AiPrise webhook handler.
        return {"ok": True, "skipped": "not_personal_type"}

    iso = _now_iso()

    # ── 1) Identity gate is now green ──────────────────────────────────
    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {"andes_kyc_status": "approved",
                    "andes_kyc_approved_at": iso,
                    "updated_at": iso}})

    # ── 2) Persist CVU/alias on the ramp_account (if not already there) ─
    if cvu or alias or andes_user_id:
        ra_patch: dict = {"updated_at": iso}
        if cvu:
            ra_patch["cvu"] = cvu
        if alias:
            ra_patch["alias"] = alias
        if cvu:
            ra_patch["cvu_status"] = "completed"
        ra_patch["onboarding_status"] = "approved"
        # Match by org_id; provider_user_id is also a valid key if present
        ra_filter: dict = {"org_id": org_id, "is_deleted": False}
        if andes_user_id:
            ra_filter = {"$or": [
                {"org_id": org_id, "is_deleted": False},
                {"provider_user_id": andes_user_id, "is_deleted": False},
            ]}
        await col(RAMP_ACCOUNTS).update_many(ra_filter, {"$set": ra_patch})

    # ── 3) Enqueue sanctions + travel-rule screenings (idempotent) ─────
    legal_name  = org_doc.get("legal_name") or "—"
    cuit        = org_doc.get("_indiv_cuit")
    birthdate   = org_doc.get("_indiv_birthdate")
    try:
        from routes.sanctions import enqueue_screening as enqueue_sanctions
        await enqueue_sanctions(
            org_id=org_id, subject_type="individual",
            full_name=legal_name, cuit=cuit, birthdate=birthdate,
            country=org_doc.get("country", "AR"))
    except Exception as e:
        logger.exception("activation: sanctions enqueue failed: %s", e)
    try:
        from routes.travel_rule import enqueue_screening as enqueue_travel_rule
        await enqueue_travel_rule(
            org_id=org_id, subject_type="individual",
            full_name=legal_name, cuit=cuit,
            country=org_doc.get("country", "AR"))
    except Exception as e:
        logger.exception("activation: travel-rule enqueue failed: %s", e)

    # ── 4) Conditional full activation ─────────────────────────────────
    # Re-read both gates post-enqueue (real providers may have flipped
    # them inside enqueue_screening).
    fresh_org = await col(ORGANIZATIONS).find_one(
        {"org_id": org_id},
        {"_id": 0, "sanctions_status": 1, "kyb_status": 1,
         "travel_rule_status": 1}) or {}
    sanctions_ok   = fresh_org.get("sanctions_status") == "clear"
    travel_rule_ok = fresh_org.get("travel_rule_status") in ("clear", "na")
    both_gates_ok  = sanctions_ok and travel_rule_ok

    activated = False
    # Phase 22+ — Audit fields for individual KYC. These keep parity with
    # what the deprecated AiPrise path used to write so admin tools that
    # read `users.kyc_decision` / `kyc_decided_at` / `kyc_raw` keep working
    # for Andes-activated individuals.
    kyc_audit_payload = {
        "source":           "andes",
        "andes_user_id":    andes_user_id,
        "fiat_account_id":  fiat_account_id,
        "decided_at":       iso,
    }
    if both_gates_ok and fresh_org.get("kyb_status") != "approved":
        await col(ORGANIZATIONS).update_one(
            {"org_id": org_id},
            {"$set": {"kyb_status": "approved", "updated_at": iso}})
        await col(USERS).update_many(
            {"org_id": org_id, "role": "client_admin"},
            {"$set": {"status": "active",
                        "kyc_status":     "approved",
                        "kyc_decision":   "approved",
                        "kyc_decided_at": iso,
                        "kyc_raw":        kyc_audit_payload,
                        "updated_at":     iso}})
        activated = True
        logger.info("activation: %s → kyb_status=approved (3 gates green, "
                       "source=%s)", org_id, source)
        # Provision the Prosper wallet eagerly to match the old AiPrise
        # behaviour. The invest hot path already calls this lazily but
        # provisioning now avoids a first-invest latency spike.
        try:
            from routes.onramp_flow import ensure_org_prosper_wallet
            await ensure_org_prosper_wallet(org_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("activation: prosper wallet provisioning failed "
                           "for %s: %s", org_id, e)
    else:
        await col(USERS).update_many(
            {"org_id": org_id, "role": "client_admin"},
            {"$set": {"kyc_status":     "approved",
                        "kyc_decision":   "approved",
                        "kyc_decided_at": iso,
                        "kyc_raw":        kyc_audit_payload,
                        "updated_at":     iso}})
        logger.info("activation: %s → andes_kyc=approved, sanctions=%s, "
                       "travel_rule=%s, kyb held at %s (source=%s)",
                       org_id, fresh_org.get("sanctions_status"),
                       fresh_org.get("travel_rule_status"),
                       fresh_org.get("kyb_status"), source)

    return {
        "ok": True,
        "org_id": org_id,
        "andes_kyc_status":   "approved",
        "sanctions_status":   fresh_org.get("sanctions_status"),
        "travel_rule_status": fresh_org.get("travel_rule_status"),
        "kyb_status":         "approved" if activated else fresh_org.get("kyb_status"),
        "activated":          activated,
        "source":             source,
    }
