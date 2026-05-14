"""Phase 12 — Admin operations: wipe demo data + seed a new demo client.

These endpoints are super_admin only — they materially affect data and are
intended for sales-demo workflows + pre-launch cleanup.
"""
from __future__ import annotations
import secrets as _s
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, requires_role
from db import (
    col,
    ALERTS, KYB_CASES, KYC_CASES, ORGANIZATIONS, POSITIONS, TRANSACTIONS,
    ONRAMP_ORDERS, OFFRAMP_ORDERS, USERS, API_KEYS, WEBHOOKS,
    SESSIONS, OUTBOUND_EMAILS, FEATURE_INTEREST, AUDIT_LOGS,
)
from roles import Role

router = APIRouter(prefix="/admin/ops", tags=["admin-ops"])

_super = requires_role(Role.super_admin)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# WIPE DEMO — deletes everything tagged `is_demo=true`
# ---------------------------------------------------------------------------
class WipeDemoIn(BaseModel):
    confirm: str  # must equal exactly "WIPE-DEMO"


# Collections we touch when wiping. Audit log is preserved (immutable).
_WIPE_TARGETS: list[tuple[str, dict]] = [
    (TRANSACTIONS,     {"is_demo": True}),
    (POSITIONS,        {"is_demo": True}),
    (ONRAMP_ORDERS,    {"is_demo": True}),
    (OFFRAMP_ORDERS,   {"is_demo": True}),
    (ALERTS,           {"is_demo": True}),
    (KYB_CASES,        {"is_demo": True}),
    (KYC_CASES,        {"is_demo": True}),
    (USERS,            {"is_demo": True}),
    (ORGANIZATIONS,    {"is_demo": True}),
    (API_KEYS,         {"is_demo": True}),
    (WEBHOOKS,         {"is_demo": True}),
    (OUTBOUND_EMAILS,  {"is_demo": True}),
    (FEATURE_INTEREST, {"is_demo": True}),
]


@router.post("/wipe-demo")
async def wipe_demo(body: WipeDemoIn, user: CurrentUser = Depends(_super)):
    if body.confirm != "WIPE-DEMO":
        raise HTTPException(400, "Confirmación inválida (escribí 'WIPE-DEMO')")
    summary: dict[str, int] = {}
    for col_name, filt in _WIPE_TARGETS:
        res = await col(col_name).delete_many(filt)
        summary[col_name] = res.deleted_count

    await log_action(actor=user, action="admin.ops.wipe_demo",
                      resource_type="system", resource_id="wipe-demo",
                      metadata={"deleted": summary})
    return {"ok": True, "deleted": summary,
             "total_deleted": sum(summary.values())}


# ---------------------------------------------------------------------------
# SEED DEMO CLIENT — creates an org + client_admin user + 1 KYB case + 30d
# of fake on-ramp + invest history. Useful for sales demos.
# ---------------------------------------------------------------------------
class SeedDemoClientIn(BaseModel):
    legal_name:      Optional[str] = None  # defaults to a generated name
    country:         Optional[str] = "AR"
    primary_email:   Optional[str] = None
    auto_approve:    bool = True
    seed_history:    bool = True


@router.post("/seed-demo-client")
async def seed_demo_client(body: SeedDemoClientIn,
                            user: CurrentUser = Depends(_super)):
    import random
    now = datetime.now(timezone.utc)
    suffix = _s.token_hex(3)
    legal = body.legal_name or f"Demo Holdings {suffix.upper()}"
    commercial = legal.replace(" Holdings", "")
    domain = f"demo-{suffix}.local"
    email = body.primary_email or f"client.admin@{domain}"
    org_id = f"org_demo_{suffix}"
    user_id = f"usr_demo_{suffix}"

    kyb_status = "approved" if body.auto_approve else "in_review"
    org_doc = {
        "org_id":          org_id,
        "legal_name":      legal,
        "commercial_name": commercial,
        "country":         body.country or "AR",
        "type":            "fintech",
        "kyb_status":      kyb_status,
        "risk_score":      35, "risk_profile": "low",
        "allowlist_domains": [domain],
        "primary_email":   email,
        "primary_name":    "Demo Admin",
        "tier":            "T2",
        "env":             "sandbox",
        "caps": {"subscribe_daily_cap_usd":    50_000,
                  "subscribe_monthly_cap_usd": 500_000,
                  "redeem_daily_cap_usd":      50_000,
                  "redeem_monthly_cap_usd":    500_000},
        "is_demo":         True,
        "is_deleted":      False,
        "created_at":      now.isoformat(),
        "updated_at":      now.isoformat(),
    }
    await col(ORGANIZATIONS).insert_one(dict(org_doc))

    user_doc = {
        "user_id":       user_id,
        "email":         email,
        "role":          Role.client_admin.value,
        "org_id":        org_id,
        "first_name":    "Demo", "last_name": "Admin",
        "status":        "active",
        "kyc_status":    "approved" if body.auto_approve else "pending",
        "mfa_enabled":   False,
        "is_demo":       True,
        "is_deleted":    False,
        "created_at":    now.isoformat(),
        "updated_at":    now.isoformat(),
    }
    await col(USERS).insert_one(dict(user_doc))

    summary = {"org_id": org_id, "user_id": user_id, "email": email,
                "tx_count": 0, "position_count": 0}

    if body.seed_history and body.auto_approve:
        # 1 onramp confirmed + 1 active position with 30d of accrual.
        amount = round(random.uniform(50_000, 250_000), 2)
        on_tx_id = f"tx_demo_on_{suffix}"
        pos_id   = f"pos_demo_{suffix}"
        ptx_id   = f"prosper_demo_{suffix}"
        start    = (now - timedelta(days=30)).isoformat()
        await col(TRANSACTIONS).insert_one({
            "tx_id":          on_tx_id,
            "prosper_tx_id":  f"prosper_demo_on_{suffix}",
            "org_id":         org_id,
            "type":           "onramp",
            "amount":         amount,
            "status":         "confirmed",
            "currency":       "USD",
            "is_demo":        True,
            "is_deleted":     False,
            "created_at":     start,
            "updated_at":     start,
        })
        await col(TRANSACTIONS).insert_one({
            "tx_id":          f"tx_demo_sub_{suffix}",
            "prosper_tx_id":  ptx_id,
            "org_id":         org_id,
            "type":           "subscribe",
            "amount":         amount,
            "status":         "confirmed",
            "currency":       "USD",
            "tx_hash":        f"DEMO_TX_HASH_{suffix.upper()}",
            "is_demo":        True,
            "is_deleted":     False,
            "created_at":     start,
            "updated_at":     start,
        })
        await col(POSITIONS).insert_one({
            "position_id":      pos_id,
            "prosper_tx_id":    ptx_id,
            "org_id":           org_id,
            "principal_usd":    amount,
            "apr_bps":          600,
            "accrued_interest": round(amount * 0.06 / 365 * 30, 2),
            "start":            start,
            "maturity":         (now + timedelta(days=335)).isoformat(),
            "status":           "active",
            "last_accrued_date": now.strftime("%Y-%m-%d"),
            "is_demo":          True,
            "is_deleted":       False,
            "created_at":       start,
            "updated_at":       now.isoformat(),
        })
        summary.update({"tx_count": 2, "position_count": 1,
                         "principal_usd": amount})

    await log_action(actor=user, action="admin.ops.seed_demo_client",
                      resource_type="organization", resource_id=org_id,
                      metadata=summary)
    return {"ok": True, **summary, "kyb_status": kyb_status}


# ---------------------------------------------------------------------------
# STATUS — public-ish health snapshot used by /status page.
# Aggregates: Mongo ping, Redis ping (if configured), counts per surface.
# NOT guarded — designed to be polled by the public status page.
# ---------------------------------------------------------------------------
status_router = APIRouter(prefix="/status", tags=["status"])


@status_router.get("")
async def status():
    from db import get_client
    import os as _os
    services: list[dict] = []

    # 1. Mongo
    try:
        await get_client().admin.command("ping")
        services.append({"id": "mongo", "name": "Database (MongoDB)",
                          "status": "operational"})
    except Exception as e:
        services.append({"id": "mongo", "name": "Database (MongoDB)",
                          "status": "outage", "detail": str(e)[:120]})

    # 2. Redis (optional — degraded if not connected)
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(_os.environ.get("REDIS_URL",
                                              "redis://localhost:6379/0"),
                              decode_responses=True)
        await r.ping()
        await r.close()
        services.append({"id": "redis", "name": "OTP Cache (Redis)",
                          "status": "operational"})
    except Exception:
        services.append({"id": "redis", "name": "OTP Cache (Redis)",
                          "status": "degraded",
                          "detail": "Fallback a Mongo OTP storage"})

    # 3. API (we're answering = ok)
    services.append({"id": "api", "name": "Public API",
                      "status": "operational"})

    # 4. Admin Portal (we trust it's up if API is)
    services.append({"id": "admin", "name": "Portal Admin",
                      "status": "operational"})

    # 5. Client Portal
    services.append({"id": "client", "name": "Portal Cliente",
                      "status": "operational"})

    # 6. Webhooks delivery — check fail rate last 1h
    try:
        from db import WEBHOOK_DELIVERIES
        one_hour_ago = (datetime.now(timezone.utc)
                         - timedelta(hours=1)).isoformat()
        total = await col(WEBHOOK_DELIVERIES).count_documents(
            {"ts": {"$gte": one_hour_ago}})
        fails = await col(WEBHOOK_DELIVERIES).count_documents(
            {"ts": {"$gte": one_hour_ago},
              "http_code": {"$not": {"$gte": 200, "$lt": 300}}})
        if total == 0:
            services.append({"id": "webhooks", "name": "Webhooks delivery",
                              "status": "operational",
                              "detail": "Sin tráfico en la última hora"})
        elif fails / total > 0.1:
            services.append({"id": "webhooks", "name": "Webhooks delivery",
                              "status": "degraded",
                              "detail": f"{fails}/{total} entregas fallidas (>10%)"})
        else:
            services.append({"id": "webhooks", "name": "Webhooks delivery",
                              "status": "operational",
                              "detail": f"{total} entregas / {fails} fallidas"})
    except Exception:
        services.append({"id": "webhooks", "name": "Webhooks delivery",
                          "status": "operational"})

    # 7. Integrations (mode flags)
    alfred_mode  = _os.environ.get("ALFRED_MODE",  "mock")
    prosper_mode = _os.environ.get("PROSPER_MODE", "mock")
    services.append({"id": "alfred", "name": "Alfred (Onramp/Offramp)",
                      "status": "operational",
                      "detail": f"modo {alfred_mode}"})
    services.append({"id": "prosper", "name": "Prosper backend (Stellar)",
                      "status": "operational",
                      "detail": f"modo {prosper_mode}"})

    all_op = all(s["status"] == "operational" for s in services)
    overall = "operational" if all_op else (
        "outage" if any(s["status"] == "outage" for s in services)
        else "degraded")

    return {
        "overall":   overall,
        "services":  services,
        "checked_at": _iso_now(),
        "version":   "0.2.0",
    }
