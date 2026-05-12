"""Shared helpers used across router modules."""
from __future__ import annotations
from typing import Any, Dict, Optional

from db import col, AUDIT_LOGS
from models import User, new_id, now_utc


def _strip_id(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


async def _log_audit(actor: Optional[User], action: str, resource: str, resource_id: str = "",
                     environment: str = "production", metadata: Optional[dict] = None):
    await col(AUDIT_LOGS).insert_one({
        "audit_id": f"aud_{new_id()}",
        "actor_id": actor.user_id if actor else None,
        "actor_email": actor.email if actor else None,
        "action": action, "resource": resource, "resource_id": resource_id,
        "environment": environment,
        "metadata": metadata or {},
        "created_at": now_utc().isoformat(),
        "is_demo": False,
    })


def _user_scope(user: User) -> Dict[str, Any]:
    """Return a MongoDB filter dict that scopes queries to the user's org.

    Internal Prosper staff (is_internal=True) see everything.
    External users only see their own `org_id`.
    """
    if user.is_internal or user.platform_role == "super_admin":
        return {}
    return {"org_id": user.org_id or "__none__"}


def _apply_scope(query: Dict[str, Any], user: User) -> Dict[str, Any]:
    scope = _user_scope(user)
    return {**query, **scope} if scope else query
