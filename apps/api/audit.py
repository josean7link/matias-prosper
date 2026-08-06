"""Phase 1 — audit log helper + decorator wrapping privileged writes."""
from __future__ import annotations
import functools
import inspect
from typing import Any, Callable, Optional

from db import write_audit
from models import AuditLog, utc_now
from auth import CurrentUser


async def log_action(
    *,
    actor: Optional[CurrentUser],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    org_id_override: Optional[str] = None,
):
    """Persist a single audit-log entry. Uses the actor's `scope_org_id` for `org_id`
    so impersonated views land under the impersonated org (and are easy to filter)."""
    entry = AuditLog(
        org_id=org_id_override or (actor.scope_org_id if actor else None),
        actor_user_id=actor.user_id if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata={
            **(metadata or {}),
            **({"acting_as_org": actor.acting_as_org} if actor and actor.acting_as_org else {}),
        },
        ip=actor.ip if actor else None,
        user_agent=actor.user_agent if actor else None,
        timestamp=utc_now(),
    ).model_dump()
    return await write_audit(entry)


def audited(action: str, resource_type: str, *, resource_id_arg: str = "resource_id"):
    """Decorator that records a privileged write after a successful call.

    Usage:
        @audited("organization.created", "organization", resource_id_arg="org_id")
        async def create_org(body: ..., user: CurrentUser = Depends(...)):
            ...
            return {"org_id": new_id, ...}

    Reads the actor from one of the kwargs (`user`, `current_user`, `acting_user`).
    Picks the resource_id from the function's return value (if it's a dict) or
    from a named kwarg.
    """
    def deco(fn: Callable[..., Any]):
        sig = inspect.signature(fn)
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            actor = None
            for k in ("user", "current_user", "acting_user"):
                if k in bound.arguments and isinstance(bound.arguments[k], CurrentUser):
                    actor = bound.arguments[k]; break
            result = await fn(*args, **kwargs) if inspect.iscoroutinefunction(fn) else fn(*args, **kwargs)
            rid: Optional[str] = None
            if isinstance(result, dict):
                rid = result.get(resource_id_arg)
            if rid is None and resource_id_arg in bound.arguments:
                rid = bound.arguments[resource_id_arg]
            await log_action(actor=actor, action=action, resource_type=resource_type,
                             resource_id=rid, metadata={"args": _summary_args(bound.arguments)})
            return result
        return wrapper
    return deco


def _summary_args(arguments: dict) -> dict:
    """Strip non-serialisable bits (Request, CurrentUser, large bodies) before audit."""
    out: dict[str, Any] = {}
    for k, v in arguments.items():
        if k in ("request", "response", "user", "current_user", "acting_user"):
            continue
        if hasattr(v, "model_dump"):
            try:
                out[k] = v.model_dump(); continue
            except Exception:
                pass
        if isinstance(v, (str, int, float, bool, list, dict)) or v is None:
            out[k] = v
        else:
            out[k] = str(type(v).__name__)
    return out
