"""Auto-split from routers.py (2026-04-20). Domain: dashboard."""
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
# DASHBOARD
# ==========================================================================
# ============================================================================
# DASHBOARD (aggregated KPIs)
# ============================================================================
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@dashboard_router.get("/overview")
async def overview(env: str = "production", user: User = Depends(get_current_user)):
    fund_filter = {"environment": env}
    funds = await col(FUNDS).find(fund_filter, {"_id": 0}).to_list(50)
    aum = sum(f.get("circulating_supply", 0) * f.get("nav_per_token", 1) for f in funds)
    total_supply = sum(f.get("total_supply", 0) for f in funds)
    circ = sum(f.get("circulating_supply", 0) for f in funds)

    active_orgs = await col(ORGANIZATIONS).count_documents({"environment": env, "status": "active"})
    active_investors_cursor = col(ORGANIZATIONS).find({"environment": env}, {"_id": 0, "active_investors": 1})
    active_investors = sum([o.get("active_investors", 0) async for o in active_investors_cursor])

    tx_today = await col(TRANSACTIONS).count_documents({
        "environment": env,
        "created_at": {"$gte": (now_utc() - timedelta(hours=24)).isoformat()}
    })
    pending_recon = await col(RECONCILIATION).count_documents({"status": {"$ne": "matched"}})
    open_onboarding = await col(ONBOARDING).count_documents({"status": {"$in": ["submitted", "under_review", "needs_info"]}})
    open_alerts = await col(ALERTS).count_documents({"resolved": False})

    # NAV series (last 14 days) — pick primary fund
    primary = next((f for f in funds if f.get("code") == "PROS"), funds[0] if funds else None)
    nav_series = []
    if primary:
        navs = await col(NAV_SNAPSHOTS).find(
            {"fund_id": primary["fund_id"]},
            {"_id": 0}
        ).sort("as_of", 1).to_list(60)
        nav_series = [{"as_of": n["as_of"], "nav": n["nav_per_token"]} for n in navs]

    # Tx volume by day (14d)
    cutoff = (now_utc() - timedelta(days=14)).isoformat()
    txs = await col(TRANSACTIONS).find(
        {"environment": env, "created_at": {"$gte": cutoff}},
        {"_id": 0, "created_at": 1, "amount": 1, "type": 1}
    ).to_list(5000)
    by_day: Dict[str, float] = {}
    for t in txs:
        d = t["created_at"][:10]
        by_day[d] = by_day.get(d, 0) + float(t.get("amount", 0))
    vol_series = [{"date": d, "volume": v} for d, v in sorted(by_day.items())]

    # Yield paid (sum of claim transactions last 30d)
    claim_cutoff = (now_utc() - timedelta(days=30)).isoformat()
    yield_txs = await col(TRANSACTIONS).find(
        {"environment": env, "type": "claim", "created_at": {"$gte": claim_cutoff}},
        {"_id": 0, "amount": 1}
    ).to_list(10000)
    yield_paid = sum(float(t.get("amount", 0)) for t in yield_txs)

    return {
        "environment": env,
        "kpis": {
            "aum_usd": aum,
            "total_supply": total_supply,
            "circulating_supply": circ,
            "active_orgs": active_orgs,
            "active_investors": active_investors,
            "tx_24h": tx_today,
            "pending_reconciliation": pending_recon,
            "open_onboarding": open_onboarding,
            "open_alerts": open_alerts,
            "yield_paid_30d": yield_paid,
        },
        "nav_series": nav_series,
        "volume_series": vol_series,
        "primary_fund_code": primary["code"] if primary else None,
    }

