"""Auto-split from routers.py (2026-04-20). Domain: transactions."""
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
# TRANSACTIONS
# ==========================================================================
# ============================================================================
# TRANSACTIONS
# ============================================================================
tx_router = APIRouter(prefix="/transactions", tags=["transactions"])


@tx_router.get("")
async def list_tx(
    env: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    org_id: Optional[str] = None,
    search: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = 1,
    page_size: int = 50,
    limit: Optional[int] = None,  # backwards compat
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if env:
        q["environment"] = env
    if type:
        q["type"] = type
    if status:
        q["status"] = status
    if org_id:
        q["org_id"] = org_id
    if search:
        q["$or"] = [
            {"tx_hash": {"$regex": search, "$options": "i"}},
            {"prosper_tx_id": {"$regex": search, "$options": "i"}},
            {"memo": {"$regex": search, "$options": "i"}},
        ]
    if from_date or to_date:
        created: Dict[str, Any] = {}
        if from_date:
            created["$gte"] = from_date
        if to_date:
            created["$lte"] = to_date + "T23:59:59.999Z" if len(to_date) == 10 else to_date
        q["created_at"] = created
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id

    # Legacy `limit` takes precedence
    if limit:
        items = await col(TRANSACTIONS).find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
        return {"items": items, "total": len(items), "page": 1, "page_size": limit, "has_more": False}

    page = max(page, 1)
    page_size = max(1, min(page_size, 500))
    total = await col(TRANSACTIONS).count_documents(q)
    items = await col(TRANSACTIONS).find(q, {"_id": 0})\
        .sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "has_more": page * page_size < total}


class MintRequest(BaseModel):
    fund_id: str
    amount: float
    reason: str


@tx_router.post("/mint")
async def mint(body: MintRequest, request: Request,
               user: User = Depends(require_roles("super_admin", "ops", "finance"))):
    """Mint request now requires TWO-SIGNER approval. Creates a pending approval instead of executing."""
    # Idempotency: if same request already created an approval, return it
    idem_key = request.headers.get("Idempotency-Key")
    if idem_key:
        cached = await col(IDEMPOTENCY).find_one({"key": idem_key, "scope": "mint"}, {"_id": 0})
        if cached:
            return cached["response"]

    prosper_tx_id = str(uuid.uuid4())
    approval = await approvals_mod.create_approval_request(
        action="mint",
        payload={"fund_id": body.fund_id, "amount": body.amount, "reason": body.reason,
                 "prosper_tx_id": prosper_tx_id},
        requester=user,
        reason=body.reason,
    )
    await _log_audit(user, "mint.requested", "approval", approval["approval_id"],
                     metadata={"prosper_tx_id": prosper_tx_id, "amount": body.amount})

    response = {"approval": approval, "status": "pending_approval",
                "message": f"Awaiting {approval['required_approvals']} approver(s). Approve in the Operations Queue.",
                "prosper_tx_id": prosper_tx_id}

    if idem_key:
        await col(IDEMPOTENCY).insert_one({
            "key": idem_key, "scope": "mint", "response": response,
            "created_at": now_utc().isoformat(),
        })
    return response

