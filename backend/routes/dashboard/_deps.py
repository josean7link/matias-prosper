"""Shared helpers for dashboard sub-routes."""
from datetime import datetime, timezone

from auth import requires_role
from roles import Role

# Roles allowed to read the dashboard
DASH_ROLES = (Role.super_admin, Role.admin, Role.finance)
require_dashboard = requires_role(*DASH_ROLES)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat()
