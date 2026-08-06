"""Phase 3 — AiPrise webhook handlers (HMAC-SHA256 verified)."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request

from audit import log_action
from db import col, ORGANIZATIONS, ONBOARDING_APPLICATIONS, USERS, WEBHOOK_EVENTS
from integrations import aiprise
from models import utc_now

logger = logging.getLogger("prosper.aiprise.webhook")
router = APIRouter(prefix="/webhooks/aiprise", tags=["webhooks"])


def _decision_to_kyb_status(decision: str) -> str:
    return {
        "approved":       "approved",
        "rejected":       "rejected",
        "pending_review": "in_review",
        "in_review":      "in_review",
    }.get(decision, "in_review")


def _decision_to_kyc_status(decision: str) -> str:
    return {
        "approved":       "approved",
        "rejected":       "rejected",
        "pending_review": "in_review",
        "in_review":      "in_review",
    }.get(decision, "in_review")


# ---------------------------------------------------------------------------
# Public functions reused by /onboarding/apply/simulate
# ---------------------------------------------------------------------------
async def _apply_kyb_decision(*, session_id: str, decision: str,
                              raw_payload: dict) -> dict:
    app_doc = await col(ONBOARDING_APPLICATIONS).find_one(
        {"aiprise_session_id": session_id, "is_deleted": False}, {"_id": 0})
    if not app_doc:
        raise HTTPException(404, f"No application for session {session_id}")

    new_kyb = _decision_to_kyb_status(decision)
    new_status = "approved" if new_kyb == "approved" else (
        "rejected" if new_kyb == "rejected" else "in_review")

    await col(ONBOARDING_APPLICATIONS).update_one(
        {"application_id": app_doc["application_id"]},
        {"$set": {
            "kyb_status":    new_kyb,
            "status":        new_status,
            "decision":      decision,
            "decision_at":   utc_now(),
            "decision_raw":  raw_payload,
            "updated_at":    utc_now(),
        }},
    )
    await col(ORGANIZATIONS).update_one(
        {"org_id": app_doc["org_id"]},
        {"$set": {"kyb_status": new_kyb, "updated_at": utc_now()}},
    )

    # Sprint 12.4 — Provision the Prosper wallet for the org immediately
    # on approval. Best-effort: if Prosper is down we just log + continue;
    # the lazy `ensure_org_prosper_wallet` call from the onramp flow will
    # retry the next time the client tries to operate.
    if new_kyb == "approved":
        from routes.onramp_flow import ensure_org_prosper_wallet
        try:
            await ensure_org_prosper_wallet(app_doc["org_id"])
        except Exception as e:  # noqa: BLE001
            logger_ = __import__("logging").getLogger("prosper.kyb")
            logger_.warning("KYB approved but Prosper wallet provisioning "
                              "failed for org=%s: %s — will retry lazily.",
                              app_doc["org_id"], e)

        # Phase 22+ — auto-provision the Andes ramp account (account +
        # wallet ARSa + fiat/CVU). Mock fires `wallet.active` and
        # `fiat.account.created` automatically so the CVU is ready by the
        # time the client logs in. Real mode will fire those webhooks
        # asynchronously — the orchestrator is idempotent.
        try:
            from routes.ramp_routes import ensure_org_ramp_account
            from ramp import FiatAccountType
            applicant_type = app_doc.get("applicant_type", "business")
            acc_type = (FiatAccountType.USER
                          if applicant_type == "individual"
                          else FiatAccountType.BUSINESS)
            await ensure_org_ramp_account(
                org_id=app_doc["org_id"],
                display_name=app_doc.get("legal_name") or app_doc["org_id"],
                holder_name=app_doc.get("contact_name"),
                account_type=acc_type)
        except Exception as e:  # noqa: BLE001
            logger_ = __import__("logging").getLogger("prosper.kyb")
            logger_.warning("KYB approved but Andes ramp provisioning failed "
                              "for org=%s: %s — operator can retry from backoffice.",
                              app_doc["org_id"], e)

        # Activate the contact user (was status=invited)
        await col(USERS).update_many(
            {"org_id": app_doc["org_id"], "role": "client_admin",
              "status": "invited"},
            {"$set": {"status": "active", "updated_at": utc_now()}})

    await log_action(actor=None, action="kyb.decided",
                     resource_type="onboarding_application",
                     resource_id=app_doc["application_id"],
                     org_id_override=app_doc["org_id"],
                     metadata={"decision": decision, "session_id": session_id})
    return {"ok": True, "application_id": app_doc["application_id"],
            "kyb_status": new_kyb, "decision": decision}


async def _apply_kyc_decision(*, session_id: str, user_ref: str | None,
                              decision: str, raw_payload: dict) -> dict:
    q = {"kyc_session_id": session_id}
    if user_ref:
        q = {"$or": [{"kyc_session_id": session_id}, {"user_id": user_ref}]}
    user_doc = await col(USERS).find_one(q, {"_id": 0})
    if not user_doc:
        raise HTTPException(404, f"No user for session {session_id}")

    # Phase 22+ — Andes is the only source of truth for individual KYC.
    # If the user's org is `type=personal`, this AiPrise webhook is a
    # complete no-op (log-and-drop). Activation only happens via
    # `services.activation.on_identity_approved` triggered from the
    # Andes path (`POST /onboarding/{app_id}/kyc-docs` or the widget
    # at `/client/kyc-docs`). DO NOT touch users.kyc_status,
    # org.kyb_status, org.andes_kyc_status, prosper wallet, or ramp
    # account from this path for personal orgs.
    if user_doc.get("org_id"):
        org_check = await col(ORGANIZATIONS).find_one(
            {"org_id": user_doc["org_id"]},
            {"_id": 0, "type": 1}) or {}
        if org_check.get("type") == "personal":
            await log_action(
                actor=None,
                action="aiprise.kyc.dropped_for_personal",
                resource_type="user",
                resource_id=user_doc["user_id"],
                metadata={"decision": decision,
                          "session_id": session_id,
                          "org_id": user_doc["org_id"]})
            return {"ok": True, "dropped": True,
                    "user_id": user_doc["user_id"],
                    "reason": "personal_org_uses_andes_only"}

    new_kyc = _decision_to_kyc_status(decision)
    await col(USERS).update_one(
        {"user_id": user_doc["user_id"]},
        {"$set": {
            "kyc_status":     new_kyc,
            "kyc_decision":   decision,
            "kyc_decided_at": utc_now(),
            "kyc_raw":        raw_payload,
            "updated_at":     utc_now(),
        }},
    )
    await log_action(actor=None, action="kyc.decided",
                     resource_type="user", resource_id=user_doc["user_id"],
                     metadata={"decision": decision, "session_id": session_id})

    # Phase 22+ — DEAD CODE for personal orgs. The early guard above
    # short-circuits any `type=personal` case. This block now only runs
    # for business orgs that somehow reach `_apply_kyc_decision`, which
    # is not a normal flow (business uses `_apply_kyb_decision`). Kept
    # for safety, no-op in practice.
    if new_kyc == "approved" and user_doc.get("org_id"):
        org_id = user_doc["org_id"]
        org_doc = await col(ORGANIZATIONS).find_one(
            {"org_id": org_id},
            {"_id": 0, "type": 1, "kyb_status": 1}) or {}
        if org_doc.get("type") == "personal":
            # unreachable: guarded above. Defensive log only.
            __import__("logging").getLogger("prosper.kyc").warning(
                "_apply_kyc_decision reached personal branch unexpectedly for %s",
                org_id)

    return {"ok": True, "user_id": user_doc["user_id"],
            "kyc_status": new_kyc, "decision": decision}


# ---------------------------------------------------------------------------
# Webhook receivers
# ---------------------------------------------------------------------------
async def _verify_and_log(request: Request, kind: str) -> dict:
    raw = await request.body()
    sig = request.headers.get("x-hmac-signature") or request.headers.get("X-HMAC-Signature")
    if not aiprise.verify_signature(raw, sig):
        # Log the rejected attempt for forensics
        await col(WEBHOOK_EVENTS).insert_one({
            "provider":   "aiprise",
            "kind":       kind,
            "status":     "rejected_signature",
            "signature":  sig,
            "received_at": utc_now(),
        })
        raise HTTPException(401, "Invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    await col(WEBHOOK_EVENTS).insert_one({
        "provider":    "aiprise",
        "kind":        kind,
        "status":      "accepted",
        "payload":     payload,
        "received_at": utc_now(),
    })
    return payload


@router.post("/kyb")
async def kyb_callback(request: Request):
    payload = await _verify_and_log(request, "kyb")
    session_id = payload.get("verification_session_id") or payload.get("session_id")
    decision = (payload.get("decision") or payload.get("status") or "").lower()
    if not session_id or not decision:
        raise HTTPException(400, "Missing verification_session_id or decision")
    return await _apply_kyb_decision(session_id=session_id, decision=decision,
                                     raw_payload=payload)


@router.post("/kyc")
async def kyc_callback(request: Request):
    payload = await _verify_and_log(request, "kyc")
    session_id = payload.get("verification_session_id") or payload.get("session_id")
    decision = (payload.get("decision") or payload.get("status") or "").lower()
    user_ref = payload.get("client_reference_id")
    if not session_id or not decision:
        raise HTTPException(400, "Missing verification_session_id or decision")
    return await _apply_kyc_decision(session_id=session_id, user_ref=user_ref,
                                     decision=decision, raw_payload=payload)
