"""Phase 6 — Users management per client."""
from __future__ import annotations
import secrets as _s
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from audit import log_action
from auth import CurrentUser
from db import col, ORGANIZATIONS, USERS
from integrations.email_sender import send_email, t_invitation
from ._deps import require_admin, require_write, iso_now

router = APIRouter(prefix="/admin/clients", tags=["admin-clients-users"])


@router.get("/{org_id}/users")
async def list_users(org_id: str, _: CurrentUser = Depends(require_admin)):
    rows = await col(USERS).find(
        {"org_id": org_id, "is_deleted": False}, {"_id": 0, "password_hash": 0}
    ).to_list(500)
    return {"items": rows, "total": len(rows)}


class InviteUser(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: Literal["client_admin", "client_user"] = "client_user"
    send_email: bool = True


@router.post("/{org_id}/users")
async def invite_user(org_id: str, body: InviteUser,
                       actor: CurrentUser = Depends(require_write)):
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id, "is_deleted": False}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Org not found")
    email = body.email.lower()
    if await col(USERS).find_one({"email": email, "is_deleted": False}):
        raise HTTPException(409, "Email already registered")

    uid = f"usr_{_s.token_hex(5)}"
    now = iso_now()
    await col(USERS).insert_one({
        "user_id":   uid, "email": email, "full_name": body.full_name or email.split("@")[0],
        "role":      body.role, "org_id": org_id,
        "status":    "invited", "kyc_status": "pending",
        "mfa_enabled": False,
        "created_at": now, "updated_at": now, "is_deleted": False,
    })

    # Send invite link
    from .links import _create_signed_link
    link = await _create_signed_link(
        purpose="invite", org_id=org_id, user_id=uid, email=email,
        ttl_hours=72, created_by=actor.email)

    if body.send_email:
        org_name = org.get("commercial_name") or org.get("legal_name")
        subj, html = t_invitation(name=body.full_name or email,
                                    org_name=org_name, link=link["url"])
        await send_email(to=email, subject=subj, html=html,
                          template="invitation",
                          context={"link": link["url"], "org": org_name},
                          org_id=org_id, user_id=uid, actor_email=actor.email)

    await log_action(actor=actor, action="clients.user.invite",
                     resource_type="user", resource_id=uid,
                     metadata={"org_id": org_id, "email": email, "role": body.role})
    return {"ok": True, "user_id": uid, "invite_link": link["url"]}


class PatchUser(BaseModel):
    role:   Optional[Literal["client_admin", "client_user"]] = None
    status: Optional[Literal["active", "invited", "revoked", "paused"]] = None


@router.patch("/{org_id}/users/{user_id}")
async def patch_user(org_id: str, user_id: str, body: PatchUser,
                     actor: CurrentUser = Depends(require_write)):
    u = await col(USERS).find_one({"user_id": user_id, "org_id": org_id,
                                     "is_deleted": False})
    if not u:
        raise HTTPException(404, "User not in org")
    upd = body.model_dump(exclude_none=True)
    upd["updated_at"] = iso_now()
    await col(USERS).update_one({"user_id": user_id}, {"$set": upd})
    await log_action(actor=actor, action="clients.user.patch",
                     resource_type="user", resource_id=user_id, metadata=upd)
    return {"ok": True}


@router.delete("/{org_id}/users/{user_id}")
async def revoke_user(org_id: str, user_id: str,
                       actor: CurrentUser = Depends(require_write)):
    res = await col(USERS).update_one(
        {"user_id": user_id, "org_id": org_id, "is_deleted": False},
        {"$set": {"status": "revoked", "revoked_at": iso_now(),
                   "revoked_by": actor.email, "updated_at": iso_now()}})
    if not res.matched_count:
        raise HTTPException(404, "User not in org")
    await log_action(actor=actor, action="clients.user.revoke",
                     resource_type="user", resource_id=user_id,
                     metadata={"org_id": org_id})
    return {"ok": True}
