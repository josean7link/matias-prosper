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
