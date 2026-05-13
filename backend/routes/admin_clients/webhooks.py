"""Phase 6 — Per-client webhook endpoints with HMAC signing + delivery log."""
from __future__ import annotations
import hashlib, hmac, json, secrets as _s
from datetime import datetime, timezone
from typing import List, Literal, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from audit import log_action
from auth import CurrentUser
from db import col, WEBHOOKS, WEBHOOK_DELIVERIES
from ._deps import require_admin, require_write, iso_now

router = APIRouter(prefix="/admin/clients", tags=["admin-clients-webhooks"])

AVAILABLE_EVENTS = [
    "tx.created", "tx.confirmed", "tx.failed",
    "kyb.approved", "kyb.rejected",
    "user.invited", "user.activated",
    "position.opened", "position.matured",
]


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _sign(secret: str, body: bytes, ts: str) -> str:
    msg = ts.encode() + b"." + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


@router.get("/{org_id}/webhooks")
async def list_webhooks(org_id: str, _: CurrentUser = Depends(require_admin)):
    rows = await col(WEBHOOKS).find(
        {"org_id": org_id, "is_deleted": False},
        {"_id": 0, "secret": 0}).sort("created_at", -1).to_list(200)
    return {"items": rows, "total": len(rows), "available_events": AVAILABLE_EVENTS}


class CreateWebhook(BaseModel):
    url:    HttpUrl
    events: List[str] = Field(..., min_length=1)
    description: Optional[str] = None


@router.post("/{org_id}/webhooks")
async def create_webhook(org_id: str, body: CreateWebhook,
                          actor: CurrentUser = Depends(require_write)):
    invalid = [e for e in body.events if e not in AVAILABLE_EVENTS]
    if invalid:
        raise HTTPException(400, f"Unknown events: {invalid}")
    wh_id = f"wh_{_s.token_hex(5)}"
    secret = _s.token_urlsafe(32)
    doc = {
        "webhook_id":  wh_id,
        "org_id":      org_id,
        "url":         str(body.url),
        "events":      body.events,
        "description": body.description or "",
        "secret":      secret,
        "secret_prefix": secret[:8],
        "status":      "active",
        "fail_count":  0,
        "last_delivery_at": None,
        "last_status":     None,
        "created_at":  iso_now(),
        "created_by":  actor.email,
        "is_deleted":  False,
    }
    await col(WEBHOOKS).insert_one(doc.copy())
    await log_action(actor=actor, action="clients.webhook.create",
                     resource_type="webhook", resource_id=wh_id,
                     metadata={"org_id": org_id, "url": str(body.url),
                                "events": body.events})
    doc.pop("_id", None)
    return {"ok": True, "webhook": {k: v for k, v in doc.items() if k != "secret"},
             "secret": secret,
             "warning": "Guardá este secret ahora; no se vuelve a mostrar completo."}


@router.post("/{org_id}/webhooks/{wh_id}/reveal-secret")
async def reveal_secret(org_id: str, wh_id: str,
                         actor: CurrentUser = Depends(require_write)):
    wh = await col(WEBHOOKS).find_one(
        {"webhook_id": wh_id, "org_id": org_id, "is_deleted": False})
    if not wh:
        raise HTTPException(404, "Webhook not found")
    await log_action(actor=actor, action="clients.webhook.reveal_secret",
                     resource_type="webhook", resource_id=wh_id,
                     metadata={"org_id": org_id})
    return {"ok": True, "secret": wh.get("secret"),
             "expires_at": _now_dt().isoformat()}


@router.delete("/{org_id}/webhooks/{wh_id}")
async def delete_webhook(org_id: str, wh_id: str,
                          actor: CurrentUser = Depends(require_write)):
    res = await col(WEBHOOKS).update_one(
        {"webhook_id": wh_id, "org_id": org_id, "is_deleted": False},
        {"$set": {"is_deleted": True, "deleted_at": iso_now(),
                   "deleted_by": actor.email}})
    if not res.matched_count:
        raise HTTPException(404, "Webhook not found")
    await log_action(actor=actor, action="clients.webhook.delete",
                     resource_type="webhook", resource_id=wh_id,
                     metadata={"org_id": org_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Test endpoint — sends a sample signed payload to the webhook URL
# ---------------------------------------------------------------------------
async def _deliver(wh: dict, event: str, payload: dict, retry: int = 0) -> dict:
    body = json.dumps({"event": event, "payload": payload,
                        "delivered_at": iso_now()}).encode()
    ts = iso_now()
    sig = _sign(wh["secret"], body, ts)
    delivery_id = f"whd_{_s.token_hex(5)}"
    delivery = {
        "delivery_id": delivery_id,
        "webhook_id":  wh["webhook_id"],
        "org_id":      wh["org_id"],
        "event":       event,
        "url":         wh["url"],
        "payload":     payload,
        "ts":          ts,
        "retry_count": retry,
        "http_code":   None,
        "response_body": None,
        "error":       None,
        "created_at":  ts,
    }
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(wh["url"], content=body,
                              headers={"Content-Type": "application/json",
                                       "X-Prosper-Signature": f"t={ts},v1={sig}",
                                       "X-Prosper-Event": event})
            delivery["http_code"]     = r.status_code
            delivery["response_body"] = r.text[:500]
    except Exception as e:
        delivery["error"] = str(e)

    await col(WEBHOOK_DELIVERIES).insert_one(delivery.copy())
    success = delivery["http_code"] and 200 <= delivery["http_code"] < 300
    await col(WEBHOOKS).update_one(
        {"webhook_id": wh["webhook_id"]},
        {"$set": {"last_delivery_at": ts,
                  "last_status":     "ok" if success else "failed"},
         "$inc":  {"fail_count": 0 if success else 1}})
    delivery.pop("_id", None)
    return delivery


@router.post("/{org_id}/webhooks/{wh_id}/test")
async def test_webhook(org_id: str, wh_id: str,
                        actor: CurrentUser = Depends(require_write)):
    wh = await col(WEBHOOKS).find_one(
        {"webhook_id": wh_id, "org_id": org_id, "is_deleted": False})
    if not wh:
        raise HTTPException(404, "Webhook not found")
    sample = {"test": True, "org_id": org_id,
              "message": "Esto es un test desde Prosper /admin/clients/webhooks",
              "ts": iso_now()}
    res = await _deliver(wh, event="webhook.test", payload=sample)
    return {"ok": bool(res.get("http_code") and 200 <= res["http_code"] < 300),
             "delivery": res}


@router.get("/{org_id}/webhooks/{wh_id}/deliveries")
async def list_deliveries(org_id: str, wh_id: str,
                           limit: int = Query(100, ge=1, le=500),
                           _: CurrentUser = Depends(require_admin)):
    rows = await col(WEBHOOK_DELIVERIES).find(
        {"webhook_id": wh_id, "org_id": org_id}, {"_id": 0}
    ).sort("ts", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}
