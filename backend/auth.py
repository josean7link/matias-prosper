"""Phase 1 — JWT issuance + decoding, current-user resolver, role + scope guards.

Sprint 11B adds session tracking: each issued JWT also creates a `sessions`
document and embeds a `jti` claim. `get_current_user` validates that the
session is still active (lenient for legacy tokens without `jti`).
"""
from __future__ import annotations
import os, secrets as _s
from datetime import datetime, timedelta, timezone
from typing import Optional, Set, Tuple
import jwt
from fastapi import Depends, HTTPException, Request

from db import col, USERS, ORGANIZATIONS, SESSIONS
from roles import Role, INTERNAL_ROLES, is_internal
from models import utc_now

JWT_SECRET = os.environ.get("JWT_SECRET", "phase0-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = 7 * 24 * 3600


# ---------------------------------------------------------------------------
# Token mint / verify
# ---------------------------------------------------------------------------
def make_jwt(*, user_id: str, email: str, role: Role, org_id: Optional[str],
              jti: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role.value,
        "org_id": org_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=JWT_TTL_SECONDS)).timestamp()),
    }
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def mint_session_token(
    *, user_id: str, email: str, role: Role, org_id: Optional[str],
    request: Optional[Request] = None,
    label: Optional[str] = None,
) -> str:
    """Create a session record + return a JWT carrying its `jti`.

    Used by login flows (`/auth/passwordless-token`, `/auth/dev-login`). The
    session is what gets listed/revoked in `/v1/client/sessions`.
    """
    jti = "ses_" + _s.token_hex(10)
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_at = (datetime.now(timezone.utc)
                   + timedelta(seconds=JWT_TTL_SECONDS)).isoformat()
    ip = request.client.host if (request and request.client) else None
    ua = request.headers.get("User-Agent") if request else None
    session_doc = {
        "session_id":   jti,
        "user_id":      user_id,
        "org_id":       org_id,
        "email":        email,
        "ip":           ip,
        "user_agent":   ua or "",
        "label":        label or _parse_ua_label(ua),
        "created_at":   now_iso,
        "last_seen_at": now_iso,
        "expires_at":   expires_at,
        "revoked":      False,
        "is_deleted":   False,
    }
    await col(SESSIONS).insert_one(dict(session_doc))
    return make_jwt(user_id=user_id, email=email, role=role,
                    org_id=org_id, jti=jti)


def _parse_ua_label(ua: Optional[str]) -> str:
    """Best-effort device label from User-Agent — no full parser."""
    if not ua:
        return "Desconocido"
    s = ua.lower()
    browser = "Browser"
    for key, label in [("edg/", "Edge"), ("chrome/", "Chrome"),
                        ("firefox/", "Firefox"), ("safari/", "Safari")]:
        if key in s and not (key == "safari/" and "chrome/" in s):
            browser = label; break
    os_name = "Desktop"
    if "iphone" in s or "ios" in s:        os_name = "iPhone"
    elif "ipad" in s:                       os_name = "iPad"
    elif "android" in s:                    os_name = "Android"
    elif "mac os" in s or "macintosh" in s: os_name = "macOS"
    elif "windows" in s:                    os_name = "Windows"
    elif "linux" in s:                      os_name = "Linux"
    return f"{browser} · {os_name}"


def parse_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


# ---------------------------------------------------------------------------
# Current user resolver
# ---------------------------------------------------------------------------
class CurrentUser:
    """Lightweight DTO returned by `get_current_user`."""
    def __init__(self, *, user_id: str, email: str, role: Role, org_id: Optional[str],
                 acting_as_org: Optional[str] = None, ip: Optional[str] = None,
                 user_agent: Optional[str] = None, jti: Optional[str] = None):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.org_id = org_id  # the user's own org from JWT
        self.acting_as_org = acting_as_org  # internal impersonation header
        self.ip = ip
        self.user_agent = user_agent
        self.jti = jti  # session id (None for legacy tokens)

    @property
    def scope_org_id(self) -> Optional[str]:
        """The org_id used for data scoping in the current request.
        - Internal users: prefer X-Acting-As-Org if present, else None (= all orgs).
        - Client users: always their own org.
        """
        if is_internal(self.role):
            return self.acting_as_org  # may be None ⇒ no scope (admin view)
        return self.org_id

    @property
    def is_internal(self) -> bool:
        return is_internal(self.role)


async def get_current_user(request: Request) -> CurrentUser:
    # 1) JWT from cookie OR Authorization header
    token = request.cookies.get("prosper_session")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Not authenticated")
    payload = parse_jwt(token)
    try:
        role = Role(payload["role"])
    except (KeyError, ValueError):
        raise HTTPException(401, "Token missing role claim")

    # 2) X-Acting-As-Org (internal users only)
    acting = request.headers.get("X-Acting-As-Org")
    if acting and not is_internal(role):
        raise HTTPException(403, "Only internal staff can use X-Acting-As-Org")

    # 3) If the token has a session id, ensure the session is still active.
    jti = payload.get("jti")
    if jti:
        sess = await col(SESSIONS).find_one(
            {"session_id": jti, "is_deleted": False}, {"_id": 0, "revoked": 1})
        if not sess:
            raise HTTPException(401, "Session not found")
        if sess.get("revoked"):
            raise HTTPException(401, "Session revoked")
        # Lazy last_seen_at update — best effort, no await chain on hot path
        await col(SESSIONS).update_one(
            {"session_id": jti},
            {"$set": {"last_seen_at": datetime.now(timezone.utc).isoformat()}})

    return CurrentUser(
        user_id=payload["sub"],
        email=payload.get("email", ""),
        role=role,
        org_id=payload.get("org_id"),
        acting_as_org=acting,
        ip=(request.client.host if request.client else None),
        user_agent=request.headers.get("User-Agent"),
        jti=jti,
    )


# ---------------------------------------------------------------------------
# Role + scope guards (FastAPI Depends factories)
# ---------------------------------------------------------------------------
def requires_role(*allowed: Role):
    allowed_set: Set[Role] = set(allowed)
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_set:
            raise HTTPException(403, f"Role {user.role.value} not permitted")
        return user
    return _dep


def org_scoped():
    """Returns a `(user, scope_filter)` tuple. Use as Depends().

    `scope_filter` is a dict ready to spread into Mongo queries. For internal
    users without an X-Acting-As-Org header it's empty (= sees everything);
    for client users it's `{ "org_id": <their_org> }`. For internal users
    impersonating with X-Acting-As-Org it's `{ "org_id": <header> }`.
    """
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> Tuple[CurrentUser, dict]:
        org = user.scope_org_id
        return user, ({"org_id": org} if org else {})
    return _dep


# ---------------------------------------------------------------------------
# Cross-org guard helper — call from a route to assert ownership of a resource
# ---------------------------------------------------------------------------
async def assert_can_read(user: CurrentUser, resource_org_id: Optional[str]):
    """Mimic 404 (not 403) when a client_user touches another org's resource."""
    if user.is_internal:
        # Internal users always pass. If they're acting-as a specific org they
        # only see that org's data — we still let them read across orgs since
        # data filtering already happens at the query layer.
        if user.acting_as_org and resource_org_id and user.acting_as_org != resource_org_id:
            raise HTTPException(404, "Not found")
        return
    if not user.org_id or resource_org_id != user.org_id:
        raise HTTPException(404, "Not found")
