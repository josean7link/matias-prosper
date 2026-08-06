"""Phase 6 — Client list + create + detail + patch + pause/reactivate."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from audit import log_action
from auth import CurrentUser
from db import (
    col, ALERTS, ORGANIZATIONS, POSITIONS, RISK_SCORES, TRANSACTIONS, USERS,
)
from integrations.email_sender import send_email, t_invitation
from ._deps import require_admin, require_write, iso_now

router = APIRouter(prefix="/admin/clients", tags=["admin-clients"])


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
@router.get("")
async def list_clients(
    kyb_status: Optional[List[str]] = Query(None),
    type:       Optional[List[str]] = Query(None, alias="type"),
    env:        Optional[List[str]] = Query(None),
    parent_org_id: Optional[str] = Query(
        None,
        description="Phase 23: filter by parent. Pass 'none' for top-level "
                    "N1 only; otherwise an org_id to list its N2s."),
    q:          Optional[str] = None,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    _: CurrentUser = Depends(require_admin),
):
    filt: dict = {"is_deleted": False}
    if kyb_status: filt["kyb_status"] = {"$in": kyb_status}
    if type:       filt["type"]       = {"$in": type}
    if env:        filt["env"]        = {"$in": env}
    if parent_org_id == "none":
        filt["parent_org_id"] = None
    elif parent_org_id:
        filt["parent_org_id"] = parent_org_id
    if q:
        rgx = {"$regex": q, "$options": "i"}
        filt["$or"] = [
            {"legal_name": rgx}, {"commercial_name": rgx},
            {"primary_email": rgx}, {"tax_id": rgx},
        ]

    total = await col(ORGANIZATIONS).count_documents(filt)
    skip = (page - 1) * page_size
    rows = await col(ORGANIZATIONS).find(filt, {"_id": 0}).sort("created_at", -1) \
              .skip(skip).limit(page_size).to_list(page_size)
    org_ids = [o["org_id"] for o in rows]

    # Last login per org (latest user.last_login_at)
    users = await col(USERS).find(
        {"org_id": {"$in": org_ids}, "is_deleted": False},
        {"_id": 0, "org_id": 1, "last_login_at": 1, "user_id": 1}).to_list(2000)
    by_org_users: dict[str, dict] = {}
    for u in users:
        b = by_org_users.setdefault(u["org_id"], {"count": 0, "last_login": ""})
        b["count"] += 1
        ll = u.get("last_login_at") or ""
        if ll > b["last_login"]: b["last_login"] = ll

    # Volume + critical alerts per org
    vol_rows = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "confirmed",
                     "org_id": {"$in": org_ids}}},
        {"$group": {"_id": "$org_id", "v": {"$sum": "$amount"}}},
    ]).to_list(500)
    vol_map = {r["_id"]: r["v"] for r in vol_rows}

    alert_rows = await col(ALERTS).aggregate([
        {"$match": {"is_deleted": False, "status": "open",
                     "severity": "critical", "org_id": {"$in": org_ids}}},
        {"$group": {"_id": "$org_id", "n": {"$sum": 1}}},
    ]).to_list(500)
    alert_map = {r["_id"]: r["n"] for r in alert_rows}

    year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    items = []
    for o in rows:
        oid = o["org_id"]
        u = by_org_users.get(oid, {"count": 0, "last_login": ""})
        items.append({
            "org_id":         oid,
            "legal_name":     o.get("legal_name"),
            "commercial_name": o.get("commercial_name") or o.get("legal_name"),
            "country":        o.get("country") or "AR",
            "type":           o.get("type") or "fintech",
            "env":            o.get("env") or "sandbox",
            "kyb_status":     o.get("kyb_status") or "pending",
            "tier":           o.get("tier") or "T2",
            "tax_id":         o.get("tax_id"),
            "primary_email":  o.get("primary_email"),
            "created_at":     o.get("created_at"),
            "last_login_at":  u["last_login"] or None,
            "users_count":    u["count"],
            "volume_total":   round(vol_map.get(oid, 0), 2),
            "critical_alerts": alert_map.get(oid, 0),
            "kyb_refresh_due": bool(
                o.get("last_kyb_refresh_at", o.get("created_at") or "") < year_ago
                and o.get("kyb_status") == "approved"),
            "paused":         bool(o.get("paused", False)),
            # Phase 23 — hierarchy
            "parent_org_id":  o.get("parent_org_id"),
            "level":          o.get("level") or 1,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
class CreateClient(BaseModel):
    legal_name:      str = Field(..., min_length=2, max_length=120)
    commercial_name: Optional[str] = None
    country:         str = Field(..., min_length=2, max_length=3)
    tax_id:          str = Field(..., min_length=4, max_length=40)
    type:            Literal["fintech", "broker", "family_office",
                              "retail_aggregator", "other"] = "fintech"
    expected_aum_usd: float = Field(0, ge=0)
    start_date:       Optional[str] = None

    primary_email:    EmailStr
    primary_name:     str = Field(..., min_length=2)
    primary_phone:    Optional[str] = None
    domain_allowlist: List[str] = []

    tier: Literal["T1", "T2", "T3"] = "T2"
    caps: dict = Field(default_factory=lambda: {
        "subscribe_daily_cap_usd":   100_000,
        "subscribe_monthly_cap_usd": 2_000_000,
        "redeem_daily_cap_usd":      100_000,
        "redeem_monthly_cap_usd":    2_000_000,
    })
    notes: Optional[str] = ""
    env:   Literal["sandbox", "production"] = "sandbox"


@router.post("")
async def create_client(body: CreateClient,
                         user: CurrentUser = Depends(require_write)):
    # Idempotent check on tax_id within env
    if await col(ORGANIZATIONS).find_one(
        {"tax_id": body.tax_id, "env": body.env, "is_deleted": False}):
        raise HTTPException(409, f"Org with tax_id={body.tax_id} already exists")

    import secrets as _s
    org_id = f"org_{_s.token_hex(6)}"
    now = iso_now()
    org = {
        "org_id":          org_id,
        "legal_name":      body.legal_name,
        "commercial_name": body.commercial_name or body.legal_name,
        "country":         body.country.upper(),
        "tax_id":          body.tax_id,
        "type":            body.type,
        "expected_aum_usd": body.expected_aum_usd,
        "start_date":      body.start_date,
        "primary_email":   body.primary_email.lower(),
        "primary_name":    body.primary_name,
        "primary_phone":   body.primary_phone,
        "domain_allowlist": [d.lower().strip().lstrip("@") for d in body.domain_allowlist if d.strip()],
        "tier":            body.tier,
        "caps":            body.caps,
        "notes":           body.notes or "",
        "env":             body.env,
        "kyb_status":      "pending",
        "paused":          False,
        "created_at":      now,
        "updated_at":      now,
        "created_by":      user.email,
        "is_deleted":      False,
    }
    await col(ORGANIZATIONS).insert_one(org.copy())

    # Pending user for the primary contact
    user_id = f"usr_{_s.token_hex(5)}"
    primary_user = {
        "user_id":     user_id,
        "email":       org["primary_email"],
        "full_name":   body.primary_name,
        "role":        "client_admin",
        "org_id":      org_id,
        "status":      "invited",
        "kyc_status":  "pending",
        "mfa_enabled": False,
        "phone":       body.primary_phone,
        "created_at":  now, "updated_at": now,
        "is_deleted":  False,
    }
    await col(USERS).insert_one(primary_user.copy())

    # Generate invite link + send email (mock-friendly if no key)
    from .links import _create_signed_link  # local import to avoid cycle
    link_doc = await _create_signed_link(
        purpose="invite", org_id=org_id, user_id=user_id,
        email=org["primary_email"], ttl_hours=72, created_by=user.email)
    subject, html = t_invitation(name=body.primary_name,
                                   org_name=org["commercial_name"],
                                   link=link_doc["url"])
    await send_email(to=org["primary_email"], subject=subject, html=html,
                      template="invitation",
                      context={"link": link_doc["url"], "org": org["commercial_name"]},
                      org_id=org_id, user_id=user_id, actor_email=user.email)

    await log_action(actor=user, action="clients.create",
                     resource_type="organization", resource_id=org_id,
                     metadata={"email": org["primary_email"]})

    org.pop("_id", None)
    return {"ok": True, "org": org, "primary_user_id": user_id,
             "invite_link": link_doc["url"]}


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
@router.get("/{org_id}")
async def get_client(org_id: str, _: CurrentUser = Depends(require_admin)):
    o = await col(ORGANIZATIONS).find_one({"org_id": org_id, "is_deleted": False}, {"_id": 0})
    if not o:
        raise HTTPException(404, "Not found")

    risk = await col(RISK_SCORES).find_one({"org_id": org_id}, {"_id": 0})

    # Aggregations
    vol_agg = await col(TRANSACTIONS).aggregate([
        {"$match": {"is_deleted": False, "status": "confirmed", "org_id": org_id}},
        {"$group": {"_id": None, "v": {"$sum": "$amount"},
                     "n": {"$sum": 1}}},
    ]).to_list(1)
    pos_count = await col(POSITIONS).count_documents(
        {"is_deleted": False, "org_id": org_id, "status": "active"})
    users_count = await col(USERS).count_documents({"org_id": org_id, "is_deleted": False})
    alerts_open = await col(ALERTS).count_documents(
        {"is_deleted": False, "status": "open", "org_id": org_id})

    return {
        "org": o,
        "metrics": {
            "volume_total_usd": round((vol_agg[0]["v"] if vol_agg else 0), 2),
            "tx_count":         (vol_agg[0]["n"] if vol_agg else 0),
            "active_positions": pos_count,
            "users_count":      users_count,
            "alerts_open":      alerts_open,
        },
        "risk": risk,
    }


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------
class ClientPatch(BaseModel):
    commercial_name:  Optional[str] = None
    country:          Optional[str] = None
    type:             Optional[str] = None
    expected_aum_usd: Optional[float] = None
    primary_name:     Optional[str] = None
    primary_phone:    Optional[str] = None
    domain_allowlist: Optional[List[str]] = None
    tier:             Optional[str] = None
    notes:            Optional[str] = None


@router.patch("/{org_id}")
async def patch_client(org_id: str, body: ClientPatch,
                       user: CurrentUser = Depends(require_write)):
    exists = await col(ORGANIZATIONS).find_one({"org_id": org_id, "is_deleted": False})
    if not exists:
        raise HTTPException(404, "Not found")
    upd = body.model_dump(exclude_none=True)
    if "domain_allowlist" in upd:
        upd["domain_allowlist"] = [d.lower().strip().lstrip("@") for d in upd["domain_allowlist"] if d.strip()]
    upd["updated_at"] = iso_now()
    await col(ORGANIZATIONS).update_one({"org_id": org_id}, {"$set": upd})
    await log_action(actor=user, action="clients.patch",
                     resource_type="organization", resource_id=org_id,
                     metadata={"changed": list(upd.keys())})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Pause / reactivate
# ---------------------------------------------------------------------------
@router.post("/{org_id}/pause")
async def pause_client(org_id: str, user: CurrentUser = Depends(require_write)):
    res = await col(ORGANIZATIONS).update_one(
        {"org_id": org_id, "is_deleted": False},
        {"$set": {"paused": True, "paused_at": iso_now(),
                   "paused_by": user.email, "updated_at": iso_now()}})
    if not res.matched_count:
        raise HTTPException(404, "Not found")
    await log_action(actor=user, action="clients.pause",
                     resource_type="organization", resource_id=org_id, metadata={})
    return {"ok": True, "paused": True}


@router.post("/{org_id}/reactivate")
async def reactivate_client(org_id: str, user: CurrentUser = Depends(require_write)):
    res = await col(ORGANIZATIONS).update_one(
        {"org_id": org_id, "is_deleted": False},
        {"$set": {"paused": False, "paused_at": None, "paused_by": None,
                   "reactivated_at": iso_now(), "reactivated_by": user.email,
                   "updated_at": iso_now()}})
    if not res.matched_count:
        raise HTTPException(404, "Not found")
    await log_action(actor=user, action="clients.reactivate",
                     resource_type="organization", resource_id=org_id, metadata={})
    return {"ok": True, "paused": False}


# ---------------------------------------------------------------------------
# Audit log per client
# ---------------------------------------------------------------------------
@router.get("/{org_id}/audit-log")
async def audit_log(org_id: str, limit: int = Query(100, ge=1, le=500),
                     _: CurrentUser = Depends(require_admin)):
    rows = await col("audit_logs").find(
        {"$or": [{"org_id": org_id}, {"resource_id": org_id}]},
        {"_id": 0}).sort("ts", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# Positions + transactions, scoped to org
# ---------------------------------------------------------------------------
@router.get("/{org_id}/positions")
async def client_positions(org_id: str, _: CurrentUser = Depends(require_admin)):
    rows = await col(POSITIONS).find(
        {"org_id": org_id, "is_deleted": False}, {"_id": 0}).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.get("/{org_id}/transactions")
async def client_transactions(org_id: str, limit: int = Query(100, ge=1, le=500),
                                _: CurrentUser = Depends(require_admin)):
    rows = await col(TRANSACTIONS).find(
        {"org_id": org_id, "is_deleted": False}, {"_id": 0})\
        .sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}
