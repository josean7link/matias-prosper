"""Prosper Phase 1 API — passwordless OTP auth + multi-tenant model + audit log."""
from __future__ import annotations
import os, secrets, logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, APIRouter, HTTPException, Response, Request, Depends, Header
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import httpx
from dotenv import load_dotenv
import redis.asyncio as aioredis

load_dotenv(Path(__file__).parent / ".env")

from db import (
    db, col, ensure_indexes,
    ORGANIZATIONS, USERS, OTP_CODES, AUDIT_LOGS,
)
from models import utc_now, Organization
from roles import Role, is_internal
from auth import (
    CurrentUser, get_current_user, make_jwt, mint_session_token,
    requires_role, org_scoped, assert_can_read,
)
from audit import log_action, audited
from seed import seed_phase1
from seed_demo import seed_demo_transactions
from nav_snapshots import backfill_nav_snapshots
from fees import backfill_fee_breakdown
from seed_compliance import seed_compliance
from routes.dashboard import router as dashboard_router
from routes.onboarding import router as onboarding_router
from routes.compliance import router as compliance_router
from routes.operations import router as operations_router
from routes.business import router as business_router
from routes.admin_settings import router as admin_settings_router
from routes.admin_clients import router as admin_clients_router
from routes.admin_clients.links import public as public_links_router
from routes.client_portal import router as client_portal_router, public as apply_public_router
from routes.client_alfred import (
    router as client_alfred_router,
    webhook_router as alfred_webhook_router,
    mock_router as alfred_mock_router,
)
from routes.alfred_kyc import (
    router as alfred_kyc_router,
    mock_router as alfred_kyc_mock_router,
)
from routes.client_invest import router as client_invest_router
from routes.client_developer import router as client_developer_router
from routes.client_profile import router as client_profile_router
from routes.admin_ops import router as admin_ops_router, status_router as ops_status_router
from routes.webhooks_aiprise import router as aiprise_webhooks_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prosper")

# ---------------------------------------------------------------------------
# App config
# ---------------------------------------------------------------------------
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
OTP_TTL = 600
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM = os.environ.get("RESEND_FROM", "onboarding@resend.dev")

app = FastAPI(title="Prosper Platform API", version="0.2.0")

# ---------------------------------------------------------------------------
# Rate limiting — lightweight per-IP token-bucket. In-process (single worker).
# Disable in tests via PROSPER_DISABLE_RATELIMIT=1.
# ---------------------------------------------------------------------------
_rate_buckets: dict[tuple[str, str], list[float]] = {}


def rate_limit(request: Request, *, scope: str, per_min: int) -> None:
    """Raise HTTPException 429 if `scope` from this IP exceeds `per_min`.

    Evaluated per call so tests can flip `PROSPER_DISABLE_RATELIMIT` at
    runtime without restarting the backend.
    """
    if os.environ.get("PROSPER_DISABLE_RATELIMIT") == "1":
        return
    now = datetime.now(timezone.utc).timestamp()
    ip = request.client.host if request.client else "anon"
    key = (scope, ip)
    window = _rate_buckets.setdefault(key, [])
    # Drop entries older than 60s
    cutoff = now - 60
    while window and window[0] < cutoff:
        window.pop(0)
    if len(window) >= per_min:
        raise HTTPException(429, f"Demasiadas requests — máx {per_min}/min en {scope}")
    window.append(now)


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Security headers — HSTS / Referrer-Policy / X-Content-Type-Options
# ---------------------------------------------------------------------------
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Strict-Transport-Security",
                                 "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=()")
    return response


# ---------------------------------------------------------------------------
# Sentry hook (mocked-friendly — only inits if SENTRY_DSN configured)
# ---------------------------------------------------------------------------
_SENTRY_DSN = os.environ.get("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(dsn=_SENTRY_DSN,
                         traces_sample_rate=0.1,
                         environment=os.environ.get("PROSPER_ENV", "preview"),
                         integrations=[FastApiIntegration()])
    except Exception:  # pragma: no cover
        pass
redis_client: aioredis.Redis | None = None


@app.on_event("startup")
async def startup():
    global redis_client
    try:
        redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connected.")
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}); using Mongo for OTP storage.")
        redis_client = None
    await ensure_indexes()
    seeded = await seed_phase1()
    logger.info(f"Seed: orgs={seeded['orgs']} users={seeded['users']}")
    demo = await seed_demo_transactions(days=180)
    logger.info(f"Demo tx seed: {demo}")
    snaps = await backfill_nav_snapshots(days=180)
    logger.info(f"NAV snapshot backfill: {snaps}")
    fees_back = await backfill_fee_breakdown()
    logger.info(f"Fee breakdown backfill: {fees_back}")
    compl = await seed_compliance()
    logger.info(f"Compliance seed: {compl}")
    from routes.client_invest import ensure_products
    await ensure_products()
    from jobs.accrual import start_scheduler
    start_scheduler()


@app.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()


# ---------------------------------------------------------------------------
# OTP storage (Redis-first, Mongo fallback)
# ---------------------------------------------------------------------------
async def _otp_put(token: str, code: str, email: str):
    payload = f"{code}|{email}"
    if redis_client:
        await redis_client.setex(f"otp:{token}", OTP_TTL, payload)
    else:
        await col(OTP_CODES).update_one(
            {"token": token},
            {"$set": {"token": token, "code": code, "email": email,
                      "expires_at": (datetime.now(timezone.utc) +
                                     timedelta(seconds=OTP_TTL)).isoformat()}},
            upsert=True,
        )


async def _otp_pop(token: str):
    if redis_client:
        raw = await redis_client.get(f"otp:{token}")
        if raw:
            await redis_client.delete(f"otp:{token}")
            code, email = raw.split("|", 1)
            return code, email
        return None
    doc = await col(OTP_CODES).find_one_and_delete({"token": token})
    if not doc:
        return None
    if doc["expires_at"] < datetime.now(timezone.utc).isoformat():
        return None
    return doc["code"], doc["email"]


async def _send_otp(email: str, code: str):
    if not RESEND_API_KEY:
        logger.warning(f"[DEV OTP] {email} -> {code}  (set RESEND_API_KEY to email it)")
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post("https://api.resend.com/emails",
                             headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                                      "Content-Type": "application/json"},
                             json={"from": RESEND_FROM, "to": [email],
                                   "subject": "Your Prosper sign-in code",
                                   "html": f"<p>Your code: <b style='font-size:24px;font-family:monospace'>{code}</b></p>"})
            r.raise_for_status()
    except Exception as e:
        logger.error(f"Resend failed: {e}; code for {email} was {code}")


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
api = APIRouter(prefix="/api")
v1  = APIRouter(prefix="/v1")


class LoginIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    code: str       # continuation
    token: str      # the OTP user typed


@v1.post("/auth/passwordless-login")
async def passwordless_login(request: Request, body: LoginIn):
    rate_limit(request, scope="passwordless-login", per_min=10)
    otp = f"{secrets.randbelow(10000):04d}"
    cont = secrets.token_urlsafe(24)
    await _otp_put(cont, otp, body.email.lower())
    await _send_otp(body.email, otp)
    payload = {"code": cont}
    # Dev/preview convenience: when there's no real email transport configured
    # we surface the OTP in the response so the user can sign in without
    # tailing the backend log. Disabled automatically as soon as RESEND is set.
    if not RESEND_API_KEY:
        payload["dev_otp"] = otp
    return payload


def _domain_allowed(email: str, allowlist: list[str]) -> bool:
    """Phase 1 — internal emails (@prosper.foundation) always allowed."""
    domain = email.lower().rsplit("@", 1)[-1]
    if domain == "prosper.foundation":
        return True
    return domain in (allowlist or [])


@v1.post("/auth/passwordless-token")
async def passwordless_token(request: Request, body: TokenIn, response: Response):
    rate_limit(request, scope="passwordless-token", per_min=30)
    stored = await _otp_pop(body.code)
    if not stored:
        raise HTTPException(401, "Code expired or already used")
    expected, email = stored
    if body.token.strip() != expected:
        await _otp_put(body.code, expected, email)
        raise HTTPException(401, "Invalid OTP")

    # Resolve user (or auto-create against allowlist)
    user_doc = await col(USERS).find_one({"email": email}, {"_id": 0})
    if not user_doc:
        # Auto-attach to the first org whose allowlist matches the email's domain
        domain = email.rsplit("@", 1)[-1]
        org_doc = await col(ORGANIZATIONS).find_one({"allowlist_domains": domain}, {"_id": 0})
        if not org_doc and domain != "prosper.foundation":
            raise HTTPException(403, "Email domain not on any organization allowlist")
        # @prosper.foundation auto-onboarding defaults to plain admin — only
        # explicitly seeded users (see seed.seed_phase1) hold super_admin. Any
        # other Prosper team member must be elevated by an existing super_admin
        # via /admin/users.
        role = Role.admin if domain == "prosper.foundation" else Role.client_user
        user_doc = {
            "user_id": f"usr_{secrets.token_hex(6)}",
            "email": email, "role": role.value,
            "org_id": org_doc["org_id"] if org_doc else None,
            "status": "active",
            "kyc_status": "pending", "mfa_enabled": False,
            "is_deleted": False,
            "created_at": utc_now(), "updated_at": utc_now(),
        }
        await col(USERS).insert_one(dict(user_doc))

    await col(USERS).update_one({"email": email},
                                {"$set": {"last_login_at": utc_now(), "updated_at": utc_now()}})

    role = Role(user_doc["role"])
    access = await mint_session_token(
        user_id=user_doc["user_id"], email=email, role=role,
        org_id=user_doc.get("org_id"), request=request)
    response.set_cookie("prosper_session", access, httponly=True, secure=COOKIE_SECURE,
                        samesite="lax", path="/", max_age=7*24*3600)
    return {"accessToken": access}


@v1.post("/auth/logout")
async def logout(response: Response, request: Request):
    # Revoke the current session (if any) before deleting the cookie so other
    # tabs / API calls reusing the JWT fail with 401 instantly.
    from auth import parse_jwt
    from db import SESSIONS
    token = request.cookies.get("prosper_session")
    if token:
        try:
            payload = parse_jwt(token)
            jti = payload.get("jti")
            if jti:
                await col(SESSIONS).update_one(
                    {"session_id": jti},
                    {"$set": {"revoked": True,
                                "revoked_at": utc_now(),
                                "revoke_reason": "logout"}})
        except Exception:
            pass
    response.delete_cookie("prosper_session", path="/")
    return {"ok": True}


# ---------------------------------------------------------------------------
# DEV magic-link: GET /api/v1/auth/dev-login?email=...&next=/admin
# Only active when RESEND_API_KEY is empty (preview / sandbox environments).
# Sets the prosper_session cookie and 302s to `next`. Bypasses all SPA cache.
# ---------------------------------------------------------------------------
@v1.get("/auth/dev-login")
async def dev_login(email: str, request: Request, next: str = "/admin"):
    if RESEND_API_KEY:
        raise HTTPException(404, "Not found")  # disable in production silently
    email = email.lower().strip()

    user_doc = await col(USERS).find_one({"email": email}, {"_id": 0})
    if not user_doc:
        domain = email.rsplit("@", 1)[-1]
        org_doc = await col(ORGANIZATIONS).find_one({"allowlist_domains": domain}, {"_id": 0})
        if not org_doc and domain != "prosper.foundation":
            raise HTTPException(403, "Email domain not on any organization allowlist")
        # @prosper.foundation auto-onboarding defaults to plain admin (same as
        # the OTP path above) — explicit super_admin seeding only.
        role = Role.admin if domain == "prosper.foundation" else Role.client_user
        user_doc = {
            "user_id": f"usr_{secrets.token_hex(6)}",
            "email": email, "role": role.value,
            "org_id": org_doc["org_id"] if org_doc else None,
            "status": "active", "kyc_status": "pending", "mfa_enabled": False,
            "is_deleted": False,
            "created_at": utc_now(), "updated_at": utc_now(),
        }
        await col(USERS).insert_one(dict(user_doc))

    await col(USERS).update_one(
        {"email": email},
        {"$set": {"last_login_at": utc_now(), "updated_at": utc_now()}})

    role = Role(user_doc["role"])
    access = await mint_session_token(
        user_id=user_doc["user_id"], email=email, role=role,
        org_id=user_doc.get("org_id"), request=request, label="Dev magic link")
    # Sanitize the `next` param so this can't be used as an open redirect
    safe_next = next if next.startswith("/") else "/admin"
    resp = RedirectResponse(url=safe_next, status_code=303)
    resp.set_cookie("prosper_session", access, httponly=True, secure=COOKIE_SECURE,
                    samesite="lax", path="/", max_age=7*24*3600)
    return resp


# ---------------------------------------------------------------------------
# /api/v1/me — user + org + role + perms + feature flags
# ---------------------------------------------------------------------------
def _calc_permissions(role: Role) -> list[str]:
    perms = {
        Role.super_admin:        ["*"],
        Role.admin:              ["org:read", "org:write", "user:read", "user:write",
                                  "compliance:read", "transactions:read", "approvals:approve"],
        Role.compliance_officer: ["org:read", "user:read", "kyc:read", "kyc:decide",
                                  "kyb:read", "kyb:decide", "audit:read"],
        Role.finance:            ["transactions:read", "treasury:read", "approvals:approve"],
        Role.client_admin:       ["org:read:self", "user:read:self", "user:write:self",
                                  "api_keys:manage", "webhooks:manage"],
        Role.client_user:        ["org:read:self", "user:read:self"],
    }
    return perms.get(role, [])


def _feature_flags(user_doc: dict, org_doc: Optional[dict]) -> dict:
    return {
        "mfa_required":  False if user_doc.get("role") == Role.super_admin.value else True,
        "mfa_enabled":   bool(user_doc.get("mfa_enabled")),
        "kyb_locked":    bool(org_doc and org_doc.get("kyb_status") not in ("approved",)),
        "kyc_pending":   user_doc.get("kyc_status") != "approved",
        "is_internal":   is_internal(Role(user_doc["role"])),
    }


@v1.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    user_doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    if not user_doc:
        raise HTTPException(404, "User not found")
    org_doc = None
    if user.scope_org_id or user_doc.get("org_id"):
        org_doc = await col(ORGANIZATIONS).find_one(
            {"org_id": user.scope_org_id or user_doc["org_id"]}, {"_id": 0})
    return {
        "user": user_doc,
        "org":  org_doc,
        "role": user.role.value,
        "is_internal": user.is_internal,
        "acting_as_org": user.acting_as_org,
        "permissions": _calc_permissions(user.role),
        "features":    _feature_flags(user_doc, org_doc),
    }


# Alias kept for Phase 0 callers (frontend, integration tests) — same payload.
@v1.get("/auth/me")
async def auth_me(user: CurrentUser = Depends(get_current_user)):
    return await me(user)


# ---------------------------------------------------------------------------
# Organizations endpoints (Phase 1 — list + get, with scope + cross-org guard)
# ---------------------------------------------------------------------------
@v1.get("/organizations")
async def list_orgs(scope = Depends(org_scoped())):
    user, scope_filter = scope
    q = {**scope_filter, "is_deleted": False}
    items = await col(ORGANIZATIONS).find(q, {"_id": 0}).to_list(500)
    return {"items": items, "total": len(items)}


@v1.get("/organizations/{org_id}")
async def get_org(org_id: str, user: CurrentUser = Depends(get_current_user)):
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id, "is_deleted": False}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Not found")
    await assert_can_read(user, org["org_id"])
    return org


class OrgCreate(BaseModel):
    legal_name: str
    commercial_name: str
    country: str
    type: str = "fintech"
    allowlist_domains: list[str] = []


@v1.post("/organizations")
async def create_org(
    body: OrgCreate,
    user: CurrentUser = Depends(requires_role(Role.super_admin, Role.admin)),
):
    org = Organization(legal_name=body.legal_name, commercial_name=body.commercial_name,
                       country=body.country, type=body.type,
                       allowlist_domains=body.allowlist_domains)
    doc = org.model_dump()
    await col(ORGANIZATIONS).insert_one(dict(doc))
    doc.pop("_id", None)
    await log_action(actor=user, action="organization.created",
                     resource_type="organization", resource_id=doc["org_id"],
                     metadata={"legal_name": body.legal_name},
                     org_id_override=doc["org_id"])
    return doc


# ---------------------------------------------------------------------------
# Admin-only sample endpoint (used by tests to validate role guard)
# ---------------------------------------------------------------------------
@v1.get("/admin/dashboard")
async def admin_dashboard(user: CurrentUser = Depends(
    requires_role(Role.super_admin, Role.admin, Role.compliance_officer, Role.finance)
)):
    return {"ok": True, "for": user.email, "role": user.role.value}


# ---------------------------------------------------------------------------
# Audit log — read-only endpoint + explicit "block mutation" routes used by tests
# ---------------------------------------------------------------------------
@v1.get("/audit-logs")
async def list_audit(scope = Depends(org_scoped()),
                     limit: int = 50):
    user, scope_filter = scope
    if not user.is_internal:
        # Clients only see their own org's audit trail
        scope_filter = {"org_id": user.org_id}
    items = await col(AUDIT_LOGS).find(scope_filter, {"_id": 0})\
              .sort("timestamp", -1).to_list(min(limit, 200))
    return {"items": items, "total": len(items)}


@v1.patch("/audit-logs/{audit_id}")
async def audit_patch_blocked(audit_id: str,
                              user: CurrentUser = Depends(requires_role(Role.super_admin))):
    raise HTTPException(405, "audit_logs is immutable")


@v1.delete("/audit-logs/{audit_id}")
async def audit_delete_blocked(audit_id: str,
                               user: CurrentUser = Depends(requires_role(Role.super_admin))):
    raise HTTPException(405, "audit_logs is immutable")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@api.get("/health")
async def health():
    return {"ok": True, "service": "prosper-api", "version": app.version}


api.include_router(v1)
api.include_router(dashboard_router, prefix="/v1")
api.include_router(onboarding_router, prefix="/v1")
api.include_router(compliance_router, prefix="/v1")
api.include_router(operations_router, prefix="/v1")
api.include_router(business_router, prefix="/v1")
api.include_router(admin_settings_router, prefix="/v1")
api.include_router(admin_clients_router, prefix="/v1")
api.include_router(public_links_router, prefix="/v1")
api.include_router(client_portal_router, prefix="/v1")
api.include_router(apply_public_router, prefix="/v1")
api.include_router(client_alfred_router, prefix="/v1")
api.include_router(alfred_webhook_router, prefix="/v1")
api.include_router(alfred_mock_router, prefix="/v1")
api.include_router(alfred_kyc_router, prefix="/v1")
api.include_router(alfred_kyc_mock_router, prefix="/v1")
api.include_router(client_invest_router, prefix="/v1")
api.include_router(client_developer_router, prefix="/v1")
api.include_router(client_profile_router, prefix="/v1")
api.include_router(admin_ops_router, prefix="/v1")
api.include_router(ops_status_router, prefix="/v1")
api.include_router(aiprise_webhooks_router, prefix="/v1")
app.include_router(api)
