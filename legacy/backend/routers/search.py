"""Auto-split from routers.py (2026-04-20). Domain: search."""
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
# GLOBAL SEARCH (⌘K)
# ==========================================================================
# ============================================================================
# GLOBAL SEARCH (for ⌘K command palette)
# ============================================================================
search_router = APIRouter(prefix="/search", tags=["search"])


@search_router.get("")
async def global_search(q: str = Query(..., min_length=1), user: User = Depends(get_current_user)):
    """Returns up to 6 matches per domain across orgs, transactions, positions, api keys, onboarding."""
    qr = {"$regex": q, "$options": "i"}

    orgs_task = col(ORGANIZATIONS).find({"name": qr}, {"_id": 0, "org_id": 1, "name": 1, "type": 1})\
        .limit(6).to_list(6)
    tx_task = col(TRANSACTIONS).find({"$or": [
        {"prosper_tx_id": qr}, {"tx_hash": qr}, {"memo": qr}
    ]}, {"_id": 0, "tx_id": 1, "prosper_tx_id": 1, "type": 1, "amount": 1, "status": 1}).limit(6).to_list(6)
    pos_task = col(POSITIONS).find({"$or": [
        {"position_id": qr}, {"user_reference_id": qr}, {"stellar_address": qr}
    ]}, {"_id": 0, "position_id": 1, "user_reference_id": 1, "principal": 1, "status": 1}).limit(6).to_list(6)
    keys_task = col(API_KEYS).find({"$or": [
        {"label": qr}, {"key_prefix": qr}
    ]}, {"_id": 0, "key_id": 1, "label": 1, "key_prefix": 1, "environment": 1, "status": 1}).limit(6).to_list(6)
    onb_task = col(ONBOARDING).find({"$or": [
        {"applicant_name": qr}, {"applicant_email": qr}, {"case_id": qr}
    ]}, {"_id": 0, "case_id": 1, "applicant_name": 1, "applicant_email": 1, "status": 1}).limit(6).to_list(6)

    import asyncio
    orgs, txs, positions, keys, cases = await asyncio.gather(
        orgs_task, tx_task, pos_task, keys_task, onb_task
    )
    return {
        "query": q,
        "groups": [
            {"label": "Clients", "kind": "organization", "items": [
                {"id": o["org_id"], "title": o["name"], "subtitle": f"{o.get('type', '')} · {o['org_id'][:12]}", "url": f"/app/clients/{o['org_id']}"} for o in orgs
            ]},
            {"label": "Transactions", "kind": "transaction", "items": [
                {"id": t["tx_id"], "title": f"{t['type'].upper()} · {t.get('amount', 0)}",
                 "subtitle": t.get("prosper_tx_id", "")[:16] + "…", "url": "/app/transactions"} for t in txs
            ]},
            {"label": "Positions", "kind": "position", "items": [
                {"id": p["position_id"], "title": p.get("user_reference_id") or p["position_id"],
                 "subtitle": f"principal {p.get('principal', 0)} · {p.get('status', '')}",
                 "url": "/app/positions"} for p in positions
            ]},
            {"label": "API Keys", "kind": "api_key", "items": [
                {"id": k["key_id"], "title": k["label"], "subtitle": f"{k['key_prefix']} · {k.get('environment', '')}",
                 "url": "/app/api-keys"} for k in keys
            ]},
            {"label": "Onboarding", "kind": "onboarding", "items": [
                {"id": c["case_id"], "title": c["applicant_name"],
                 "subtitle": f"{c.get('applicant_email', '')} · {c.get('status', '')}",
                 "url": "/app/onboarding"} for c in cases
            ]},
        ]
    }


