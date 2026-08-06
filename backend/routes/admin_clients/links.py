"""Phase 6 — Signed JWT links: KYB, reset-password, invite."""
from __future__ import annotations
import os, secrets as _s
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from audit import log_action
from auth import CurrentUser, JWT_SECRET, JWT_ALGORITHM
from db import col, ORGANIZATIONS, SIGNED_LINKS, USERS
from integrations.email_sender import (
    send_email, t_invitation, t_reset_password, t_kyb_link,
)
from ._deps import require_admin, require_write, iso_now

router = APIRouter(prefix="/admin/clients", tags=["admin-clients-links"])

PURPOSE_PATHS = {
    "kyb":            "/apply",
    "reset_password": "/reset-password",
    "invite":         "/accept-invite",
}
TTL_HOURS = {"kyb": 72, "reset_password": 24, "invite": 72}


def _public_base() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/") or ""


async def _create_signed_link(
    *, purpose: Literal["kyb", "reset_password", "invite"],
    org_id: str, user_id: Optional[str] = None, email: Optional[str] = None,
    ttl_hours: Optional[int] = None, created_by: str,
) -> dict:
    ttl_hours = ttl_hours or TTL_HOURS[purpose]
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=ttl_hours)
    link_id = f"slk_{_s.token_hex(8)}"
    payload = {
        "link_id":  link_id,
        "purpose":  purpose,
        "org_id":   org_id,
        "user_id":  user_id,
        "email":    email,
        "iat":      int(now.timestamp()),
        "exp":      int(exp.timestamp()),
        "iss":      "prosper-admin",
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    base = _public_base()
    url = f"{base}{PURPOSE_PATHS[purpose]}?token={token}"
    record = {
        "link_id":      link_id,
        "purpose":      purpose,
        "org_id":       org_id,
        "user_id":      user_id,
        "email":        email,
        "status":       "pending",
        "ttl_hours":    ttl_hours,
        "created_at":   now.isoformat(),
        "expires_at":   exp.isoformat(),
        "consumed_at":  None,
        "consumed_by":  None,
        "created_by":   created_by,
        "url":          url,
        "is_deleted":   False,
    }
    await col(SIGNED_LINKS).insert_one(record.copy())
    record.pop("_id", None)
    return record


class LinkBody(BaseModel):
    email: Optional[str] = None      # for reset-password / invite when user is new
    name:  Optional[str] = None
    send_email: bool = True


@router.post("/{org_id}/links/{purpose}")
async def make_link(org_id: str, purpose: str, body: LinkBody,
                     user: CurrentUser = Depends(require_write)):
    if purpose not in PURPOSE_PATHS:
        raise HTTPException(400, f"Unknown purpose '{purpose}'")
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id, "is_deleted": False}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Org not found")

    target_user = None
    user_id = None
    target_email = (body.email or "").lower().strip() or org.get("primary_email")
    if target_email:
        target_user = await col(USERS).find_one(
            {"email": target_email, "is_deleted": False}, {"_id": 0})
        if target_user:
            user_id = target_user.get("user_id")

    link = await _create_signed_link(
        purpose=purpose, org_id=org_id, user_id=user_id, email=target_email,
        created_by=user.email)

    if body.send_email and target_email:
        name = (body.name or (target_user or {}).get("full_name")
                or org.get("primary_name") or "")
        org_name = org.get("commercial_name") or org.get("legal_name") or ""
        if purpose == "invite":
            subj, html = t_invitation(name=name, org_name=org_name, link=link["url"])
        elif purpose == "reset_password":
            subj, html = t_reset_password(name=name, link=link["url"])
        else:  # kyb
            subj, html = t_kyb_link(org_name=org_name, link=link["url"])
        await send_email(to=target_email, subject=subj, html=html,
                          template=f"{purpose}_link",
                          context={"link": link["url"], "org": org_name},
                          org_id=org_id, user_id=user_id, actor_email=user.email)

    await log_action(actor=user, action=f"clients.link.{purpose}",
                     resource_type="organization", resource_id=org_id,
                     metadata={"email": target_email, "link_id": link["link_id"]})
    return link


@router.get("/{org_id}/links")
async def list_links(org_id: str, _: CurrentUser = Depends(require_admin)):
    rows = await col(SIGNED_LINKS).find(
        {"org_id": org_id, "is_deleted": False}, {"_id": 0})\
        .sort("created_at", -1).limit(50).to_list(50)
    # Compute live status (pending vs expired)
    now_iso = iso_now()
    for r in rows:
        if r["status"] == "pending" and (r.get("expires_at") or "") < now_iso:
            r["status"] = "expired"
    return {"items": rows, "total": len(rows)}


# Convenience public consume endpoint used by /apply, /accept-invite, etc.
public = APIRouter(prefix="/links", tags=["public-links"])


class ConsumeBody(BaseModel):
    token: str


@public.post("/verify")
async def verify_link(body: ConsumeBody):
    try:
        payload = jwt.decode(body.token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    doc = await col(SIGNED_LINKS).find_one(
        {"link_id": payload.get("link_id"), "is_deleted": False}, {"_id": 0})
    if not doc:
        raise HTTPException(401, "Unknown link")
    if doc["status"] != "pending":
        raise HTTPException(401, f"Link {doc['status']}")
    return {"ok": True, "purpose": doc["purpose"], "org_id": doc["org_id"],
             "email": doc.get("email"), "expires_at": doc["expires_at"]}


@public.post("/consume")
async def consume_link(body: ConsumeBody):
    try:
        payload = jwt.decode(body.token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    res = await col(SIGNED_LINKS).update_one(
        {"link_id": payload.get("link_id"), "status": "pending", "is_deleted": False},
        {"$set": {"status": "used", "consumed_at": iso_now()}})
    if not res.modified_count:
        raise HTTPException(401, "Link already used or expired")
    return {"ok": True, "purpose": payload.get("purpose"),
             "org_id": payload.get("org_id")}


# Re-export so server can mount /links public sub-router too if desired
router.public = public  # type: ignore[attr-defined]
