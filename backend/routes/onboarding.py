"""Phase 3 — Onboarding (public /apply + KYC initiation for client users).

Public endpoints (no auth):
  POST /onboarding/apply             — submit business application + start KYB
  POST /onboarding/apply/simulate    — DEV: simulate AiPrise completion
  GET  /onboarding/apply/{app_id}    — poll status (returns sanitized view)

Authenticated endpoints (client_user / client_admin):
  POST /onboarding/me/kyc            — start a KYC verification for current user
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ORGANIZATIONS, ONBOARDING_APPLICATIONS, USERS, WEBHOOK_EVENTS,
)
from integrations import aiprise
from models import Organization, new_id, utc_now
from roles import Role

logger = logging.getLogger("prosper.onboarding")
router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class UBOIn(BaseModel):
    full_name: str
    ownership_pct: float = Field(..., ge=0, le=100)
    role: Optional[str] = None
    country: Optional[str] = None


class ApplicationIn(BaseModel):
    legal_name: str
    commercial_name: Optional[str] = None
    country: str
    jurisdiction: str
    incorporation_date: Optional[str] = None
    registration_number: Optional[str] = None
    contact_name: str
    contact_email: EmailStr
    contact_phone: Optional[str] = None
    website: Optional[str] = None
    expected_monthly_volume_usd: Optional[float] = None
    use_case: Optional[str] = None
    ubos: List[UBOIn] = []


class ApplicationOut(BaseModel):
    application_id: str
    org_id: str
    status: str
    kyb_status: str
    hosted_url: Optional[str] = None
    mode: str  # "live" or "simulated"


def _public_base_url(req: Request) -> str:
    return f"{req.url.scheme}://{req.url.netloc}"


# ---------------------------------------------------------------------------
# POST /onboarding/apply
# ---------------------------------------------------------------------------
@router.post("/apply", response_model=ApplicationOut)
async def submit_application(body: ApplicationIn, request: Request):
    """Public — submit a new business onboarding application."""
    org_id = new_id("org")
    app_id = new_id("app")

    # 1. Create organization in pending state
    org = Organization(
        org_id=org_id,
        legal_name=body.legal_name,
        commercial_name=body.commercial_name or body.legal_name,
        country=body.country,
        type="fintech",
        kyb_status="pending",
        allowlist_domains=[body.contact_email.split("@", 1)[-1]],
    )
    org_doc = org.model_dump()
    await col(ORGANIZATIONS).insert_one(dict(org_doc))

    # 2. Persist the application
    app_doc = {
        "application_id": app_id,
        "org_id": org_id,
        "legal_name": body.legal_name,
        "commercial_name": body.commercial_name,
        "country": body.country,
        "jurisdiction": body.jurisdiction,
        "incorporation_date": body.incorporation_date,
        "registration_number": body.registration_number,
        "contact_name": body.contact_name,
        "contact_email": body.contact_email,
        "contact_phone": body.contact_phone,
        "website": body.website,
        "expected_monthly_volume_usd": body.expected_monthly_volume_usd,
        "use_case": body.use_case,
        "ubos": [u.model_dump() for u in body.ubos],
        "status": "in_review",
        "kyb_status": "pending",
        "aiprise_session_id": None,
        "aiprise_mode": None,
        "decision": None,
        "decision_at": None,
        "submitted_at": utc_now(),
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "is_deleted": False,
    }
    await col(ONBOARDING_APPLICATIONS).insert_one(dict(app_doc))

    # 3. Call AiPrise (or simulator)
    base = _public_base_url(request)
    callback = f"{base}/api/v1/webhooks/aiprise/kyb"
    redirect = f"{base}/apply/status?app_id={app_id}"
    try:
        ai = await aiprise.create_business_verification(
            client_reference_id=app_id,
            business_data={
                "legal_name": body.legal_name,
                "country": body.country,
                "jurisdiction": body.jurisdiction,
                "incorporation_date": body.incorporation_date,
                "registration_number": body.registration_number,
                "ubo_names": [u.full_name for u in body.ubos],
            },
            callback_url=callback,
            redirect_uri=redirect,
        )
    except aiprise.AipriseError as e:
        logger.exception("AiPrise KYB creation failed")
        raise HTTPException(502, f"KYB provider error: {e.body}")

    await col(ONBOARDING_APPLICATIONS).update_one(
        {"application_id": app_id},
        {"$set": {
            "aiprise_session_id": ai["verification_session_id"],
            "aiprise_mode": ai.get("mode"),
            "hosted_url": ai["hosted_url"],
            "updated_at": utc_now(),
        }},
    )

    # 4. Audit
    await log_action(actor=None, action="application.submitted",
                     resource_type="onboarding_application",
                     resource_id=app_id, org_id_override=org_id,
                     metadata={"contact_email": body.contact_email,
                              "mode": ai.get("mode")})

    return ApplicationOut(
        application_id=app_id,
        org_id=org_id,
        status="in_review",
        kyb_status="pending",
        hosted_url=ai["hosted_url"],
        mode=ai.get("mode", "live"),
    )


# ---------------------------------------------------------------------------
# GET /onboarding/apply/{app_id} — public read-back (sanitized)
# ---------------------------------------------------------------------------
@router.get("/apply/{app_id}")
async def get_application(app_id: str):
    app_doc = await col(ONBOARDING_APPLICATIONS).find_one(
        {"application_id": app_id, "is_deleted": False}, {"_id": 0})
    if not app_doc:
        raise HTTPException(404, "Application not found")
    return {
        "application_id":   app_doc["application_id"],
        "org_id":           app_doc["org_id"],
        "legal_name":       app_doc["legal_name"],
        "status":           app_doc["status"],
        "kyb_status":       app_doc["kyb_status"],
        "decision":         app_doc.get("decision"),
        "submitted_at":     app_doc["submitted_at"],
        "hosted_url":       app_doc.get("hosted_url"),
        "aiprise_mode":     app_doc.get("aiprise_mode"),
    }


# ---------------------------------------------------------------------------
# POST /onboarding/apply/simulate — DEV ONLY when sim mode active
# Allows the user clicking the simulator hosted_url to "complete" the flow
# without AiPrise being configured. Stripe-style local development helper.
# ---------------------------------------------------------------------------
class SimulateIn(BaseModel):
    session_id: str
    decision: str  # "approved" | "rejected" | "pending_review"


@router.post("/apply/simulate")
async def simulate_decision(body: SimulateIn):
    if body.session_id.startswith("sim_") is False:
        raise HTTPException(400, "Only simulated sessions are accepted here")
    if body.decision not in ("approved", "rejected", "pending_review"):
        raise HTTPException(400, "Invalid decision")

    # Re-use the real webhook code path so audit + side effects are consistent
    from routes.webhooks_aiprise import _apply_kyb_decision
    return await _apply_kyb_decision(session_id=body.session_id,
                                     decision=body.decision,
                                     raw_payload={"simulated": True,
                                                  "decision": body.decision})


# ---------------------------------------------------------------------------
# POST /onboarding/me/kyc — start a KYC for the current logged-in user
# ---------------------------------------------------------------------------
class KycStartOut(BaseModel):
    user_id: str
    kyc_status: str
    hosted_url: Optional[str]
    mode: str


@router.post("/me/kyc", response_model=KycStartOut)
async def start_my_kyc(request: Request, user: CurrentUser = Depends(get_current_user)):
    user_doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    if not user_doc:
        raise HTTPException(404, "User not found")
    if user_doc.get("kyc_status") == "approved":
        return KycStartOut(user_id=user.user_id, kyc_status="approved",
                           hosted_url=None, mode="skipped")

    base = _public_base_url(request)
    callback = f"{base}/api/v1/webhooks/aiprise/kyc"
    redirect = f"{base}/client/verify-identity?status=complete"
    try:
        ai = await aiprise.create_user_verification(
            client_reference_id=user.user_id,
            user_data={"email": user.email},
            callback_url=callback,
            redirect_uri=redirect,
        )
    except aiprise.AipriseError as e:
        raise HTTPException(502, f"KYC provider error: {e.body}")

    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {
            "kyc_status": "in_review",
            "kyc_session_id": ai["verification_session_id"],
            "kyc_mode": ai.get("mode"),
            "updated_at": utc_now(),
        }},
    )
    await log_action(actor=user, action="kyc.started",
                     resource_type="user", resource_id=user.user_id,
                     metadata={"mode": ai.get("mode")})

    return KycStartOut(user_id=user.user_id, kyc_status="in_review",
                       hosted_url=ai["hosted_url"], mode=ai.get("mode", "live"))
