"""Sprint 12.6 — Alfred Hybrid KYB + KYC routes.

Public endpoints
================
POST  /onboarding/alfred/kyb/start
    Token-gated (uses the same JWT the wizard receives). Creates an Alfred
    KYB customer for the organization, persists ``alfred_customer_id`` on the
    org doc, and returns the iframe URL to embed.

POST  /onboarding/alfred/kyc/start
    Auth required. Creates an Alfred KYC customer for the current user and
    returns the iframe URL. Used by `/client/verify-identity`.

GET   /alfred/mock-kyc/{customer_id}
POST  /alfred/mock-kyc/{customer_id}/settle
    Mock-mode only — local HTML page that simulates Alfred's hosted widget.
    Pressing "Aprobar" fires a synthetic webhook so the rest of the flow
    behaves exactly like real Alfred.

GET   /onboarding/alfred/status?customer_id=...
    Lightweight poll endpoint for the wizard so it can advance once KYB is
    approved (the webhook updates the org; this endpoint just reads).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from audit import log_action
from auth import CurrentUser, get_current_user, JWT_SECRET, JWT_ALGORITHM
from db import col, ORGANIZATIONS, USERS
from integrations.alfred import AlfredError, current_mode
from integrations.alfred.kyc import (
    AlfredKycAdapter, current_kyc_mode, get_kyc_adapter,
)

logger = logging.getLogger("prosper.alfred.kyc.routes")

router = APIRouter(prefix="/onboarding/alfred", tags=["alfred-kyc"])
mock_router = APIRouter(prefix="/alfred", tags=["alfred-kyc-mock"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_base(req: Request) -> str:
    override = (os.environ.get("PUBLIC_BASE_URL") or "").strip()
    if override:
        return override.rstrip("/")
    proto = req.headers.get("x-forwarded-proto", req.url.scheme)
    host  = req.headers.get("x-forwarded-host",  req.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}"


def _decode_apply_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired apply token")
    if payload.get("purpose") != "kyb":
        raise HTTPException(400, "Token is not a KYB link")
    return payload


# ---------------------------------------------------------------------------
# KYB — public (token-gated)
# ---------------------------------------------------------------------------
class KybStartIn(BaseModel):
    token: str
    legal_name: Optional[str] = None
    primary_email: Optional[str] = None
    primary_phone: Optional[str] = None
    country: Optional[str] = None
    applicant: Optional[dict[str, Any]] = None  # {first_name, last_name, dob, ...}


class KycStartOut(BaseModel):
    customer_id: str
    iframe_url: str
    status: str
    mode: str


@router.post("/kyb/start", response_model=KycStartOut)
async def kyb_start(body: KybStartIn, request: Request):
    """Create an Alfred KYB customer for the organisation."""
    payload = _decode_apply_token(body.token)
    org_id = payload.get("org_id")
    if not org_id:
        raise HTTPException(400, "Token missing org_id")

    org = await col(ORGANIZATIONS).find_one({"org_id": org_id, "is_deleted": False},
                                              {"_id": 0})
    if not org:
        raise HTTPException(404, "Organization not found")

    # Already provisioned? Return the cached iframe URL.
    if org.get("alfred_customer_id") and org.get("alfred_kyb_iframe_url"):
        return KycStartOut(
            customer_id=org["alfred_customer_id"],
            iframe_url=org["alfred_kyb_iframe_url"],
            status=org.get("alfred_kyb_status") or "pending",
            mode=current_kyc_mode())

    base = _public_base(request)
    redirect_uri = f"{base}/apply/status?app_id={org_id}"

    business_data = {
        "legal_name":    body.legal_name or org.get("legal_name"),
        "country":       body.country or org.get("country") or "ARG",
        "tax_id":        org.get("tax_id"),
        "primary_email": body.primary_email or org.get("primary_email"),
        "primary_phone": body.primary_phone or org.get("primary_phone"),
        "primary_contact": body.applicant or {},
    }
    try:
        resp = await get_kyc_adapter().create_kyb_customer(
            org_id=org_id, business=business_data, redirect_uri=redirect_uri)
    except AlfredError as e:
        logger.exception("alfred KYB start failed")
        raise HTTPException(502, f"Alfred KYB failed: {e}")

    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {
            "alfred_customer_id":    resp.customer_id,
            "alfred_kyb_iframe_url": resp.iframe_url,
            "alfred_kyb_init_tx":    resp.init_transaction,
            "alfred_kyb_status":     resp.status,
            "alfred_kyb_mode":       resp.mode,
            "alfred_kyb_started_at": _iso_now(),
            "updated_at":            _iso_now(),
        }})

    await log_action(actor=None, action="alfred.kyb.started",
                     resource_type="organization", resource_id=org_id,
                     metadata={"alfred_customer_id": resp.customer_id,
                                "mode": resp.mode})
    return KycStartOut(customer_id=resp.customer_id, iframe_url=resp.iframe_url,
                        status=resp.status, mode=resp.mode)


# ---------------------------------------------------------------------------
# KYC — authenticated
# ---------------------------------------------------------------------------
class KycStartIn(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    dob: Optional[str] = None
    phone: Optional[str] = None
    nationality: Optional[str] = None
    doc_id: Optional[str] = None


@router.post("/kyc/start", response_model=KycStartOut)
async def kyc_start(body: KycStartIn, request: Request,
                     user: CurrentUser = Depends(get_current_user)):
    user_doc = await col(USERS).find_one({"user_id": user.user_id}, {"_id": 0})
    if not user_doc:
        raise HTTPException(404, "User not found")

    # Idempotent on the user side too
    if user_doc.get("alfred_customer_id") and user_doc.get("alfred_kyc_iframe_url"):
        return KycStartOut(
            customer_id=user_doc["alfred_customer_id"],
            iframe_url=user_doc["alfred_kyc_iframe_url"],
            status=user_doc.get("alfred_kyc_status") or "pending",
            mode=current_kyc_mode())

    base = _public_base(request)
    redirect_uri = f"{base}/client/verify-identity?status=complete"

    personal = {
        "first_name":  body.first_name or user_doc.get("first_name"),
        "last_name":   body.last_name  or user_doc.get("last_name"),
        "email":       user_doc.get("email"),
        "phone":       body.phone,
        "dob":         body.dob,
        "country":     body.nationality or "ARG",
        "doc_id":      body.doc_id,
    }
    try:
        resp = await get_kyc_adapter().create_kyc_customer(
            user_id=user.user_id, personal=personal, redirect_uri=redirect_uri)
    except AlfredError as e:
        logger.exception("alfred KYC start failed")
        raise HTTPException(502, f"Alfred KYC failed: {e}")

    await col(USERS).update_one(
        {"user_id": user.user_id},
        {"$set": {
            "alfred_customer_id":     resp.customer_id,
            "alfred_kyc_iframe_url":  resp.iframe_url,
            "alfred_kyc_init_tx":     resp.init_transaction,
            "alfred_kyc_status":      resp.status,
            "alfred_kyc_mode":        resp.mode,
            "alfred_kyc_started_at":  _iso_now(),
            "updated_at":             _iso_now(),
        }})

    await log_action(actor=user, action="alfred.kyc.started",
                     resource_type="user", resource_id=user.user_id,
                     metadata={"alfred_customer_id": resp.customer_id,
                                "mode": resp.mode})
    return KycStartOut(customer_id=resp.customer_id, iframe_url=resp.iframe_url,
                        status=resp.status, mode=resp.mode)


# ---------------------------------------------------------------------------
# Status — public (used by the wizard to poll until approved)
# ---------------------------------------------------------------------------
@router.get("/status")
async def kyb_status(customer_id: str = Query(..., min_length=4)):
    org = await col(ORGANIZATIONS).find_one(
        {"alfred_customer_id": customer_id},
        {"_id": 0, "org_id": 1, "alfred_kyb_status": 1, "kyb_status": 1})
    user_doc = None
    if not org:
        user_doc = await col(USERS).find_one(
            {"alfred_customer_id": customer_id},
            {"_id": 0, "user_id": 1, "alfred_kyc_status": 1, "kyc_status": 1})
        if not user_doc:
            raise HTTPException(404, "Unknown alfred_customer_id")

    # Best-effort: re-read live status from Alfred when in sandbox/production
    # mode so the wizard converges automatically as Alfred updates the customer.
    live_status: Optional[str] = None
    if current_kyc_mode() != "mock":
        try:
            live = await get_kyc_adapter().get_customer_status(customer_id)
            live_status = str(live.get("statusKyc") or "").lower() or None
        except AlfredError:
            live_status = None

    if live_status in ("approved", "pending", "rejected", "created"):
        # Persist + fire side effects when transitioning to approved/rejected
        normalised = "approved" if live_status == "approved" else (
            "rejected" if live_status == "rejected" else "pending")
        if org:
            await col(ORGANIZATIONS).update_one(
                {"alfred_customer_id": customer_id},
                {"$set": {"alfred_kyb_status": normalised,
                            "updated_at": _iso_now()}})
            if normalised == "approved" and org.get("kyb_status") != "approved":
                await col(ORGANIZATIONS).update_one(
                    {"alfred_customer_id": customer_id},
                    {"$set": {"kyb_status": "approved",
                                "kyb_decided_at": _iso_now()}})
                try:
                    from routes.onramp_flow import ensure_org_prosper_wallet
                    await ensure_org_prosper_wallet(org["org_id"])
                except Exception as e:  # noqa: BLE001
                    logger.exception("provisioning wallet on poll-approval: %s", e)
                # Phase 14 — best-effort Andes account auto-create
                try:
                    from routes.ramp_routes import ensure_org_ramp_account
                    org_full = await col(ORGANIZATIONS).find_one(
                        {"org_id": org["org_id"]},
                        {"_id": 0, "org_id": 1, "legal_name": 1,
                          "commercial_name": 1, "tax_id": 1})
                    if org_full:
                        await ensure_org_ramp_account(
                            org_id=org_full["org_id"],
                            end_customer_id=org_full["org_id"],
                            display_name=(org_full.get("commercial_name")
                                           or org_full.get("legal_name")),
                            holder_name=(org_full.get("legal_name")
                                          or org_full.get("commercial_name")),
                            holder_tax_id=org_full.get("tax_id"))
                except Exception as e:  # noqa: BLE001
                    logger.exception("Andes account auto-create on poll: %s", e)
        elif user_doc:
            await col(USERS).update_one(
                {"alfred_customer_id": customer_id},
                {"$set": {"alfred_kyc_status": normalised,
                            "kyc_status": normalised,
                            "updated_at": _iso_now()}})

    if org:
        # Re-read in case we just updated
        org = await col(ORGANIZATIONS).find_one(
            {"alfred_customer_id": customer_id},
            {"_id": 0, "org_id": 1, "alfred_kyb_status": 1, "kyb_status": 1})
        return {"kind": "kyb", "org_id": org["org_id"],
                 "alfred_status": org.get("alfred_kyb_status") or "pending",
                 "kyb_status": org.get("kyb_status") or "pending",
                 "live_status": live_status}
    user_doc = await col(USERS).find_one(
        {"alfred_customer_id": customer_id},
        {"_id": 0, "user_id": 1, "alfred_kyc_status": 1, "kyc_status": 1})
    return {"kind": "kyc", "user_id": user_doc["user_id"],
             "alfred_status": user_doc.get("alfred_kyc_status") or "pending",
             "kyc_status": user_doc.get("kyc_status") or "pending",
             "live_status": live_status}


# ---------------------------------------------------------------------------
# Real-KYC stub — shown when ALFRED_KYC_WIDGET_BASE isn't configured yet.
# Surfaces the customerId + raw status fields so partners can run a KYC review
# from Alfred's own dashboard while we finalise widget embedding.
# ---------------------------------------------------------------------------
@mock_router.get("/real-kyc-stub/{customer_id}", response_class=HTMLResponse)
async def real_kyc_stub(customer_id: str, redirect: str = ""):
    return HTMLResponse(f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Alfred KYC · {customer_id}</title>
  <style>
    body{{font-family:system-ui,sans-serif;background:#0B0F19;color:#E2E8F0;
         display:grid;place-items:center;min-height:100vh;margin:0;padding:32px}}
    .card{{background:#111827;border:1px solid #1F2937;border-radius:14px;
           padding:28px;max-width:560px;width:100%}}
    h1{{margin:0 0 8px;font-size:18px}}
    .pill{{display:inline-block;background:#2563FF22;color:#60A5FA;padding:3px 10px;
           border-radius:99px;font-size:10px;text-transform:uppercase;
           letter-spacing:.12em;font-weight:700}}
    code{{background:#1F2937;padding:2px 8px;border-radius:4px;font-size:11px}}
    p{{font-size:13px;line-height:1.6;color:#94A3B8}}
    a{{color:#60A5FA;text-decoration:none}}
    a:hover{{text-decoration:underline}}
  </style></head>
<body><div class="card">
  <span class="pill">Alfred · Real KYC sandbox</span>
  <h1>Customer creado correctamente</h1>
  <p>Tu Alfred customer ID:</p>
  <p><code>{customer_id}</code></p>
  <p>El compliance team de Alfred revisará y aprobará tu KYC dentro de las
  próximas horas. Te llegará un email cuando esté aprobado. Esta pantalla se
  actualiza automáticamente.</p>
  <p>Configurá <code>ALFRED_KYC_WIDGET_BASE</code> para embeber el widget oficial.</p>
  {('<p><a href="' + redirect + '">Volver al wizard</a></p>') if redirect else ''}
</div></body></html>""")


# ---------------------------------------------------------------------------
# Mock — local hosted-widget emulation
# ---------------------------------------------------------------------------
@mock_router.get("/mock-kyc/{customer_id}", response_class=HTMLResponse)
async def mock_kyc_page(customer_id: str, request: Request,
                          kind: str = "kyb", redirect: str = ""):
    """Self-contained HTML that emulates Alfred's hosted KYC iframe.

    Clicking Approve fires a webhook so the rest of the system reacts as if
    real Alfred had signed off."""
    base = _public_base(request)
    title = "KYB · Verificación empresa" if kind == "kyb" else "KYC · Verificación identidad"
    label = "Empresa" if kind == "kyb" else "Persona"
    return HTMLResponse(f"""<!doctype html>
<html lang="es"><head>
  <meta charset="utf-8"><title>Alfred · {title}</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{{font-family:system-ui,sans-serif;background:#0B0F19;color:#E2E8F0;
         display:grid;place-items:center;min-height:100vh;margin:0;padding:24px}}
    .card{{background:#111827;border:1px solid #1F2937;border-radius:14px;
           padding:28px;max-width:460px;width:100%}}
    h1{{margin:0 0 6px;font-size:18px}}
    .pill{{display:inline-block;background:#F59E0B22;color:#FBBF24;
           padding:2px 10px;border-radius:99px;font-size:10px;
           text-transform:uppercase;letter-spacing:.12em}}
    code{{background:#1F2937;padding:2px 6px;border-radius:4px;font-size:11px}}
    button{{display:block;width:100%;height:42px;border-radius:8px;
            border:0;margin-top:10px;cursor:pointer;font-weight:600}}
    .ok{{background:#22C55E;color:#fff}}
    .no{{background:transparent;color:#EF4444;border:1px solid #EF444466}}
    p{{font-size:12px;line-height:1.55;color:#94A3B8}}
    ul{{font-size:12px;color:#94A3B8;padding-left:18px}}
  </style></head>
<body>
  <div class="card">
    <span class="pill">Alfred · Mock {kind.upper()}</span>
    <h1 style="margin-top:8px">{title}</h1>
    <p>{label}: <code>{customer_id}</code>. Esta pantalla simula el widget
       hosteado de Alfred mientras finalizamos el contrato productivo.</p>
    <ul>
      <li>Documento de identidad capturado</li>
      <li>Selfie + liveness check OK</li>
      <li>Address proof revisado</li>
    </ul>
    <button class="ok" onclick="settle('approve')" data-testid="alfred-mock-approve">Aprobar</button>
    <button class="no" onclick="settle('reject')"  data-testid="alfred-mock-reject">Rechazar</button>
    <p id="msg" data-testid="alfred-mock-msg"></p>
  </div>
  <script>
    async function settle(kind){{
      const url = "{base}/api/v1/alfred/mock-kyc/{customer_id}/settle?decision="+kind;
      const r = await fetch(url, {{method:'POST'}});
      const j = await r.json();
      document.getElementById('msg').textContent =
        (j.ok ? '✓ '+(j.status||'ok')+'. Podés cerrar esta ventana.' :
                '✗ '+(j.detail||'error'));
      try {{ window.parent && window.parent.postMessage(
              {{type:'alfred:kyc:'+kind, customer_id:'{customer_id}'}}, '*'); }} catch(_) {{}}
      if(j.ok && "{redirect}") setTimeout(()=> location.href = "{redirect}", 1500);
    }}
  </script>
</body></html>""")


@mock_router.post("/mock-kyc/{customer_id}/settle")
async def mock_kyc_settle(customer_id: str, request: Request,
                            decision: str = Query("approve")):
    if current_mode() != "mock" and current_kyc_mode() != "mock":
        raise HTTPException(404, "Mock endpoints only available in mock mode")

    # Figure out if this customer maps to an org (KYB) or user (KYC)
    org = await col(ORGANIZATIONS).find_one(
        {"alfred_customer_id": customer_id}, {"_id": 0, "org_id": 1})
    user = None
    if not org:
        user = await col(USERS).find_one(
            {"alfred_customer_id": customer_id}, {"_id": 0, "user_id": 1})
    if not org and not user:
        raise HTTPException(404, "Unknown alfred_customer_id")

    approved = decision.lower() == "approve"
    kind = "kyb" if org else "kyc"
    evt_type = (f"customer.{kind}.approved" if approved
                  else f"customer.{kind}.rejected")
    payload = {
        "event_id":  "evt_" + secrets.token_hex(6),
        "type":      evt_type,
        "customerId": customer_id,
        "alfred_id":  customer_id,
        "status":     "approved" if approved else "rejected",
    }
    body = json.dumps(payload).encode()
    secret = os.environ.get("ALFRED_WEBHOOK_SECRET", "mock_secret_change_me").encode()
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()

    # Fire the webhook synchronously through the existing handler
    from routes.client_alfred import alfred_webhook
    from fastapi import Request as FRequest

    async def _receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    fake_scope = {
        "type": "http", "method": "POST",
        "path": "/api/v1/webhooks/alfred",
        "headers": [(b"x-alfred-signature", sig.encode()),
                     (b"content-type", b"application/json")],
        "query_string": b"",
    }
    fake_req = FRequest(fake_scope, _receive)
    try:
        result = await alfred_webhook(fake_req)
    except HTTPException as e:
        return {"ok": False, "detail": e.detail}

    return {"ok": True, "status": "approved" if approved else "rejected",
             "event": evt_type, "webhook": result}
