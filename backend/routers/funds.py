"""Auto-split from routers.py (2026-04-20). Domain: funds."""
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
# FUNDS + PRODUCTS
# ==========================================================================
# ============================================================================
# FUNDS + PRODUCTS
# ============================================================================
funds_router = APIRouter(prefix="/funds", tags=["funds"])


@funds_router.get("")
async def list_funds(env: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if env:
        q["environment"] = env
    items = await col(FUNDS).find(q, {"_id": 0}).to_list(100)
    for f in items:
        f["products"] = await col(PRODUCTS).find({"fund_id": f["fund_id"]}, {"_id": 0}).to_list(50)
    return {"items": items, "total": len(items)}


@funds_router.get("/{fund_id}/nav")
async def fund_nav(fund_id: str, user: User = Depends(get_current_user)):
    items = await col(NAV_SNAPSHOTS).find(
        {"fund_id": fund_id}, {"_id": 0}
    ).sort("as_of", 1).to_list(500)
    return {"items": items}


class FundCreate(BaseModel):
    code: str
    name: str
    underlying: str
    home_domain: Optional[str] = None
    initial_amount: float = 0
    environment: str = "sandbox"


@funds_router.post("")
async def create_fund(body: FundCreate,
                      user: User = Depends(require_roles("super_admin", "ops"))):
    prosper_tx_id = str(uuid.uuid4())
    proxy = await prosper_client.call("POST", "/v1/funds", {
        "InitialAmount": str(body.initial_amount),
        "homeDomain": body.home_domain or "prosper.foundation",
        "prosperTxId": prosper_tx_id,
    })
    doc = {
        "fund_id": f"fund_{new_id()}", "code": body.code, "name": body.name,
        "underlying": body.underlying, "home_domain": body.home_domain,
        "total_supply": body.initial_amount,
        "circulating_supply": 0, "nav_per_token": 1.0,
        "status": "active", "environment": body.environment,
        "is_demo": False, "created_at": now_utc().isoformat(),
    }
    await col(FUNDS).insert_one(dict(doc))
    await _log_audit(user, "fund.create", "fund", doc["fund_id"], environment=body.environment,
                     metadata={"prosper_tx_id": prosper_tx_id, "proxy": proxy})
    _strip_id(doc)
    return {"fund": doc, "prosper_tx_id": prosper_tx_id, "proxy": proxy}


products_router = APIRouter(prefix="/products", tags=["products"])


@products_router.get("")
async def list_products(user: User = Depends(get_current_user)):
    items = await col(PRODUCTS).find({}, {"_id": 0}).to_list(200)
    return {"items": items, "total": len(items)}



# ---- Product create (missing) ----
class ProductCreate(BaseModel):
    fund_id: str
    name: str
    kind: str = "term_staking"
    term_days: Optional[int] = None
    apr_bps: int = 0
    min_amount: float = 0
    payout_asset: str = "USDC"
    principal_asset: str = "PROS"


@products_router.post("")
async def create_product(body: ProductCreate,
                         user: User = Depends(require_roles("super_admin", "ops", "finance"))):
    doc = {
        "product_id": f"prod_{new_id()}", **body.model_dump(),
        "max_amount": None, "status": "active",
        "is_demo": False, "created_at": now_utc().isoformat(),
    }
    await col(PRODUCTS).insert_one(dict(doc))
    await _log_audit(user, "product.create", "product", doc["product_id"])
    _strip_id(doc)
    return doc
