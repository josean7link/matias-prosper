"""Shared helpers for Phase 5 compliance route module."""
from fastapi import Depends
from auth import CurrentUser, requires_role
from roles import Role

COMPLIANCE_ROLES = (Role.super_admin, Role.admin, Role.compliance_officer)
COMPLIANCE_DECIDE_ROLES = (Role.super_admin, Role.compliance_officer)

require_compliance = requires_role(*COMPLIANCE_ROLES)
require_compliance_decide = requires_role(*COMPLIANCE_DECIDE_ROLES)
