"""Auto-split from routers.py (2026-04-20). Domain: admin."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request, UploadFile, File, Form, Header
from pydantic import BaseModel
import hashlib
import secrets
import uuid

from db import (
    col, ORGANIZATIONS, ONBOARDING, COMPLIANCE, FUNDS, PRODUCTS, NAV_SNAPSHOTS,
    TREASURY, POSITIONS, TRANSACTIONS, RECONCILIATION, API_APPS, API_KEYS,
    WEBHOOK_ENDPOINTS, WEBHOOK_DELIVERIES, ALERTS, REPORTS, AUDIT_LOGS,
    END_CUSTOMERS, ORG_USERS, USERS, SESSIONS, APPROVALS, IDEMPOTENCY, DOCUMENTS
)
from models import (
    User, Organization, OnboardingCase, ComplianceReview, Fund, Product,
    NavSnapshot, Position, TreasuryAccount, Transaction, ReconciliationRecord,
    ApiApp, ApiKey, WebhookEndpoint, WebhookDelivery, Alert, Report, AuditLog,
    EndCustomer, OrgUser, now_utc, new_id
)
from auth import (
    get_current_user, require_roles, exchange_session, upsert_user,
    create_session, delete_session,
)
import prosper_client
import seed as seed_module
import approvals as approvals_mod
import mfa as mfa_mod
import webhook_signing
import storage as storage_mod
from ._helpers import _strip_id, _log_audit, _user_scope, _apply_scope


# ==========================================================================
# ADMIN (seed / wipe)
# ==========================================================================
# SEED / ADMIN
# ============================================================================
admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post("/seed")
async def run_seed(force: bool = False, user: Optional[User] = None):
    # Open-access seeding (no auth) because it's demo data, and first-time
    # bootstrap might run before any user exists. Safe because it only adds
    # data tagged is_demo=true.
    return await seed_module.seed_all(force=force)


@admin_router.post("/wipe-demo")
async def wipe_demo_endpoint(user: User = Depends(require_roles("super_admin"))):
    await seed_module.wipe_demo()
    await _log_audit(user, "admin.wipe_demo", "system")
    return {"ok": True}


@admin_router.get("/prosper-upstream")
async def prosper_upstream_status(user: User = Depends(require_roles("super_admin", "ops"))):
    """Diagnostic: is the real Prosper Stellar API reachable + authenticating?

    Returns:
      - enabled: whether PROSPER_API_ENABLED is true
      - base_url: the configured upstream URL
      - reachable: True if we can complete a TCP+TLS+HTTP roundtrip
      - authenticated: True if /v1/Auth/Login returns a token
    """
    import os
    info = {
        "enabled": prosper_client.PROSPER_API_ENABLED,
        "base_url": prosper_client.PROSPER_API_BASE,
        "reachable": False,
        "authenticated": False,
        "error": None,
    }
    if not prosper_client.PROSPER_API_ENABLED:
        info["error"] = "PROSPER_API_ENABLED=false — set it to true in backend/.env to enable the proxy"
        return info
    # Force a fresh login attempt
    prosper_client._jwt_cache["token"] = None
    token = await prosper_client._login()
    if token:
        info["reachable"] = True
        info["authenticated"] = True
    else:
        # Try a bare GET to see if host is even reachable
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(prosper_client.PROSPER_API_BASE)
                info["reachable"] = True
                info["error"] = f"Host reachable but login failed (HTTP {r.status_code})"
        except Exception as e:
            info["error"] = f"Host unreachable: {type(e).__name__}: {e}"
    return info

