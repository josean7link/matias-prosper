"""Phase 3 — Onboarding (public /apply + KYC initiation for client users).

Public endpoints (no auth):
  POST /onboarding/apply             — submit business OR individual application
                                          (toggle via `applicant_type`)
  POST /onboarding/apply/simulate    — DEV: simulate AiPrise completion
  GET  /onboarding/apply/{app_id}    — poll status (returns sanitized view)

Authenticated endpoints (client_user / client_admin):
  POST /onboarding/me/kyc            — start a KYC verification for current user

ALTA DE INDIVIDUO (Phase 22+):
  - `applicant_type='individual'` skips UBOs and runs AiPrise KYC instead
    of KYB.
  - In BOTH paths we ALWAYS create the contact's User row up front with
    role=`client_admin` so the contact can log in immediately and operate
    its own ramp account post-approval.
  - The response embeds a `magic_link` (passwordless dev-login URL) so the
    end-to-end alta works without Resend in mock. Resend send-out is a
    TODO for real production wiring.
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from audit import log_action
from auth import CurrentUser, get_current_user
from db import (
    col, ORGANIZATIONS, ONBOARDING_APPLICATIONS, USERS, WEBHOOK_EVENTS,
)
from integrations import aiprise
from models import Organization, new_id, utc_now
from roles import Role

logger = logging.getLogger("prosper.onboarding")
router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class UBOIn(BaseModel):
    full_name: str
    ownership_pct: float = Field(..., ge=0, le=100)
    role: Optional[str] = None
    country: Optional[str] = None


class ApplicationIn(BaseModel):
    # Phase 22+ — toggle individuo (persona física) vs empresa.
    # When 'individual', UBOs are skipped, AiPrise is NOT called, and the
    # KYC happens via Andes `fiat.create` (orden b — see addendum 05).
    applicant_type: str = Field("business", pattern="^(business|individual)$")

    legal_name: str
    commercial_name: Optional[str] = None
    country: str
    jurisdiction: str
    incorporation_date: Optional[str] = None
    registration_number: Optional[str] = None
    contact_name: str
    contact_email: EmailStr
    contact_phone: Optional[str] = None
    website: Optional[str] = None
    expected_monthly_volume_usd: Optional[float] = None
    use_case: Optional[str] = None
    ubos: List[UBOIn] = []
    # Phase 22+ — Andes-required fields for INDIVIDUAL alta (AR).
    # Captured here so /onboarding/apply for `applicant_type='individual'`
    # has all the data `fiat.create` will need at the docs-upload step.
    last_name:   Optional[str] = None
    cuit:        Optional[str] = Field(None, pattern=r"^\d{11}$")
    birthdate:   Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    phone:       Optional[str] = Field(None, pattern=r"^\+\d{8,15}$")
    chain:       str = Field("stellar", pattern="^(stellar|base)$")


class ApplicationOut(BaseModel):
    application_id: str
    org_id: str
    user_id: Optional[str] = None        # contact user (always created)
    status: str
    kyb_status: str
    kyc_status: Optional[str] = None     # only set for applicant_type='individual'
    applicant_type: str = "business"
    hosted_url: Optional[str] = None
    mode: str  # "live" or "simulated"
    magic_link: Optional[str] = None     # MOCK ONLY — returned so the user can
                                            # log in without waiting for Resend.
                                            # TODO(real): remove from response,
                                            # send only by email.


def _public_base_url(req: Request) -> str:
    """Resolve the public origin even when running behind a reverse proxy.

    The K8s ingress sets X-Forwarded-Host + X-Forwarded-Proto with the public
    hostname; req.url.netloc by itself would return the internal upstream
    cluster host, which would break webhook callbacks AND the redirect URLs
    we embed in the AiPrise hosted page.
    """
    override = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    proto = req.headers.get("x-forwarded-proto", req.url.scheme)
    host  = req.headers.get("x-forwarded-host",  req.url.netloc)
    # `x-forwarded-host` can be a comma-separated list — keep the first hop
    host = host.split(",")[0].strip()
    return f"{proto}://{host}"


# ---------------------------------------------------------------------------
# POST /onboarding/apply
# ---------------------------------------------------------------------------
@router.post("/apply", response_model=ApplicationOut)
async def submit_application(body: ApplicationIn, request: Request):
    """Public — submit a new onboarding application.

    Only `applicant_type='individual'` is served. Corporate onboarding
    (`applicant_type='business'`) is handled by the KYB module via
    invitation; the endpoint returns 410 Gone with a message aligned
    with the public /apply form notice.
    """
    is_individual = body.applicant_type == "individual"
    if not is_individual:
        raise HTTPException(
            status_code=410,
            detail=("El alta de empresas se realiza por invitación. "
                    "Escribí a support@prosper.foundation para recibir "
                    "el enlace y comenzar el proceso."))
    org_id = new_id("org")
    app_id = new_id("app")
    user_id = new_id("usr")

    # 1. Create organization in pending state
    org = Organization(
        org_id=org_id,
        legal_name=body.legal_name,
        commercial_name=body.commercial_name or body.legal_name,
        country=body.country,
        type="personal" if is_individual else "fintech",
        kyb_status="pending",
        allowlist_domains=[body.contact_email.split("@", 1)[-1]],
    )
    org_doc = org.model_dump()
    # Phase 23 — explicit hierarchy fields; new orgs are N1 by default.
    org_doc["parent_org_id"] = None
    org_doc["level"]         = 1
    # Sanctions/PEP gate — every new org starts pending. Cleared by the
    # admin sanctions queue (manual provider) or by a real screening API
    # adapter; see integrations/sanctions/.
    org_doc["sanctions_status"] = "pending"
    if is_individual:
        # Stored on the org so the sanctions screening can be enqueued
        # later (after Andes confirms identity) without a join.
        org_doc["_indiv_cuit"]      = body.cuit
        org_doc["_indiv_birthdate"] = body.birthdate
    await col(ORGANIZATIONS).insert_one(dict(org_doc))

    # 2. Create the contact User with role=client_admin so they can log
    #    in immediately + operate their own ramp account post-approval.
    #    Idempotent on email (upsert): re-applying with the same email
    #    re-targets the user to the new org.
    user_doc = {
        "user_id":      user_id,
        "email":        body.contact_email,
        "full_name":    body.contact_name,
        "role":         "client_admin",
        "org_id":       org_id,
        "status":       "invited",
        "kyc_status":   "pending",
        "mfa_enabled":  False,
        "is_deleted":   False,
        "created_at":   utc_now(),
        "updated_at":   utc_now(),
    }
    existing = await col(USERS).find_one({"email": body.contact_email},
                                            {"_id": 0, "user_id": 1})
    if existing:
        user_id = existing["user_id"]
        await col(USERS).update_one({"user_id": user_id},
            {"$set": {"role": "client_admin", "org_id": org_id,
                        "full_name": body.contact_name,
                        "status": "invited", "updated_at": utc_now()}})
    else:
        await col(USERS).insert_one(dict(user_doc))

    # 3. Persist the application
    app_doc = {
        "application_id": app_id,
        "org_id": org_id,
        "user_id": user_id,
        "applicant_type": body.applicant_type,
        "legal_name": body.legal_name,
        "commercial_name": body.commercial_name,
        "country": body.country,
        "jurisdiction": body.jurisdiction,
        "incorporation_date": body.incorporation_date,
        "registration_number": body.registration_number,
        "contact_name": body.contact_name,
        "contact_email": body.contact_email,
        "contact_phone": body.contact_phone,
        "website": body.website,
        "expected_monthly_volume_usd": body.expected_monthly_volume_usd,
        "use_case": body.use_case,
        "ubos": [] if is_individual else [u.model_dump() for u in body.ubos],
        # Phase 22+ — Andes-required individual fields (chain default stellar)
        "individual": {
            "last_name": body.last_name,
            "cuit":      body.cuit,
            "birthdate": body.birthdate,
            "phone":     body.phone or body.contact_phone,
            "chain":     body.chain,
        } if is_individual else None,
        "status": "in_review",
        "kyb_status": "pending",
        "kyc_status": "pending" if is_individual else None,
        "aiprise_session_id": None,
        "aiprise_mode": None,
        "decision": None,
        "decision_at": None,
        "submitted_at": utc_now(),
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "is_deleted": False,
    }
    await col(ONBOARDING_APPLICATIONS).insert_one(dict(app_doc))

    # 4. KYC/KYB provider call
    #
    # **Phase 22+ — orden (b) Andes-only para individuos AR**:
    # Para `applicant_type='individual'` NO disparamos AiPrise. El KYC se
    # resuelve cuando el cliente sube las 3 fotos (DNI + selfie) al endpoint
    # `POST /onboarding/{app_id}/kyc-docs` y Andes valida vía `fiat.create`.
    # El gate de aprobación es el webhook `fiat.account.created`.
    base = _public_base_url(request)
    redirect = f"{base}/apply/status?app_id={app_id}"
    if is_individual:
        ai = {"verification_session_id": f"andes_kyc_{user_id}",
              "hosted_url": f"{base}/apply/{app_id}/kyc-docs",
              "mode": "andes-direct"}
    else:
        callback = f"{base}/api/v1/webhooks/aiprise/kyb"
        try:
            ai = await aiprise.create_business_verification(
                client_reference_id=app_id,
                business_data={
                    "legal_name": body.legal_name,
                    "country": body.country,
                    "jurisdiction": body.jurisdiction,
                    "incorporation_date": body.incorporation_date,
                    "registration_number": body.registration_number,
                    "ubo_names": [u.full_name for u in body.ubos],
                },
                callback_url=callback,
                redirect_uri=redirect,
            )
        except aiprise.ProviderMisconfigured as e:
            # Fail-safe en producción: template_id / api_key ausentes o
            # modo simulator forzado en prod. Ver aiprise.is_simulated_async.
            logger.error("AiPrise misconfigured in production: %s", e)
            raise HTTPException(503, "KYB verification provider not "
                                     "available. Please retry later.")
        except aiprise.AipriseError as e:
            logger.exception("AiPrise verification creation failed")
            raise HTTPException(502, f"KYB provider error: {e.body}")

    await col(ONBOARDING_APPLICATIONS).update_one(
        {"application_id": app_id},
        {"$set": {
            "aiprise_session_id": ai["verification_session_id"],
            "aiprise_mode": ai.get("mode"),
            "hosted_url": ai["hosted_url"],
            "updated_at": utc_now(),
        }},
    )

    # 5. Magic-link de primera-vez.
    # En modo dev (RESEND_API_KEY vacío) lo devolvemos en el JSON para que el
    # equipo pueda saltar al portal sin esperar email. En modo real, lo
    # mandamos por email vía Resend (con fallback a outbound_emails si Resend
    # falla) y NO lo exponemos en la respuesta.
    magic_link = (f"{base}/api/v1/auth/dev-login"
                   f"?email={body.contact_email}&next=/client")
    resend_live = bool(os.environ.get("RESEND_API_KEY"))
    # Opción C: en producción, nunca devolvemos el magic-link en el body,
    # sin importar RESEND. Si el operador olvidó RESEND_API_KEY en prod,
    # eso no debe habilitar un login sin contraseña por respuesta HTTP.
    from kyb.verification_modes import kyb_environment
    force_hide_magic = kyb_environment() == "production"
    if resend_live:
        try:
            from integrations.email_sender import _shell, send_email
            html_body = f"""
              <h1>¡Bienvenido a Prosper!</h1>
              <p>Recibimos tu solicitud para abrir cuenta como
                 <strong>{body.contact_name}</strong>.</p>
              <p>Mientras verificamos tu identidad podés guardar este link
                 para acceder al portal cuando esté lista tu cuenta:</p>
              <p><a class="btn" href="{base}/login">Ingresar al portal</a></p>
              <p style="font-size:12px;color:#6B7280">
                Vamos a mandarte otro email apenas tu cuenta esté activa.
                Si no esperabas este mail, ignoralo.</p>"""
            await send_email(
                to=body.contact_email,
                subject="Tu cuenta Prosper está en revisión",
                html=_shell(html_body),
                template="onboarding_welcome",
                org_id=org_id,
                context={"applicant_type": body.applicant_type})
        except Exception as e:
            logger.exception("welcome email send failed (non-fatal): %s", e)
        # Don't leak the dev magic-link in production
        magic_link_for_resp = None
    else:
        magic_link_for_resp = None if force_hide_magic else magic_link

    # 6. Audit
    await log_action(actor=None, action="application.submitted",
                     resource_type="onboarding_application",
                     resource_id=app_id, org_id_override=org_id,
                     metadata={"contact_email": body.contact_email,
                                "applicant_type": body.applicant_type,
                                "mode": ai.get("mode")})

    return ApplicationOut(
        application_id=app_id,
        org_id=org_id,
        user_id=user_id,
        status="in_review",
        kyb_status="pending",
        kyc_status="in_review" if is_individual else None,
        applicant_type=body.applicant_type,
        hosted_url=ai["hosted_url"],
        mode=ai.get("mode", "live"),
        magic_link=magic_link_for_resp,
    )


# ---------------------------------------------------------------------------
# GET /onboarding/apply/{app_id} — public read-back (sanitized)
# ---------------------------------------------------------------------------
@router.get("/apply/{app_id}")
async def get_application(app_id: str):
    app_doc = await col(ONBOARDING_APPLICATIONS).find_one(
        {"application_id": app_id, "is_deleted": False}, {"_id": 0})
    if not app_doc:
        raise HTTPException(404, "Application not found")
    # Surface the org's gates so the public polling page can show the
    # correct stage (Andes → sanctions → activación).
    org_doc = await col(ORGANIZATIONS).find_one(
        {"org_id": app_doc["org_id"]},
        {"_id": 0, "sanctions_status": 1, "kyb_status": 1}) or {}
    # Effective status that the UI should react to. As long as the org
    # isn't fully activated (`kyb_status=approved`) we keep the application
    # surface as `in_review` even if Andes already said OK — sanctions or
    # other gates may still be pending.
    effective_status = app_doc["status"]
    if effective_status == "approved" and org_doc.get("kyb_status") != "approved":
        effective_status = "in_review"
    return {
        "application_id":   app_doc["application_id"],
        "org_id":           app_doc["org_id"],
        "legal_name":       app_doc["legal_name"],
        "status":           effective_status,
        "kyb_status":       org_doc.get("kyb_status", app_doc["kyb_status"]),
        "sanctions_status": org_doc.get("sanctions_status", "pending"),
        "decision":         app_doc.get("decision"),
        "submitted_at":     app_doc["submitted_at"],
        "hosted_url":       app_doc.get("hosted_url"),
        "aiprise_mode":     app_doc.get("aiprise_mode"),
        "andes_onboarding_status": app_doc.get("andes_onboarding_status"),
    }


# ---------------------------------------------------------------------------
# POST /onboarding/apply/simulate — RETIRADO en la Fase 1 del retiro de
# AiPrise. La ruta ya no está montada en el router: FastAPI devuelve
# 404 Not Found opaco a cualquier request. Motivación: el simulator
# reusaba `_apply_kyb_decision` que fue neutralizado (log-and-drop) y
# el frontend legacy que lo consumía (`app/apply/simulate/page.tsx`)
# también fue retirado.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# POST /onboarding/me/kyc — start a KYC for the current logged-in user
# ---------------------------------------------------------------------------
class KycStartOut(BaseModel):
    user_id: str
    kyc_status: str
    hosted_url: Optional[str]
    mode: str


@router.post("/me/kyc", response_model=KycStartOut)
async def start_my_kyc(request: Request, user: CurrentUser = Depends(get_current_user)):
    """Retired — la verificación de identidad individual se resuelve por
    el path Andes (`POST /onboarding/{app_id}/kyc-docs` y el widget en
    `/client/kyc-docs`). Cerrado con 410 Gone; ningún flujo real
    dependía de esta ruta."""
    raise HTTPException(
        status_code=410,
        detail=("La verificación de identidad se realiza subiendo "
                "documentación desde tu cuenta. Ingresá a "
                "/client/kyc-docs para continuar."))


# ---------------------------------------------------------------------------
# Phase 22+ — INDIVIDUO AR: subida de docs de KYC (orden b)
#
# El cliente captura 3 fotos (selfie + DNI front/back) en el portal y las
# manda acá. Guardamos una copia local en /app/backend/var/kyc_docs/ para
# audit (Andes no permite descargarlas después), y disparamos el orden
# Andes:
#     accounts.create → wallets.create(stellar, arsa) → fiat.create(body, files)
# El resultado `onboarding_status` es directo (approved/pending/rejected).
# El webhook `fiat.account.created` activará `client_admin` cuando llegue.
# ---------------------------------------------------------------------------
from fastapi import UploadFile, File, Form
import httpx
import pathlib

KYC_DOCS_DIR = pathlib.Path(os.environ.get("KYC_DOCS_DIR", str(pathlib.Path(__file__).resolve().parent.parent / "var" / "kyc_docs")))
try:
    KYC_DOCS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


@router.post("/{app_id}/kyc-docs")
async def upload_kyc_docs_individual(
    app_id: str, request: Request,
    face:     UploadFile = File(...),
    id_front: UploadFile = File(...),
    id_back:  UploadFile = File(...),
):
    """Public — un individuo sube sus 3 fotos para que Andes haga el KYC.

    Reutiliza el `application_id` devuelto por `POST /onboarding/apply`. No
    requiere auth de usuario (el `app_id` actúa como el handle de sesión).

    Orden:
        1. Validar app_doc (existe, applicant_type=individual, no consumido).
        2. Guardar copia local de los 3 archivos.
        3. Llamar gateway `POST /accounts` → Andes user_id.
        4. Llamar gateway `POST /wallets/<chain>` → wallet ARSa.
        5. Llamar gateway `POST /fiat` (multipart) con body + 3 archivos.
        6. Persistir estado + responder onboarding_status al cliente.
    """
    app_doc = await col(ONBOARDING_APPLICATIONS).find_one(
        {"application_id": app_id}, {"_id": 0})
    if not app_doc:
        raise HTTPException(404, "application not found")
    if app_doc.get("applicant_type") != "individual":
        raise HTTPException(400, "kyc-docs upload solo aplica para applicant_type=individual")
    if app_doc.get("kyc_docs_uploaded_at"):
        raise HTTPException(409, "documentos ya enviados; consultá /apply/status")

    indiv = app_doc.get("individual") or {}
    missing = [k for k in ("last_name", "cuit", "birthdate", "phone")
                  if not indiv.get(k)]
    if missing:
        raise HTTPException(400,
            f"campos individuales faltantes en la application: {missing}")

    # 2. Guardar copia local audit
    audit_dir = KYC_DOCS_DIR / app_id
    audit_dir.mkdir(parents=True, exist_ok=True)
    files_data = {}
    for fname, upload in (("face", face), ("id_front", id_front),
                            ("id_back", id_back)):
        buf = await upload.read()
        if len(buf) < 1024:
            raise HTTPException(400, f"{fname} muy chico (<1KB) — revisar captura")
        ext = (upload.filename or "").split(".")[-1].lower() or "jpg"
        (audit_dir / f"{fname}.{ext}").write_bytes(buf)
        files_data[fname] = (upload.filename or f"{fname}.{ext}",
                                buf,
                                upload.content_type or "image/jpeg")

    await log_action(actor=None, action="kyc.docs.uploaded_local",
                       resource_type="onboarding_application",
                       resource_id=app_id, org_id_override=app_doc["org_id"],
                       metadata={"bytes_total": sum(len(b) for b,_,_ in files_data.values())})

    # 3. Llamar gateway encadenado
    gw_url = os.environ.get("ANDES_GATEWAY_URL", "http://localhost:8090")
    gw_tok = os.environ.get("GATEWAY_INTERNAL_TOKEN", "")
    headers = {"X-Internal-Token": gw_tok}

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=15.0, read=120.0, write=60.0, pool=30.0)) as cx:
        # 3a. accounts.create — idempotent. Reuse existing andes_user_id if
        # a previous partial upload already created it.
        andes_user_id = app_doc.get("andes_user_id")
        if not andes_user_id:
            unique_name = (f"{app_doc['contact_name']} "
                              f"{indiv['last_name']} [{app_id[-6:]}]")
            r = await cx.post(f"{gw_url}/accounts",
                                json={"name": unique_name},
                                headers=headers)
            if r.status_code >= 400:
                raise HTTPException(502, f"andes accounts.create: {r.text[:200]}")
            andes_user_id = r.json().get("userId")
            await col(ONBOARDING_APPLICATIONS).update_one(
                {"application_id": app_id},
                {"$set": {"andes_user_id": andes_user_id,
                            "updated_at": utc_now()}})

        # 3b. wallets.create — idempotent. On 409 (already exists) we GET
        # the existing wallet and continue. Andes will not let us create
        # the same (user, chain, asset) twice.
        chain = indiv.get("chain", "stellar")
        r = await cx.post(f"{gw_url}/wallets",
                            json={"user_id": andes_user_id,
                                    "chain":   chain,
                                    "asset":   "arsa"},
                            headers=headers)
        if r.status_code == 409 or (
                r.status_code >= 400 and "already exists" in r.text.lower()):
            rl = await cx.get(f"{gw_url}/wallets/{andes_user_id}",
                                headers=headers)
            if rl.status_code >= 400:
                raise HTTPException(502,
                    f"andes wallets.list (resume): {rl.text[:200]}")
            payload = rl.json()
            items = payload.get("items") if isinstance(payload, dict) else payload
            wallet = next((w for w in (items or [])
                              if (w.get("chain") or "").lower() == chain
                              and (w.get("asset") or "").lower() == "arsa"),
                             {"address": None})
        elif r.status_code >= 400:
            raise HTTPException(502, f"andes wallets.create: {r.text[:200]}")
        else:
            wallet = r.json()

        # 3c. fiat.create — multipart con los 3 archivos.
        # httpx: campos string vía `data=`, archivos vía `files=`.
        form_data = {
            "user_id":   andes_user_id,
            "chain":     chain,
            "email":     app_doc["contact_email"],
            "cuit":      indiv["cuit"],
            "name":      app_doc["contact_name"],
            "last_name": indiv["last_name"],
            "phone":     indiv["phone"],
            "birthdate": indiv["birthdate"],
        }
        files_multipart = {
            "face":      files_data["face"],
            "id_front":  files_data["id_front"],
            "id_back":   files_data["id_back"],
        }
        r = await cx.post(f"{gw_url}/fiat",
                            data=form_data, files=files_multipart,
                            headers=headers)
        if r.status_code >= 400:
            # Andes typically rejects bad photos with a 4xx/5xx. Surface a
            # customer-friendly message so the frontend can offer a "retry
            # with better lighting" UX instead of a generic 502.
            body_lc = r.text.lower()
            if any(t in body_lc for t in (
                "unsupported image", "image type", "no nítida",
                "nítidez", "blurry", "low quality", "image quality")):
                raise HTTPException(422,
                    "Las fotos no pasaron el control de calidad. "
                    "Probá de nuevo con más luz y los 4 bordes del DNI visibles.")
            raise HTTPException(502, f"andes fiat.create: {r.text[:200]}")
        fiat_resp = r.json()

    onb = fiat_resp.get("onboarding_status") or fiat_resp.get("onboardingStatus")

    # 4. Persistir: ramp_account + ramp_wallet + ramp_fiat_account
    from db import RAMP_ACCOUNTS, RAMP_WALLETS, RAMP_FIAT_ACCOUNTS
    iso = utc_now()
    ramp_acc_id = "racc_" + secrets.token_hex(6)
    await col(RAMP_ACCOUNTS).insert_one({
        "id": ramp_acc_id, "org_id": app_doc["org_id"],
        "end_customer_id": app_doc["org_id"],
        "provider": "andeslabs", "provider_user_id": andes_user_id,
        "account_name": app_doc["contact_name"],
        "wallet_chain": chain, "wallet_address": wallet.get("address"),
        "wallet_status": "active",
        "cvu": fiat_resp.get("cvu"),
        "alias": fiat_resp.get("alias"),
        "cvu_status": "completed" if fiat_resp.get("cvu") else "pending",
        "onboarding_status": onb or "pending_approval",
        "onboarding_message": None,
        "created_at": iso, "updated_at": iso, "is_deleted": False,
    })
    await col(RAMP_WALLETS).insert_one({
        "id": "rw_" + secrets.token_hex(6),
        "org_id": app_doc["org_id"], "ramp_account_id": ramp_acc_id,
        "provider_user_id": andes_user_id,
        "asset": "arsa", "chain": chain,
        "address": wallet.get("address"), "status": "active",
        "created_at": iso, "updated_at": iso, "is_deleted": False,
    })
    if fiat_resp.get("fiat_account_id"):
        await col(RAMP_FIAT_ACCOUNTS).insert_one({
            "id": "rfa_" + secrets.token_hex(6),
            "org_id": app_doc["org_id"], "ramp_account_id": ramp_acc_id,
            "fiat_account_id": fiat_resp["fiat_account_id"],
            "cvu": fiat_resp.get("cvu"), "alias": fiat_resp.get("alias"),
            "account_type": "user",
            "onboarding_status": onb or "pending_approval",
            "status": "pending" if (onb or "").startswith("pending") else "active",
            "created_at": iso, "updated_at": iso, "is_deleted": False,
        })

    # 5. Si Andes devolvió `approved` synchrónicamente (sandbox), activamos
    # la GATE 1 (identidad) y delegamos al helper de activación. El helper
    # encolará el screening de sanctions (gate 2) y, solo si ese gate ya
    # está clear, promoverá la org a kyb_status=approved. Si quedó pending
    # o flagged, el cliente espera. NUNCA tocamos kyb_status directamente
    # acá — la consistencia de los dos gates vive en `on_identity_approved`.
    activation_state: dict = {}
    if onb in ("approved", "completed"):
        from services.activation import on_identity_approved
        activation_state = await on_identity_approved(
            org_id=app_doc["org_id"],
            andes_user_id=andes_user_id,
            cvu=fiat_resp.get("cvu"),
            alias=fiat_resp.get("alias"),
            fiat_account_id=fiat_resp.get("fiat_account_id"),
            source="kyc_docs_upload",
        )

    await col(ONBOARDING_APPLICATIONS).update_one(
        {"application_id": app_id},
        {"$set": {
            "kyc_docs_uploaded_at": utc_now(),
            "andes_user_id": andes_user_id,
            "andes_onboarding_status": onb,
            # `status` y `kyb_status` reflejan la realidad de los DOS gates.
            # Si Andes aprobó identidad pero sanctions sigue pending, la app
            # queda en `in_review` con `kyb_status=pending`. La activación
            # full (kyb_status=approved) la decide on_identity_approved.
            "status":     "approved" if activation_state.get("activated") else "in_review",
            "kyb_status": "approved" if activation_state.get("activated") else "pending",
            "updated_at": utc_now(),
        }})

    await log_action(actor=None, action="kyc.docs.sent_to_andes",
                       resource_type="onboarding_application",
                       resource_id=app_id, org_id_override=app_doc["org_id"],
                       metadata={"andes_user_id": andes_user_id,
                                  "onboarding_status": onb,
                                  "cvu_emitted": bool(fiat_resp.get("cvu")),
                                  "activated_full": activation_state.get("activated", False),
                                  "sanctions_status": activation_state.get("sanctions_status")})

    return {
        "ok": True,
        "andes_user_id":      andes_user_id,
        "onboarding_status":  onb,
        "cvu":                fiat_resp.get("cvu"),
        "alias":              fiat_resp.get("alias"),
        "kyb_status":         activation_state.get("kyb_status") or "pending",
        "andes_kyc_status":   activation_state.get("andes_kyc_status") or (
                                  "approved" if onb in ("approved", "completed")
                                  else "pending"),
        "sanctions_status":   activation_state.get("sanctions_status") or "pending",
        # `next` ya no es "portal" si solo Andes aprobó. El frontend reacciona
        # a sanctions_status=pending mostrando la pantalla "Verificando
        # antecedentes". "portal" solo cuando ambos gates están verdes.
        "next":               ("portal" if activation_state.get("activated")
                                  else "wait_sanctions" if onb in ("approved", "completed")
                                  else "wait_webhook"),
    }
