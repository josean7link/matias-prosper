"""Fase 3 — Wizard del expediente: guardado por sección + documentos.

Prefijo /api/v1/kyb/case. Requiere sesión de cliente (cookie). Todas
las escrituras exigen rol client_admin de la org dueña del caso y
respetan la máquina de estados: editable solo en draft (transiciona a
in_progress con el primer guardado), in_progress e info_required (solo
secciones observed).

Documentos: capa de storage + validador de la Fase 0.5. Versionado
incremental por slot (nunca se pisa), storage_key jamás viaja al
cliente, descarga por URL firmada de vida corta.
"""
from __future__ import annotations

import os
import re
from typing import List, Literal, Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel, EmailStr, Field

from auth import CurrentUser, get_current_user
from db import col, ORGANIZATIONS
from models import utc_now
from roles import Role
from services.file_validator import FileValidationError, validate_file
from services.storage import get_storage
from kyb.audit import kyb_audit
from kyb.legal_docs import LEGAL_DOCS, current_docs
from kyb.models import (FUNDS, FUNDS_ORIGIN_TYPES, KYB_CASES,
                        KYB_COMPANY_PROFILES, KYB_DOCUMENTS,
                        LEGAL_STRUCTURES, PURPOSES, KybDocument)
from kyb.state_machine import apply_transition, client_can_edit, \
    editable_sections

router = APIRouter(prefix="/kyb/case", tags=["kyb-case"])

PHASE3_SLOTS = ["tax_registration_certificate", "constitutive_document",
                "funds_origin_evidence", "authorities_appointment",
                "company_proof_of_address"]

COMPANY_SUBSECTIONS = ["legal_name", "data", "address", "operations",
                       "funds_origin"]

READONLY_MESSAGE = ("El expediente está en revisión y no puede editarse en "
                    "este momento.")


# ---------------------------------------------------------------------------
# Resolución del caso + guards
# ---------------------------------------------------------------------------
async def get_case_ctx(user: CurrentUser = Depends(get_current_user)) -> dict:
    if not user.org_id:
        raise HTTPException(403, "Sesión sin organización")
    org = await col(ORGANIZATIONS).find_one({"org_id": user.org_id},
                                            {"_id": 0, "kyb_case_id": 1})
    case_id = (org or {}).get("kyb_case_id")
    case = case_id and await col(KYB_CASES).find_one(
        {"case_id": case_id, "is_deleted": False,
         "verification_modes": {"$exists": True}}, {"_id": 0})
    if not case:
        raise HTTPException(404, "Tu organización no tiene un expediente "
                                 "KYB del módulo nuevo")
    return {"user": user, "case": case}


def _require_admin(user: CurrentUser) -> None:
    if user.role != Role.client_admin:
        raise HTTPException(403, "Solo el administrador de la organización "
                                 "puede editar el expediente")


def _guard_editable(case: dict, section_key: str) -> None:
    status = case["status"]
    if not client_can_edit(status):
        raise HTTPException(403, READONLY_MESSAGE)
    if status == "info_required" and \
            section_key not in editable_sections(case):
        raise HTTPException(403, "En este estado solo podés editar las "
                                 "secciones observadas por el analista")


async def _profile(case_id: str) -> dict:
    doc = await col(KYB_COMPANY_PROFILES).find_one({"case_id": case_id},
                                                   {"_id": 0})
    if not doc:
        doc = {"case_id": case_id, "tax_id": None, "tax_id_locked": False,
               "legal_acceptances": [], "tax_residences": [],
               "subsections_saved": {},
               "created_at": utc_now(), "updated_at": utc_now()}
        await col(KYB_COMPANY_PROFILES).insert_one(dict(doc))
    return doc


async def _save_profile(case_id: str, fields: dict,
                        subsection: Optional[str] = None) -> None:
    fields = {**fields, "updated_at": utc_now()}
    if subsection:
        fields[f"subsections_saved.{subsection}"] = utc_now()
    await col(KYB_COMPANY_PROFILES).update_one({"case_id": case_id},
                                               {"$set": fields})


async def _mark_section(ctx: dict, section_key: str, request: Request,
                        draft: bool) -> None:
    """Guardado explícito: marca completada + transición draft→in_progress
    + auditoría. El autosave (draft=True) no marca nada."""
    case = ctx["case"]
    if draft:
        return
    # Fase 3.1: una sección observada que se guarda pasa a `resubmitted`,
    # no a `completed` — el analista distingue "corrigió lo observado" de
    # una sección nunca observada. La observación original se conserva
    # SIEMPRE (es historial). Para el cliente, resubmitted cuenta como
    # completa a efectos del envío.
    was_observed = ((case.get("sections") or {}).get(section_key)
                    or {}).get("status") == "observed"
    new_status = "resubmitted" if was_observed else "completed"
    await col(KYB_CASES).update_one(
        {"case_id": case["case_id"]},
        {"$set": {f"sections.{section_key}.status": new_status,
                  f"sections.{section_key}.completed_at": utc_now(),
                  "updated_at": utc_now()}})
    await kyb_audit("kyb.case.section_saved", case_id=case["case_id"],
                    actor=ctx["user"], request=request,
                    org_id=case.get("org_id"),
                    metadata={"section": section_key,
                              "new_status": new_status})
    if case["status"] == "draft":
        await apply_transition(case, "in_progress", actor_type="client",
                               actor=ctx["user"], request=request,
                               metadata={"trigger": "first_section_saved"})


def _company_section_complete(profile: dict) -> bool:
    saved = profile.get("subsections_saved") or {}
    return all(k in saved for k in COMPANY_SUBSECTIONS)


async def _maybe_complete_company(ctx: dict, request: Request,
                                  draft: bool) -> None:
    if draft:
        return
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": ctx["case"]["case_id"]}, {"_id": 0})
    if _company_section_complete(profile):
        await _mark_section(ctx, "company_data", request, draft=False)
    elif ctx["case"]["status"] == "draft":
        # Un guardado explícito parcial igualmente saca el caso de draft.
        await apply_transition(ctx["case"], "in_progress",
                               actor_type="client", actor=ctx["user"],
                               request=request,
                               metadata={"trigger": "company_subsection"})


# ---------------------------------------------------------------------------
# CUIT — validación de dígito verificador (mod 11)
# ---------------------------------------------------------------------------
def cuit_is_valid(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 11:
        return False
    weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    s = sum(int(d) * w for d, w in zip(digits[:10], weights))
    dv = 11 - (s % 11)
    dv = {11: 0, 10: 9}.get(dv, dv)
    return dv == int(digits[10])


# ---------------------------------------------------------------------------
# GET /case — expediente completo (sin storage_key, sin _id)
# ---------------------------------------------------------------------------
@router.get("")
async def get_case(ctx: dict = Depends(get_case_ctx)):
    case = ctx["case"]
    profile = await _profile(case["case_id"])
    docs = await col(KYB_DOCUMENTS).find(
        {"case_id": case["case_id"]},
        {"_id": 0, "storage_key": 0}).sort("version", 1).to_list(200)
    ubos = await _ubos(case["case_id"])
    sections = case.get("sections") or {}
    missing = [k for k, v in sections.items()
               if k != "team" and (v or {}).get("status")
               not in ("completed", "resubmitted")]
    blockers = await _submit_blockers(case)
    return {
        "case": case,
        "profile": profile,
        "documents": docs,
        "ubos": ubos,
        "legal_docs": current_docs(),
        "progress": {
            "sections": {k: (v or {}).get("status") for k, v in
                         sections.items()},
            "missing": missing,
            "submit_blockers": blockers,
            "can_submit": case["status"] in ("in_progress", "info_required")
            and not blockers,
        },
        "editable": client_can_edit(case["status"]),
        "editable_sections": editable_sections(case),
        "phase3_slots": PHASE3_SLOTS,
        "ubo_slots": UBO_SLOTS,
    }


# ---------------------------------------------------------------------------
# Sección 1 — Identificación tributaria
# ---------------------------------------------------------------------------
class TaxIdIn(BaseModel):
    tax_id: str = Field(..., min_length=11, max_length=13)
    accepted_documents: List[str] = []
    draft: bool = False


@router.put("/tax-identification")
async def put_tax_identification(body: TaxIdIn, request: Request,
                                 ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "tax_identification")
    profile = await _profile(ctx["case"]["case_id"])
    if profile.get("tax_id_locked"):
        raise HTTPException(409, "El número de identificación tributaria ya "
                                 "fue confirmado y no puede editarse")
    if not cuit_is_valid(body.tax_id):
        raise HTTPException(422, "CUIT inválido: el dígito verificador no "
                                 "coincide")
    tax_id = re.sub(r"\D", "", body.tax_id)
    if body.draft:
        await _save_profile(ctx["case"]["case_id"], {"tax_id": tax_id})
        return {"ok": True, "draft": True}
    known = {d["document_key"] for d in LEGAL_DOCS}
    if set(body.accepted_documents) != known:
        raise HTTPException(422, "Debés aceptar todos los documentos "
                                 "legales para confirmar esta sección")
    # Evidencia: versión + hash del contenido VIGENTE, calculado acá.
    acceptances = [{**d, "accepted_at": utc_now(),
                    "ip": request.headers.get("x-forwarded-for",
                                              "").split(",")[0].strip()
                    or (request.client.host if request.client else None),
                    "user_agent": request.headers.get("user-agent")}
                   for d in current_docs()]
    dup = await col(KYB_COMPANY_PROFILES).find_one(
        {"tax_id": tax_id, "case_id": {"$ne": ctx["case"]["case_id"]}},
        {"_id": 1})
    if dup:
        raise HTTPException(409, "Ese CUIT ya está registrado en otro "
                                 "expediente")
    await _save_profile(ctx["case"]["case_id"],
                        {"tax_id": tax_id, "tax_id_locked": True,
                         "legal_acceptances": acceptances},
                        subsection=None)
    await _mark_section(ctx, "tax_identification", request, draft=False)
    return {"ok": True, "tax_id_locked": True}


# ---------------------------------------------------------------------------
# Sección 2 — Representante legal
# ---------------------------------------------------------------------------
class LegalRepIn(BaseModel):
    country_of_residence: str = Field(..., min_length=2, max_length=2)
    full_name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    tax_id: Optional[str] = Field(None, max_length=13)
    draft: bool = False


@router.put("/legal-representative")
async def put_legal_rep(body: LegalRepIn, request: Request,
                        ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "legal_representative")
    case_id = ctx["case"]["case_id"]
    rep_tax = _norm_tax(body.tax_id)
    await _save_profile(case_id, {"legal_representative": {
        "country_of_residence": body.country_of_residence.upper(),
        "full_name": body.full_name.strip(), "email": body.email.lower(),
        "tax_id": rep_tax or None}})
    # Recalcula el vínculo declarativo de cada UBO (mismo tax_id ⇒ misma
    # persona para el orquestador). No es una mutación del cuadro: no
    # invalida la DDJJ.
    async for u in col(KYB_BENEFICIAL_OWNERS).find(
            {"case_id": case_id},
            {"_id": 0, "ubo_id": 1, "tax_id": 1,
             "is_also_legal_representative": 1}):
        flag = bool(rep_tax) and _norm_tax(u.get("tax_id")) == rep_tax
        if flag != bool(u.get("is_also_legal_representative")):
            await col(KYB_BENEFICIAL_OWNERS).update_one(
                {"ubo_id": u["ubo_id"]},
                {"$set": {"is_also_legal_representative": flag,
                          "updated_at": utc_now()}})
    await _mark_section(ctx, "legal_representative", request, body.draft)
    return {"ok": True, "draft": body.draft}


# ---------------------------------------------------------------------------
# Sección 3 — Datos de la empresa (5 subsecciones)
# ---------------------------------------------------------------------------
class LegalNameIn(BaseModel):
    legal_name: str = Field(..., min_length=2, max_length=200)
    legal_structure: str
    legal_structure_other: Optional[str] = None
    draft: bool = False


@router.put("/company/legal-name")
async def put_company_legal_name(body: LegalNameIn, request: Request,
                                 ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "company_data")
    if body.legal_structure not in LEGAL_STRUCTURES:
        raise HTTPException(422, f"legal_structure debe ser una de "
                                 f"{LEGAL_STRUCTURES}")
    if body.legal_structure == "OTRA" and not body.draft \
            and not (body.legal_structure_other or "").strip():
        raise HTTPException(422, "Detallá la estructura legal")
    await _save_profile(ctx["case"]["case_id"],
                        {"legal_name": body.legal_name.strip(),
                         "legal_structure": body.legal_structure,
                         "legal_structure_other": body.legal_structure_other},
                        subsection=None if body.draft else "legal_name")
    await _maybe_complete_company(ctx, request, body.draft)
    return {"ok": True, "draft": body.draft}


class CompanyDataIn(BaseModel):
    activity_description: str = Field(..., max_length=500)
    registration_number: Optional[str] = None
    registration_date: Optional[str] = None
    website: Optional[str] = None
    draft: bool = False


@router.put("/company/data")
async def put_company_data(body: CompanyDataIn, request: Request,
                           ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "company_data")
    if not body.draft and len(body.activity_description.strip()) < 100:
        raise HTTPException(422, "La descripción de actividad requiere un "
                                 "mínimo de 100 caracteres")
    await _save_profile(ctx["case"]["case_id"], {
        "activity_description": body.activity_description,
        "registration_number": body.registration_number,
        "registration_date": body.registration_date,
        "website": body.website},
        subsection=None if body.draft else "data")
    await _maybe_complete_company(ctx, request, body.draft)
    return {"ok": True, "draft": body.draft}


class AddressIn(BaseModel):
    raw: str = Field(..., min_length=5, max_length=300)
    street: Optional[str] = None
    number: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    draft: bool = False


@router.put("/company/address")
async def put_company_address(body: AddressIn, request: Request,
                              ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "company_data")
    if not body.draft and not (body.country and body.city):
        raise HTTPException(422, "La dirección debe incluir al menos país y "
                                 "localidad (alimentan el motor de riesgo)")
    data = body.model_dump(exclude={"draft"})
    await _save_profile(ctx["case"]["case_id"],
                        {"registered_address": data},
                        subsection=None if body.draft else "address")
    await _maybe_complete_company(ctx, request, body.draft)
    return {"ok": True, "draft": body.draft}


class OperationsIn(BaseModel):
    estimated_monthly_volume_usd: Optional[float] = Field(None, ge=0)
    purposes: List[str] = []
    purpose_other: Optional[str] = None
    funds_subscribed: List[str] = []
    draft: bool = False


@router.put("/company/operations")
async def put_company_operations(body: OperationsIn, request: Request,
                                 ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "company_data")
    if bad := [p for p in body.purposes if p not in PURPOSES]:
        raise HTTPException(422, f"Objetivos inválidos: {bad}")
    if bad := [f for f in body.funds_subscribed if f not in FUNDS]:
        raise HTTPException(422, f"Fondos inválidos: {bad}")
    if not body.draft:
        if not body.purposes or body.estimated_monthly_volume_usd is None \
                or not body.funds_subscribed:
            raise HTTPException(422, "Completá monto estimado, objetivos y "
                                     "fondo/s a suscribir")
        if "OTHER" in body.purposes and not (body.purpose_other or "").strip():
            raise HTTPException(422, "Detallá el otro objetivo")
    await _save_profile(ctx["case"]["case_id"],
                        {"operations": body.model_dump(exclude={"draft"})},
                        subsection=None if body.draft else "operations")
    await _maybe_complete_company(ctx, request, body.draft)
    return {"ok": True, "draft": body.draft}


class FundsOriginIn(BaseModel):
    type: str
    client_funds_ratio: Optional[float] = Field(None, ge=0, le=100)
    license_type: Optional[str] = None
    license_number: Optional[str] = None
    has_aml_policy: Optional[bool] = None
    compliance_officer_name: Optional[str] = None
    end_user_kyc_description: Optional[str] = None
    segregated_assets: Optional[bool] = None
    is_uif_obliged_subject: Optional[bool] = None
    uif_registration_number: Optional[str] = None
    tax_residences: List[dict] = []
    draft: bool = False


@router.put("/company/funds-origin")
async def put_funds_origin(body: FundsOriginIn, request: Request,
                           ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "company_data")
    if body.type not in FUNDS_ORIGIN_TYPES:
        raise HTTPException(422, f"type debe ser uno de {FUNDS_ORIGIN_TYPES}")
    if not body.draft and body.type in ("CLIENT_FUNDS", "MIXED"):
        required = {"license_type": body.license_type,
                    "license_number": body.license_number,
                    "compliance_officer_name": body.compliance_officer_name,
                    "end_user_kyc_description": body.end_user_kyc_description}
        if missing := [k for k, v in required.items()
                       if not (v or "").strip()]:
            raise HTTPException(422, f"Faltan campos obligatorios para "
                                     f"fondos de clientes: {missing}")
        if body.has_aml_policy is None or body.segregated_assets is None:
            raise HTTPException(422, "Declarás política PLA/FT y "
                                     "segregación patrimonial (sí/no)")
        if body.type == "MIXED" and body.client_funds_ratio is None:
            raise HTTPException(422, "Indicá la proporción estimada entre "
                                     "ambos flujos")
    if not body.draft and body.is_uif_obliged_subject \
            and not (body.uif_registration_number or "").strip():
        raise HTTPException(422, "Indicá el número de registración UIF")
    fo = body.model_dump(exclude={"draft", "is_uif_obliged_subject",
                                  "uif_registration_number",
                                  "tax_residences"})
    await _save_profile(ctx["case"]["case_id"], {
        "funds_origin": fo,
        "is_uif_obliged_subject": body.is_uif_obliged_subject,
        "uif_registration_number": body.uif_registration_number,
        "tax_residences": body.tax_residences},
        subsection=None if body.draft else "funds_origin")
    await _maybe_complete_company(ctx, request, body.draft)
    return {"ok": True, "draft": body.draft}


# ---------------------------------------------------------------------------
# Sección 4 — Documentación
# ---------------------------------------------------------------------------
@router.post("/documents")
async def upload_document(request: Request,
                          slot: str = Form(...),
                          description: str = Form("", max_length=499),
                          ubo_id: Optional[str] = Form(None),
                          file: UploadFile = File(...),
                          ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "documentation")
    if slot not in PHASE3_SLOTS + UBO_SLOTS:
        raise HTTPException(422, f"slot debe ser uno de "
                                 f"{PHASE3_SLOTS + UBO_SLOTS}")
    if ubo_id and slot not in UBO_SLOTS:
        raise HTTPException(422, "ubo_id solo aplica a slots de "
                                 "beneficiarios")
    case_id = ctx["case"]["case_id"]
    if ubo_id and not await col(KYB_BENEFICIAL_OWNERS).find_one(
            {"ubo_id": ubo_id, "case_id": case_id}, {"_id": 1}):
        raise HTTPException(404, "Beneficiario no encontrado")
    content = await file.read()
    try:
        detected = validate_file(file.filename or "archivo", content)
    except FileValidationError as e:
        raise HTTPException(422, str(e))
    storage = get_storage()
    # Carga en dos pasos: primero el binario, después el registro. Si el
    # registro falla, se borra el binario para no dejar huérfanos — una
    # carga que falla a mitad no deja versión fantasma ni pisa nada.
    storage_key = await storage.put(
        content=content, filename=file.filename or "archivo",
        content_type=detected,
        metadata={"uploaded_by": ctx["user"].user_id,
                  "scope_kind": "kyb_case", "scope_id": case_id})
    try:
        # El versionado de slots UBO es por beneficiario: el filtro incluye
        # ubo_id (None matchea los docs societarios de la Fase 3).
        prev = await col(KYB_DOCUMENTS).find(
            {"case_id": case_id, "slot": slot, "ubo_id": ubo_id},
            {"version": 1}).sort("version", -1).limit(1).to_list(1)
        version = (prev[0]["version"] + 1) if prev else 1
        import hashlib
        doc = KybDocument(case_id=case_id, slot=slot, version=version,
                          filename=file.filename, content_type=detected,
                          size_bytes=len(content), storage_key=storage_key,
                          sha256=hashlib.sha256(content).hexdigest(),
                          description=description or None,
                          uploaded_by=ctx["user"].user_id,
                          uploaded_via="owner", ubo_id=ubo_id)
        await col(KYB_DOCUMENTS).update_many(
            {"case_id": case_id, "slot": slot, "ubo_id": ubo_id,
             "is_current": True},
            {"$set": {"is_current": False, "updated_at": utc_now()}})
        await col(KYB_DOCUMENTS).insert_one(doc.model_dump())
    except Exception:
        await storage.delete(storage_key)
        raise
    await kyb_audit("kyb.document.uploaded", case_id=case_id,
                    actor=ctx["user"], request=request,
                    org_id=ctx["case"].get("org_id"),
                    metadata={"slot": slot, "version": version,
                              "document_id": doc.document_id,
                              "sha256": doc.sha256})
    out = doc.model_dump()
    out.pop("storage_key", None)
    return out


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, request: Request,
                          ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "documentation")
    row = await col(KYB_DOCUMENTS).find_one_and_update(
        {"document_id": document_id, "case_id": ctx["case"]["case_id"],
         "is_current": True},
        {"$set": {"is_current": False, "updated_at": utc_now()}})
    if not row:
        raise HTTPException(404, "Documento no encontrado")
    await kyb_audit("kyb.document.deleted", case_id=ctx["case"]["case_id"],
                    actor=ctx["user"], request=request,
                    org_id=ctx["case"].get("org_id"),
                    metadata={"document_id": document_id,
                              "slot": row.get("slot"),
                              "version": row.get("version")})
    return {"ok": True}


@router.get("/documents/{document_id}/url")
async def document_url(document_id: str,
                       ctx: dict = Depends(get_case_ctx)):
    row = await col(KYB_DOCUMENTS).find_one(
        {"document_id": document_id, "case_id": ctx["case"]["case_id"]},
        {"_id": 0, "storage_key": 1})
    if not row:
        raise HTTPException(404, "Documento no encontrado")
    url = await get_storage().signed_url(row["storage_key"],
                                         ttl_seconds=300)
    return {"url": url, "expires_in": 300}


class ConfirmIn(BaseModel):
    slot: str
    recently_incorporated: bool = False


@router.post("/documents/confirm")
async def confirm_slot(body: ConfirmIn, request: Request,
                       ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "documentation")
    if body.slot not in PHASE3_SLOTS:
        raise HTTPException(422, f"slot debe ser uno de {PHASE3_SLOTS}")
    case_id = ctx["case"]["case_id"]
    if body.recently_incorporated:
        if body.slot != "funds_origin_evidence":
            raise HTTPException(422, "La declaración de reciente creación "
                                     "solo aplica al slot de origen de "
                                     "fondos")
        await _save_profile(case_id, {"recently_incorporated_declared": True})
    else:
        has_file = await col(KYB_DOCUMENTS).find_one(
            {"case_id": case_id, "slot": body.slot, "is_current": True},
            {"_id": 1})
        if not has_file:
            raise HTTPException(422, "No hay archivos cargados en esta "
                                     "subsección")
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {f"sections.documentation.slots.{body.slot}": "confirmed",
                  "updated_at": utc_now()}})
    fresh = await col(KYB_CASES).find_one({"case_id": case_id}, {"_id": 0})
    slots = ((fresh.get("sections") or {}).get("documentation")
             or {}).get("slots") or {}
    if all(slots.get(s) == "confirmed" for s in ALL_DOC_SUBSECTIONS):
        await _mark_section(ctx, "documentation", request, draft=False)
    elif ctx["case"]["status"] == "draft":
        await apply_transition(ctx["case"], "in_progress",
                               actor_type="client", actor=ctx["user"],
                               request=request,
                               metadata={"trigger": "document_confirm"})
    return {"ok": True, "slots": slots}


# ===========================================================================
# Fase 4 — Beneficiarios finales (UBO) + envío a revisión
# ===========================================================================
UBO_SLOTS = ["ubo_document_front", "ubo_document_back"]
# Todas las estructuras legales listadas requieren los mismos 5 documentos.
REQUIRED_DOCS = {s: list(PHASE3_SLOTS) for s in LEGAL_STRUCTURES}
# La subsección de beneficiarios es parte de "documentation": la sección se
# completa cuando los 5 slots documentales Y el cuadro societario confirman.
ALL_DOC_SUBSECTIONS = PHASE3_SLOTS + ["beneficial_owners"]
from kyb.models import KYB_BENEFICIAL_OWNERS, KybBeneficialOwner


def _norm_tax(v) -> str:
    return re.sub(r"\D", "", v or "")


def _pct_ok(v) -> bool:
    return v is not None and 0 <= v <= 100 and round(v, 2) == v


async def _ubos(case_id: str) -> list[dict]:
    return await col(KYB_BENEFICIAL_OWNERS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(100)


def _ownership_total(ubos: list[dict]) -> float:
    return round(sum(u.get("ownership_percentage") or 0 for u in ubos
                     if u.get("control_type") == "OWNERSHIP"), 2)


def _cuadro(ubos: list[dict]) -> list[dict]:
    """Snapshot del cuadro societario para auditoría (antes/después)."""
    return [{"ubo_id": u["ubo_id"],
             "name": f"{u.get('first_name', '')} "
                     f"{u.get('last_name', '')}".strip(),
             "control_type": u.get("control_type"),
             "ownership_percentage": u.get("ownership_percentage")}
            for u in ubos]


async def _rep_tax_id(case_id: str) -> str:
    prof = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case_id}, {"_id": 0, "legal_representative": 1})
    return _norm_tax(((prof or {}).get("legal_representative")
                      or {}).get("tax_id"))


async def _link_ubo_documents(case_id: str, ubo_id: str, doc_ids) -> None:
    ids = [d for d in doc_ids if d]
    if ids:
        await col(KYB_DOCUMENTS).update_many(
            {"case_id": case_id, "document_id": {"$in": ids}},
            {"$set": {"ubo_id": ubo_id, "updated_at": utc_now()}})


async def _invalidate_ubo_confirmation(ctx, request, before, after,
                                       action: str, ubo_id: str,
                                       ubo_name: str) -> None:
    """La DDJJ se firmó sobre un cuadro determinado: cualquier alta, baja o
    edición posterior saca la subsección de confirmada y ARCHIVA el
    acknowledgment vigente en `ubo_confirmation_history` — nunca se pierde:
    el analista ve cada aceptación, su %, quién la firmó y qué cambio
    concreto la invalidó."""
    case = await col(KYB_CASES).find_one(
        {"case_id": ctx["case"]["case_id"]}, {"_id": 0})
    conf = case.get("ubo_confirmation")
    slots = ((case.get("sections") or {}).get("documentation")
             or {}).get("slots") or {}
    if not conf and slots.get("beneficial_owners") != "confirmed":
        return
    invalidated = {**(conf or {}),
                   "invalidated_at": utc_now(),
                   "invalidated_by": ctx["user"].user_id,
                   "invalidated_by_change": {"action": action,
                                             "ubo_id": ubo_id,
                                             "ubo_name": ubo_name},
                   "cuadro_before": before, "cuadro_after": after}
    upd = {"$set": {"ubo_confirmation": None,
                    "sections.documentation.slots.beneficial_owners": None,
                    "updated_at": utc_now()},
           "$push": {"ubo_confirmation_history": invalidated}}
    if ((case.get("sections") or {}).get("documentation")
            or {}).get("status") in ("completed", "resubmitted"):
        upd["$set"]["sections.documentation.status"] = "pending"
    await col(KYB_CASES).update_one({"case_id": case["case_id"]}, upd)
    await kyb_audit("kyb.ubo.confirmation_invalidated",
                    case_id=case["case_id"], actor=ctx["user"],
                    request=request, org_id=case.get("org_id"),
                    metadata={"action": action, "ubo_id": ubo_id,
                              "ubo_name": ubo_name,
                              "cuadro_anterior": before,
                              "cuadro_nuevo": after,
                              "acknowledgment_archivado": conf})


class UboIn(BaseModel):
    control_type: Literal["OWNERSHIP", "CONTROL_BODY"] = "OWNERSHIP"
    first_name: str = Field(..., min_length=1, max_length=80)
    last_name: str = Field(..., min_length=1, max_length=80)
    birth_date: Optional[str] = None
    nationality: Optional[str] = None
    address: Optional[str] = None
    marital_status: Optional[str] = None
    profession: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    document_number: Optional[str] = None
    tax_id: Optional[str] = None
    ownership_percentage: Optional[float] = None
    relationship_start_date: Optional[str] = None
    is_obliged_subject: bool = False
    is_pep: bool = False
    document_front_id: Optional[str] = None
    document_back_id: Optional[str] = None


def _validate_ubo(body: UboIn) -> None:
    if body.control_type == "OWNERSHIP":
        if not _pct_ok(body.ownership_percentage):
            raise HTTPException(422, "El porcentaje de participación debe "
                                     "estar entre 0 y 100, con hasta dos "
                                     "decimales")
    elif body.ownership_percentage is not None:
        raise HTTPException(422, "La declaración de control por órgano no "
                                 "lleva porcentaje de participación")
    if not body.document_front_id:
        raise HTTPException(422, "El frente del documento de identidad es "
                                 "obligatorio")


async def _ubo_mutation_guard(ctx, request, before, action, ubo_id,
                              ubo_name) -> None:
    after = _cuadro(await _ubos(ctx["case"]["case_id"]))
    await _invalidate_ubo_confirmation(ctx, request, before, after,
                                       action, ubo_id, ubo_name)


@router.post("/ubos")
async def create_ubo(body: UboIn, request: Request,
                     ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "documentation")
    _validate_ubo(body)
    case_id = ctx["case"]["case_id"]
    before = _cuadro(await _ubos(case_id))
    # Vínculo declarativo UBO ↔ representante legal por coincidencia de
    # CUIT/CUIL — no fusiona datos ni bloquea nada: existe para que el
    # orquestador (Fase 5b) reutilice el mismo sujeto externo y no cree
    # dos applicants para la misma persona.
    rep_tax = await _rep_tax_id(case_id)
    also_rep = bool(rep_tax) and _norm_tax(body.tax_id) == rep_tax
    ubo = KybBeneficialOwner(case_id=case_id, **body.model_dump(),
                             is_also_legal_representative=also_rep)
    await col(KYB_BENEFICIAL_OWNERS).insert_one(ubo.model_dump())
    await _link_ubo_documents(case_id, ubo.ubo_id,
                              [body.document_front_id, body.document_back_id])
    await kyb_audit("kyb.ubo.created", case_id=case_id,
                    actor=ctx["user"], request=request,
                    org_id=ctx["case"].get("org_id"),
                    metadata={"ubo_id": ubo.ubo_id,
                              "control_type": body.control_type,
                              "is_also_legal_representative": also_rep})
    await _ubo_mutation_guard(ctx, request, before, "created", ubo.ubo_id,
                              f"{body.first_name} {body.last_name}")
    if ctx["case"]["status"] == "draft":
        await apply_transition(ctx["case"], "in_progress",
                               actor_type="client", actor=ctx["user"],
                               request=request,
                               metadata={"trigger": "ubo_created"})
    return {"ok": True, "ubo_id": ubo.ubo_id,
            "is_also_legal_representative": also_rep}


@router.put("/ubos/{ubo_id}")
async def update_ubo(ubo_id: str, body: UboIn, request: Request,
                     ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "documentation")
    _validate_ubo(body)
    case_id = ctx["case"]["case_id"]
    existing = await col(KYB_BENEFICIAL_OWNERS).find_one(
        {"ubo_id": ubo_id, "case_id": case_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Beneficiario no encontrado")
    before = _cuadro(await _ubos(case_id))
    rep_tax = await _rep_tax_id(case_id)
    also_rep = bool(rep_tax) and _norm_tax(body.tax_id) == rep_tax
    await col(KYB_BENEFICIAL_OWNERS).update_one(
        {"ubo_id": ubo_id, "case_id": case_id},
        {"$set": {**body.model_dump(),
                  "is_also_legal_representative": also_rep,
                  "updated_at": utc_now()}})
    await _link_ubo_documents(case_id, ubo_id,
                              [body.document_front_id, body.document_back_id])
    await kyb_audit("kyb.ubo.updated", case_id=case_id,
                    actor=ctx["user"], request=request,
                    org_id=ctx["case"].get("org_id"),
                    metadata={"ubo_id": ubo_id,
                              "is_also_legal_representative": also_rep})
    await _ubo_mutation_guard(ctx, request, before, "updated", ubo_id,
                              f"{body.first_name} {body.last_name}")
    return {"ok": True, "is_also_legal_representative": also_rep}


@router.delete("/ubos/{ubo_id}")
async def delete_ubo(ubo_id: str, request: Request,
                     ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "documentation")
    case_id = ctx["case"]["case_id"]
    before = _cuadro(await _ubos(case_id))
    row = await col(KYB_BENEFICIAL_OWNERS).find_one(
        {"ubo_id": ubo_id, "case_id": case_id}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Beneficiario no encontrado")
    await col(KYB_BENEFICIAL_OWNERS).delete_one(
        {"ubo_id": ubo_id, "case_id": case_id})
    name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
    await kyb_audit("kyb.ubo.deleted", case_id=case_id,
                    actor=ctx["user"], request=request,
                    org_id=ctx["case"].get("org_id"),
                    metadata={"ubo_id": ubo_id, "ubo_name": name})
    await _ubo_mutation_guard(ctx, request, before, "deleted", ubo_id, name)
    return {"ok": True}


class UboConfirmIn(BaseModel):
    declaration: bool = False
    acknowledge_incomplete: bool = False


@router.post("/ubos/confirm")
async def confirm_ubos(body: UboConfirmIn, request: Request,
                       ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    _guard_editable(ctx["case"], "documentation")
    if not body.declaration:
        raise HTTPException(422, "La declaración jurada es obligatoria")
    case_id = ctx["case"]["case_id"]
    ubos = await _ubos(case_id)
    if not ubos:
        raise HTTPException(422, "Cargá al menos un beneficiario final o "
                                 "declará el control por órgano societario")
    total = _ownership_total(ubos)
    only_control_body = all(u.get("control_type") == "CONTROL_BODY"
                            for u in ubos)
    if total > 100:
        raise HTTPException(422, f"La participación declarada suma {total}% "
                                 "(supera el 100%). Corregí los porcentajes")
    conf = {"declared_at": utc_now(), "declared_by": ctx["user"].user_id,
            "total_percentage": total, "acknowledged_incomplete": False,
            "acknowledged_incomplete_at": None,
            "ownership_percentage_at_acknowledgment": None,
            "cuadro": _cuadro(ubos)}
    if total < 100 and not only_control_body:
        if not body.acknowledge_incomplete:
            raise HTTPException(409, {"code": "OWNERSHIP_BELOW_100",
                                      "total_percentage": total})
        # Snapshot: % exacto al momento de aceptar continuar — si después
        # el cuadro cambia, el analista ve ambos números por separado.
        conf.update({"acknowledged_incomplete": True,
                     "acknowledged_incomplete_at": utc_now(),
                     "ownership_percentage_at_acknowledgment": total})
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"ubo_confirmation": conf,
                  "sections.documentation.slots.beneficial_owners":
                      "confirmed", "updated_at": utc_now()}})
    await kyb_audit("kyb.ubo.confirmed", case_id=case_id,
                    actor=ctx["user"], request=request,
                    org_id=ctx["case"].get("org_id"), metadata=dict(conf))
    fresh = await col(KYB_CASES).find_one({"case_id": case_id}, {"_id": 0})
    slots = ((fresh.get("sections") or {}).get("documentation")
             or {}).get("slots") or {}
    if all(slots.get(s) == "confirmed" for s in ALL_DOC_SUBSECTIONS):
        await _mark_section(ctx, "documentation", request, draft=False)
    elif ctx["case"]["status"] == "draft":
        await apply_transition(ctx["case"], "in_progress",
                               actor_type="client", actor=ctx["user"],
                               request=request,
                               metadata={"trigger": "ubo_confirm"})
    return {"ok": True, "confirmation": conf}


async def _submit_blockers(case: dict) -> list[dict]:
    """Faltantes estructurados para el envío a revisión — nunca strings
    planos. Compartido por GET /case (can_submit) y POST /submit."""
    missing: list[dict] = []
    for k in ("tax_identification", "legal_representative", "company_data",
              "documentation"):
        st = ((case.get("sections") or {}).get(k) or {}).get("status")
        if st not in ("completed", "resubmitted"):
            missing.append({"code": "SECTION_INCOMPLETE", "section": k,
                            "description": f"La sección {k} no está "
                                           "completa"})
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case["case_id"]}, {"_id": 0}) or {}
    for slot in REQUIRED_DOCS.get(profile.get("legal_structure") or "OTRA",
                                  PHASE3_SLOTS):
        if slot == "funds_origin_evidence" and \
                profile.get("recently_incorporated_declared"):
            continue
        if not await col(KYB_DOCUMENTS).find_one(
                {"case_id": case["case_id"], "slot": slot,
                 "is_current": True}, {"_id": 1}):
            missing.append({"code": "DOCUMENT_MISSING",
                            "section": "documentation",
                            "description": f"Falta al menos un documento "
                                           f"vigente en {slot}"})
    ubos = await _ubos(case["case_id"])
    if not ubos:
        missing.append({"code": "UBO_MISSING", "section": "documentation",
                        "description": "Cargá al menos un beneficiario "
                        "final o declará el control por órgano"})
    total = _ownership_total(ubos)
    if total > 100:
        # Un cuadro que suma más de 100% es un dato imposible: no puede
        # llegar a revisión sin importar por qué camino se armó.
        missing.append({"code": "OWNERSHIP_EXCEEDS_100",
                        "section": "documentation",
                        "description": f"La participación declarada suma "
                                       f"{total}% (supera el 100%)"})
    if not (case.get("ubo_confirmation") or {}).get("declared_at"):
        missing.append({"code": "UBO_NOT_CONFIRMED",
                        "section": "documentation",
                        "description": "Confirmá el cuadro societario con "
                        "la declaración jurada"})
    return missing


@router.post("/submit")
async def submit_case(request: Request, ctx: dict = Depends(get_case_ctx)):
    _require_admin(ctx["user"])
    case = ctx["case"]
    if case["status"] not in ("in_progress", "info_required"):
        raise HTTPException(403, READONLY_MESSAGE)
    missing = await _submit_blockers(case)
    if missing:
        raise HTTPException(422, {"missing": missing})
    # Fase 5a — snapshot: el expediente conserva los modos de verificación
    # vigentes al momento del envío (kyb_verification_modes → caso). Sin
    # esto habría legajos mitad manuales y mitad automáticos sin poder
    # explicar cuál es cuál ante una auditoría.
    from kyb.models import VERIFICATION_CATEGORIES
    from kyb.verification_modes import get_verification_modes
    live = await get_verification_modes()
    snapshot = {c: (live.get(c) or {}).get("mode", "manual")
                for c in VERIFICATION_CATEGORIES}
    states = {c: {"state": "manual" if snapshot[c] == "manual"
                  else "automatic", "updated_at": utc_now()}
              for c in VERIFICATION_CATEGORIES}
    await col(KYB_CASES).update_one(
        {"case_id": case["case_id"]},
        {"$set": {"verification_modes": snapshot,
                  "verification_states": states,
                  "updated_at": utc_now()}})
    fields = await apply_transition(case, "submitted", actor_type="client",
                                    actor=ctx["user"], request=request)
    conf = case.get("ubo_confirmation") or {}
    await kyb_audit("kyb.case.submitted", case_id=case["case_id"],
                    actor=ctx["user"], request=request,
                    org_id=case.get("org_id"),
                    metadata={"acknowledged_incomplete":
                              conf.get("acknowledged_incomplete"),
                              "total_percentage":
                              conf.get("total_percentage")})
    fresh = await col(KYB_CASES).find_one({"case_id": case["case_id"]},
                                          {"_id": 0})
    if fresh:
        # F8-fix (post-diag 6 puntos): orquestador único. Idempotente y
        # resiliente — si falla la generación de checklists de alguna
        # categoría, el caso avanza igual y el error queda visible en
        # `case.dispatch_state`.
        from kyb.orchestrator import dispatch_on_submit
        await dispatch_on_submit(fresh, actor=ctx["user"], request=request)
        fresh = await col(KYB_CASES).find_one({"case_id": case["case_id"]},
                                              {"_id": 0})
        await _notify_on_submit(fresh)
    return {"ok": True, "status": "submitted",
            "submitted_at": fields.get("submitted_at")}


# ---------------------------------------------------------------------------
# F8 — Notificaciones de submit por el dispatcher central (fuera del
# endpoint para no bloquear la respuesta con el envío).
# ---------------------------------------------------------------------------
async def _notify_on_submit(case: dict) -> None:
    from kyb.notifications import notify as _notify
    company = case.get("company_name_declared") or ""
    if case.get("applicant_email"):
        try:
            await _notify("kyb.case.submitted", case_id=case["case_id"],
                          recipient=case["applicant_email"],
                          context={"company_name": company})
        except Exception:  # pragma: no cover — envío no bloquea el flujo
            pass
    inbox = os.environ.get("COMPLIANCE_INBOX_EMAIL")
    if inbox:
        try:
            await _notify("kyb.case.submitted", case_id=case["case_id"],
                          recipient=inbox, discriminator="internal",
                          context={"company_name": company})
        except Exception:  # pragma: no cover
            pass
