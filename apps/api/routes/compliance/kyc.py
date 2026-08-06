"""Phase 5 — KYC queue + decision endpoints.

The queue unifies TWO sources so super_admins see real onboarding alongside
the legacy seed cases:

  1. `kyc_cases` collection — seed + AiPrise hosted-flow cases.
  2. `onboarding_applications` with `applicant_type=individual` —
     the live "andes-direct" flow (Phase 22+). These are projected into the
     KycCase shape with `provider="Andes"` and surface the live
     `org.sanctions_status` / `org.andes_kyc_status` so compliance can see
     where each individual is in the two-gate funnel.

Decisions on real applications mirror through to:
  - the application document (status / kyb_status),
  - the org (`andes_kyc_status` / `sanctions_status` are NOT touched here —
    those gates are governed by the Andes webhook and the sanctions
    decision endpoint respectively. KYC officers can decide via the
    Sanctions queue if they want to clear the second gate).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser
from db import col, KYC_CASES, ONBOARDING_APPLICATIONS, ORGANIZATIONS, USERS
from roles import Role
from ._deps import (
    require_compliance, require_compliance_decide, SANCTIONS_OVERRIDE_ROLES,
)

router = APIRouter(prefix="/admin/compliance/kyc", tags=["admin-compliance-kyc"])


def _sla_color(hours: float) -> str:
    if hours <= 12:
        return "red"
    if hours <= 24:
        return "amber"
    return "green"


def _provider_label(app: dict) -> str:
    """Map an onboarding_applications.aiprise_mode to the queue's provider label."""
    mode = (app.get("aiprise_mode") or "").lower()
    if mode == "andes-direct":
        return "Andes"
    if mode in ("simulated", "sim"):
        return "AiPrise (sim)"
    return "AiPrise"


def _map_application_to_case(app: dict, org: Optional[dict]) -> dict:
    """Project an onboarding_applications doc into the KycCase shape.

    Status is derived from the application + the org's two gates:
      - app.kyc_docs_uploaded_at missing → "pending" (waiting for selfie)
      - andes_onboarding_status=approved + sanctions=clear → "approved"
      - andes_onboarding_status=rejected → "rejected"
      - any other intermediate → "in_review"
    """
    applied_at = app.get("submitted_at") or app.get("created_at") or _iso_now()
    full_name = (app.get("legal_name") or "").strip()
    parts = full_name.split(" ", 1)
    first_name = parts[0] if parts else "—"
    last_name  = parts[1] if len(parts) > 1 else ""
    indiv = app.get("individual") or {}

    # Derived status using the two-gate policy
    andes_onb = app.get("andes_onboarding_status")
    sanctions = (org or {}).get("sanctions_status") or "pending"
    if app.get("status") == "rejected" or andes_onb == "rejected":
        st = "rejected"
    elif (org or {}).get("kyb_status") == "approved" and sanctions == "clear":
        st = "approved"
    elif not app.get("kyc_docs_uploaded_at"):
        st = "pending"      # esperando que el cliente suba fotos
    else:
        st = "in_review"

    # Checks reflect the three-gate state
    aml_check = "pass" if andes_onb in ("approved", "completed") else "pending"
    sanctions_check = {"clear": "pass", "flagged": "fail",
                          "pending": "pending"}.get(sanctions, "pending")
    travel_rule = (org or {}).get("travel_rule_status") or "pending"
    travel_rule_check = {"clear": "pass", "na": "n/a", "flagged": "fail",
                            "pending": "pending"}.get(travel_rule, "pending")

    return {
        "case_id":   app["application_id"],   # already prefixed `app_…`
        "first_name": first_name,
        "last_name":  last_name,
        "email":      app.get("contact_email", ""),
        "country":    app.get("country") or indiv.get("country", "AR"),
        "doc_id":     indiv.get("cuit") or "—",
        "doc_type":   "national_id",
        "documents": [],   # populated on detail call from /app/backend/var/kyc_docs/
        "provider":   _provider_label(app),
        "provider_score":      100 if andes_onb in ("approved", "completed") else 0,
        "provider_confidence": 1.0 if andes_onb in ("approved", "completed") else 0.0,
        "provider_flags":      _derive_flags(app, sanctions),
        "checks": {
            "aml":          aml_check,
            "sanctions":    sanctions_check,
            "pep":          sanctions_check,
            "travel_rule":  travel_rule_check,
        },
        "status":     st,
        "applied_at": applied_at,
        "sla_hours_left": 0.0,     # filled in below
        "sla_color":  "green",
        "org_id":     app.get("org_id"),
        # Surface the three-gate state for the detail drawer
        "andes_kyc_status":   (org or {}).get("andes_kyc_status") or (
                                   "approved" if andes_onb in ("approved", "completed")
                                   else "pending"),
        "sanctions_status":   sanctions,
        "travel_rule_status": travel_rule,
        "kyb_status":         (org or {}).get("kyb_status", "pending"),
        "andes_onboarding_status": andes_onb,
        "cvu":                None,  # filled in by detail endpoint from ramp_accounts
        "timeline": [
            {"ts": applied_at, "by": "system", "what": "application_submitted",
             "meta": {"applicant_type": "individual",
                       "mode": app.get("aiprise_mode")}},
        ] + ([{"ts": app["kyc_docs_uploaded_at"], "by": "system",
                "what": "kyc_docs.uploaded", "meta": {}}]
              if app.get("kyc_docs_uploaded_at") else []),
        "is_deleted": app.get("is_deleted", False),
        "source": "onboarding_application",   # debug aid
    }


def _derive_flags(app: dict, sanctions: str) -> List[str]:
    flags: List[str] = []
    if app.get("aiprise_mode") == "andes-direct":
        flags.append("andes_direct")
    if app.get("andes_onboarding_status") in ("approved", "completed"):
        flags.append("identity_approved")
    elif app.get("andes_onboarding_status") == "rejected":
        flags.append("identity_rejected")
    if sanctions == "clear":
        flags.append("sanctions_clear")
    elif sanctions == "flagged":
        flags.append("sanctions_flagged")
    else:
        flags.append("sanctions_pending")
    return flags


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/queue")
async def kyc_queue(
    status: Optional[List[str]] = Query(None),
    provider: Optional[List[str]] = Query(None),
    _: CurrentUser = Depends(require_compliance),
):
    # ── Source 1: legacy/seed `kyc_cases` ─────────────────────────────
    q1: dict = {"is_deleted": False}
    if status:
        q1["status"]   = {"$in": status}
    if provider:
        q1["provider"] = {"$in": provider}
    seed_items = await col(KYC_CASES).find(q1, {"_id": 0}) \
                       .sort("applied_at", -1).to_list(500)

    # ── Source 2: real onboarding applications (individuals) ──────────
    q2: dict = {"applicant_type": "individual", "is_deleted": False}
    apps = await col(ONBOARDING_APPLICATIONS).find(q2, {"_id": 0}) \
                 .sort("submitted_at", -1).to_list(500)

    org_ids = [a["org_id"] for a in apps if a.get("org_id")]
    orgs_by_id: dict = {}
    if org_ids:
        async for o in col(ORGANIZATIONS).find(
                {"org_id": {"$in": org_ids}},
                {"_id": 0, "org_id": 1, "kyb_status": 1, "sanctions_status": 1,
                 "andes_kyc_status": 1, "travel_rule_status": 1}):
            orgs_by_id[o["org_id"]] = o

    real_items = [_map_application_to_case(a, orgs_by_id.get(a.get("org_id"))) for a in apps]

    # Apply post-mapping filters (status / provider) to the real source.
    # We do it in-process because the derived `status` for a real
    # application is not stored as-is in mongo.
    if status:
        real_items = [r for r in real_items if r["status"] in status]
    if provider:
        real_items = [r for r in real_items if r["provider"] in provider]

    # ── Merge + dynamic SLA enrichment ─────────────────────────────────
    items = real_items + seed_items   # real first — they are the priority
    now = datetime.now(timezone.utc)
    for it in items:
        try:
            applied = datetime.fromisoformat(it["applied_at"])
            it["sla_hours_left"] = round(
                max(0, 24 - (now - applied).total_seconds() / 3600), 1)
        except Exception:
            it["sla_hours_left"] = 0
        it["sla_color"] = _sla_color(it["sla_hours_left"])

    # Sort merged list by applied_at desc
    items.sort(key=lambda x: x.get("applied_at") or "", reverse=True)
    return {"items": items, "total": len(items)}


@router.get("/{case_id}")
async def kyc_detail(case_id: str, _: CurrentUser = Depends(require_compliance)):
    # Real onboarding application — case_id IS the application_id (already
    # prefixed `app_…`). Seed KYC cases use `kyc_seed_NN`.
    if case_id.startswith("app_"):
        app_id = case_id
        app_doc = await col(ONBOARDING_APPLICATIONS).find_one(
            {"application_id": app_id, "is_deleted": False}, {"_id": 0})
        if not app_doc:
            raise HTTPException(404, "Not found")
        org = await col(ORGANIZATIONS).find_one(
            {"org_id": app_doc.get("org_id")},
            {"_id": 0, "kyb_status": 1, "sanctions_status": 1,
             "andes_kyc_status": 1, "travel_rule_status": 1,
             "legal_name": 1, "country": 1}) or None
        case = _map_application_to_case(app_doc, org)
        # Hydrate CVU + ramp account info
        from db import RAMP_ACCOUNTS, SANCTIONS_SCREENINGS, TRAVEL_RULE_SCREENINGS
        ra = await col(RAMP_ACCOUNTS).find_one(
            {"org_id": app_doc.get("org_id"), "is_deleted": False},
            {"_id": 0, "cvu": 1, "alias": 1, "onboarding_status": 1,
             "wallet_address": 1, "provider_user_id": 1}) or {}
        case["cvu"]   = ra.get("cvu")
        case["alias"] = ra.get("alias")
        case["wallet_address"] = ra.get("wallet_address")
        case["andes_user_id"]  = ra.get("provider_user_id")
        # Hydrate sanctions + travel_rule rows
        case["sanctions"] = await col(SANCTIONS_SCREENINGS).find_one(
            {"org_id": app_doc.get("org_id")}, {"_id": 0}) or None
        case["travel_rule"] = await col(TRAVEL_RULE_SCREENINGS).find_one(
            {"org_id": app_doc.get("org_id")}, {"_id": 0}) or None
        # SLA enrichment
        try:
            applied = datetime.fromisoformat(case["applied_at"])
            case["sla_hours_left"] = round(
                max(0, 24 - (datetime.now(timezone.utc) - applied).total_seconds() / 3600), 1)
            case["sla_color"] = _sla_color(case["sla_hours_left"])
        except Exception:
            pass
        return case

    # Legacy seed/AiPrise case
    doc = await col(KYC_CASES).find_one({"case_id": case_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    try:
        applied = datetime.fromisoformat(doc["applied_at"])
        doc["sla_hours_left"] = round(max(0, 24 - (datetime.now(timezone.utc) - applied).total_seconds() / 3600), 1)
        doc["sla_color"] = _sla_color(doc["sla_hours_left"])
    except Exception:
        pass
    return doc


class KycDecision(BaseModel):
    action: Literal["approve", "reject", "request_info"]
    reason: str = Field(..., min_length=20, max_length=2000)
    # Manual override flags — only honored for andes-direct cases when:
    #   * the actor has SANCTIONS_OVERRIDE_ROLES (super_admin / finance)
    #   * the corresponding gate (sanctions / travel_rule) is `pending`
    # The same `reason` is recorded on each override decision.
    override_sanctions:   bool = False
    override_travel_rule: bool = False


@router.post("/{case_id}/decision")
async def kyc_decide(case_id: str, body: KycDecision,
                     user: CurrentUser = Depends(require_compliance_decide)):
    # ── Real onboarding application (andes-direct or AiPrise hosted) ──
    if case_id.startswith("app_"):
        app_id = case_id
        app_doc = await col(ONBOARDING_APPLICATIONS).find_one(
            {"application_id": app_id, "is_deleted": False}, {"_id": 0})
        if not app_doc:
            raise HTTPException(404, "Not found")

        # Approve here = override identity gate manually. It does NOT
        # short-circuit the sanctions gate — for that, compliance must use
        # the /admin/sanctions queue. We persist the decision on the app
        # and audit-log it.
        new_status = {"approve": "approved", "reject": "rejected",
                       "request_info": "needs_info"}[body.action]
        await col(ONBOARDING_APPLICATIONS).update_one(
            {"application_id": app_id},
            {"$set": {"status": "approved" if body.action == "approve" else
                                  "rejected" if body.action == "reject"
                                  else "in_review",
                      "decision": body.action,
                      "decision_reason": body.reason,
                      "decided_by": user.user_id,
                      "decided_at": _iso_now(),
                      "updated_at": _iso_now()}})
        # Mirror to USERS.kyc_status when there's an email-linked user
        if app_doc.get("contact_email"):
            await col(USERS).update_one(
                {"email": app_doc["contact_email"]},
                {"$set": {"kyc_status": new_status, "updated_at": _iso_now()}})
        # If approved manually, call the activation helper so the org's
        # andes_kyc_status flips correctly. The sanctions gate still applies.
        sanctions_override_applied = False
        travel_rule_override_applied = False
        if body.action == "approve" and app_doc.get("org_id"):
            try:
                from services.activation import on_identity_approved
                await on_identity_approved(
                    org_id=app_doc["org_id"],
                    source="compliance.kyc.manual_approve")
            except Exception:
                pass

            # ── Sanctions/PEP manual override ──────────────────────────
            # Only super_admin / finance can flip the second gate while
            # SANCTIONS_PROVIDER=manual. compliance_officer can approve
            # identity but not resolve sanctions/travel-rule.
            override_requested = body.override_sanctions or body.override_travel_rule
            if override_requested and \
                    user.role not in [r.value for r in SANCTIONS_OVERRIDE_ROLES]:
                raise HTTPException(
                    403,
                    "Sanctions / Travel-rule override requires super_admin or "
                    "finance role. Compliance officers can approve identity "
                    "but cannot resolve those gates manually.")

            # Verify the row is still pending (idempotency + safety).
            from db import SANCTIONS_SCREENINGS, TRAVEL_RULE_SCREENINGS
            if body.override_sanctions:
                scr = await col(SANCTIONS_SCREENINGS).find_one(
                    {"org_id": app_doc["org_id"]}, {"_id": 0}) or {}
                if scr.get("status") == "pending":
                    from routes.sanctions import apply_sanctions_decision
                    await apply_sanctions_decision(
                        org_id=app_doc["org_id"],
                        decision="clear", reason=body.reason,
                        actor_email=user.email, actor_id=user.user_id,
                        resolution="manual_override")
                    sanctions_override_applied = True

            if body.override_travel_rule:
                tr = await col(TRAVEL_RULE_SCREENINGS).find_one(
                    {"org_id": app_doc["org_id"]}, {"_id": 0}) or {}
                if tr.get("status") == "pending":
                    from routes.travel_rule import apply_travel_rule_decision
                    await apply_travel_rule_decision(
                        org_id=app_doc["org_id"],
                        decision="clear", reason=body.reason,
                        actor_email=user.email, actor_id=user.user_id,
                        resolution="manual_override")
                    travel_rule_override_applied = True

        await log_action(actor=user, action=f"compliance.kyc.{body.action}",
                         resource_type="onboarding_application",
                         resource_id=app_id, org_id_override=app_doc.get("org_id"),
                         metadata={"reason": body.reason, "case_id": case_id,
                                    "sanctions_override_applied": sanctions_override_applied,
                                    "travel_rule_override_applied": travel_rule_override_applied})
        return {"ok": True, "case_id": case_id, "status": new_status,
                "sanctions_override_applied":   sanctions_override_applied,
                "travel_rule_override_applied": travel_rule_override_applied}

    # ── Legacy/seed kyc_cases ─────────────────────────────────────────
    doc = await col(KYC_CASES).find_one({"case_id": case_id, "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    new_status = {"approve": "approved", "reject": "rejected",
                   "request_info": "needs_info"}[body.action]
    entry = {"ts": _iso_now(), "by": user.email,
             "what": f"decision.{body.action}", "meta": {"reason": body.reason}}
    await col(KYC_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"status": new_status, "decision": body.action,
                   "decision_reason": body.reason, "decided_by": user.user_id,
                   "decided_at": _iso_now(), "updated_at": _iso_now()},
         "$push": {"timeline": entry}},
    )
    email = doc.get("email")
    if email:
        await col(USERS).update_one(
            {"email": email},
            {"$set": {"kyc_status": new_status, "updated_at": _iso_now()}})
    await log_action(actor=user, action=f"compliance.kyc.{body.action}",
                     resource_type="kyc_case", resource_id=case_id,
                     metadata={"reason": body.reason})
    return {"ok": True, "case_id": case_id, "status": new_status}
