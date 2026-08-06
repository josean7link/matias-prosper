"""Shared helpers for Phase 5 compliance route module."""
from fastapi import Depends
from auth import CurrentUser, requires_role
from roles import Role

COMPLIANCE_ROLES = (Role.super_admin, Role.admin, Role.compliance_officer)
COMPLIANCE_DECIDE_ROLES = (Role.super_admin, Role.compliance_officer)

# Sanctions/PEP MANUAL OVERRIDE — higher bar than identity review. Allowed
# ONLY while `SANCTIONS_PROVIDER=manual` and used by super_admin / finance
# to unblock the sanctions gate for demos and edge cases. NEVER expose to
# compliance_officer or any client role.
SANCTIONS_OVERRIDE_ROLES = (Role.super_admin, Role.finance)

require_compliance = requires_role(*COMPLIANCE_ROLES)
require_compliance_decide = requires_role(*COMPLIANCE_DECIDE_ROLES)
