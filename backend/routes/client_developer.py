"""Phase 11A — Client self-service endpoints.

Mirrors the admin api-keys + webhooks endpoints but scoped to the caller's
own org_id. Only `client_admin` and `client_user` roles can read; only
`client_admin` can mutate keys / webhooks.

Also exposes `/client/feature-interest` for the coming-soon page.
"""
from __future__ import annotations
import secrets as _s
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, HttpUrl

from audit import log_action
from auth import CurrentUser, get_current_user
from db import col, API_KEYS, FEATURE_INTEREST, WEBHOOKS, WEBHOOK_DELIVERIES
from routes.admin_clients.api_keys import _hash, _new_secret
from routes.admin_clients.webhooks import AVAILABLE_EVENTS, _deliver

router = APIRouter(prefix="/client", tags=["client-self-service"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_admin(user: CurrentUser) -> None:
    """client_admin only — mutations on API keys / webhooks."""
    if user.role not in ("client_admin", "super_admin"):
        raise HTTPException(403, "Only client_admin can manage keys/webhooks")


# ---------------------------------------------------------------------------
# API KEYS
# ---------------------------------------------------------------------------
@router.get("/api-keys")
async def list_api_keys(user: CurrentUser = Depends(get_current_user)):
    rows = await col(API_KEYS).find(
        {"org_id": user.org_id, "is_deleted": False},
        {"_id": 0, "secret_hash": 0}).sort("created_at", -1).to_list(200)
    return {"items": rows, "total": len(rows)}


class CreateKeyIn(BaseModel):
    name:  str = Field(..., min_length=1, max_length=80)
    scope: Literal["sandbox", "production"] = "sandbox"


@router.post("/api-keys")
async def create_api_key(body: CreateKeyIn,
                          user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    # Production keys gated by org.env == production (only super_admin can
    # currently flip env)
    if body.scope == "production":
        from db import ORGANIZATIONS
        org = await col(ORGANIZATIONS).find_one(
            {"org_id": user.org_id, "is_deleted": False}, {"_id": 0, "env": 1})
        if (org or {}).get("env") != "production":
            raise HTTPException(
                400, "Tu organización todavía está en sandbox. "
                      "Contactanos para habilitar production.")
    key_id = f"key_{_s.token_hex(5)}"
    plaintext, prefix = _new_secret(body.scope)
    doc = {
        "key_id":       key_id,
        "org_id":       user.org_id,
        "name":         body.name,
        "scope":        body.scope,
        "prefix":       prefix,
        "secret_hash":  _hash(plaintext),
        "created_at":   _iso_now(),
        "created_by":   user.email,
        "last_used_at": None,
        "last_used_ip": None,
        "status":       "active",
        "is_deleted":   False,
    }
    await col(API_KEYS).insert_one(doc.copy())
    await log_action(actor=user, action="client.api_key.create",
                      resource_type="api_key", resource_id=key_id,
                      metadata={"scope": body.scope, "name": body.name})
    return {"ok": True, "key_id": key_id, "name": body.name, "scope": body.scope,
             "prefix": prefix, "plaintext": plaintext,
             "warning": "Esta es la única vez que vas a ver la key completa. Guardala ahora."}


@router.post("/api-keys/{key_id}/rotate")
async def rotate_api_key(key_id: str,
                          user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    existing = await col(API_KEYS).find_one(
        {"key_id": key_id, "org_id": user.org_id, "is_deleted": False})
    if not existing:
        raise HTTPException(404, "Key not found")
    plaintext, prefix = _new_secret(existing["scope"])
    await col(API_KEYS).update_one(
        {"key_id": key_id},
        {"$set": {"prefix": prefix, "secret_hash": _hash(plaintext),
                    "rotated_at": _iso_now(), "rotated_by": user.email,
                    "last_used_at": None, "last_used_ip": None,
                    "status": "active"}})
    await log_action(actor=user, action="client.api_key.rotate",
                      resource_type="api_key", resource_id=key_id, metadata={})
    return {"ok": True, "key_id": key_id, "prefix": prefix,
             "plaintext": plaintext,
             "warning": "Esta es la única vez que vas a ver la nueva key."}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: str,
                          user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    res = await col(API_KEYS).update_one(
        {"key_id": key_id, "org_id": user.org_id, "is_deleted": False},
        {"$set": {"status": "revoked", "revoked_at": _iso_now(),
                    "revoked_by": user.email, "is_deleted": True}})
    if not res.matched_count:
        raise HTTPException(404, "Key not found")
    await log_action(actor=user, action="client.api_key.revoke",
                      resource_type="api_key", resource_id=key_id, metadata={})
    return {"ok": True}


# ---------------------------------------------------------------------------
# WEBHOOKS
# ---------------------------------------------------------------------------
CLIENT_EVENTS = [
    "onramp.confirmed", "onramp.failed",
    "offramp.completed", "offramp.failed",
    "subscribe.confirmed", "redeem.confirmed",
    "position.matured",
    "kyc.approved", "kyc.rejected",
    "alert.critical",
]


@router.get("/webhooks")
async def list_webhooks(user: CurrentUser = Depends(get_current_user)):
    rows = await col(WEBHOOKS).find(
        {"org_id": user.org_id, "is_deleted": False},
        {"_id": 0, "secret": 0}).sort("created_at", -1).to_list(200)
    return {"items": rows, "total": len(rows),
             "available_events": CLIENT_EVENTS}


class CreateWebhookIn(BaseModel):
    url:    HttpUrl
    events: List[str] = Field(..., min_length=1)
    description: Optional[str] = None


@router.post("/webhooks")
async def create_webhook(body: CreateWebhookIn,
                          user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    invalid = [e for e in body.events if e not in CLIENT_EVENTS]
    if invalid:
        raise HTTPException(400, f"Unknown events: {invalid}")
    wh_id = f"wh_{_s.token_hex(5)}"
    secret = _s.token_urlsafe(32)
    doc = {
        "webhook_id":   wh_id,
        "org_id":       user.org_id,
        "url":          str(body.url),
        "events":       body.events,
        "description":  body.description or "",
        "secret":       secret,
        "secret_prefix": secret[:8],
        "status":       "active",
        "fail_count":   0,
        "last_delivery_at": None,
        "last_status":      None,
        "created_at":   _iso_now(),
        "created_by":   user.email,
        "is_deleted":   False,
    }
    await col(WEBHOOKS).insert_one(doc.copy())
    await log_action(actor=user, action="client.webhook.create",
                      resource_type="webhook", resource_id=wh_id,
                      metadata={"url": str(body.url), "events": body.events})
    doc.pop("_id", None)
    return {"ok": True,
             "webhook": {k: v for k, v in doc.items() if k != "secret"},
             "secret": secret,
             "warning": "Guardá este secret HMAC ahora; no se vuelve a mostrar completo."}


class UpdateWebhookIn(BaseModel):
    events:      Optional[List[str]] = None
    description: Optional[str]       = None
    status:      Optional[Literal["active", "paused"]] = None


@router.patch("/webhooks/{wh_id}")
async def update_webhook(wh_id: str, body: UpdateWebhookIn,
                          user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    update: dict = {}
    if body.events is not None:
        invalid = [e for e in body.events if e not in CLIENT_EVENTS]
        if invalid:
            raise HTTPException(400, f"Unknown events: {invalid}")
        update["events"] = body.events
    if body.description is not None: update["description"] = body.description
    if body.status      is not None: update["status"]      = body.status
    if not update:
        raise HTTPException(400, "no changes")
    res = await col(WEBHOOKS).update_one(
        {"webhook_id": wh_id, "org_id": user.org_id, "is_deleted": False},
        {"$set": {**update, "updated_at": _iso_now()}})
    if not res.matched_count:
        raise HTTPException(404, "Webhook not found")
    await log_action(actor=user, action="client.webhook.update",
                      resource_type="webhook", resource_id=wh_id,
                      metadata=update)
    return {"ok": True}


@router.delete("/webhooks/{wh_id}")
async def delete_webhook(wh_id: str,
                          user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    res = await col(WEBHOOKS).update_one(
        {"webhook_id": wh_id, "org_id": user.org_id, "is_deleted": False},
        {"$set": {"is_deleted": True, "deleted_at": _iso_now(),
                    "deleted_by": user.email}})
    if not res.matched_count:
        raise HTTPException(404, "Webhook not found")
    await log_action(actor=user, action="client.webhook.delete",
                      resource_type="webhook", resource_id=wh_id, metadata={})
    return {"ok": True}


@router.post("/webhooks/{wh_id}/test")
async def test_webhook(wh_id: str,
                        user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    wh = await col(WEBHOOKS).find_one(
        {"webhook_id": wh_id, "org_id": user.org_id, "is_deleted": False})
    if not wh:
        raise HTTPException(404, "Webhook not found")
    sample = {"test": True, "org_id": user.org_id,
                "message": "Test desde Prosper /client/webhooks",
                "ts": _iso_now()}
    delivery = await _deliver(wh, event="webhook.test", payload=sample)
    return {"ok": bool(delivery.get("http_code")
                        and 200 <= delivery["http_code"] < 300),
             "delivery": delivery}


@router.post("/webhooks/{wh_id}/reveal-secret")
async def reveal_webhook_secret(wh_id: str,
                                  user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    wh = await col(WEBHOOKS).find_one(
        {"webhook_id": wh_id, "org_id": user.org_id, "is_deleted": False})
    if not wh:
        raise HTTPException(404, "Webhook not found")
    await log_action(actor=user, action="client.webhook.reveal_secret",
                      resource_type="webhook", resource_id=wh_id, metadata={})
    return {"ok": True, "secret": wh.get("secret"),
             "expires_at": _iso_now()}


@router.get("/webhooks/{wh_id}/deliveries")
async def list_deliveries(wh_id: str,
                           limit: int = Query(100, ge=1, le=500),
                           user: CurrentUser = Depends(get_current_user)):
    # Sanity-check the webhook belongs to caller
    wh = await col(WEBHOOKS).find_one(
        {"webhook_id": wh_id, "org_id": user.org_id, "is_deleted": False})
    if not wh:
        raise HTTPException(404, "Webhook not found")
    rows = await col(WEBHOOK_DELIVERIES).find(
        {"webhook_id": wh_id, "org_id": user.org_id}, {"_id": 0}
    ).sort("ts", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# WIDGET CONFIG  (persisted on org.widget_config)
# ---------------------------------------------------------------------------
class WidgetConfigIn(BaseModel):
    theme:          Literal["light", "dark"] = "light"
    color:          str = "#2B6BFF"
    locale:         Literal["es", "en", "auto"] = "es"
    amount:         Optional[float] = None
    product_id:     str = "usdc_end"
    show_branding:  bool = True


@router.get("/widget/config")
async def get_widget_config(user: CurrentUser = Depends(get_current_user)):
    from db import ORGANIZATIONS
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": user.org_id, "is_deleted": False},
        {"_id": 0, "widget_config": 1, "commercial_name": 1, "legal_name": 1})
    cfg = (org or {}).get("widget_config") or WidgetConfigIn().model_dump()
    return {"config": cfg,
             "org_name": (org or {}).get("commercial_name")
                          or (org or {}).get("legal_name")}


@router.put("/widget/config")
async def save_widget_config(body: WidgetConfigIn,
                              user: CurrentUser = Depends(get_current_user)):
    _assert_admin(user)
    from db import ORGANIZATIONS
    cfg = body.model_dump()
    res = await col(ORGANIZATIONS).update_one(
        {"org_id": user.org_id, "is_deleted": False},
        {"$set": {"widget_config": cfg, "updated_at": _iso_now()}})
    if not res.matched_count:
        raise HTTPException(404, "Organization not found")
    await log_action(actor=user, action="client.widget.save",
                      resource_type="organization", resource_id=user.org_id,
                      metadata=cfg)
    return {"ok": True, "config": cfg}


# ---------------------------------------------------------------------------
# FEATURE INTEREST  (coming-soon page CTAs)
# ---------------------------------------------------------------------------
KNOWN_FEATURES = {"lending", "multi_asset", "card", "marketplace", "yield_aggregator"}


class FeatureInterestIn(BaseModel):
    feature: str


@router.post("/feature-interest")
async def register_feature_interest(body: FeatureInterestIn,
                                      user: CurrentUser = Depends(get_current_user)):
    if body.feature not in KNOWN_FEATURES:
        raise HTTPException(400, f"Unknown feature {body.feature}")
    existing = await col(FEATURE_INTEREST).find_one(
        {"org_id": user.org_id, "user_id": user.user_id,
          "feature": body.feature})
    if existing:
        return {"ok": True, "already_registered": True}
    await col(FEATURE_INTEREST).insert_one({
        "interest_id":   "ft_" + _s.token_hex(5),
        "org_id":        user.org_id,
        "user_id":       user.user_id,
        "feature":       body.feature,
        "registered_at": _iso_now(),
        "email_sent":    False,
    })
    await log_action(actor=user, action="client.feature_interest",
                      resource_type="feature", resource_id=body.feature,
                      metadata={})
    return {"ok": True, "registered": True}


@router.get("/feature-interest")
async def list_feature_interest(user: CurrentUser = Depends(get_current_user)):
    rows = await col(FEATURE_INTEREST).find(
        {"org_id": user.org_id}, {"_id": 0}).to_list(50)
    return {"items": rows, "registered": [r["feature"] for r in rows]}
