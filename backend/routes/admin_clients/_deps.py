"""Shared deps for /admin/clients route family."""
from datetime import datetime, timezone
from fastapi import HTTPException
from auth import requires_role
from roles import Role

ADMIN_ROLES = (Role.super_admin, Role.admin)
WRITE_ROLES = (Role.super_admin, Role.admin)

require_admin = requires_role(*ADMIN_ROLES)
require_write = requires_role(*WRITE_ROLES)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
