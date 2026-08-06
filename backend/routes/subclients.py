"""Phase 23 — N1/N2 hierarchy. A client-side `client_admin` (the N1) can create
sub-clients (N2). Each N2 is a full `Organization` with its own KYB, ramp
account, caps and posiciones — only linked to the N1 via `parent_org_id`.

Rules enforced here:
    * Only `client_admin` of an N1 (parent_org_id = None) can create N2.
    * Maximum depth = 2: a request to create a sub-client from an org whose
      `parent_org_id is not None` returns 403.
    * The actor's `org_id` must equal the URL `{n1_org_id}` (no cross-tenant).
    * The N2 owner login goes to a brand-new email (the contact provided in
      the request) — not the N1 admin. N2 is a fully independent tenant.

Read endpoints expose ONLY summary data (balances + position counts) of the
N2 to the N1. The N1 cannot operate on the N2: all cashin/cashout/invest
endpoints remain scoped by `actor.org_id` (the N1's JWT cannot impersonate
the N2 — its `org_id` claim is N1's).
"""
from __future__ import annotations

import logging
import secrets as _s
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ORGANIZATIONS, USERS, RAMP_ACCOUNTS, RAMP_BALANCES, POSITIONS,
)
from roles import Role
from routes.admin_clients._deps import iso_now

logger = logging.getLogger("prosper.subclients")
router = APIRouter(prefix="/clients", tags=["subclients"])


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
async def _resolve_n1(n1_org_id: str, actor: CurrentUser) -> dict:
    """Return the N1 org doc after validating:
       * the actor's JWT scopes to that org (cross-tenant blocked),
       * the actor's role is client_admin (only owner can manage subclients),
       * the org is a true N1 (parent_org_id is None).
    """
    if actor.role != Role.client_admin:
        raise HTTPException(403, "Only client_admin may manage subclients")
    if actor.org_id != n1_org_id:
        raise HTTPException(403,
            "Cross-tenant access blocked: you may only manage your own org")
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": n1_org_id, "is_deleted": False}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Organization not found")
    if org.get("parent_org_id"):
        # An N2 is trying to create N3 — DENY (max depth = 2)
        raise HTTPException(403,
            "Maximum hierarchy depth (2) reached — sub-clients cannot create "
            "their own sub-clients")
    return org


# ---------------------------------------------------------------------------
# B — Create N2
# ---------------------------------------------------------------------------
class SubclientCreate(BaseModel):
    legal_name:       str = Field(..., min_length=2, max_length=200)
    commercial_name:  str = Field(..., min_length=2, max_length=200)
    country:          str = Field(..., min_length=2, max_length=2,
                                     description="ISO country code (2 letters)")
    contact_email:    EmailStr = Field(..., description="N2's own login email")
    contact_full_name: str = Field("", max_length=200)
    org_type:         str = Field("fintech",
                                     pattern="^(fintech|broker|family_office|retail_aggregator|other)$")


class SubclientOut(BaseModel):
    org_id: str
    legal_name: str
    commercial_name: str
    country: str
    kyb_status: str
    parent_org_id: str
    level: int
    contact_email: EmailStr
    invite_link: str
    created_at: str


@router.post("/{n1_org_id}/subclients", response_model=SubclientOut)
async def create_subclient(n1_org_id: str, body: SubclientCreate,
                                 actor: CurrentUser = Depends(get_current_user)):
    """Phase 23.B — N1 creates an N2. The N2 is a brand-new Organization
    + a fresh `client_admin` invited at `contact_email`."""
    n1 = await _resolve_n1(n1_org_id, actor)

    contact_email = body.contact_email.lower()
    # Reject if the contact email is already a user anywhere
    existing = await col(USERS).find_one(
        {"email": contact_email, "is_deleted": False},
        {"_id": 0, "user_id": 1})
    if existing:
        raise HTTPException(409,
            "An account already exists for that contact email")

    # Reject if commercial_name collides under the same parent
    dup = await col(ORGANIZATIONS).find_one(
        {"parent_org_id": n1_org_id,
          "commercial_name": body.commercial_name,
          "is_deleted": False},
        {"_id": 0, "org_id": 1})
    if dup:
        raise HTTPException(409,
            "You already have a sub-client with that commercial name")

    now = iso_now()
    n2_org_id = "org_" + _s.token_hex(5)
    org_doc = {
        "org_id":          n2_org_id,
        "legal_name":      body.legal_name,
        "commercial_name": body.commercial_name,
        "country":         body.country.upper(),
        "type":            body.org_type,
        "kyb_status":      "pending",
        "risk_score":      0,
        "risk_profile":    "low",
        "allowlist_domains": [],
        "caps":            {},
        "parent_org_id":   n1_org_id,
        "level":           2,
        "internal_notes":  f"Created via subclient flow by {actor.email}",
        "created_at":      now,
        "updated_at":      now,
        "is_deleted":      False,
    }
    await col(ORGANIZATIONS).insert_one(dict(org_doc))

    # Create the N2's client_admin user (invited)
    user_id = "usr_" + _s.token_hex(5)
    full_name = body.contact_full_name or contact_email.split("@")[0]
    await col(USERS).insert_one({
        "user_id":      user_id,
        "email":        contact_email,
        "full_name":    full_name,
        "role":         Role.client_admin.value,
        "org_id":       n2_org_id,
        "status":       "invited",
        "kyc_status":   "pending",
        "mfa_enabled":  False,
        "created_at":   now,
        "updated_at":   now,
        "is_deleted":   False,
    })

    # Issue a magic-link invite
    invite_link = ""
    try:
        from routes.admin_clients.links import _create_signed_link
        link = await _create_signed_link(
            purpose="invite", org_id=n2_org_id, user_id=user_id,
            email=contact_email, ttl_hours=72,
            created_by=actor.email or actor.user_id)
        invite_link = link.get("url", "")
    except Exception as e:  # noqa: BLE001
        logger.warning("invite link generation failed for %s: %s",
                          contact_email, e)

    # Best-effort transactional email (template may not exist in dev)
    try:
        from integrations.email_sender import send_email
        from routes.admin_clients.email_templates import t_invitation
        subj, html = t_invitation(name=full_name,
                                     org_name=body.commercial_name,
                                     link=invite_link)
        await send_email(to=contact_email, subject=subj, html=html,
                          template="invitation",
                          context={"link": invite_link,
                                    "org": body.commercial_name},
                          org_id=n2_org_id, user_id=user_id,
                          actor_email=actor.email)
    except Exception as e:  # noqa: BLE001
        logger.info("subclient invitation email skipped (%s): %s",
                       contact_email, e)

    await log_action(actor=actor, action="clients.subclient.created",
                       resource_type="organization",
                       resource_id=n2_org_id,
                       metadata={"parent_org_id": n1_org_id,
                                  "contact_email": contact_email,
                                  "legal_name": body.legal_name,
                                  "commercial_name": body.commercial_name})

    return SubclientOut(
        org_id=n2_org_id,
        legal_name=body.legal_name,
        commercial_name=body.commercial_name,
        country=body.country.upper(),
        kyb_status="pending",
        parent_org_id=n1_org_id,
        level=2,
        contact_email=contact_email,
        invite_link=invite_link,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# D — List N2 (read-only summary)
# ---------------------------------------------------------------------------
class SubclientSummary(BaseModel):
    org_id: str
    commercial_name: str
    legal_name: str
    country: str
    kyb_status: str
    arsa_balance: float = 0.0
    position_count: int = 0
    total_aum_usd: float = 0.0
    last_activity_at: Optional[str] = None
    contact_email: Optional[str] = None
    created_at: str


@router.get("/{n1_org_id}/subclients", response_model=list[SubclientSummary])
async def list_subclients(n1_org_id: str,
                              actor: CurrentUser = Depends(get_current_user)):
    """Phase 23.D — N1 lists its N2s with summary (balances, position count).
    Read-only; no movement-level data exposed here (that's PII of the N2)."""
    await _resolve_n1(n1_org_id, actor)
    rows = await col(ORGANIZATIONS).find(
        {"parent_org_id": n1_org_id, "is_deleted": False},
        {"_id": 0, "org_id": 1, "legal_name": 1, "commercial_name": 1,
          "country": 1, "kyb_status": 1, "created_at": 1, "updated_at": 1}
    ).sort("created_at", -1).to_list(200)

    items: list[SubclientSummary] = []
    for org in rows:
        # ARSa balance (sum across all wallets of that org)
        arsa = 0.0
        async for b in col(RAMP_BALANCES).find(
                {"asset": "arsa"}, {"_id": 0, "balance": 1, "ramp_account_id": 1}):
            # Filter via parent ramp_account
            acc = await col(RAMP_ACCOUNTS).find_one(
                {"id": b.get("ramp_account_id"), "org_id": org["org_id"]},
                {"_id": 0})
            if acc:
                try:    arsa += float(b.get("balance") or 0)
                except Exception:  pass

        # Position aggregates
        pos_count = 0
        aum = 0.0
        async for p in col(POSITIONS).find(
                {"org_id": org["org_id"], "status": "active",
                  "is_deleted": False},
                {"_id": 0, "principal_usd": 1}):
            pos_count += 1
            try:    aum += float(p.get("principal_usd") or 0)
            except Exception: pass

        # N2's primary contact user
        owner = await col(USERS).find_one(
            {"org_id": org["org_id"], "role": Role.client_admin.value,
              "is_deleted": False},
            {"_id": 0, "email": 1})

        items.append(SubclientSummary(
            org_id=org["org_id"],
            commercial_name=org["commercial_name"],
            legal_name=org["legal_name"],
            country=org["country"],
            kyb_status=org.get("kyb_status", "pending"),
            arsa_balance=arsa,
            position_count=pos_count,
            total_aum_usd=aum,
            last_activity_at=org.get("updated_at"),
            contact_email=(owner or {}).get("email"),
            created_at=org["created_at"]))

    await log_action(actor=actor, action="clients.subclient.list_read",
                       resource_type="organization",
                       resource_id=n1_org_id,
                       metadata={"count": len(items)})
    return items
