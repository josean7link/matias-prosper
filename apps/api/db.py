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
# Phase 13 — Ramp provider abstraction
RAMP_PROVIDER_CONFIG = "ramp_provider_config"
RAMP_ACCOUNTS        = "ramp_accounts"
RAMP_WALLETS         = "ramp_wallets"
RAMP_FIAT_ACCOUNTS   = "ramp_fiat_accounts"
RAMP_BALANCES        = "ramp_balances"
RAMP_MOVEMENTS       = "ramp_movements"
RAMP_WEBHOOK_EVENTS  = "ramp_webhook_events"
# Phase 15.2 — International offramp
RAMP_INTL_ACCOUNTS   = "ramp_intl_accounts"
# Phase 20 v2 — ARSa <-> USDC <-> Prosper bridge
INVESTMENT_INTENTS   = "investment_intents"
# Sanctions / PEP screening (manual provider by default — see
# integrations/sanctions/__init__.py)
SANCTIONS_SCREENINGS = "sanctions_screenings"
# Travel Rule (FATF/UIF) screening — same pattern as sanctions, separate
# collection. See integrations/travel_rule/__init__.py
TRAVEL_RULE_SCREENINGS = "travel_rule_screenings"
# P0 CMS migration (Feb 2026) — staking sync run history (capped/singleton).
STAKING_SYNC_RUNS    = "staking_sync_runs"
# Phase 02 — Deposit Detection Engine (Camino A: Horizon-first detector).
# Collections are introduced in PR1 (cimientos) and consumed by PR2/PR3.
# No indexes are created here yet — they are added with their consumers so
# the migration order stays inspectable. See:
#   * deposit_watcher_cursors → singleton row per cursor key (single global
#                                cursor for the Horizon /payments stream).
#   * deposit_events          → append-only observability log emitted by
#                                the watcher and the ARSa safety poller.
DEPOSIT_WATCHER_CURSORS = "deposit_watcher_cursors"
DEPOSIT_EVENTS          = "deposit_events"

# Phase 03 — In-app notifications (deposit_credited etc).
# One row per (recipient_user, idempotency_key). The same deposit on a
# business-org with N client_admins produces N rows — see notification
# handler for resolver logic.
NOTIFICATIONS = "notifications"

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

    # Phase 12 — hot-path query indexes
    await col(TRANSACTIONS).create_index("tx_hash", sparse=True)
    await col(TRANSACTIONS).create_index([("org_id", 1), ("type", 1),
                                            ("status", 1)])
    await col(ALERTS).create_index("assigned_to", sparse=True)
    await col(ALERTS).create_index([("org_id", 1), ("severity", 1),
                                      ("status", 1)])
    await col(SESSIONS).create_index("session_id", unique=True)
    await col(SESSIONS).create_index("user_id")
    await col(SESSIONS).create_index([("expires_at", 1)])
    # Soft-delete tail queries
    await col(ORGANIZATIONS).create_index([("kyb_status", 1), ("is_deleted", 1)])
    await col(KYB_CASES).create_index([("status", 1), ("is_deleted", 1)])
    await col(POSITIONS).create_index([("org_id", 1), ("status", 1)])
    # NAV unique-per-day
    try:
        await col(NAV_SNAPSHOTS).create_index("date", unique=True)
    except Exception:
        pass  # Already exists or duplicate dates pre-fix — log and continue
    # Audit log indices (created_at via `timestamp` field for fast tail queries)
    await col(AUDIT_LOGS).create_index("timestamp")
    await col(AUDIT_LOGS).create_index("org_id")
    await col(AUDIT_LOGS).create_index("actor_user_id")
    await col(AUDIT_LOGS).create_index("resource_id")

    # Phase 13 — Ramp provider abstraction
    await col(RAMP_PROVIDER_CONFIG).create_index("scope", unique=True, sparse=True)
    await col(RAMP_ACCOUNTS).create_index([("org_id", 1), ("end_customer_id", 1)],
                                            unique=True, sparse=True)
    await col(RAMP_ACCOUNTS).create_index("provider")
    await col(RAMP_ACCOUNTS).create_index("provider_user_id", sparse=True)
    await col(RAMP_WALLETS).create_index([("org_id", 1), ("provider_user_id", 1),
                                            ("asset", 1), ("chain", 1)],
                                            unique=True, sparse=True)
    await col(RAMP_FIAT_ACCOUNTS).create_index([("org_id", 1), ("fiat_account_id", 1)],
                                                  unique=True, sparse=True)
    await col(RAMP_FIAT_ACCOUNTS).create_index("ramp_account_id")
    await col(RAMP_BALANCES).create_index([("ramp_account_id", 1),
                                              ("asset", 1), ("chain", 1)],
                                              unique=True, sparse=True)
    await col(RAMP_MOVEMENTS).create_index("org_id")
    await col(RAMP_MOVEMENTS).create_index("prosper_tx_id", sparse=True)
    await col(RAMP_MOVEMENTS).create_index("external_id", sparse=True)
    await col(RAMP_WEBHOOK_EVENTS).create_index("delivery_id", unique=True, sparse=True)
    await col(RAMP_WEBHOOK_EVENTS).create_index("provider")

    # Phase 23 — N1/N2 hierarchy
    await col(ORGANIZATIONS).create_index("parent_org_id", sparse=True)
    # Backfill any pre-Phase23 org rows (idempotent)
    await col(ORGANIZATIONS).update_many(
        {"parent_org_id": {"$exists": False}},
        {"$set": {"parent_org_id": None, "level": 1}})

    # Phase 15.2 — International offramp
    await col(RAMP_INTL_ACCOUNTS).create_index([("org_id", 1),
                                                   ("end_customer_id", 1)])
    await col(RAMP_INTL_ACCOUNTS).create_index([("provider_user_id", 1),
                                                   ("country", 1)])
    # Stuck-movement queries (Phase 15.2 / C)
    await col(RAMP_MOVEMENTS).create_index([("status", 1), ("created_at", 1)])
    await col(RAMP_MOVEMENTS).create_index("provider_user_id")

    # Phase 20 v2 — investment intents (ARSa <-> USDC <-> Prosper bridge)
    await col(INVESTMENT_INTENTS).create_index("prosper_tx_id", unique=True,
                                                 sparse=True)
    await col(INVESTMENT_INTENTS).create_index([("org_id", 1), ("step", 1)])
    await col(INVESTMENT_INTENTS).create_index("end_customer_id", sparse=True)
    await col(INVESTMENT_INTENTS).create_index("andes_transfer_id", sparse=True)

    # Sanctions / PEP — one screening row per (org, subject). Status drives
    # the activation gate (`organizations.sanctions_status`).
    await col(SANCTIONS_SCREENINGS).create_index("org_id")
    await col(SANCTIONS_SCREENINGS).create_index("status")
    await col(SANCTIONS_SCREENINGS).create_index(
        [("org_id", 1), ("subject_type", 1)], unique=True, sparse=True)

    # Travel Rule — same shape as sanctions, separate collection.
    await col(TRAVEL_RULE_SCREENINGS).create_index("org_id")
    await col(TRAVEL_RULE_SCREENINGS).create_index("status")
    await col(TRAVEL_RULE_SCREENINGS).create_index(
        [("org_id", 1), ("subject_type", 1)], unique=True, sparse=True)

    # Phase 03 — Notifications. Idempotency MUST be per-recipient: a
    # business-org deposit with 2 client_admin yields 2 notifications,
    # one per user. A unique index on idempotency_key alone would
    # collapse them to 1.
    await col(NOTIFICATIONS).create_index(
        [("idempotency_key", 1), ("user_id", 1)],
        unique=True, sparse=True,
        name="idempotency_per_user")
    await col(NOTIFICATIONS).create_index(
        [("user_id", 1), ("read", 1), ("created_at", -1)],
        name="user_unread_recent")
    await col(NOTIFICATIONS).create_index(
        [("org_id", 1), ("created_at", -1)])

    # Phase 03 — deposit_events: persistent audit trail for the event
    # bus. Event publishing is idempotent by `event_id`.
    await col(DEPOSIT_EVENTS).create_index("event_id", unique=True)
    await col(DEPOSIT_EVENTS).create_index([("created_at", -1)])
    await col(DEPOSIT_EVENTS).create_index([("deposit_id", 1), ("asset", 1)])


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
