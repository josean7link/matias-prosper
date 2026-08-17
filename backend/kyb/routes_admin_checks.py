"""Fase 5a — Endpoints admin de verificación manual.

Prefijo /api/v1/admin/compliance/kyb. IMPORTANTE: este router se registra
ANTES que el router legacy de compliance (que tiene GET /{case_id}
catch-all) para que las rutas literales de acá ganen el match. No hay
middleware global en backend: CADA ruta lleva su Depends explícito.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import List, Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile)
from pydantic import BaseModel, Field

from auth import CurrentUser, requires_role
from db import col
from models import utc_now
from roles import Role
from routes.compliance._deps import require_compliance, \
    require_compliance_decide
from services.file_validator import FileValidationError, validate_file
from services.storage import get_storage
from kyb.audit import kyb_audit
from kyb.manual_checks import complete_check, generate_checks
from kyb.orchestrator import TRIGGER_RETRY, dispatch_on_submit
from kyb.models import (CATEGORY_MODES, KYB_CASES, KYB_DOCUMENTS,
                        KYB_MANUAL_CHECKS, KYB_MANUAL_CHECK_TEMPLATES,
                        VERIFICATION_CATEGORIES, KybDocument,
                        KybManualCheckTemplate)
from kyb.verification_modes import get_verification_modes, \
    set_verification_mode

router = APIRouter(prefix="/admin/compliance/kyb", tags=["kyb-admin-manual"])

require_super_admin = requires_role(Role.super_admin)


async def _new_case(case_id: str) -> dict:
    case = await col(KYB_CASES).find_one(
        {"case_id": case_id, "is_deleted": False,
         "verification_modes": {"$exists": True}}, {"_id": 0})
    if not case:
        raise HTTPException(404, "Caso del módulo KYB nuevo no encontrado")
    return case


async def _check(check_id: str) -> dict:
    row = await col(KYB_MANUAL_CHECKS).find_one({"check_id": check_id},
                                                {"_id": 0})
    if not row:
        raise HTTPException(404, "Checklist no encontrado")
    return row


# ---------------------------------------------------------------------------
# Modos de verificación
# ---------------------------------------------------------------------------
@router.get("/verification-modes")
async def get_modes(_: CurrentUser = Depends(require_compliance)):
    return await get_verification_modes()


class ModeIn(BaseModel):
    mode: str


@router.put("/verification-modes/{category}")
async def put_mode(category: str, body: ModeIn, request: Request,
                   user: CurrentUser = Depends(require_super_admin)):
    out = await set_verification_mode(category, body.mode, user.user_id)
    await kyb_audit("kyb.verification_modes.updated", case_id="global",
                    actor=user, request=request,
                    metadata={"category": category, "mode": body.mode,
                              "environment": out["environment"]})
    return out


# ---------------------------------------------------------------------------
# Plantillas de checklist (editables por Compliance sin deploy)
# ---------------------------------------------------------------------------
class TemplateItemIn(BaseModel):
    item_key: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=3, max_length=200)
    description: str = ""
    source_url: Optional[str] = None
    evidence_required: bool = False
    possible_outcomes: List[str] = Field(..., min_length=1)
    order: int = 0


class TemplateIn(BaseModel):
    category: str
    country: Optional[str] = None
    subject_types: List[str] = Field(..., min_length=1)
    active: bool = True
    items: List[TemplateItemIn] = Field(..., min_length=1)


def _validate_template(body: TemplateIn) -> None:
    if body.category not in VERIFICATION_CATEGORIES:
        raise HTTPException(422, f"category debe ser una de "
                                 f"{VERIFICATION_CATEGORIES}")
    if bad := [t for t in body.subject_types
               if t not in ("company", "legal_representative", "ubo")]:
        raise HTTPException(422, f"subject_types inválidos: {bad}")
    keys = [i.item_key for i in body.items]
    if len(keys) != len(set(keys)):
        raise HTTPException(422, "item_key duplicado en la plantilla")


@router.get("/templates")
async def list_templates(_: CurrentUser = Depends(require_compliance)):
    rows = await col(KYB_MANUAL_CHECK_TEMPLATES).find(
        {}, {"_id": 0}).sort([("category", 1), ("version", -1)]).to_list(200)
    return {"items": rows}


@router.post("/templates")
async def create_template(body: TemplateIn, request: Request,
                          user: CurrentUser = Depends(require_super_admin)):
    _validate_template(body)
    tpl = KybManualCheckTemplate(
        template_id=f"tpl_{uuid.uuid4().hex[:12]}", category=body.category,
        country=body.country, subject_types=body.subject_types,
        version=1, active=body.active,
        items=[i.model_dump() for i in body.items], updated_by=user.user_id)
    await col(KYB_MANUAL_CHECK_TEMPLATES).insert_one(tpl.model_dump())
    await kyb_audit("kyb.template.created", case_id="global", actor=user,
                    request=request,
                    metadata={"template_id": tpl.template_id,
                              "category": body.category, "version": 1})
    return {"ok": True, "template_id": tpl.template_id, "version": 1}


@router.put("/templates/{template_id}")
async def update_template(template_id: str, body: TemplateIn,
                          request: Request,
                          user: CurrentUser = Depends(require_super_admin)):
    _validate_template(body)
    prev = await col(KYB_MANUAL_CHECK_TEMPLATES).find(
        {"template_id": template_id},
        {"version": 1}).sort("version", -1).limit(1).to_list(1)
    if not prev:
        raise HTTPException(404, "Plantilla no encontrada")
    version = prev[0]["version"] + 1
    # Versionado: cada edición inserta versión nueva; los checks en curso
    # conservan template_version con el que se generaron.
    tpl = KybManualCheckTemplate(
        template_id=template_id, category=body.category,
        country=body.country, subject_types=body.subject_types,
        version=version, active=body.active,
        items=[i.model_dump() for i in body.items], updated_by=user.user_id)
    await col(KYB_MANUAL_CHECK_TEMPLATES).update_many(
        {"template_id": template_id, "version": {"$lt": version}},
        {"$set": {"active": False, "updated_at": utc_now()}})
    await col(KYB_MANUAL_CHECK_TEMPLATES).insert_one(tpl.model_dump())
    await kyb_audit("kyb.template.updated", case_id="global", actor=user,
                    request=request,
                    metadata={"template_id": template_id,
                              "version": version, "active": body.active})
    return {"ok": True, "template_id": template_id, "version": version}


# ---------------------------------------------------------------------------
# Checklists por caso
# ---------------------------------------------------------------------------
@router.get("/cases/{case_id}/manual-checks")
async def list_checks(case_id: str,
                      _: CurrentUser = Depends(require_compliance)):
    case = await _new_case(case_id)
    checks = await col(KYB_MANUAL_CHECKS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(200)
    evidence_docs = await col(KYB_DOCUMENTS).find(
        {"case_id": case_id, "slot": "manual_check_evidence"},
        {"_id": 0, "storage_key": 0}).to_list(500)
    # Metadata mínima del caso para la vista provisional (el detalle
    # completo del módulo nuevo llega con la bandeja de la Fase 6).
    return {"case": {"case_id": case["case_id"], "status": case["status"],
                     "company_name": case.get("company_name_declared"),
                     "country": case.get("country_of_incorporation"),
                     "verification_modes": case.get("verification_modes"),
                     "verification_states": case.get("verification_states"),
                     "submitted_at": case.get("submitted_at")},
            "checks": checks,
            "evidence_documents": evidence_docs}


@router.post("/cases/{case_id}/manual-checks/generate")
async def generate(case_id: str, request: Request,
                   user: CurrentUser = Depends(require_compliance)):
    case = await _new_case(case_id)
    if case["status"] not in ("submitted", "screening", "under_review",
                              "info_required"):
        raise HTTPException(409, "Los checklists se generan sobre "
                                 "expedientes enviados a revisión")
    # F8-bugfix 6: el botón "Generar checklists" pasa por el orquestador
    # (mismo camino que el submit del cliente). Es idempotente y avanza
    # el caso a `screening` / `under_review` si corresponde.
    result = await dispatch_on_submit(case, actor=user, request=request,
                                      trigger=TRIGGER_RETRY)
    checks_created = 0
    for cat in (result.get("dispatch_state") or {}).get("categories", []):
        checks_created += int(cat.get("checks_created") or 0)
    return {"ok": True, "created": checks_created,
            "advanced_to": result.get("advanced_to"),
            "errors": (result.get("dispatch_state") or {}).get("errors", [])}


class ItemPatch(BaseModel):
    outcome: str
    notes: str
    evidence_document_ids: List[str] = []


@router.patch("/manual-checks/{check_id}/items/{item_key}")
async def patch_item(check_id: str, item_key: str, body: ItemPatch,
                     request: Request,
                     user: CurrentUser = Depends(require_compliance)):
    check = await _check(check_id)
    if check["status"] == "completed":
        raise HTTPException(409, "El checklist ya fue completado")
    item = next((i for i in check["items"] if i["item_key"] == item_key),
                None)
    if not item:
        raise HTTPException(404, "Ítem no encontrado")
    if body.outcome not in (item.get("possible_outcomes") or []):
        raise HTTPException(422, f"outcome debe ser uno de "
                                 f"{item.get('possible_outcomes')}")
    if len(body.notes.strip()) < 10:
        raise HTTPException(422, "Las notas del verificador son "
                                 "obligatorias: mínimo 10 caracteres (sin "
                                 "relleno)")
    evidence = [e for e in body.evidence_document_ids if e]
    if item.get("evidence_required") and not evidence:
        raise HTTPException(422, "Este ítem exige al menos un documento de "
                                 "evidencia adjunto")
    if evidence:
        n = await col(KYB_DOCUMENTS).count_documents(
            {"case_id": check["case_id"], "document_id": {"$in": evidence},
             "slot": "manual_check_evidence", "is_current": True,
             "discarded": None})
        if n != len(evidence):
            raise HTTPException(422, "Evidencia inválida: documentos "
                                     "inexistentes, descartados o de otro "
                                     "caso")
    now = utc_now()
    await col(KYB_MANUAL_CHECKS).update_one(
        {"check_id": check_id, "items.item_key": item_key},
        {"$set": {"items.$.outcome": body.outcome,
                  "items.$.notes": body.notes.strip(),
                  "items.$.evidence_document_ids": evidence,
                  "items.$.completed_by": user.user_id,
                  "items.$.completed_at": now,
                  "status": "in_progress", "updated_at": now},
         "$addToSet": {"contributors": user.user_id}})
    await kyb_audit("kyb.manual_check.item_completed",
                    case_id=check["case_id"], actor=user, request=request,
                    metadata={"check_id": check_id, "item_key": item_key,
                              "outcome": body.outcome,
                              "evidence_count": len(evidence)})
    return {"ok": True}


@router.post("/manual-checks/{check_id}/evidence")
async def upload_evidence(check_id: str, request: Request,
                          item_key: str = Form(...),
                          file: UploadFile = File(...),
                          user: CurrentUser = Depends(require_compliance)):
    check = await _check(check_id)
    if check["status"] == "completed":
        raise HTTPException(409, "El checklist ya fue completado")
    content = await file.read()
    try:
        detected = validate_file(file.filename or "archivo", content)
    except FileValidationError as e:
        raise HTTPException(422, str(e))
    storage = get_storage()
    storage_key = await storage.put(
        content=content, filename=file.filename or "archivo",
        content_type=detected,
        metadata={"uploaded_by": user.user_id, "scope_kind": "kyb_case",
                  "scope_id": check["case_id"]})
    try:
        # A diferencia de los slots del expediente, CADA evidencia queda
        # vigente (no se apaga la anterior): un ítem puede acumular varias.
        prev = await col(KYB_DOCUMENTS).find(
            {"case_id": check["case_id"], "slot": "manual_check_evidence",
             "check_id": check_id},
            {"version": 1}).sort("version", -1).limit(1).to_list(1)
        version = (prev[0]["version"] + 1) if prev else 1
        doc = KybDocument(case_id=check["case_id"],
                          slot="manual_check_evidence", version=version,
                          filename=file.filename, content_type=detected,
                          size_bytes=len(content), storage_key=storage_key,
                          sha256=hashlib.sha256(content).hexdigest(),
                          description=f"Evidencia {check_id}/{item_key}",
                          uploaded_by=user.user_id, uploaded_via="owner",
                          check_id=check_id)
        await col(KYB_DOCUMENTS).insert_one(doc.model_dump())
    except Exception:
        await storage.delete(storage_key)
        raise
    await kyb_audit("kyb.document.uploaded", case_id=check["case_id"],
                    actor=user, request=request,
                    metadata={"slot": "manual_check_evidence",
                              "check_id": check_id, "item_key": item_key,
                              "document_id": doc.document_id,
                              "version": version, "sha256": doc.sha256})
    out = doc.model_dump()
    out.pop("storage_key", None)
    return out


class EvidenceDiscardIn(BaseModel):
    reason: str = Field(..., min_length=10, max_length=500)


@router.post("/manual-checks/{check_id}/evidence/{document_id}/discard")
async def discard_evidence(check_id: str, document_id: str,
                           body: EvidenceDiscardIn, request: Request,
                           user: CurrentUser = Depends(require_compliance)):
    """Marca una evidencia como descartada. NO se borra (es evidencia: la
    trazabilidad importa) — deja de contar para el requisito del ítem y
    en la exportación del legajo (F7) aparece en sección aparte."""
    check = await _check(check_id)
    doc = await col(KYB_DOCUMENTS).find_one(
        {"document_id": document_id, "check_id": check_id,
         "slot": "manual_check_evidence"}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Evidencia no encontrada en este checklist")
    if doc.get("discarded"):
        raise HTTPException(409, "La evidencia ya fue descartada")
    now = utc_now()
    await col(KYB_DOCUMENTS).update_one(
        {"document_id": document_id},
        {"$set": {"discarded": {"at": now, "by": user.user_id,
                                "reason": body.reason.strip()},
                  "updated_at": now}})
    reset_items = []
    if check["status"] != "completed":
        # Checklist abierto: la evidencia se quita de los ítems que la
        # referencian; si un ítem con evidencia obligatoria queda sin
        # ninguna vigente, su resultado se anula y debe re-completarse.
        for item in check["items"]:
            if document_id not in (item.get("evidence_document_ids") or []):
                continue
            remaining = [e for e in item["evidence_document_ids"]
                         if e != document_id]
            upd = {"items.$.evidence_document_ids": remaining,
                   "updated_at": now}
            if item.get("evidence_required") and not remaining \
                    and item.get("outcome"):
                upd.update({"items.$.outcome": None, "items.$.notes": None,
                            "items.$.completed_by": None,
                            "items.$.completed_at": None})
                reset_items.append(item["item_key"])
            await col(KYB_MANUAL_CHECKS).update_one(
                {"check_id": check_id, "items.item_key": item["item_key"]},
                {"$set": upd})
    await kyb_audit("kyb.manual_check.evidence_discarded",
                    case_id=check["case_id"], actor=user, request=request,
                    metadata={"check_id": check_id,
                              "document_id": document_id,
                              "reason": body.reason.strip(),
                              "check_status": check["status"],
                              "reset_items": reset_items})
    return {"ok": True, "reset_items": reset_items}


@router.post("/manual-checks/{check_id}/complete")
async def complete(check_id: str, request: Request,
                   user: CurrentUser = Depends(require_compliance)):
    check = await _check(check_id)
    if check["status"] == "completed":
        raise HTTPException(409, "El checklist ya fue completado")
    if pending := [i["item_key"] for i in check["items"]
                   if not i.get("outcome")]:
        raise HTTPException(422, {"pending_items": pending})
    result = await complete_check(check, user, request)
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Force-manual (decisión de gestión → require_compliance_decide)
# ---------------------------------------------------------------------------
class ForceManualIn(BaseModel):
    category: str
    reason: str = Field(..., min_length=10, max_length=500)


@router.post("/cases/{case_id}/force-manual")
async def force_manual(case_id: str, body: ForceManualIn, request: Request,
                       user: CurrentUser =
                       Depends(require_compliance_decide)):
    case = await _new_case(case_id)
    if body.category not in VERIFICATION_CATEGORIES:
        raise HTTPException(422, f"category debe ser una de "
                                 f"{VERIFICATION_CATEGORIES}")
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {f"verification_states.{body.category}": {
            "state": "manual_forced", "reason": body.reason.strip(),
            "updated_by": user.user_id, "updated_at": utc_now()},
            "updated_at": utc_now()}})
    await kyb_audit("kyb.case.forced_manual", case_id=case_id, actor=user,
                    request=request, org_id=case.get("org_id"),
                    metadata={"category": body.category,
                              "reason": body.reason.strip()})
    fresh = await _new_case(case_id)
    created = await generate_checks(fresh, user, request)
    return {"ok": True, "state": "manual_forced",
            "checks_created": len(created)}
