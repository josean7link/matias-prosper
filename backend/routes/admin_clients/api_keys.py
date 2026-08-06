"""Phase 6 — Per-client API keys.

Storage: `api_keys` collection. Each row has a stable `prefix` (visible)
and a bcrypt `secret_hash`. Plaintext is returned ONLY in the POST create
response; subsequent GETs surface prefix + last_used info only.
"""
from __future__ import annotations
import secrets as _s
from typing import Literal, Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser
from db import col, API_KEYS
from ._deps import require_admin, require_write, iso_now

router = APIRouter(prefix="/admin/clients", tags=["admin-clients-api-keys"])


def _hash(secret: str) -> str:
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=10)).decode()


def _new_secret(scope: Literal["sandbox", "production"]) -> tuple[str, str]:
    """Returns (plaintext, prefix)."""
    body = _s.token_urlsafe(28).replace("_", "").replace("-", "")[:40]
    prefix_word = "live" if scope == "production" else "test"
    plaintext = f"pk_{prefix_word}_{body}"
    prefix    = plaintext[:14]    # e.g. pk_live_a1b2cd
    return plaintext, prefix


@router.get("/{org_id}/api-keys")
async def list_keys(org_id: str, _: CurrentUser = Depends(require_admin)):
    rows = await col(API_KEYS).find(
        {"org_id": org_id, "is_deleted": False},
        {"_id": 0, "secret_hash": 0}).sort("created_at", -1).to_list(200)
    return {"items": rows, "total": len(rows)}


class CreateKey(BaseModel):
    name:  str = Field(..., min_length=1, max_length=80)
    scope: Literal["sandbox", "production"] = "sandbox"


@router.post("/{org_id}/api-keys")
async def create_key(org_id: str, body: CreateKey,
                      user: CurrentUser = Depends(require_write)):
    key_id = f"key_{_s.token_hex(5)}"
    plaintext, prefix = _new_secret(body.scope)
    doc = {
        "key_id":       key_id,
        "org_id":       org_id,
        "name":         body.name,
        "scope":        body.scope,
        "prefix":       prefix,
        "secret_hash":  _hash(plaintext),
        "created_at":   iso_now(),
        "created_by":   user.email,
        "last_used_at": None,
        "last_used_ip": None,
        "status":       "active",
        "is_deleted":   False,
    }
    await col(API_KEYS).insert_one(doc.copy())
    await log_action(actor=user, action="clients.api_key.create",
                     resource_type="api_key", resource_id=key_id,
                     metadata={"org_id": org_id, "scope": body.scope, "name": body.name})
    return {"ok": True, "key_id": key_id, "name": body.name, "scope": body.scope,
             "prefix": prefix, "plaintext": plaintext,
             "warning": "Esta es la única vez que vas a ver la key completa. Guardala ahora."}


@router.post("/{org_id}/api-keys/{key_id}/rotate")
async def rotate_key(org_id: str, key_id: str,
                     user: CurrentUser = Depends(require_write)):
    existing = await col(API_KEYS).find_one(
        {"key_id": key_id, "org_id": org_id, "is_deleted": False})
    if not existing:
        raise HTTPException(404, "Key not found")
    plaintext, prefix = _new_secret(existing["scope"])
    await col(API_KEYS).update_one(
        {"key_id": key_id},
        {"$set": {"prefix": prefix, "secret_hash": _hash(plaintext),
                  "rotated_at": iso_now(), "rotated_by": user.email,
                  "last_used_at": None, "last_used_ip": None,
                  "status": "active"}})
    await log_action(actor=user, action="clients.api_key.rotate",
                     resource_type="api_key", resource_id=key_id,
                     metadata={"org_id": org_id})
    return {"ok": True, "key_id": key_id, "prefix": prefix,
             "plaintext": plaintext,
             "warning": "Esta es la única vez que vas a ver la nueva key."}


@router.delete("/{org_id}/api-keys/{key_id}")
async def revoke_key(org_id: str, key_id: str,
                      user: CurrentUser = Depends(require_write)):
    res = await col(API_KEYS).update_one(
        {"key_id": key_id, "org_id": org_id, "is_deleted": False},
        {"$set": {"status": "revoked", "revoked_at": iso_now(),
                  "revoked_by": user.email, "is_deleted": True}})
    if not res.matched_count:
        raise HTTPException(404, "Key not found")
    await log_action(actor=user, action="clients.api_key.revoke",
                     resource_type="api_key", resource_id=key_id,
                     metadata={"org_id": org_id})
    return {"ok": True}
