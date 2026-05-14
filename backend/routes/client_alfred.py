"""Phase 8 — Alfred onramp/offramp endpoints + webhook + history.

Mounted under /api/v1 in server.py.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ALERTS, AUDIT_LOGS, OFFRAMP_ORDERS, ONRAMP_ORDERS, ORGANIZATIONS,
    TRANSACTIONS, WEBHOOKS, WEBHOOK_EVENTS,
)
from integrations.alfred import (
    AlfredError, current_mode, get_adapter, verify_webhook,
)
from integrations.alfred.mock import settle_now
from integrations.email_sender import send_email, _shell

logger = logging.getLogger("prosper.alfred.routes")

ALFRED_CALLS_LOG = "alfred_calls_log"
# Outgoing webhook deliveries collection already used in Phase 6
WEBHOOK_DELIVERIES = "webhook_deliveries"

router = APIRouter(prefix="/client", tags=["client-alfred"])
# Webhook public router (separate prefix, no auth dep)
webhook_router = APIRouter(prefix="/webhooks", tags=["alfred-webhook"])
# Mock-checkout helper (returned as Alfred checkout_url when mode=mock)
mock_router = APIRouter(prefix="/alfred", tags=["alfred-mock"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _log_call(name: str, *, org_id: Optional[str], user_id: Optional[str],
                     payload: dict, response: dict, error: Optional[str] = None) -> None:
    """Persist every Alfred call for audit & debug."""
    await col(ALFRED_CALLS_LOG).insert_one({
        "call_id":   "alc_" + secrets.token_hex(6),
        "name":      name,
        "mode":      current_mode(),
        "org_id":    org_id,
        "user_id":   user_id,
        "payload":   payload,
        "response":  response,
        "error":     error,
        "created_at": _iso_now(),
    })


async def _assert_can_operate(user: CurrentUser) -> dict:
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": user.org_id, "is_deleted": False}, {"_id": 0})
    if not org:
        raise HTTPException(404, "Organization not found")
    if org.get("kyb_status") != "approved":
        raise HTTPException(403, "KYB not approved — operations are blocked")
    if org.get("paused"):
        raise HTTPException(403, "Organization is paused")
    return org


async def _sum_today(org_id: str, tx_type: str) -> float:
    today = _iso_now()[:10]
    cur = col(TRANSACTIONS).aggregate([
        {"$match": {"org_id": org_id, "type": tx_type, "is_deleted": False,
                     "status": {"$in": ["pending", "confirmed"]},
                     "created_at": {"$regex": f"^{today}"}}},
        {"$group": {"_id": None, "v": {"$sum": "$amount"}}},
    ])
    rows = await cur.to_list(1)
    return float(rows[0]["v"]) if rows else 0.0


async def _sum_month(org_id: str, tx_type: str) -> float:
    month = _iso_now()[:7]
    cur = col(TRANSACTIONS).aggregate([
        {"$match": {"org_id": org_id, "type": tx_type, "is_deleted": False,
                     "status": {"$in": ["pending", "confirmed"]},
                     "created_at": {"$regex": f"^{month}"}}},
        {"$group": {"_id": None, "v": {"$sum": "$amount"}}},
    ])
    rows = await cur.to_list(1)
    return float(rows[0]["v"]) if rows else 0.0


# ---------------------------------------------------------------------------
# ONRAMP — quote + create + status
# ---------------------------------------------------------------------------
class OnrampQuoteIn(BaseModel):
    source_currency: str = Field(..., min_length=3, max_length=4)
    source_amount:   float = Field(..., gt=0)
    target_currency: str = "USDC"


@router.post("/onramp/quote")
async def onramp_quote(body: OnrampQuoteIn,
                        user: CurrentUser = Depends(get_current_user)):
    await _assert_can_operate(user)
    try:
        q = await get_adapter().get_quote(
            direction="onramp",
            source_currency=body.source_currency,
            source_amount=body.source_amount,
            target_currency=body.target_currency)
    except AlfredError as e:
        await _log_call("get_quote", org_id=user.org_id, user_id=user.user_id,
                         payload=body.model_dump(), response={}, error=str(e))
        raise HTTPException(400, str(e))

    await _log_call("get_quote", org_id=user.org_id, user_id=user.user_id,
                     payload=body.model_dump(), response=q.__dict__)
    return {
        "quote_id":        q.quote_id,
        "direction":       q.direction,
        "source_currency": q.source_currency,
        "source_amount":   q.source_amount,
        "target_currency": q.target_currency,
        "target_amount":   q.target_amount,
        "rate":            q.rate,
        "fee_amount":      q.fee_amount,
        "fee_currency":    q.fee_currency,
        "ttl_seconds":     q.ttl_seconds,
        "expires_at":      q.expires_at,
        "mode":            q.mode,
    }


class OnrampCreate(BaseModel):
    quote_id:        str
    source_currency: str
    source_amount:   float = Field(..., gt=0)
    payment_method:  Literal["transfer", "mercadopago", "crypto", "card"] = "transfer"


@router.post("/onramp/orders")
async def create_onramp(body: OnrampCreate, request: Request,
                         user: CurrentUser = Depends(get_current_user)):
    org = await _assert_can_operate(user)

    # Cap check (using subscribe caps, since onramped USDC is intended for subscribe)
    caps = (org.get("caps") or {})
    daily_cap   = caps.get("subscribe_daily_cap_usd")
    monthly_cap = caps.get("subscribe_monthly_cap_usd")
    # Expected USDC ≈ source_amount converted; use the mock adapter rate to be precise.
    try:
        quote = await get_adapter().get_quote(
            direction="onramp", source_currency=body.source_currency,
            source_amount=body.source_amount, target_currency="USDC")
    except AlfredError as e:
        raise HTTPException(400, f"Could not re-quote: {e}")
    expected_usdc = quote.target_amount

    if daily_cap is not None:
        used_today = await _sum_today(user.org_id, "onramp")
        if used_today + expected_usdc > daily_cap:
            raise HTTPException(
                400, f"Excede cap diario USD {daily_cap:.0f} (usaste {used_today:.0f})")
    if monthly_cap is not None:
        used_month = await _sum_month(user.org_id, "onramp")
        if used_month + expected_usdc > monthly_cap:
            raise HTTPException(
                400, f"Excede cap mensual USD {monthly_cap:.0f}")

    base = str(request.base_url).rstrip("/")
    callback = f"{base}/api/v1/webhooks/alfred"

    try:
        resp = await get_adapter().create_onramp_order(
            quote_id=body.quote_id,
            source_currency=body.source_currency,
            source_amount=body.source_amount,
            user_id=user.user_id,
            org_id=user.org_id,
            callback_url=callback,
            payment_method=body.payment_method)
    except AlfredError as e:
        await _log_call("create_onramp_order", org_id=user.org_id, user_id=user.user_id,
                         payload=body.model_dump(), response={}, error=str(e))
        raise HTTPException(502, f"Alfred create order failed: {e}")

    onramp_id = "on_" + secrets.token_hex(6)
    doc = {
        "onramp_id":         onramp_id,
        "org_id":            user.org_id,
        "user_id":           user.user_id,
        "alfred_id":         resp.alfred_id,
        "coelsa_id":         None,
        "source_currency":   body.source_currency.upper(),
        "source_amount":     body.source_amount,
        "target_currency":   "USDC",
        "expected_usdc":     expected_usdc,
        "rate":              quote.rate,
        "fee_amount":        quote.fee_amount,
        "fee_currency":      quote.fee_currency,
        "usdc_received":     None,
        "payment_method":    body.payment_method,
        "checkout_url":      resp.checkout_url,
        "status":            "pending",
        "mode":              resp.mode,
        "created_at":        _iso_now(),
        "updated_at":        _iso_now(),
        "is_deleted":        False,
    }
    await col(ONRAMP_ORDERS).insert_one(doc.copy())
    doc.pop("_id", None)
    await _log_call("create_onramp_order", org_id=user.org_id, user_id=user.user_id,
                     payload=body.model_dump(), response={"alfred_id": resp.alfred_id})
    await log_action(actor=user, action="client.onramp.create",
                     resource_type="onramp_order", resource_id=onramp_id,
                     metadata={"alfred_id": resp.alfred_id,
                                "source_amount": body.source_amount,
                                "source_currency": body.source_currency.upper()})
    return {"ok": True, "order": doc}


@router.get("/onramp/orders/{onramp_id}")
async def get_onramp(onramp_id: str,
                      user: CurrentUser = Depends(get_current_user)):
    order = await col(ONRAMP_ORDERS).find_one(
        {"onramp_id": onramp_id, "org_id": user.org_id, "is_deleted": False},
        {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")

    # Refresh status from Alfred if still pending
    if order["status"] == "pending" and order.get("alfred_id"):
        try:
            st = await get_adapter().get_order_status(order["alfred_id"])
            if st.status != "pending":
                update = {"status": st.status, "updated_at": _iso_now()}
                if st.status == "confirmed":
                    update.update({
                        "usdc_received": st.settled_amount,
                        "coelsa_id":     st.coelsa_id,
                        "settled_at":    _iso_now(),
                    })
                    await _ensure_tx_for_onramp(order["org_id"], order, st)
                await col(ONRAMP_ORDERS).update_one(
                    {"onramp_id": onramp_id}, {"$set": update})
                order.update(update)
        except AlfredError as e:
            logger.warning("get_order_status failed: %s", e)

    return {"order": order}


async def _ensure_tx_for_onramp(org_id: str, order: dict, st) -> None:
    """Create a transaction record reflecting the settled onramp."""
    existing = await col(TRANSACTIONS).find_one(
        {"prosper_tx_id": f"onramp::{order['onramp_id']}"})
    if existing:
        return
    await col(TRANSACTIONS).insert_one({
        "tx_id":         "tx_" + secrets.token_hex(6),
        "org_id":        org_id,
        "prosper_tx_id": f"onramp::{order['onramp_id']}",
        "type":          "onramp",
        "amount":        float(st.settled_amount or order.get("expected_usdc") or 0),
        "asset":         "USDC",
        "status":        "confirmed",
        "tx_hash":       st.tx_hash,
        "memo":          f"Alfred onramp {order['alfred_id']}",
        "metadata":      {"onramp_id": order["onramp_id"],
                          "alfred_id": order["alfred_id"],
                          "coelsa_id": st.coelsa_id},
        "fee_amount":    order.get("fee_amount"),
        "fee_currency":  order.get("fee_currency"),
        "created_at":    _iso_now(),
        "updated_at":    _iso_now(),
        "is_deleted":    False,
    })


# ---------------------------------------------------------------------------
# OFFRAMP — quote + create + status
# ---------------------------------------------------------------------------
class OfframpQuoteIn(BaseModel):
    usdc_amount:     float = Field(..., gt=0)
    target_currency: str = Field(..., min_length=3, max_length=4)


@router.post("/offramp/quote")
async def offramp_quote(body: OfframpQuoteIn,
                         user: CurrentUser = Depends(get_current_user)):
    await _assert_can_operate(user)
    try:
        q = await get_adapter().get_quote(
            direction="offramp",
            source_currency="USDC",
            source_amount=body.usdc_amount,
            target_currency=body.target_currency)
    except AlfredError as e:
        raise HTTPException(400, str(e))
    return {
        "quote_id":        q.quote_id,
        "direction":       q.direction,
        "usdc_amount":     q.source_amount,
        "target_currency": q.target_currency,
        "target_amount":   q.target_amount,
        "rate":            q.rate,
        "fee_amount":      q.fee_amount,
        "fee_currency":    q.fee_currency,
        "ttl_seconds":     q.ttl_seconds,
        "expires_at":      q.expires_at,
        "mode":            q.mode,
    }


class BankAccountIn(BaseModel):
    holder_name:    str
    country:        str = "AR"
    cbu_or_iban:    Optional[str] = None
    bank_name:      Optional[str] = None
    account_alias:  Optional[str] = None


class OfframpCreate(BaseModel):
    quote_id:        str
    usdc_amount:     float = Field(..., gt=0)
    target_currency: str
    bank_account:    BankAccountIn
    source:          Literal["balance", "position"] = "balance"
    position_id:     Optional[str] = None   # required when source=position


@router.post("/offramp/orders")
async def create_offramp(body: OfframpCreate,
                          user: CurrentUser = Depends(get_current_user)):
    org = await _assert_can_operate(user)

    # Holder name guard
    legal_name = (org.get("legal_name") or "").strip().lower()
    holder     = body.bank_account.holder_name.strip().lower()
    if legal_name and legal_name not in holder and holder not in legal_name:
        raise HTTPException(
            400,
            f"Titular '{body.bank_account.holder_name}' no coincide con la razón social registrada.")

    # Caps (redeem caps)
    caps = (org.get("caps") or {})
    daily_cap   = caps.get("redeem_daily_cap_usd")
    monthly_cap = caps.get("redeem_monthly_cap_usd")
    if daily_cap is not None:
        used_today = await _sum_today(user.org_id, "offramp")
        if used_today + body.usdc_amount > daily_cap:
            raise HTTPException(400, f"Excede cap diario USD {daily_cap:.0f}")
    if monthly_cap is not None:
        used_month = await _sum_month(user.org_id, "offramp")
        if used_month + body.usdc_amount > monthly_cap:
            raise HTTPException(400, f"Excede cap mensual USD {monthly_cap:.0f}")

    if body.source == "position" and not body.position_id:
        raise HTTPException(400, "position_id is required when source=position")

    try:
        resp = await get_adapter().create_offramp_order(
            quote_id=body.quote_id,
            usdc_amount=body.usdc_amount,
            target_currency=body.target_currency,
            bank_account=body.bank_account.model_dump(),
            user_id=user.user_id,
            org_id=user.org_id)
    except AlfredError as e:
        raise HTTPException(502, f"Alfred create offramp failed: {e}")

    offramp_id = "off_" + secrets.token_hex(6)
    timeline = [
        {"key": "redeem_position", "label": "Posición liquidada",
         "done": body.source == "balance",
         "skipped": body.source == "balance"},
        {"key": "usdc_ready",      "label": "USDC disponible", "done": False},
        {"key": "alfred_sent",     "label": "Enviado a Alfred", "done": True},
        {"key": "bank_processing", "label": "En proceso bancario", "done": False},
        {"key": "credited",        "label": "Acreditado", "done": False},
    ]
    if body.source == "position":
        # Mark redeem step pending (Phase 9 will actually trigger redeem)
        timeline[0]["done"] = False

    doc = {
        "offramp_id":     offramp_id,
        "org_id":         user.org_id,
        "user_id":        user.user_id,
        "alfred_id":      resp.alfred_id,
        "usdc_sent":      body.usdc_amount,
        "target_currency": body.target_currency.upper(),
        "expected_fiat":  resp.expected_fiat,
        "fee_amount":     None,
        "rate":           None,
        "bank_account":   body.bank_account.model_dump(),
        "source":         body.source,
        "position_id":    body.position_id,
        "status":         "pending",
        "mode":           resp.mode,
        "timeline":       timeline,
        "created_at":     _iso_now(),
        "updated_at":     _iso_now(),
        "is_deleted":     False,
    }
    await col(OFFRAMP_ORDERS).insert_one(doc.copy())
    doc.pop("_id", None)
    await _log_call("create_offramp_order", org_id=user.org_id, user_id=user.user_id,
                     payload=body.model_dump(), response={"alfred_id": resp.alfred_id})
    await log_action(actor=user, action="client.offramp.create",
                     resource_type="offramp_order", resource_id=offramp_id,
                     metadata={"alfred_id": resp.alfred_id,
                                "usdc_amount": body.usdc_amount,
                                "target_currency": body.target_currency.upper()})
    return {"ok": True, "order": doc}


@router.get("/offramp/orders/{offramp_id}")
async def get_offramp(offramp_id: str,
                       user: CurrentUser = Depends(get_current_user)):
    order = await col(OFFRAMP_ORDERS).find_one(
        {"offramp_id": offramp_id, "org_id": user.org_id, "is_deleted": False},
        {"_id": 0})
    if not order:
        raise HTTPException(404, "Order not found")

    if order["status"] == "pending" and order.get("alfred_id"):
        try:
            st = await get_adapter().get_order_status(order["alfred_id"])
            if st.status != "pending":
                # Walk timeline
                timeline = order.get("timeline") or []
                for step in timeline:
                    step["done"] = True
                update = {
                    "status":   st.status,
                    "timeline": timeline,
                    "updated_at": _iso_now(),
                }
                if st.status == "completed":
                    update["fiat_received"] = st.settled_amount
                    update["settled_at"]    = _iso_now()
                    await _ensure_tx_for_offramp(order["org_id"], order, st)
                await col(OFFRAMP_ORDERS).update_one(
                    {"offramp_id": offramp_id}, {"$set": update})
                order.update(update)
        except AlfredError as e:
            logger.warning("offramp status refresh failed: %s", e)

    return {"order": order}


async def _ensure_tx_for_offramp(org_id: str, order: dict, st) -> None:
    existing = await col(TRANSACTIONS).find_one(
        {"prosper_tx_id": f"offramp::{order['offramp_id']}"})
    if existing:
        return
    await col(TRANSACTIONS).insert_one({
        "tx_id":         "tx_" + secrets.token_hex(6),
        "org_id":        org_id,
        "prosper_tx_id": f"offramp::{order['offramp_id']}",
        "type":          "offramp",
        "amount":        float(order.get("usdc_sent") or 0),
        "asset":         "USDC",
        "status":        "confirmed",
        "memo":          f"Alfred offramp {order['alfred_id']}",
        "metadata":      {"offramp_id": order["offramp_id"],
                          "alfred_id":  order["alfred_id"],
                          "coelsa_id":  st.coelsa_id,
                          "fiat_amount": st.settled_amount,
                          "target_currency": order.get("target_currency")},
        "created_at":    _iso_now(),
        "updated_at":    _iso_now(),
        "is_deleted":    False,
    })


# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------
@router.get("/transactions/history")
async def transactions_history(limit: int = Query(200, ge=1, le=500),
                                tx_type: Optional[str] = None,
                                status: Optional[str] = None,
                                user: CurrentUser = Depends(get_current_user)):
    q: dict[str, Any] = {"org_id": user.org_id, "is_deleted": False}
    if tx_type:
        q["type"] = tx_type
    if status:
        q["status"] = status
    rows = await col(TRANSACTIONS).find(q, {"_id": 0})\
        .sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# Alfred webhook (PUBLIC — HMAC verified)
# ---------------------------------------------------------------------------
@webhook_router.post("/alfred")
async def alfred_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("x-alfred-signature", "") or \
          request.headers.get("X-Alfred-Signature", "")
    if not verify_webhook(payload=raw, signature=sig):
        logger.warning("alfred webhook: invalid signature")
        raise HTTPException(401, "Invalid HMAC signature")

    try:
        evt = json.loads(raw.decode("utf-8") or "{}")
    except Exception as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    event_id = evt.get("event_id") or evt.get("id")
    if not event_id:
        raise HTTPException(400, "event_id missing")

    # Idempotency
    existing = await col(WEBHOOK_EVENTS).find_one(
        {"provider": "alfred", "event_id": event_id})
    if existing:
        return {"ok": True, "idempotent": True}

    await col(WEBHOOK_EVENTS).insert_one({
        "event_id":   event_id,
        "provider":   "alfred",
        "type":       evt.get("type"),
        "payload":    evt,
        "received_at": _iso_now(),
    })

    alfred_id = evt.get("order_id") or evt.get("alfred_id")
    typ = (evt.get("type") or "").lower()
    if alfred_id and typ in {"order.confirmed", "order.completed",
                              "order.failed", "order.pending"}:
        new_status = (
            "confirmed" if typ == "order.confirmed"
            else "completed" if typ == "order.completed"
            else "failed"    if typ == "order.failed"
            else "pending"
        )
        # update either onramp or offramp
        ramp_doc = await col(ONRAMP_ORDERS).find_one_and_update(
            {"alfred_id": alfred_id},
            {"$set": {"status": new_status, "updated_at": _iso_now(),
                       "coelsa_id": evt.get("coelsa_id"),
                       "usdc_received": evt.get("settled_amount")}},
            return_document=False)
        if not ramp_doc:
            await col(OFFRAMP_ORDERS).update_one(
                {"alfred_id": alfred_id},
                {"$set": {"status": new_status, "updated_at": _iso_now()}})

    await log_action(actor=None, action="alfred.webhook.received",
                     resource_type="webhook_event", resource_id=event_id,
                     metadata={"type": typ, "alfred_id": alfred_id})

    return {"ok": True, "event_id": event_id, "type": typ}


# ---------------------------------------------------------------------------
# Mock-checkout HTML (returned as `checkout_url` when ALFRED_MODE=mock)
# ---------------------------------------------------------------------------
@mock_router.get("/mock-checkout/{alfred_id}", response_class=HTMLResponse)
async def mock_checkout(alfred_id: str, request: Request):
    """Tiny self-contained HTML that emulates the Alfred hosted checkout.
    The user clicks 'Pagar' to settle, or 'Cancelar' to fail."""
    base = str(request.base_url).rstrip("/")
    html = f"""<!doctype html>
<html lang="es"><head>
  <meta charset="utf-8">
  <title>Alfred · Sandbox checkout</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{{font-family:system-ui,sans-serif;background:#0B0F19;color:#E2E8F0;
         display:grid;place-items:center;height:100vh;margin:0}}
    .card{{background:#111827;border:1px solid #1F2937;border-radius:12px;
           padding:32px;max-width:420px;width:90%}}
    h1{{margin:0 0 4px;font-size:18px}}
    .pill{{display:inline-block;background:#F59E0B22;color:#FBBF24;
           padding:2px 8px;border-radius:99px;font-size:10px;
           text-transform:uppercase;letter-spacing:.1em}}
    code{{background:#1F2937;padding:2px 6px;border-radius:4px;font-size:11px}}
    button{{display:block;width:100%;height:40px;border-radius:8px;
            border:0;margin-top:10px;cursor:pointer;font-weight:600}}
    .pay{{background:#22C55E;color:#fff}}
    .fail{{background:transparent;color:#EF4444;border:1px solid #EF444466}}
    p{{font-size:12px;line-height:1.5;color:#94A3B8}}
  </style>
</head>
<body>
  <div class="card">
    <span class="pill">Alfred · Mock checkout</span>
    <h1 style="margin-top:8px">Confirmar pago</h1>
    <p>Orden <code>{alfred_id}</code>. Esta pantalla simula el checkout
       de Alfred mientras esperamos credenciales reales.</p>
    <button class="pay"  onclick="settle('pay')">Confirmar pago</button>
    <button class="fail" onclick="settle('fail')">Cancelar pago</button>
    <p id="msg"></p>
  </div>
  <script>
    async function settle(kind){{
      const url = "{base}/api/v1/alfred/mock-settle/{alfred_id}?force_failure="+(kind==='fail'?'1':'0');
      const r = await fetch(url, {{method:'POST'}});
      const j = await r.json();
      document.getElementById('msg').textContent =
        (j.ok ? '✓ Status='+j.status+'. Podés cerrar esta ventana.' :
                '✗ '+(j.detail||'error'));
      if(j.ok){{ setTimeout(()=>window.close(), 1200); }}
    }}
  </script>
</body></html>"""
    return HTMLResponse(html)


@mock_router.post("/mock-settle/{alfred_id}")
async def mock_settle(alfred_id: str, force_failure: int = 0):
    """Called by mock-checkout page to settle the order + fire a self-webhook."""
    if current_mode() != "mock":
        raise HTTPException(404, "Mock endpoints only available in mock mode")
    try:
        order = settle_now(alfred_id, force_failure=bool(force_failure))
    except AlfredError as e:
        raise HTTPException(404, str(e))

    # Synthetic webhook event so the rest of the system reacts identically
    typ = ("order.failed" if force_failure
           else "order.confirmed" if order["direction"] == "onramp"
           else "order.completed")
    payload = {
        "event_id":  "evt_" + secrets.token_hex(6),
        "type":      typ,
        "order_id":  alfred_id,
        "alfred_id": alfred_id,
        "status":    order["status"],
        "settled_amount": order.get("expected_usdc") or order.get("expected_fiat"),
        "coelsa_id":      order.get("coelsa_id"),
    }
    body = json.dumps(payload).encode()
    secret = (
        __import__("os").environ.get("ALFRED_WEBHOOK_SECRET", "mock_secret_change_me")
        .encode()
    )
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()

    # Update DB directly (the synthetic webhook is also useful for clients
    # that hit our public endpoint, but here we apply the side-effect inline).
    new_status = ("failed" if force_failure
                  else "confirmed" if order["direction"] == "onramp"
                  else "completed")
    if order["direction"] == "onramp":
        ramp = await col(ONRAMP_ORDERS).find_one({"alfred_id": alfred_id})
        if ramp and ramp.get("status") == "pending":
            await col(ONRAMP_ORDERS).update_one(
                {"alfred_id": alfred_id},
                {"$set": {"status": new_status,
                           "usdc_received": payload["settled_amount"] if not force_failure else None,
                           "coelsa_id":     order.get("coelsa_id"),
                           "settled_at":    _iso_now() if not force_failure else None,
                           "updated_at":    _iso_now()}})
            if not force_failure:
                # Reuse the existing helper to mint the tx record.
                class _St:
                    settled_amount = payload["settled_amount"]
                    settled_currency = "USDC"
                    coelsa_id = order.get("coelsa_id")
                    tx_hash = order.get("tx_hash")
                await _ensure_tx_for_onramp(ramp["org_id"], ramp, _St())
    else:
        ramp = await col(OFFRAMP_ORDERS).find_one({"alfred_id": alfred_id})
        if ramp and ramp.get("status") == "pending":
            tl = ramp.get("timeline") or []
            for step in tl:
                step["done"] = not force_failure
            await col(OFFRAMP_ORDERS).update_one(
                {"alfred_id": alfred_id},
                {"$set": {"status": new_status, "timeline": tl,
                           "fiat_received": payload["settled_amount"] if not force_failure else None,
                           "settled_at":    _iso_now() if not force_failure else None,
                           "updated_at":    _iso_now()}})
            if not force_failure:
                class _St:
                    settled_amount = payload["settled_amount"]
                    settled_currency = ramp.get("target_currency")
                    coelsa_id = order.get("coelsa_id")
                await _ensure_tx_for_offramp(ramp["org_id"], ramp, _St())

    # Record the webhook event (idempotent-safe)
    await col(WEBHOOK_EVENTS).update_one(
        {"provider": "alfred", "event_id": payload["event_id"]},
        {"$setOnInsert": {**payload, "provider": "alfred",
                            "signature": sig, "received_at": _iso_now()}},
        upsert=True)

    return {"ok": True, "status": new_status, "type": typ, "event_id": payload["event_id"]}
