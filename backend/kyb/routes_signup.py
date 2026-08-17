"""Fase 2 — Alta pre-autenticada de organizaciones + activación por
magic link. Prefijo /api/v1/kyb, SIN autenticación.

Todo este router se registra solo con KYB_MODULE_ENABLED=true (gate en
server.py). Anti-enumeración: /signup/start y /signup/resend devuelven
SIEMPRE 200 con el mismo cuerpo, exista o no el email, con retardo
compensatorio para igualar tiempos. Los sondeos (email con org/caso
aprobado o rechazado, o email ya registrado) NO envían correo y quedan
registrados en auditoría para detectar patrones.
"""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from auth import mint_session_token
from db import col, ORGANIZATIONS, USERS
from models import new_id, utc_now
from roles import Role
from kyb.audit import kyb_audit, client_ip
from kyb.emails import send_activation_email
from kyb.models import KYB_CASES, KybCase
from kyb.tokens import (activation_ttl_hours, check_signup_token,
                        consume_activation_token, mint_token,
                        signup_ttl_hours)

router = APIRouter(prefix="/kyb", tags=["kyb-signup"])

# Estados del modelo nuevo que consideramos "resueltos" para el signup.
RESOLVED_STATUSES = ("approved", "rejected")

# Respuesta idéntica de /signup/start — mismo shape para email nuevo,
# caso en curso o sondeo (el token de sondeo es un señuelo no persistido).
START_MESSAGE = ("Continuá completando tus datos. Si tu empresa ya tenía "
                 "un registro en curso, te reenviamos el enlace por email.")
RESEND_MESSAGE = ("Si el email corresponde a un registro en curso, vas a "
                  "recibir el enlace de activación en unos minutos.")

# El error de token de signup vencido es accionable: el caso persiste
# asociado al email — se reinicia desde /kyb/signup sin perder nada.
SIGNUP_TOKEN_ERROR = ("El enlace de registro venció o no es válido. Volvé "
                      "a ingresar tu email en /kyb/signup para retomar el "
                      "proceso donde lo dejaste — tus datos no se pierden.")

_MIN_RESPONSE_MS = 350          # piso anti-timing para start/resend

_ISO2 = re.compile(r"^[A-Z]{2}$")


def _rate_disabled() -> bool:
    return os.environ.get("PROSPER_DISABLE_RATELIMIT") == "1"


# ---------------------------------------------------------------------------
# Rate limiting horario en memoria — mismo patrón que server.rate_limit
# (token bucket in-process) pero con ventana de 1 h y clave arbitraria
# (email o IP), porque el limiter existente es solo por-IP y por-minuto.
# ---------------------------------------------------------------------------
_hour_buckets: dict[tuple[str, str], list[float]] = {}


def hourly_limit(scope: str, key: str, per_hour: int) -> None:
    if _rate_disabled():
        return
    now = time.monotonic()
    bucket = _hour_buckets.setdefault((scope, key), [])
    cutoff = now - 3600
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= per_hour:
        raise HTTPException(429, "Demasiados intentos. Probá más tarde.")
    bucket.append(now)


def _minute_limit(request: Request, scope: str, per_min: int) -> None:
    from server import rate_limit
    rate_limit(request, scope=scope, per_min=per_min)


async def _equalize(t0: float) -> None:
    """Iguala el tiempo de respuesta a un piso para que un sondeo (menos
    trabajo interno) no se distinga por timing."""
    elapsed_ms = (time.monotonic() - t0) * 1000
    if elapsed_ms < _MIN_RESPONSE_MS:
        await asyncio.sleep((_MIN_RESPONSE_MS - elapsed_ms) / 1000)


def _decoy_token() -> str:
    """Señuelo con el mismo shape que un signup_token real. No se
    persiste: cualquier uso posterior falla igual que un token vencido."""
    return secrets.token_urlsafe(32)


async def _find_case_by_email(email: str) -> Optional[dict]:
    return await col(KYB_CASES).find_one(
        {"applicant_email": email, "is_deleted": False}, {"_id": 0})


async def _audit_probe(email: str, reason: str, request: Request) -> None:
    """Registro interno de intento de sondeo (email ya registrado /
    caso resuelto). Nunca incluye más que el email y el motivo."""
    await kyb_audit("kyb.signup.probe_attempt", case_id="n/a",
                    request=request,
                    metadata={"email": email, "reason": reason})


# ---------------------------------------------------------------------------
# POST /signup/start
# ---------------------------------------------------------------------------
class StartIn(BaseModel):
    email: EmailStr
    company_name: str = Field(..., min_length=2, max_length=200)


@router.post("/signup/start")
async def signup_start(body: StartIn, request: Request):
    t0 = time.monotonic()
    _minute_limit(request, "kyb-signup-start", 10)
    email = body.email.lower().strip()
    hourly_limit("kyb-start-email", email, 5)
    hourly_limit("kyb-start-ip", client_ip(request) or "anon", 30)

    response = {"ok": True, "signup_token": _decoy_token(),
                "message": START_MESSAGE}

    # 1. Email ya registrado como usuario de la plataforma → sondeo.
    if await col(USERS).find_one({"email": email}, {"_id": 1}):
        await _audit_probe(email, "email_has_platform_user", request)
        await _equalize(t0)
        return response

    case = await _find_case_by_email(email)

    # 2. Caso resuelto (approved/rejected) → sondeo. Sin correo.
    if case and case["status"] in RESOLVED_STATUSES:
        await _audit_probe(email, f"case_{case['status']}", request)
        await _equalize(t0)
        return response

    # 3. Caso no resuelto → reingreso: token nuevo, sin duplicar caso.
    if case:
        if (body.company_name.strip()
                and body.company_name.strip() != case.get(
                    "company_name_declared")):
            # El dato original es el que declaró primero — no se pisa.
            await kyb_audit("kyb.signup.reentry_name_mismatch",
                            case_id=case["case_id"], request=request,
                            org_id=case.get("org_id"),
                            metadata={
                                "original": case.get("company_name_declared"),
                                "attempted": body.company_name.strip()})
        raw_signup = await mint_token(kind="signup",
                                      case_id=case["case_id"], email=email,
                                      ttl_hours=signup_ttl_hours())
        # Si el flujo ya había disparado activación (país cargado),
        # reenviamos el enlace en lugar de duplicar.
        if case.get("country_of_incorporation"):
            raw_act = await mint_token(kind="activation",
                                       case_id=case["case_id"], email=email,
                                       ttl_hours=activation_ttl_hours())
            await send_activation_email(
                case_id=case["case_id"], recipient=email,
                company_name=case.get("company_name_declared") or "",
                raw_token=raw_act)
            await kyb_audit("kyb.signup.resend", case_id=case["case_id"],
                            request=request, org_id=case.get("org_id"),
                            metadata={"via": "start_reentry"})
        response["signup_token"] = raw_signup
        await _equalize(t0)
        return response

    # 4. Alta nueva: organización no operativa + caso draft.
    org_id = new_id("org")
    now = utc_now()
    await col(ORGANIZATIONS).insert_one({
        "org_id": org_id,
        "legal_name": body.company_name.strip(),
        "commercial_name": body.company_name.strip(),
        "country": "",
        "type": "fintech",
        # Escritura ÚNICA en el alta (validada Fase 2): "pending" es el
        # valor NO operativo del vocabulario legacy → kyb_locked=true en
        # /me y el cliente no puede operar. El módulo KYB nuevo NUNCA
        # actualiza este campo después de este insert.
        "kyb_status": "pending",
        "kyb_case_id": None,        # se completa tras crear el caso
        "risk_score": 0, "risk_profile": "low",
        "allowlist_domains": [],
        "is_deleted": False,
        "created_at": now, "updated_at": now,
    })
    case_doc = KybCase(org_id=org_id, status="draft",
                       applicant_email=email,
                       company_name_declared=body.company_name.strip())
    doc = case_doc.model_dump()
    await col(KYB_CASES).insert_one(doc)
    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {"kyb_case_id": case_doc.case_id, "updated_at": utc_now()}})
    await kyb_audit("kyb.case.created", case_id=case_doc.case_id,
                    request=request, org_id=org_id,
                    metadata={"email": email,
                              "company_name": body.company_name.strip(),
                              "via": "self_signup"})
    raw_signup = await mint_token(kind="signup", case_id=case_doc.case_id,
                                  email=email,
                                  ttl_hours=signup_ttl_hours())
    response["signup_token"] = raw_signup
    await _equalize(t0)
    return response


# ---------------------------------------------------------------------------
# POST /signup/contact
# ---------------------------------------------------------------------------
class PhoneIn(BaseModel):
    country_code: str = Field(..., min_length=1, max_length=6)
    number: str = Field(..., min_length=5, max_length=20)


class ContactIn(BaseModel):
    signup_token: str
    full_name: str = Field(..., min_length=2, max_length=160)
    phone: PhoneIn


@router.post("/signup/contact")
async def signup_contact(body: ContactIn, request: Request):
    _minute_limit(request, "kyb-signup-contact", 20)
    tok = await check_signup_token(body.signup_token)
    if tok is None:
        raise HTTPException(401, SIGNUP_TOKEN_ERROR)
    await col(KYB_CASES).update_one(
        {"case_id": tok["case_id"]},
        {"$set": {"applicant_name": body.full_name.strip(),
                  "applicant_phone": body.phone.model_dump(),
                  "updated_at": utc_now()}})
    await kyb_audit("kyb.signup.contact_saved", case_id=tok["case_id"],
                    request=request, metadata={})
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /signup/country — al guardar dispara el email de activación
# ---------------------------------------------------------------------------
class CountryIn(BaseModel):
    signup_token: str
    country: str = Field(..., min_length=2, max_length=2)


@router.post("/signup/country")
async def signup_country(body: CountryIn, request: Request):
    _minute_limit(request, "kyb-signup-country", 20)
    country = body.country.strip().upper()
    if not _ISO2.match(country):
        raise HTTPException(422, "country debe ser ISO-3166 alpha-2")
    tok = await check_signup_token(body.signup_token)
    if tok is None:
        raise HTTPException(401, SIGNUP_TOKEN_ERROR)
    case = await col(KYB_CASES).find_one({"case_id": tok["case_id"]},
                                         {"_id": 0})
    await col(KYB_CASES).update_one(
        {"case_id": tok["case_id"]},
        {"$set": {"country_of_incorporation": country,
                  "updated_at": utc_now()}})
    raw_act = await mint_token(kind="activation", case_id=tok["case_id"],
                               email=tok["email"],
                               ttl_hours=activation_ttl_hours())
    rec = await send_activation_email(
        case_id=tok["case_id"], recipient=tok["email"],
        company_name=(case or {}).get("company_name_declared") or "",
        raw_token=raw_act)
    await kyb_audit("kyb.signup.country_saved", case_id=tok["case_id"],
                    request=request, org_id=(case or {}).get("org_id"),
                    metadata={"country": country,
                              "email_status": rec.get("status")})
    return {"ok": True, "email_status": rec.get("status")}


# ---------------------------------------------------------------------------
# POST /signup/resend — 3/hora por email + tope por IP (ambos)
# ---------------------------------------------------------------------------
class ResendIn(BaseModel):
    email: EmailStr


@router.post("/signup/resend")
async def signup_resend(body: ResendIn, request: Request):
    t0 = time.monotonic()
    _minute_limit(request, "kyb-signup-resend", 10)
    email = body.email.lower().strip()
    hourly_limit("kyb-resend-email", email, 3)
    hourly_limit("kyb-resend-ip", client_ip(request) or "anon", 10)

    response = {"ok": True, "message": RESEND_MESSAGE}
    case = await _find_case_by_email(email)

    if case is None or case["status"] in RESOLVED_STATUSES \
            or await col(USERS).find_one({"email": email}, {"_id": 1}):
        reason = ("no_case" if case is None else
                  f"case_{case['status']}" if case["status"]
                  in RESOLVED_STATUSES else "email_has_platform_user")
        await _audit_probe(email, reason, request)
        await _equalize(t0)
        return response

    raw_act = await mint_token(kind="activation", case_id=case["case_id"],
                               email=email,
                               ttl_hours=activation_ttl_hours())
    await send_activation_email(
        case_id=case["case_id"], recipient=email,
        company_name=case.get("company_name_declared") or "",
        raw_token=raw_act)
    await kyb_audit("kyb.signup.resend", case_id=case["case_id"],
                    request=request, org_id=case.get("org_id"),
                    metadata={"via": "resend_endpoint"})
    await _equalize(t0)
    return response


# ---------------------------------------------------------------------------
# POST /signup/activate — token de un solo uso → sesión
# ---------------------------------------------------------------------------
class ActivateIn(BaseModel):
    activation_token: str


def _cookie_secure(request: Request) -> bool:
    # Misma semántica que server._cookie_secure (no importable sin ciclo).
    if os.environ.get("COOKIE_SECURE", "true").lower() in ("false", "0"):
        return False
    proto = (request.headers.get("x-forwarded-proto")
             or request.url.scheme or "").lower()
    return proto != "http"


@router.post("/signup/activate")
async def signup_activate(body: ActivateIn, request: Request,
                          response: Response):
    _minute_limit(request, "kyb-signup-activate", 10)
    tok = await consume_activation_token(body.activation_token)
    if tok is None:
        # Idéntico para no-existe / vencido / ya usado / revocado.
        raise HTTPException(401, "El enlace de activación no es válido o "
                                 "ya fue utilizado. Pedí uno nuevo desde "
                                 "/kyb/signup.")
    case = await col(KYB_CASES).find_one({"case_id": tok["case_id"]},
                                         {"_id": 0})
    if not case:
        raise HTTPException(401, "El enlace de activación no es válido o "
                                 "ya fue utilizado. Pedí uno nuevo desde "
                                 "/kyb/signup.")
    email = tok["email"]
    user = await col(USERS).find_one({"email": email}, {"_id": 0})
    if user is None:
        user = {
            "user_id": new_id("usr"),
            "email": email,
            "role": Role.client_admin.value,
            "intended_role": "administrator",   # F8 mapping
            "org_id": case.get("org_id"),
            "first_name": None, "last_name": None,
            "status": "active",
            "kyc_status": "pending",
            "mfa_enabled": False,
            "is_deleted": False,
            "created_at": utc_now(), "updated_at": utc_now(),
        }
        await col(USERS).insert_one(dict(user))
    elif user.get("org_id") != case.get("org_id"):
        # El email quedó asociado a otra org entre el alta y la
        # activación — no emitimos sesión cruzada.
        raise HTTPException(401, "El enlace de activación no es válido o "
                                 "ya fue utilizado. Pedí uno nuevo desde "
                                 "/kyb/signup.")

    access = await mint_session_token(
        user_id=user["user_id"], email=email,
        role=Role(user["role"]), org_id=user.get("org_id"),
        request=request, label="KYB activation link")
    response.set_cookie("prosper_session", access, httponly=True,
                        secure=_cookie_secure(request), samesite="lax",
                        path="/", max_age=7 * 24 * 3600)
    await kyb_audit("kyb.signup.activated", case_id=case["case_id"],
                    request=request, org_id=case.get("org_id"),
                    metadata={"user_id": user["user_id"]})
    return {"ok": True, "accessToken": access, "portal": "/client",
            "case_status": case["status"],
            "company_name": case.get("company_name_declared")}
