"""Phase 1 — Role enum, shared with the frontend via packages/types."""
from enum import Enum


class Role(str, Enum):
    super_admin        = "super_admin"
    admin              = "admin"
    compliance_officer = "compliance_officer"
    finance            = "finance"
    client_admin       = "client_admin"
    client_user        = "client_user"


# Internal Prosper staff — can see across all orgs (with audit) and act on system-wide ops.
INTERNAL_ROLES = {
    Role.super_admin, Role.admin, Role.compliance_officer, Role.finance,
}
CLIENT_ROLES = {Role.client_admin, Role.client_user}


def is_internal(role: Role) -> bool:
    return role in INTERNAL_ROLES
