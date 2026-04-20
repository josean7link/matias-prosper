"""Auto-split from routers.py (2026-04-20). Domain: end_customers."""
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
# END CUSTOMERS
# ==========================================================================
# ============================================================================
# END CUSTOMERS (for partner orgs)
# ============================================================================
ec_router = APIRouter(prefix="/end-customers", tags=["end-customers"])


@ec_router.get("")
async def list_ecs(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    items = await col(END_CUSTOMERS).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}

