"""Auto-split from routers.py (2026-04-20). Domain: positions."""
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
# POSITIONS
# ==========================================================================
# ============================================================================
# POSITIONS
# ============================================================================
pos_router = APIRouter(prefix="/positions", tags=["positions"])


@pos_router.get("")
async def list_positions(
    org_id: Optional[str] = None,
    status: Optional[str] = None,
    product_id: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    if status:
        q["status"] = status
    if product_id:
        q["product_id"] = product_id
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    items = await col(POSITIONS).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}



# ============================================================================
# P0 EXTRA ENDPOINTS — Subscribe/Redeem + missing CRUD
# ============================================================================

# ---- Subscribe / Redeem (core business flow) ----
class SubscribeRequest(BaseModel):
    org_id: str
    product_id: str
    amount: float
    user_reference_id: Optional[str] = None


@pos_router.post("/subscribe")
async def subscribe(body: SubscribeRequest, user: User = Depends(get_current_user)):
    """Subscribe to a product — creates a position and a `subscribe` transaction.

    Flow: USDC in → PROS out from Treasury to user account. Uses prosperTxId as idempotency anchor.
    """
    # Non-internal user can only subscribe on behalf of own org
    if not user.is_internal and body.org_id != user.org_id:
        raise HTTPException(403, "Cannot subscribe on behalf of another org")

    product = await col(PRODUCTS).find_one({"product_id": body.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(404, "Product not found")
    if body.amount < (product.get("min_amount") or 0):
        raise HTTPException(400, f"Amount below minimum of {product.get('min_amount')}")

    fund = await col(FUNDS).find_one({"fund_id": product["fund_id"]}, {"_id": 0})
    prosper_tx_id = str(uuid.uuid4())
    now = now_utc()
    maturity = None
    if product.get("term_days"):
        maturity = now + timedelta(days=product["term_days"])

    # 1) Call upstream Prosper (proxy). If disabled, returns simulated response.
    proxy = await prosper_client.call("POST", "/v1/users/deposit", {
        "userReferenceId": body.user_reference_id or f"user_{user.user_id}",
        "amount": str(body.amount),
        "prosperTxId": prosper_tx_id,
    })
    tx_hash = (proxy.get("data") or {}).get("txHash") if proxy.get("proxied") else \
              hashlib.sha256(prosper_tx_id.encode()).hexdigest()

    # 2) Create position
    position = {
        "position_id": f"pos_{new_id()}",
        "org_id": body.org_id,
        "user_reference_id": body.user_reference_id or f"user_{user.user_id}",
        "product_id": body.product_id,
        "fund_id": product["fund_id"],
        "principal": body.amount,
        "accrued_interest": 0.0, "claimed_interest": 0.0,
        "start_date": now.isoformat(),
        "maturity_date": maturity.isoformat() if maturity else None,
        "status": "active",
        "stellar_address": (proxy.get("data") or {}).get("address"),
        "is_demo": False,
        "created_at": now.isoformat(),
    }
    await col(POSITIONS).insert_one(dict(position))

    # 3) Create transaction
    tx = {
        "tx_id": f"tx_{new_id()}",
        "prosper_tx_id": prosper_tx_id,
        "org_id": body.org_id,
        "user_reference_id": position["user_reference_id"],
        "position_id": position["position_id"],
        "fund_id": product["fund_id"],
        "product_id": body.product_id,
        "type": "subscribe",
        "amount": body.amount,
        "asset_code": "PROS",
        "from_address": fund.get("treasury_address") if fund else None,
        "to_address": position["stellar_address"],
        "memo": prosper_tx_id,
        "tx_hash": tx_hash,
        "status": "submitted" if proxy.get("proxied") else "confirmed",
        "metadata": {"proxy": proxy},
        "environment": fund.get("environment", "sandbox") if fund else "sandbox",
        "is_demo": False,
        "created_at": now.isoformat(),
    }
    await col(TRANSACTIONS).insert_one(dict(tx))

    # 4) Reconciliation stub
    await col(RECONCILIATION).insert_one({
        "recon_id": f"rec_{new_id()}", "prosper_tx_id": prosper_tx_id,
        "onchain_match": proxy.get("proxied", False),
        "offchain_match": True, "tx_hash": tx_hash,
        "status": "matched" if proxy.get("proxied") else "investigating",
        "is_demo": False, "created_at": now.isoformat(),
    })

    await _log_audit(user, "position.subscribe", "position", position["position_id"],
                     metadata={"prosper_tx_id": prosper_tx_id, "amount": body.amount,
                               "product_id": body.product_id})
    _strip_id(position); _strip_id(tx)
    return {"position": position, "transaction": tx, "prosper_tx_id": prosper_tx_id, "proxy": proxy}


@pos_router.post("/{position_id}/redeem")
async def redeem(position_id: str, user: User = Depends(get_current_user)):
    """Redeem a matured (or early) position — PROS back to Treasury + principal+interest out."""
    p = await col(POSITIONS).find_one({"position_id": position_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Position not found")
    if p["status"] in ("redeemed", "cancelled"):
        raise HTTPException(400, f"Position already {p['status']}")
    if not user.is_internal and p.get("org_id") != user.org_id:
        raise HTTPException(403, "Not your position")

    prosper_tx_id = str(uuid.uuid4())
    total_payout = float(p.get("principal", 0)) + float(p.get("accrued_interest", 0))
    now = now_utc()

    proxy = await prosper_client.call("POST", "/v1/users/withdraw", {
        "userReferenceId": p.get("user_reference_id"),
        "amount": str(total_payout),
        "prosperTxId": prosper_tx_id,
    })
    tx_hash = (proxy.get("data") or {}).get("txHash") if proxy.get("proxied") else \
              hashlib.sha256(prosper_tx_id.encode()).hexdigest()

    await col(POSITIONS).update_one(
        {"position_id": position_id},
        {"$set": {"status": "redeemed", "claimed_interest": p.get("accrued_interest", 0)}}
    )

    tx = {
        "tx_id": f"tx_{new_id()}", "prosper_tx_id": prosper_tx_id,
        "org_id": p.get("org_id"), "user_reference_id": p.get("user_reference_id"),
        "position_id": position_id, "fund_id": p.get("fund_id"),
        "product_id": p.get("product_id"),
        "type": "redeem", "amount": total_payout, "asset_code": "USDC",
        "from_address": p.get("stellar_address"),
        "to_address": None,
        "memo": prosper_tx_id, "tx_hash": tx_hash,
        "status": "submitted" if proxy.get("proxied") else "confirmed",
        "metadata": {"principal": p.get("principal"), "interest": p.get("accrued_interest"), "proxy": proxy},
        "environment": "sandbox",
        "is_demo": False, "created_at": now.isoformat(),
    }
    await col(TRANSACTIONS).insert_one(dict(tx))
    await _log_audit(user, "position.redeem", "position", position_id,
                     metadata={"prosper_tx_id": prosper_tx_id, "amount": total_payout})
    _strip_id(tx)
    return {"transaction": tx, "prosper_tx_id": prosper_tx_id, "proxy": proxy}
