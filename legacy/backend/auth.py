"""Emergent Google Auth integration for Prosper platform.

REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH.
Frontend derives redirect_url from window.location.origin.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Request, HTTPException, status, Depends
import httpx
from db import col, USERS, SESSIONS
from models import User, now_utc, new_id

EMERGENT_AUTH_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


async def exchange_session(session_id: str) -> dict:
    """Call Emergent auth backend and return user data + session_token."""
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(EMERGENT_AUTH_SESSION_URL, headers={"X-Session-ID": session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session_id")
    return r.json()


async def upsert_user(data: dict) -> User:
    """Create or update user from Emergent payload."""
    email = data["email"].lower().strip()
    existing = await col(USERS).find_one({"email": email}, {"_id": 0})
    now = now_utc()
    if existing:
        await col(USERS).update_one(
            {"email": email},
            {"$set": {
                "name": data.get("name", existing.get("name", email)),
                "picture": data.get("picture") or existing.get("picture"),
            }}
        )
        existing["name"] = data.get("name", existing.get("name"))
        existing["picture"] = data.get("picture") or existing.get("picture")
        return User(**existing)
    # New user — default platform_role based on internal domain if needed
    is_internal = email.endswith("@prosper.foundation") or email.endswith("@emergent.sh")
    platform_role = "super_admin" if is_internal else "client_admin"
    user_doc = {
        "user_id": f"user_{new_id()}",
        "email": email,
        "name": data.get("name", email),
        "picture": data.get("picture"),
        "platform_role": platform_role,
        "org_id": None,
        "is_internal": is_internal,
        "mfa_enabled": False,
        "created_at": now.isoformat(),
    }
    await col(USERS).insert_one(dict(user_doc))
    user_doc.pop("_id", None)
    user_doc["created_at"] = now
    return User(**user_doc)


async def create_session(user_id: str, session_token: str) -> None:
    expires = now_utc() + timedelta(days=7)
    await col(SESSIONS).insert_one({
        "session_id": f"sess_{new_id()}",
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires.isoformat(),
        "created_at": now_utc().isoformat(),
    })


async def get_current_user(request: Request) -> User:
    token = request.cookies.get("session_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sess = await col(SESSIONS).find_one({"session_token": token}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = sess.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    user_doc = await col(USERS).find_one({"user_id": sess["user_id"]}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    # Normalise datetime
    if isinstance(user_doc.get("created_at"), str):
        user_doc["created_at"] = datetime.fromisoformat(user_doc["created_at"])
    return User(**user_doc)


def require_roles(*roles: str):
    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.platform_role not in roles and not user.is_internal:
            raise HTTPException(status_code=403, detail=f"Requires role in {roles}")
        return user
    return _checker


async def delete_session(token: str) -> None:
    await col(SESSIONS).delete_one({"session_token": token})
