"""Fase 8 — Enlaces compartidos para carga de documentación por terceros.

Contexto (`docs/kyb/write_access.md`):
  * hoy toda escritura del wizard exige sesión + rol `client_admin` de
    la org dueña del expediente;
  * la Fase 8 necesita que un tercero SIN sesión (contador, estudio)
    pueda cargar documentos — pero SOLO documentos, jamás CUIT ni
    equipo ni envío a revisión.

Diseño (respetando el punto de entrada documentado):
  * el token en claro NUNCA se persiste — solo su SHA-256;
  * scope se limita a `["documents"]` a nivel de tipo, y a los slots
    de documentación a nivel de endpoint;
  * rate limiting por token + por IP para las rutas públicas;
  * cada archivo subido queda con `uploaded_via="shared_link"` y
    `shared_link_id` — la trazabilidad de "quién cargó qué" es
    evidencia, no cosmética.

Rutas admin (client_admin, prefijo `/api/v1/kyb/case`):
  POST /shared-links, GET /shared-links, DELETE /shared-links/{id}

Rutas públicas (autenticadas por token, prefijo `/api/v1/kyb/shared`):
  GET /{token}                    → contexto acotado del expediente
  POST /{token}/documents         → subir documento a un slot
  POST /{token}/documents/confirm → confirmar slot
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException,
                     Request, UploadFile)
from pydantic import BaseModel, Field

from auth import CurrentUser, get_current_user
from db import col, ORGANIZATIONS
from models import utc_now
from roles import Role
from services.file_validator import FileValidationError, validate_file
from services.storage import get_storage
from kyb.audit import kyb_audit
from kyb.models import (KYB_CASES, KYB_COMPANY_PROFILES, KYB_DOCUMENTS,
                        KYB_SHARED_LINKS, KybDocument, KybSharedLink)
from kyb.state_machine import client_can_edit

# El módulo de wizard define slots + validación de docs; los reusamos.
from kyb.routes_case import (ALL_DOC_SUBSECTIONS, PHASE3_SLOTS, UBO_SLOTS,
                             ConfirmIn as _ConfirmIn)

admin_router = APIRouter(prefix="/kyb/case", tags=["kyb-shared-links-admin"])
public_router = APIRouter(prefix="/kyb/shared", tags=["kyb-shared-public"])

DEFAULT_HOURS = 168     # 7 días
MAX_HOURS     = 24 * 30
SCOPE_DOCS    = "documents"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _base_url() -> str:
    return (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")


def _shared_url(raw_token: str) -> str:
    return f"{_base_url()}/kyb/shared/{raw_token}"


async def _case_of(org_id: str) -> dict:
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id},
                                            {"_id": 0, "kyb_case_id": 1})
    case_id = (org or {}).get("kyb_case_id")
    case = case_id and await col(KYB_CASES).find_one(
        {"case_id": case_id, "is_deleted": False,
         "verification_modes": {"$exists": True}}, {"_id": 0})
    if not case:
        raise HTTPException(404, "Tu organización no tiene un expediente "
                                 "KYB del módulo nuevo")
    return case


def _require_admin(user: CurrentUser) -> None:
    if user.role != Role.client_admin:
        raise HTTPException(403, "Solo el administrador puede gestionar "
                                 "enlaces compartidos")


# ---------------------------------------------------------------------------
# Admin: crear / listar / revocar
# ---------------------------------------------------------------------------
class CreateSharedLinkIn(BaseModel):
    expires_in_hours: int = Field(DEFAULT_HOURS, ge=1, le=MAX_HOURS)
    note: Optional[str] = Field(None, max_length=200)


@admin_router.post("/shared-links")
async def create_shared_link(body: CreateSharedLinkIn, request: Request,
                             user: CurrentUser = Depends(get_current_user)):
    _require_admin(user)
    case = await _case_of(user.org_id)
    raw = secrets.token_urlsafe(32)
    now = utc_now()
    expires_iso = (datetime.fromisoformat(now.replace("Z", "+00:00"))
                   + timedelta(hours=body.expires_in_hours)).isoformat()
    link = KybSharedLink(case_id=case["case_id"], token_hash=_hash(raw),
                         scope=[SCOPE_DOCS], created_by=user.user_id,
                         expires_at=expires_iso)
    doc = link.model_dump()
    if body.note:
        doc["note"] = body.note.strip()
    await col(KYB_SHARED_LINKS).insert_one(dict(doc))
    await kyb_audit("kyb.shared_link.created", case_id=case["case_id"],
                    actor=user, request=request, org_id=user.org_id,
                    metadata={"link_id": link.link_id,
                              "expires_at": expires_iso,
                              "expires_in_hours": body.expires_in_hours})
    # El claro se devuelve UNA sola vez; el hash queda en base.
    return {"link_id": link.link_id, "url": _shared_url(raw),
            "expires_at": expires_iso,
            "expires_in_hours": body.expires_in_hours}


@admin_router.get("/shared-links")
async def list_shared_links(user: CurrentUser = Depends(get_current_user)):
    _require_admin(user)
    case = await _case_of(user.org_id)
    rows = await col(KYB_SHARED_LINKS).find(
        {"case_id": case["case_id"]},
        {"_id": 0, "token_hash": 0}).sort("created_at", -1).to_list(50)
    now = utc_now()
    for r in rows:
        r["active"] = (not r.get("revoked_at")) and \
                      (not r.get("expires_at") or r["expires_at"] > now)
    return {"items": rows}


@admin_router.delete("/shared-links/{link_id}")
async def revoke_shared_link(link_id: str, request: Request,
                             user: CurrentUser =
                             Depends(get_current_user)):
    _require_admin(user)
    case = await _case_of(user.org_id)
    r = await col(KYB_SHARED_LINKS).find_one_and_update(
        {"link_id": link_id, "case_id": case["case_id"],
         "revoked_at": None},
        {"$set": {"revoked_at": utc_now(), "updated_at": utc_now()}},
        return_document=True)
    if not r:
        raise HTTPException(404, "Enlace no encontrado o ya revocado")
    await kyb_audit("kyb.shared_link.revoked", case_id=case["case_id"],
                    actor=user, request=request, org_id=user.org_id,
                    metadata={"link_id": link_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Público: dep + rate limit
# ---------------------------------------------------------------------------
async def _resolve_token(token: str, request: Request) -> dict:
    """Rate limit por IP + validación completa del token. Devuelve el
    link + el case + el profile. El texto claro no queda en logs."""
    from server import rate_limit
    rate_limit(request, scope=f"kyb-shared-{token[:10]}", per_min=30)
    rate_limit(request, scope="kyb-shared-public", per_min=120)
    link = await col(KYB_SHARED_LINKS).find_one({"token_hash": _hash(token)},
                                                {"_id": 0})
    if not link:
        # Anti-enumeración: mismo mensaje para "no existe" y "revocado".
        raise HTTPException(404, "Enlace inválido")
    if link.get("revoked_at"):
        raise HTTPException(404, "Enlace inválido")
    if link.get("expires_at") and link["expires_at"] < utc_now():
        raise HTTPException(404, "Enlace inválido")
    if SCOPE_DOCS not in (link.get("scope") or []):
        raise HTTPException(403, "Enlace sin permiso de carga de documentos")
    case = await col(KYB_CASES).find_one(
        {"case_id": link["case_id"], "is_deleted": False,
         "verification_modes": {"$exists": True}}, {"_id": 0})
    if not case:
        raise HTTPException(404, "Enlace inválido")
    if not client_can_edit(case["status"]):
        raise HTTPException(403, "El expediente está en revisión y no "
                                 "puede editarse")
    return {"link": link, "case": case}


async def _touch(link_id: str) -> None:
    await col(KYB_SHARED_LINKS).update_one(
        {"link_id": link_id},
        {"$set": {"last_used_at": utc_now(), "updated_at": utc_now()},
         "$inc": {"use_count": 1}})


# ---------------------------------------------------------------------------
# Público: contexto acotado
# ---------------------------------------------------------------------------
@public_router.get("/{token}")
async def shared_context(token: str, request: Request):
    ctx = await _resolve_token(token, request)
    case = ctx["case"]
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case["case_id"]},
        {"_id": 0, "legal_name": 1}) or {}
    docs = await col(KYB_DOCUMENTS).find(
        {"case_id": case["case_id"], "uploaded_via": "shared_link",
         "shared_link_id": ctx["link"]["link_id"], "is_current": True},
        {"_id": 0, "storage_key": 0}).to_list(200)
    await _touch(ctx["link"]["link_id"])
    return {"company_name": profile.get("legal_name") or "la empresa",
            "case_id": case["case_id"], "status": case["status"],
            "expires_at": ctx["link"].get("expires_at"),
            "phase3_slots": PHASE3_SLOTS, "ubo_slots": UBO_SLOTS,
            "documents_uploaded_here": docs}


# ---------------------------------------------------------------------------
# Público: upload
# ---------------------------------------------------------------------------
@public_router.post("/{token}/documents")
async def shared_upload_document(token: str, request: Request,
                                 slot: str = Form(...),
                                 description: str = Form("", max_length=499),
                                 ubo_id: Optional[str] = Form(None),
                                 file: UploadFile = File(...)):
    ctx = await _resolve_token(token, request)
    case = ctx["case"]; link = ctx["link"]
    if slot not in PHASE3_SLOTS + UBO_SLOTS:
        raise HTTPException(422, f"slot debe ser uno de "
                                 f"{PHASE3_SLOTS + UBO_SLOTS}")
    if ubo_id and slot not in UBO_SLOTS:
        raise HTTPException(422, "ubo_id solo aplica a slots de "
                                 "beneficiarios")
    content = await file.read()
    try:
        detected = validate_file(file.filename or "archivo", content)
    except FileValidationError as e:
        raise HTTPException(422, str(e))
    storage = get_storage()
    storage_key = await storage.put(
        content=content, filename=file.filename or "archivo",
        content_type=detected,
        metadata={"uploaded_by": f"shared_link:{link['link_id']}",
                  "scope_kind": "kyb_case", "scope_id": case["case_id"]})
    try:
        prev = await col(KYB_DOCUMENTS).find(
            {"case_id": case["case_id"], "slot": slot, "ubo_id": ubo_id},
            {"version": 1}).sort("version", -1).limit(1).to_list(1)
        version = (prev[0]["version"] + 1) if prev else 1
        doc = KybDocument(case_id=case["case_id"], slot=slot,
                          version=version,
                          filename=file.filename, content_type=detected,
                          size_bytes=len(content), storage_key=storage_key,
                          sha256=hashlib.sha256(content).hexdigest(),
                          description=description or None,
                          uploaded_by=f"shared_link:{link['link_id']}",
                          uploaded_via="shared_link",
                          shared_link_id=link["link_id"], ubo_id=ubo_id)
        await col(KYB_DOCUMENTS).update_many(
            {"case_id": case["case_id"], "slot": slot, "ubo_id": ubo_id,
             "is_current": True},
            {"$set": {"is_current": False, "updated_at": utc_now()}})
        await col(KYB_DOCUMENTS).insert_one(doc.model_dump())
    except Exception:
        await storage.delete(storage_key)
        raise
    await _touch(link["link_id"])
    # Auditoría con actor sintético — no hay user_id real.
    await kyb_audit("kyb.document.uploaded", case_id=case["case_id"],
                    actor=None, request=request, org_id=case.get("org_id"),
                    metadata={"slot": slot, "version": version,
                              "document_id": doc.document_id,
                              "sha256": doc.sha256,
                              "uploaded_via": "shared_link",
                              "shared_link_id": link["link_id"]})
    out = doc.model_dump(); out.pop("storage_key", None)
    return out


# ---------------------------------------------------------------------------
# Público: confirmar slot documental
# ---------------------------------------------------------------------------
@public_router.post("/{token}/documents/confirm")
async def shared_confirm_slot(token: str, body: _ConfirmIn, request: Request):
    ctx = await _resolve_token(token, request)
    case = ctx["case"]; link = ctx["link"]
    if body.slot not in PHASE3_SLOTS:
        raise HTTPException(422, f"slot debe ser uno de {PHASE3_SLOTS}")
    # El shared link puede confirmar documentos pero JAMÁS declarar
    # "empresa reciente" — es una afirmación del titular, no de un
    # tercero cargador.
    if body.recently_incorporated:
        raise HTTPException(403, "Solo el administrador de la organización "
                                 "puede declarar reciente creación")
    has_file = await col(KYB_DOCUMENTS).find_one(
        {"case_id": case["case_id"], "slot": body.slot, "is_current": True},
        {"_id": 1})
    if not has_file:
        raise HTTPException(422, "No hay archivos cargados en esta "
                                 "subsección")
    await col(KYB_CASES).update_one(
        {"case_id": case["case_id"]},
        {"$set": {f"sections.documentation.slots.{body.slot}": "confirmed",
                  "updated_at": utc_now()}})
    fresh = await col(KYB_CASES).find_one({"case_id": case["case_id"]},
                                          {"_id": 0})
    slots = ((fresh.get("sections") or {}).get("documentation")
             or {}).get("slots") or {}
    # Envío a revisión NO puede dispararse desde acá: el shared link no
    # marca la sección `documentation` como completada. Eso queda para
    # que el titular lo haga desde el wizard.
    await _touch(link["link_id"])
    await kyb_audit("kyb.document.confirmed", case_id=case["case_id"],
                    actor=None, request=request, org_id=case.get("org_id"),
                    metadata={"slot": body.slot,
                              "uploaded_via": "shared_link",
                              "shared_link_id": link["link_id"]})
    return {"ok": True, "slots": slots}
