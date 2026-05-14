"""Phase 1 — Mongo collections, indexes and the immutable audit-log helper."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

INTEGRATION_SETTINGS = "integration_settings"
SIGNED_LINKS         = "signed_links"
WEBHOOK_DELIVERIES   = "webhook_deliveries"
OUTBOUND_EMAILS      = "outbound_emails"
# Collection names
ORGANIZATIONS    = "organizations"
USERS            = "users"
SESSIONS         = "sessions"
OTP_CODES        = "otp_codes"
KYC_CASES        = "kyc_cases"
KYB_CASES        = "kyb_cases"
POSITIONS        = "positions"
TRANSACTIONS     = "transactions"
ONRAMP_ORDERS    = "onramp_orders"
OFFRAMP_ORDERS   = "offramp_orders"
API_KEYS         = "api_keys"
WEBHOOKS         = "webhook_endpoints"
ALERTS           = "alerts"
AUDIT_LOGS       = "audit_logs"
APPROVALS        = "approvals"
NAV_SNAPSHOTS    = "nav_snapshots"
ONBOARDING_APPLICATIONS = "onboarding_applications"
WEBHOOK_EVENTS   = "webhook_events"
# Phase 5 — Compliance
KYT_RULES        = "kyt_rules"
KYT_ALERTS       = "kyt_alerts"
RISK_SCORES      = "risk_scores"
WATCHLIST        = "watchlist_entries"
LIMITS_HISTORY   = "limits_history"
# Phase 11
FEATURE_INTEREST = "feature_interest"

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return _client


def db() -> AsyncIOMotorDatabase:
    return get_client()[os.environ["DB_NAME"]]


def col(name: str):
    return db()[name]


# ---------------------------------------------------------------------------
# Index setup — called once at startup
# ---------------------------------------------------------------------------
async def ensure_indexes():
    # Mandatory cross-collection indexes
    for name in (ORGANIZATIONS, USERS, KYC_CASES, KYB_CASES, POSITIONS, TRANSACTIONS,
                 ONRAMP_ORDERS, OFFRAMP_ORDERS, API_KEYS, WEBHOOKS, ALERTS, APPROVALS):
        c = col(name)
        if name != ORGANIZATIONS:
            await c.create_index("org_id")
        await c.create_index("created_at")
        await c.create_index("status")
        await c.create_index("is_deleted")

    # Unique business-key indexes
    await col(USERS).create_index("email", unique=True)
    await col(USERS).create_index("user_id", unique=True)
    await col(ORGANIZATIONS).create_index("org_id", unique=True)
    await col(TRANSACTIONS).create_index("prosper_tx_id", unique=True)
    await col(POSITIONS).create_index("prosper_tx_id")

    # Audit log indices (created_at via `timestamp` field for fast tail queries)
    await col(AUDIT_LOGS).create_index("timestamp")
    await col(AUDIT_LOGS).create_index("org_id")
    await col(AUDIT_LOGS).create_index("actor_user_id")
    await col(AUDIT_LOGS).create_index("resource_id")


# ---------------------------------------------------------------------------
# Immutable audit log helper
# ---------------------------------------------------------------------------
class AuditMutationError(Exception):
    pass


async def write_audit(doc: dict) -> dict:
    """The ONLY supported path to append to audit_logs. Insert-only."""
    await col(AUDIT_LOGS).insert_one(doc)
    return doc


async def audit_update_blocked(*_args, **_kw):
    raise AuditMutationError("audit_logs is immutable — updates are not allowed")


async def audit_delete_blocked(*_args, **_kw):
    raise AuditMutationError("audit_logs is immutable — deletes are not allowed")
