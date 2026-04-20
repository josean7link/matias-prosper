"""All API routers for the Prosper platform, grouped by domain."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from pydantic import BaseModel
import hashlib
import secrets
import uuid

from db import (
    col, ORGANIZATIONS, ONBOARDING, COMPLIANCE, FUNDS, PRODUCTS, NAV_SNAPSHOTS,
    TREASURY, POSITIONS, TRANSACTIONS, RECONCILIATION, API_APPS, API_KEYS,
    WEBHOOK_ENDPOINTS, WEBHOOK_DELIVERIES, ALERTS, REPORTS, AUDIT_LOGS,
    END_CUSTOMERS, ORG_USERS, USERS, SESSIONS, APPROVALS, IDEMPOTENCY
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

# Tag helpers -----------------------------------------------------------------


def _strip_id(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


async def _log_audit(actor: User | None, action: str, resource: str, resource_id: str = "",
                     environment: str = "production", metadata: Optional[dict] = None):
    await col(AUDIT_LOGS).insert_one({
        "audit_id": f"aud_{new_id()}",
        "actor_id": actor.user_id if actor else None,
        "actor_email": actor.email if actor else None,
        "action": action, "resource": resource, "resource_id": resource_id,
        "environment": environment,
        "metadata": metadata or {},
        "created_at": now_utc().isoformat(),
        "is_demo": False,
    })


def _user_scope(user: User) -> Dict[str, Any]:
    """Return a MongoDB filter dict that scopes queries to the user's org.

    Internal Prosper staff (is_internal=True) see everything.
    External users only see their own `org_id`.
    """
    if user.is_internal or user.platform_role == "super_admin":
        return {}
    return {"org_id": user.org_id or "__none__"}


def _apply_scope(query: Dict[str, Any], user: User) -> Dict[str, Any]:
    scope = _user_scope(user)
    return {**query, **scope} if scope else query


# ============================================================================
# AUTH
# ============================================================================
auth_router = APIRouter(prefix="/auth", tags=["auth"])


class SessionRequest(BaseModel):
    session_id: str


@auth_router.post("/session")
async def create_session_endpoint(body: SessionRequest, response: Response):
    data = await exchange_session(body.session_id)
    user = await upsert_user(data)
    session_token = data["session_token"]
    await create_session(user.user_id, session_token)
    response.set_cookie(
        "session_token", session_token,
        httponly=True, secure=True, samesite="none",
        path="/", max_age=7 * 24 * 3600,
    )
    await _log_audit(user, "user.login", "user", user.user_id)
    return {"user": user.model_dump(mode="json"), "session_token": session_token}


@auth_router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return user.model_dump(mode="json")


@auth_router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token") or ""
    if token:
        await delete_session(token)
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


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


# ============================================================================
# ORGANIZATIONS (clients)
# ============================================================================
orgs_router = APIRouter(prefix="/organizations", tags=["organizations"])


@orgs_router.get("")
async def list_orgs(
    env: Optional[str] = None,
    search: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if env:
        q["environment"] = env
    if type:
        q["type"] = type
    if status:
        q["status"] = status
    if search:
        q["name"] = {"$regex": search, "$options": "i"}
    # Non-internal users only see their own org
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    items = await col(ORGANIZATIONS).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


@orgs_router.get("/{org_id}")
async def get_org(org_id: str, user: User = Depends(get_current_user)):
    doc = await col(ORGANIZATIONS).find_one({"org_id": org_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Org not found")
    # Extras
    apps = await col(API_APPS).count_documents({"org_id": org_id})
    keys = await col(API_KEYS).count_documents({"org_id": org_id, "status": "active"})
    hooks = await col(WEBHOOK_ENDPOINTS).count_documents({"org_id": org_id, "status": "active"})
    positions_count = await col(POSITIONS).count_documents({"org_id": org_id})
    tx_count = await col(TRANSACTIONS).count_documents({"org_id": org_id})
    doc.update({
        "counts": {"apps": apps, "keys": keys, "hooks": hooks,
                   "positions": positions_count, "tx": tx_count}
    })
    return doc


class OrgCreate(BaseModel):
    name: str
    legal_name: Optional[str] = None
    type: str = "partner"
    country: Optional[str] = None
    contact_email: Optional[str] = None
    environment: str = "sandbox"


@orgs_router.post("")
async def create_org(body: OrgCreate, user: User = Depends(require_roles("super_admin", "ops"))):
    doc = {
        "org_id": f"org_{new_id()}",
        **body.model_dump(),
        "status": "active",
        "aum_usd": 0, "active_investors": 0,
        "is_demo": False,
        "created_at": now_utc().isoformat(),
    }
    await col(ORGANIZATIONS).insert_one(dict(doc))
    await _log_audit(user, "org.create", "organization", doc["org_id"])
    _strip_id(doc)
    return doc


# ============================================================================
# ONBOARDING
# ============================================================================
ob_router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@ob_router.get("")
async def list_cases(
    status: Optional[str] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if search:
        q["applicant_name"] = {"$regex": search, "$options": "i"}
    items = await col(ONBOARDING).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


@ob_router.get("/{case_id}")
async def get_case(case_id: str, user: User = Depends(get_current_user)):
    c = await col(ONBOARDING).find_one({"case_id": case_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Case not found")
    review = await col(COMPLIANCE).find_one({"case_id": case_id}, {"_id": 0})
    return {"case": c, "compliance": review}


class CaseUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    progress: Optional[int] = None


@ob_router.patch("/{case_id}")
async def update_case(case_id: str, body: CaseUpdate,
                      user: User = Depends(require_roles("super_admin", "ops", "compliance"))):
    patch: Dict[str, Any] = {"updated_at": now_utc().isoformat()}
    for k, v in body.model_dump(exclude_none=True).items():
        patch[k] = v
    r = await col(ONBOARDING).update_one({"case_id": case_id}, {"$set": patch})
    if r.matched_count == 0:
        raise HTTPException(404, "Case not found")
    await _log_audit(user, f"onboarding.{body.status or 'update'}", "onboarding_case", case_id)
    doc = await col(ONBOARDING).find_one({"case_id": case_id}, {"_id": 0})
    return doc


# ============================================================================
# COMPLIANCE
# ============================================================================
comp_router = APIRouter(prefix="/compliance", tags=["compliance"])


@comp_router.get("/queue")
async def comp_queue(user: User = Depends(get_current_user)):
    reviews = await col(COMPLIANCE).find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Attach case info
    case_ids = list({r["case_id"] for r in reviews})
    cases = await col(ONBOARDING).find({"case_id": {"$in": case_ids}}, {"_id": 0}).to_list(500)
    by_id = {c["case_id"]: c for c in cases}
    for r in reviews:
        r["case"] = by_id.get(r["case_id"])
    return {"items": reviews, "total": len(reviews)}


class CompDecision(BaseModel):
    decision: str
    comments: Optional[str] = None


@comp_router.post("/{review_id}/decide")
async def decide(review_id: str, body: CompDecision,
                 user: User = Depends(require_roles("super_admin", "compliance"))):
    r = await col(COMPLIANCE).find_one({"review_id": review_id}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Review not found")
    await col(COMPLIANCE).update_one(
        {"review_id": review_id},
        {"$set": {"decision": body.decision, "comments": body.comments, "reviewer_id": user.user_id}}
    )
    # If approved, move case to approved
    if body.decision == "approved":
        await col(ONBOARDING).update_one(
            {"case_id": r["case_id"]},
            {"$set": {"status": "approved", "progress": 100}}
        )
    elif body.decision == "rejected":
        await col(ONBOARDING).update_one(
            {"case_id": r["case_id"]},
            {"$set": {"status": "rejected", "progress": 100}}
        )
    await _log_audit(user, f"compliance.{body.decision}", "compliance_review", review_id)
    return {"ok": True}


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
# TREASURY
# ============================================================================
treas_router = APIRouter(prefix="/treasury", tags=["treasury"])


@treas_router.get("/accounts")
async def list_accounts(env: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if env:
        q["environment"] = env
    items = await col(TREASURY).find(q, {"_id": 0}).to_list(100)
    return {"items": items, "total": len(items)}


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


# ============================================================================
# RECONCILIATION
# ============================================================================
recon_router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@recon_router.get("")
async def list_recon(
    status: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    items = await col(RECONCILIATION).find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Join tx by prosper_tx_id
    p_ids = [r["prosper_tx_id"] for r in items]
    tx_map = {}
    if p_ids:
        async for t in col(TRANSACTIONS).find({"prosper_tx_id": {"$in": p_ids}}, {"_id": 0}):
            tx_map[t["prosper_tx_id"]] = t
    for r in items:
        r["tx"] = tx_map.get(r["prosper_tx_id"])
    return {"items": items, "total": len(items)}


@recon_router.post("/{recon_id}/resolve")
async def resolve_recon(recon_id: str, user: User = Depends(require_roles("super_admin", "ops", "finance"))):
    r = await col(RECONCILIATION).update_one(
        {"recon_id": recon_id},
        {"$set": {"status": "resolved", "discrepancy": None}}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Record not found")
    await _log_audit(user, "recon.resolve", "reconciliation", recon_id)
    return {"ok": True}


# ============================================================================
# API APPS / KEYS / WEBHOOKS
# ============================================================================
int_router = APIRouter(prefix="/integrations", tags=["integrations"])


@int_router.get("/apps")
async def list_apps(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    items = await col(API_APPS).find(q, {"_id": 0}).to_list(200)
    return {"items": items, "total": len(items)}


class AppCreate(BaseModel):
    org_id: str
    name: str
    description: Optional[str] = None
    environment: str = "sandbox"


@int_router.post("/apps")
async def create_app(body: AppCreate, user: User = Depends(require_roles("super_admin", "ops", "client_admin"))):
    doc = {
        "app_id": f"app_{new_id()}", **body.model_dump(),
        "status": "active", "is_demo": False,
        "created_at": now_utc().isoformat(),
    }
    await col(API_APPS).insert_one(dict(doc))
    await _log_audit(user, "app.create", "api_app", doc["app_id"])
    _strip_id(doc)
    return doc


@int_router.get("/keys")
async def list_keys(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    items = await col(API_KEYS).find(q, {"_id": 0}).to_list(200)
    return {"items": items, "total": len(items)}


class KeyCreate(BaseModel):
    app_id: str
    org_id: str
    label: str
    scopes: List[str] = []
    environment: str = "sandbox"


@int_router.post("/keys")
async def create_key(body: KeyCreate, user: User = Depends(require_roles("super_admin", "ops", "client_admin", "developer"))):
    raw = f"pk_{body.environment[:4]}_{secrets.token_urlsafe(32)}"
    doc = {
        "key_id": f"key_{new_id()}", **body.model_dump(),
        "key_prefix": raw[:16] + "...",
        "key_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "status": "active", "last_used_at": None,
        "is_demo": False, "created_at": now_utc().isoformat(),
    }
    await col(API_KEYS).insert_one(dict(doc))
    await _log_audit(user, "apikey.create", "api_key", doc["key_id"])
    # Return the raw key ONCE (never stored in plaintext)
    _strip_id(doc)
    return {"api_key_plaintext": raw, **doc}


@int_router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, user: User = Depends(require_roles("super_admin", "ops", "client_admin"))):
    r = await col(API_KEYS).update_one({"key_id": key_id}, {"$set": {"status": "revoked"}})
    if r.matched_count == 0:
        raise HTTPException(404, "Key not found")
    await _log_audit(user, "apikey.revoke", "api_key", key_id)
    return {"ok": True}


@int_router.get("/webhooks")
async def list_webhooks(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    if not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    # NEVER return the stored `secret` field
    items = await col(WEBHOOK_ENDPOINTS).find(q, {"_id": 0, "secret": 0}).to_list(200)
    return {"items": items, "total": len(items)}


class HookCreate(BaseModel):
    app_id: str
    org_id: str
    url: str
    events: List[str] = []
    environment: str = "sandbox"


@int_router.post("/webhooks")
async def create_webhook(body: HookCreate, user: User = Depends(require_roles("super_admin", "ops", "client_admin", "developer"))):
    full_secret = webhook_signing.generate_secret()
    doc = {
        "endpoint_id": f"hook_{new_id()}", **body.model_dump(),
        "secret": full_secret,  # stored (for signing). Returned ONCE on creation.
        "secret_prefix": full_secret[:14] + "…",
        "status": "active", "is_demo": False,
        "created_at": now_utc().isoformat(),
    }
    await col(WEBHOOK_ENDPOINTS).insert_one(dict(doc))
    await _log_audit(user, "webhook.create", "webhook_endpoint", doc["endpoint_id"])
    _strip_id(doc)
    # Return plaintext secret once
    response = {**doc, "webhook_secret_plaintext": full_secret,
                "signing_instructions": "Verify X-Prosper-Signature: t=<timestamp>,v1=<hmac-sha256(secret, t+'.'+body)>"}
    # Never return stored secret in future list calls
    response.pop("secret", None)
    return response


@int_router.get("/webhooks/{endpoint_id}/deliveries")
async def webhook_deliveries(endpoint_id: str, user: User = Depends(get_current_user)):
    items = await col(WEBHOOK_DELIVERIES).find(
        {"endpoint_id": endpoint_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


# ============================================================================
# ALERTS / REPORTS / AUDIT
# ============================================================================
misc_router = APIRouter(tags=["misc"])


@misc_router.get("/alerts")
async def list_alerts(resolved: Optional[bool] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if resolved is not None:
        q["resolved"] = resolved
    items = await col(ALERTS).find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@misc_router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, user: User = Depends(require_roles("super_admin", "ops"))):
    r = await col(ALERTS).update_one({"alert_id": alert_id}, {"$set": {"resolved": True}})
    if r.matched_count == 0:
        raise HTTPException(404, "Alert not found")
    await _log_audit(user, "alert.resolve", "alert", alert_id)
    return {"ok": True}


@misc_router.get("/reports")
async def list_reports(kind: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if kind:
        q["kind"] = kind
    items = await col(REPORTS).find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@misc_router.get("/audit-logs")
async def list_audit(
    actor_email: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
):
    q: Dict[str, Any] = {}
    if actor_email:
        q["actor_email"] = {"$regex": actor_email, "$options": "i"}
    if action:
        q["action"] = {"$regex": action, "$options": "i"}
    if resource:
        q["resource"] = resource
    if from_date or to_date:
        created: Dict[str, Any] = {}
        if from_date:
            created["$gte"] = from_date
        if to_date:
            created["$lte"] = to_date + "T23:59:59.999Z" if len(to_date) == 10 else to_date
        q["created_at"] = created
    page = max(page, 1)
    page_size = max(1, min(page_size, 500))
    total = await col(AUDIT_LOGS).count_documents(q)
    items = await col(AUDIT_LOGS).find(q, {"_id": 0})\
        .sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "has_more": page * page_size < total}


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


# ============================================================================
# USERS / ADMIN
# ============================================================================
users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("")
async def list_users(user: User = Depends(get_current_user)):
    items = await col(USERS).find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": items, "total": len(items)}


class RoleUpdate(BaseModel):
    platform_role: str
    org_id: Optional[str] = None


@users_router.patch("/{user_id}")
async def update_user(user_id: str, body: RoleUpdate,
                      user: User = Depends(require_roles("super_admin"))):
    await col(USERS).update_one({"user_id": user_id}, {"$set": body.model_dump(exclude_none=True)})
    await _log_audit(user, "user.role_update", "user", user_id, metadata=body.model_dump())
    return {"ok": True}


# ============================================================================
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


# ---- Onboarding create (missing) ----
class OnboardingCreate(BaseModel):
    applicant_name: str
    applicant_email: str
    applicant_type: str = "individual"
    country: Optional[str] = None
    org_id: Optional[str] = None
    notes: Optional[str] = None


@ob_router.post("")
async def create_onboarding(body: OnboardingCreate,
                            user: User = Depends(require_roles("super_admin", "ops", "compliance", "client_admin"))):
    now = now_utc()
    case_id = f"case_{new_id()}"
    doc = {
        "case_id": case_id, "org_id": body.org_id or user.org_id,
        "applicant_name": body.applicant_name,
        "applicant_email": body.applicant_email,
        "applicant_type": body.applicant_type,
        "country": body.country,
        "status": "submitted",
        "progress": 20,
        "sla_due": (now + timedelta(hours=48)).isoformat(),
        "risk_score": None, "notes": body.notes, "is_demo": False,
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
    }
    await col(ONBOARDING).insert_one(dict(doc))
    # Also create an empty compliance review
    await col(COMPLIANCE).insert_one({
        "review_id": f"rev_{new_id()}", "case_id": case_id,
        "kyc_status": "pending", "aml_check": "pending",
        "sanctions_check": "pending", "pep_check": "pending", "travel_rule": "pending",
        "decision": "pending", "is_demo": False, "created_at": now.isoformat(),
    })
    await _log_audit(user, "onboarding.create", "onboarding_case", case_id)
    _strip_id(doc)
    return doc


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


# ---- Org user invite (missing) ----
class OrgUserInvite(BaseModel):
    email: str
    name: str
    role: str = "client_user"
    org_id: str


@users_router.post("/invite")
async def invite_org_user(body: OrgUserInvite,
                          user: User = Depends(require_roles("super_admin", "ops", "client_admin"))):
    if not user.is_internal and body.org_id != user.org_id:
        raise HTTPException(403, "Cannot invite users for another org")
    existing = await col(ORG_USERS).find_one({"email": body.email.lower(), "org_id": body.org_id}, {"_id": 0})
    if existing:
        raise HTTPException(409, "User already invited")
    doc = {
        "org_user_id": f"ou_{new_id()}",
        "org_id": body.org_id, "user_id": None,
        "email": body.email.lower(), "name": body.name,
        "role": body.role, "status": "invited",
        "created_at": now_utc().isoformat(),
    }
    await col(ORG_USERS).insert_one(dict(doc))
    await _log_audit(user, "user.invite", "org_user", doc["org_user_id"],
                     metadata={"email": body.email, "role": body.role})
    _strip_id(doc)
    return doc


@users_router.get("/org-members")
async def list_org_members(org_id: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if org_id:
        q["org_id"] = org_id
    elif not user.is_internal and user.org_id:
        q["org_id"] = user.org_id
    items = await col(ORG_USERS).find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


# ============================================================================
# APPROVAL WORKFLOW (two-signer pattern)
# ============================================================================
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])


@approvals_router.get("")
async def list_approvals(status: Optional[str] = None, user: User = Depends(get_current_user)):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    items = await col(APPROVALS).find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@approvals_router.get("/pending/count")
async def pending_count(user: User = Depends(get_current_user)):
    n = await col(APPROVALS).count_documents({"status": "pending"})
    return {"count": n}


class ApproveBody(BaseModel):
    mfa_code: Optional[str] = None  # optional MFA challenge code


@approvals_router.post("/{approval_id}/approve")
async def approve(approval_id: str, body: ApproveBody,
                  user: User = Depends(require_roles("super_admin", "ops", "finance"))):
    a = await col(APPROVALS).find_one({"approval_id": approval_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Approval not found")
    if a["status"] != "pending":
        raise HTTPException(400, f"Approval is {a['status']}, cannot approve")
    if a["requested_by"] == user.user_id:
        raise HTTPException(400, "Cannot approve your own request (four-eyes principle)")
    already = any(ap["user_id"] == user.user_id for ap in a.get("approvals", []))
    if already:
        raise HTTPException(400, "You already approved this request")

    # Optional: enforce MFA if user has it enabled
    user_doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    if user_doc and user_doc.get("mfa_enabled") and user_doc.get("mfa_secret"):
        if not body.mfa_code or not mfa_mod.verify_code(user_doc["mfa_secret"], body.mfa_code):
            raise HTTPException(401, "Valid MFA code required")

    approvals_list = a.get("approvals", []) + [{
        "user_id": user.user_id, "email": user.email,
        "at": now_utc().isoformat(),
    }]

    if len(approvals_list) >= a["required_approvals"]:
        # Execute
        try:
            result = await approvals_mod.execute_approved_action(
                a["action"], a["payload"], a["requested_by_email"]
            )
            await col(APPROVALS).update_one(
                {"approval_id": approval_id},
                {"$set": {"status": "executed", "approvals": approvals_list,
                          "executed_at": now_utc().isoformat(), "result": result}}
            )
            await _log_audit(user, f"approval.execute", "approval", approval_id,
                             metadata={"action": a["action"]})
            return {"status": "executed", "result": result}
        except Exception as e:
            await col(APPROVALS).update_one(
                {"approval_id": approval_id},
                {"$set": {"status": "failed", "approvals": approvals_list,
                          "result": {"error": str(e)}}}
            )
            raise HTTPException(500, f"Execution failed: {e}")
    else:
        await col(APPROVALS).update_one(
            {"approval_id": approval_id},
            {"$set": {"approvals": approvals_list}}
        )
        await _log_audit(user, "approval.sign", "approval", approval_id)
        return {"status": "pending", "approvals_count": len(approvals_list)}


class RejectBody(BaseModel):
    reason: Optional[str] = None


@approvals_router.post("/{approval_id}/reject")
async def reject(approval_id: str, body: RejectBody,
                 user: User = Depends(require_roles("super_admin", "ops", "finance"))):
    a = await col(APPROVALS).find_one({"approval_id": approval_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Approval not found")
    if a["status"] != "pending":
        raise HTTPException(400, f"Approval is {a['status']}")
    await col(APPROVALS).update_one(
        {"approval_id": approval_id},
        {"$set": {"status": "rejected", "rejected_by_email": user.email,
                  "rejected_reason": body.reason, "executed_at": now_utc().isoformat()}}
    )
    await _log_audit(user, "approval.reject", "approval", approval_id,
                     metadata={"reason": body.reason})
    return {"status": "rejected"}


# ============================================================================
# MFA TOTP
# ============================================================================
mfa_router = APIRouter(prefix="/auth/mfa", tags=["mfa"])


@mfa_router.post("/enable")
async def mfa_enable(user: User = Depends(get_current_user)):
    """Returns secret + QR code. User must verify with /mfa/verify to actually enable."""
    secret = mfa_mod.generate_secret()
    uri = mfa_mod.provisioning_uri(user.email, secret)
    qr = mfa_mod.qr_png_base64(uri)
    # Stash pending secret on user doc (not yet enabled)
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_secret_pending": secret}}
    )
    return {"secret": secret, "provisioning_uri": uri, "qr_code_data_url": qr}


class MfaVerifyBody(BaseModel):
    code: str


@mfa_router.post("/verify")
async def mfa_verify(body: MfaVerifyBody, user: User = Depends(get_current_user)):
    doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    secret = doc.get("mfa_secret_pending") or doc.get("mfa_secret")
    if not secret:
        raise HTTPException(400, "No MFA setup pending. Call /mfa/enable first.")
    if not mfa_mod.verify_code(secret, body.code):
        raise HTTPException(401, "Invalid code")
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_enabled": True, "mfa_secret": secret},
         "$unset": {"mfa_secret_pending": ""}}
    )
    await _log_audit(user, "mfa.enabled", "user", user.user_id)
    return {"ok": True, "mfa_enabled": True}


@mfa_router.post("/disable")
async def mfa_disable(body: MfaVerifyBody, user: User = Depends(get_current_user)):
    doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc.get("mfa_enabled"):
        return {"ok": True}
    if not mfa_mod.verify_code(doc.get("mfa_secret", ""), body.code):
        raise HTTPException(401, "Invalid code")
    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {"mfa_enabled": False},
         "$unset": {"mfa_secret": "", "mfa_secret_pending": ""}}
    )
    await _log_audit(user, "mfa.disabled", "user", user.user_id)
    return {"ok": True, "mfa_enabled": False}


# Aggregate all routers
ALL_ROUTERS = [
    auth_router, dashboard_router, orgs_router, ob_router, comp_router,
    funds_router, products_router, pos_router, treas_router, tx_router,
    recon_router, int_router, misc_router, ec_router, users_router, admin_router,
    approvals_router, mfa_router,
]


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


ALL_ROUTERS.append(search_router)
