"""Fase 6 — Portal Admin KYB: bandeja, detalle, decisión.

Reemplaza la bandeja legacy (los endpoints viejos redirigen acá con el
flag encendido). Cada ruta declara su Depends explícito: no hay
middleware global en backend.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from auth import CurrentUser, requires_role
from db import col
from models import utc_now
from roles import Role
from routes.compliance._deps import require_compliance, \
    require_compliance_decide
from kyb.audit import kyb_audit
from kyb.manual_checks import enforce_maker_checker
from kyb.models import (KYB_BENEFICIAL_OWNERS, KYB_CASES,
                        KYB_COMPANY_PROFILES, KYB_DOCUMENTS,
                        KYB_MANUAL_CHECKS, KYB_MANUAL_CHECK_TEMPLATES,
                        KYB_SCREENING_HITS,
                        KYB_VERIFICATIONS, VERIFICATION_CATEGORIES)
from kyb.state_machine import apply_transition

router = APIRouter(prefix="/admin/compliance/kyb", tags=["kyb-admin-cases"])

CLIENT_SECTIONS = ("tax_identification", "legal_representative",
                   "company_data", "documentation", "team")
REVIEWABLE = CLIENT_SECTIONS[:4]
REJECT_REASON_CODES = ["sanctions_hit", "fraud_suspicion",
                       "incomplete_information", "unsupported_jurisdiction",
                       "high_risk_activity", "regulatory_restriction",
                       "other"]
DECIDABLE = ("under_review",)   # F8-fix: aprobar/rechazar/pedir info solo


def _sla_hours() -> int:
    return int(os.environ.get("KYB_SLA_HOURS", "72"))


def _sla_state(submitted_at) -> Optional[str]:
    if not submitted_at:
        return None
    if isinstance(submitted_at, str):
        submitted_at = datetime.fromisoformat(submitted_at)
    if submitted_at.tzinfo is None:
        submitted_at = submitted_at.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - submitted_at).total_seconds() / 3600
    ratio = elapsed / _sla_hours()
    return "green" if ratio < 0.7 else ("amber" if ratio <= 1 else "red")


async def _case(case_id: str) -> dict:
    case = await col(KYB_CASES).find_one(
        {"case_id": case_id, "is_deleted": False,
         "verification_modes": {"$exists": True}}, {"_id": 0})
    if not case:
        raise HTTPException(404, "Caso no encontrado")
    return case


async def _ensure_under_review(case: dict, user, request) -> dict:
    """DEPRECATED (post-diag 6 puntos): saltear submitted → under_review
    en el momento de aprobar equivalía a aprobar sin verificar cuando los
    checklists todavía no existían. Reemplazado por `kyb.orchestrator`,
    que corre al submit y solo transiciona si el trabajo real está hecho.

    Se mantiene el símbolo por si algún test lo importa; no debe usarse
    desde código de producción y lanza si se invoca.
    """
    raise RuntimeError(
        "_ensure_under_review fue removido. El avance de estado ocurre "
        "en kyb.orchestrator.dispatch_on_submit(); los endpoints de "
        "decisión sólo operan sobre under_review.")


async def _pending_checks(case_id: str) -> int:
    return await col(KYB_MANUAL_CHECKS).count_documents(
        {"case_id": case_id, "status": {"$ne": "completed"}})


async def _blocking_hits(case_id: str) -> int:
    return await col(KYB_SCREENING_HITS).count_documents(
        {"case_id": case_id, "is_blocking": True,
         "resolution": {"$in": [None]}})


# ---------------------------------------------------------------------------
# Bandeja
# ---------------------------------------------------------------------------
@router.get("/cases")
async def list_cases(status: Optional[str] = None,
                     risk_level: Optional[str] = None,
                     country: Optional[str] = None,
                     assigned_to: Optional[str] = None,
                     mine: bool = False,
                     reopened_by_alert: bool = False,
                     manual_pending: bool = False,
                     legacy: bool = False,
                     include_closed: bool = False,
                     include_drafts: bool = False,
                     q: Optional[str] = None,
                     page: int = 1, page_size: int = 25,
                     user: CurrentUser = Depends(require_compliance)):
    # F8-fix (post-diag 6 puntos): la bandeja de Compliance es trabajo
    # en curso. Los borradores del cliente NO son trabajo del analista y
    # ensucian el SLA; los cerrados no son trabajo activo. Ambos se
    # traen sólo con toggle explícito.
    ACTIVE = ["submitted", "screening", "under_review", "info_required"]
    DRAFTS = ["draft", "in_progress", "expired"]
    CLOSED = ["approved", "rejected"]
    query: dict = {"is_deleted": False,
                   "verification_modes": {"$exists": True}}
    if status:
        query["status"] = status
    else:
        allowed = list(ACTIVE)
        if include_drafts:
            allowed += DRAFTS
        if include_closed:
            allowed += CLOSED
        query["status"] = {"$in": allowed}
    if risk_level:
        query["risk.level"] = risk_level
    if country:
        query["country_of_incorporation"] = country.upper()
    if mine:
        query["assigned_to"] = user.user_id
    elif assigned_to:
        query["assigned_to"] = assigned_to
    if reopened_by_alert:
        query["reopen_reason"] = "provider_alert"
    if legacy:
        query["legacy_origin"] = {"$exists": True, "$ne": None}
    if q:
        import re as _re
        rx = {"$regex": _re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"company_name_declared": rx}, {"tax_id": rx},
                        {"legal_name": rx}]
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    total = await col(KYB_CASES).count_documents(query)
    rows = await col(KYB_CASES).find(query, {"_id": 0}) \
        .sort([("submitted_at", 1), ("created_at", 1)]) \
        .skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    items = []
    for c in rows:
        pending = await _pending_checks(c["case_id"])
        if manual_pending and pending == 0:
            continue
        prof = await col(KYB_COMPANY_PROFILES).find_one(
            {"case_id": c["case_id"]}, {"_id": 0, "legal_name": 1,
                                        "tax_id": 1})
        items.append({
            "case_id": c["case_id"],
            "company_name": (prof or {}).get("legal_name")
            or c.get("company_name_declared"),
            "tax_id": (prof or {}).get("tax_id") or c.get("tax_id"),
            "country": c.get("country_of_incorporation"),
            "status": c["status"],
            "risk_level": (c.get("risk") or {}).get("level"),
            "assigned_to": c.get("assigned_to"),
            "submitted_at": c.get("submitted_at"),
            "sla": _sla_state(c.get("submitted_at")),
            "blocking_hits": await _blocking_hits(c["case_id"]),
            "priority": c.get("priority"),
            "pending_checks": pending,
            "verification_modes": c.get("verification_modes"),
            "verification_states": {
                k: (v or {}).get("state") for k, v in
                (c.get("verification_states") or {}).items()},
            "reopen_reason": c.get("reopen_reason"),
            "legacy_origin": c.get("legacy_origin"),
            "suspended": bool(c.get("suspended")),
            "pending_second_approval": c.get("pending_second_approval"),
        })
    # Tablero de carga: checklists pendientes por analista asignado
    workload = await col(KYB_MANUAL_CHECKS).aggregate([
        {"$match": {"status": {"$ne": "completed"}}},
        {"$lookup": {"from": KYB_CASES, "localField": "case_id",
                     "foreignField": "case_id", "as": "case"}},
        {"$unwind": "$case"},
        {"$group": {"_id": "$case.assigned_to", "pending": {"$sum": 1}}},
    ]).to_list(100)
    return {"items": items, "total": total, "page": page,
            "page_size": page_size, "sla_hours": _sla_hours(),
            "workload": [{"assigned_to": w["_id"], "pending": w["pending"]}
                         for w in workload]}


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------
@router.get("/cases/{case_id}")
async def get_case_detail(case_id: str,
                          _: CurrentUser = Depends(require_compliance)):
    case = await _case(case_id)
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case_id}, {"_id": 0})
    ubos = await col(KYB_BENEFICIAL_OWNERS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(100)
    docs = await col(KYB_DOCUMENTS).find(
        {"case_id": case_id}, {"_id": 0, "storage_key": 0}) \
        .sort("created_at", 1).to_list(300)
    vers = await col(KYB_VERIFICATIONS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(100)
    hits = await col(KYB_SCREENING_HITS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(200)
    pending = await _pending_checks(case_id)
    return {"case": case, "profile": profile, "ubos": ubos,
            "documents": docs, "verifications": vers, "hits": hits,
            "pending_checks": pending,
            "blocking_hits": await _blocking_hits(case_id),
            "sla": _sla_state(case.get("submitted_at")),
            "reject_reason_codes": REJECT_REASON_CODES}


class AssignIn(BaseModel):
    assignee_user_id: Optional[str] = None   # None = desasignar


@router.post("/cases/{case_id}/assign")
async def assign_case(case_id: str, body: AssignIn, request: Request,
                      user: CurrentUser = Depends(require_compliance)):
    case = await _case(case_id)
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"assigned_to": body.assignee_user_id,
                  "updated_at": utc_now()}})
    await kyb_audit("kyb.case.assigned", case_id=case_id, actor=user,
                    request=request, org_id=case.get("org_id"),
                    metadata={"from": case.get("assigned_to"),
                              "to": body.assignee_user_id})
    return {"ok": True, "assigned_to": body.assignee_user_id}


class SectionReviewIn(BaseModel):
    action: str                                   # approve | observe
    observation: Optional[str] = Field(None, max_length=2000)


@router.post("/cases/{case_id}/sections/{section}/review")
async def review_section(case_id: str, section: str, body: SectionReviewIn,
                         request: Request,
                         user: CurrentUser = Depends(require_compliance)):
    case = await _case(case_id)
    if section not in REVIEWABLE:
        raise HTTPException(422, f"section debe ser una de {REVIEWABLE}")
    if case["status"] not in DECIDABLE:
        raise HTTPException(409, "El caso no está en revisión")
    if body.action not in ("approve", "observe"):
        raise HTTPException(422, "action debe ser approve u observe")
    upd = {f"sections.{section}.reviewed_by": user.user_id,
           f"sections.{section}.reviewed_at": utc_now(),
           "updated_at": utc_now()}
    push = {}
    if body.action == "observe":
        text = (body.observation or "").strip()
        if len(text) < 10:
            raise HTTPException(422, "Observar exige texto (mín. 10 "
                                     "caracteres). Este texto es "
                                     "EXACTAMENTE el que verá el cliente.")
        upd.update({f"sections.{section}.status": "observed",
                    f"sections.{section}.observation": text,
                    f"sections.{section}.observed_by": user.user_id,
                    f"sections.{section}.review_status": "observed"})
        push = {"$addToSet": {"observers": user.user_id}}
    else:
        upd[f"sections.{section}.review_status"] = "approved"
    await col(KYB_CASES).update_one({"case_id": case_id},
                                    {"$set": upd, **push})
    await kyb_audit("kyb.section.reviewed", case_id=case_id, actor=user,
                    request=request, org_id=case.get("org_id"),
                    metadata={"section": section, "action": body.action,
                              "observation": (body.observation or "").strip()
                              or None})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Decisión — tres endpoints separados
# ---------------------------------------------------------------------------
@router.post("/cases/{case_id}/request-info")
async def request_info(case_id: str, request: Request,
                       user: CurrentUser =
                       Depends(require_compliance_decide)):
    case = await _case(case_id)
    if case["status"] not in DECIDABLE:
        raise HTTPException(409, "El caso no está en revisión")
    observed = {k: (v or {}).get("observation") for k, v in
                (case.get("sections") or {}).items()
                if (v or {}).get("status") == "observed"}
    if not observed:
        raise HTTPException(422, "No hay secciones observadas: observá al "
                                 "menos una antes de solicitar información")
    if not case.get("applicant_email"):
        raise HTTPException(409, "El expediente no tiene contacto "
                                 "registrado. Registrá el email de "
                                 "contacto antes de solicitar información.")
    await apply_transition(case, "info_required", actor_type="internal",
                           actor=user, request=request,
                           metadata={"sections": list(observed)})
    from kyb.emails import send_request_info_email
    await send_request_info_email(case_id=case_id,
                                  recipient=case["applicant_email"],
                                  company_name=case.get(
                                      "company_name_declared") or "",
                                  observations=observed)
    # F8 — mismo evento por el dispatcher centralizado (idempotente).
    # `send_request_info_email` queda por compatibilidad histórica; el
    # dispatcher es el punto único que los tests deben mirar.
    from kyb.notifications import notify as _notify
    payload_key = "|".join(f"{k}:{v}" for k, v in sorted(observed.items()))
    import hashlib as _h
    await _notify("kyb.case.info_required", case_id=case_id,
                  recipient=case["applicant_email"],
                  context={"company_name":
                           case.get("company_name_declared") or "",
                           "sections": observed},
                  discriminator=_h.sha256(payload_key.encode()).hexdigest()[:16])
    await kyb_audit("kyb.case.request_info_sent", case_id=case_id,
                    actor=user, request=request,
                    org_id=case.get("org_id"),
                    metadata={"sections": observed})
    return {"ok": True, "status": "info_required",
            "sections": list(observed)}


class ApproveIn(BaseModel):
    maker_checker_override_reason: Optional[str] = None


@router.post("/cases/{case_id}/approve")
async def approve_case(case_id: str, request: Request,
                       body: ApproveIn = ApproveIn(),
                       user: CurrentUser =
                       Depends(require_compliance_decide)):
    case = await _case(case_id)
    if case["status"] not in DECIDABLE:
        raise HTTPException(409, "El caso no está en revisión")
    blockers = []
    if (n := await _blocking_hits(case_id)):
        blockers.append({"code": "BLOCKING_HITS", "count": n,
                         "description": f"{n} hit(s) bloqueante(s) sin "
                                        "resolver"})
    # Gate anti-atajo del modo manual: NINGÚN checklist puede quedar
    # incompleto — completar checklists es la verificación en sí.
    if (n := await _pending_checks(case_id)):
        blockers.append({"code": "MANUAL_CHECKS_PENDING", "count": n,
                         "description": f"{n} checklist(s) manual(es) sin "
                                        "completar"})
    unreviewed = [s for s in REVIEWABLE
                  if ((case.get("sections") or {}).get(s) or {})
                  .get("review_status") != "approved"]
    if unreviewed:
        blockers.append({"code": "SECTIONS_UNREVIEWED",
                         "sections": unreviewed,
                         "description": "Secciones sin revisar/aprobar: "
                                        + ", ".join(unreviewed)})
    if blockers:
        raise HTTPException(422, {"blockers": blockers})
    # Maker-checker (override super_admin ≥20 chars, auditado)
    await enforce_maker_checker(case_id, user,
                                body.maker_checker_override_reason, request)
    # Quien observó y reabrió el caso no puede aprobarlo (sin override)
    if user.user_id in (case.get("observers") or []):
        raise HTTPException(403, "Observaste secciones de este caso: no "
                                 "podés aprobarlo (cuatro ojos)")
    # Riesgo alto → segunda firma de OTRO usuario con rol de decisión
    risk_high = (case.get("risk") or {}).get("level") == "high"
    pending2 = case.get("pending_second_approval")
    if risk_high and not pending2:
        await col(KYB_CASES).update_one(
            {"case_id": case_id},
            {"$set": {"pending_second_approval": {
                "first_by": user.user_id, "first_at": utc_now(),
                "requires": "segunda firma de otro usuario con rol de "
                            "decisión (compliance_officer o super_admin)"},
                "updated_at": utc_now()}})
        await kyb_audit("kyb.case.approval_first_signature",
                        case_id=case_id, actor=user, request=request,
                        org_id=case.get("org_id"), metadata={})
        return {"ok": True, "pending_second_approval": True}
    if pending2 and pending2.get("first_by") == user.user_id:
        raise HTTPException(403, "La segunda firma debe darla otro "
                                 "usuario con rol de decisión")
    await apply_transition(case, "approved", actor_type="internal",
                           actor=user, request=request)
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"pending_second_approval": None, "updated_at": utc_now()}})
    from kyb.provisioning import emit_case_approved
    await emit_case_approved(case, approved_by=user.user_id)
    await kyb_audit("kyb.case.approved", case_id=case_id, actor=user,
                    request=request, org_id=case.get("org_id"),
                    metadata={"second_signature": bool(pending2)})
    # F8 — aviso al solicitante.
    if case.get("applicant_email"):
        from kyb.notifications import notify as _notify
        await _notify("kyb.case.approved", case_id=case_id,
                      recipient=case["applicant_email"],
                      context={"company_name":
                               case.get("company_name_declared") or ""})
    return {"ok": True, "status": "approved"}


class RejectIn(BaseModel):
    reason_code: str
    notes: str = Field(..., min_length=10, max_length=2000)


@router.post("/cases/{case_id}/reject")
async def reject_case(case_id: str, body: RejectIn, request: Request,
                      user: CurrentUser =
                      Depends(require_compliance_decide)):
    case = await _case(case_id)
    if case["status"] not in DECIDABLE:
        raise HTTPException(409, "El caso no está en revisión")
    if body.reason_code not in REJECT_REASON_CODES:
        raise HTTPException(422, f"reason_code debe ser uno de "
                                 f"{REJECT_REASON_CODES}")
    await apply_transition(case, "rejected", actor_type="internal",
                           actor=user, request=request,
                           metadata={"reason_code": body.reason_code})
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"resolution": {"decision": "rejected",
                                 "reason_code": body.reason_code,
                                 "notes": body.notes.strip(),
                                 "decided_by": user.user_id,
                                 "decided_at": utc_now()},
                  "updated_at": utc_now()}})
    await kyb_audit("kyb.case.rejected", case_id=case_id, actor=user,
                    request=request, org_id=case.get("org_id"),
                    metadata={"reason_code": body.reason_code,
                              "notes": body.notes.strip()})
    # F8 — aviso al solicitante.
    if case.get("applicant_email"):
        from kyb.notifications import notify as _notify
        await _notify("kyb.case.rejected", case_id=case_id,
                      recipient=case["applicant_email"],
                      context={"company_name":
                               case.get("company_name_declared") or "",
                               "reason": body.notes.strip()},
                      discriminator=body.reason_code)
    return {"ok": True, "status": "rejected"}


class ReasonIn(BaseModel):
    reason: str = Field(..., min_length=10, max_length=1000)


@router.post("/cases/{case_id}/suspend")
async def suspend_case(case_id: str, body: ReasonIn, request: Request,
                       user: CurrentUser =
                       Depends(require_compliance_decide)):
    case = await _case(case_id)
    if case["status"] != "approved":
        raise HTTPException(409, "Solo se suspende la operatoria de un "
                                 "caso aprobado")
    if case.get("suspended"):
        raise HTTPException(409, "La operatoria ya está suspendida")
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"suspended": {"at": utc_now(), "by": user.user_id,
                                "reason": body.reason.strip()},
                  "updated_at": utc_now()}})
    await kyb_audit("kyb.case.suspended", case_id=case_id, actor=user,
                    request=request, org_id=case.get("org_id"),
                    metadata={"reason": body.reason.strip()})
    return {"ok": True}


@router.post("/cases/{case_id}/unsuspend")
async def unsuspend_case(case_id: str, body: ReasonIn, request: Request,
                         user: CurrentUser =
                         Depends(require_compliance_decide)):
    case = await _case(case_id)
    if not case.get("suspended"):
        raise HTTPException(409, "La operatoria no está suspendida")
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"suspended": None, "updated_at": utc_now()},
         "$push": {"suspension_history": {**case["suspended"],
                                          "lifted_at": utc_now(),
                                          "lifted_by": user.user_id,
                                          "lift_reason":
                                          body.reason.strip()}}})
    await kyb_audit("kyb.case.unsuspended", case_id=case_id, actor=user,
                    request=request, org_id=case.get("org_id"),
                    metadata={"reason": body.reason.strip()})
    return {"ok": True}


class RiskOverrideIn(BaseModel):
    level: str
    justification: str = Field(..., min_length=10, max_length=1000)


@router.post("/cases/{case_id}/risk-override")
async def risk_override(case_id: str, body: RiskOverrideIn,
                        request: Request,
                        user: CurrentUser =
                        Depends(require_compliance_decide)):
    case = await _case(case_id)
    if body.level not in ("low", "medium", "high"):
        raise HTTPException(422, "level debe ser low, medium o high")
    prev = case.get("risk") or {}
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"risk": {**prev, "level": body.level,
                           "overridden": True,
                           "overridden_by": user.user_id,
                           "overridden_at": utc_now(),
                           "override_justification":
                           body.justification.strip()},
                  "updated_at": utc_now()}})
    await kyb_audit("kyb.case.risk_overridden", case_id=case_id,
                    actor=user, request=request, org_id=case.get("org_id"),
                    metadata={"from": prev.get("level"), "to": body.level,
                              "justification": body.justification.strip()})
    return {"ok": True, "level": body.level}


class ContactEmailIn(BaseModel):
    email: EmailStr


@router.post("/cases/{case_id}/contact-email")
async def register_contact_email(case_id: str, body: ContactEmailIn,
                                 request: Request,
                                 user: CurrentUser =
                                 Depends(require_compliance)):
    """Solo casos migrados del legacy sin contacto. Escritura ÚNICA."""
    case = await _case(case_id)
    if not case.get("legacy_origin"):
        raise HTTPException(409, "Solo disponible para expedientes "
                                 "migrados del sistema anterior")
    if case.get("applicant_email"):
        raise HTTPException(409, "El expediente ya tiene contacto "
                                 "registrado (escritura única)")
    await col(KYB_CASES).update_one(
        {"case_id": case_id, "applicant_email": None},
        {"$set": {"applicant_email": body.email.lower(),
                  "updated_at": utc_now()}})
    await kyb_audit("kyb.case.contact_email_registered", case_id=case_id,
                    actor=user, request=request, org_id=case.get("org_id"),
                    metadata={"email": body.email.lower()})
    return {"ok": True}


@router.get("/cases/{case_id}/documents/{document_id}/url")
async def admin_document_url(case_id: str, document_id: str,
                             _: CurrentUser = Depends(require_compliance)):
    await _case(case_id)
    from services.storage import get_storage
    row = await col(KYB_DOCUMENTS).find_one(
        {"document_id": document_id, "case_id": case_id},
        {"_id": 0, "storage_key": 1})
    if not row:
        raise HTTPException(404, "Documento no encontrado")
    url = await get_storage().signed_url(row["storage_key"],
                                         ttl_seconds=300)
    return {"url": url, "expires_in": 300}


@router.get("/cases/{case_id}/audit")
async def case_audit(case_id: str, action: Optional[str] = None,
                     actor: Optional[str] = None, limit: int = 200,
                     _: CurrentUser = Depends(require_compliance)):
    q: dict = {"$or": [{"resource_id": case_id},
                       {"metadata.case_id": case_id}]}
    if action:
        q["action"] = action
    if actor:
        q["actor_user_id"] = actor
    rows = await col("audit_logs").find(q, {"_id": 0}) \
        .sort("timestamp", -1).limit(min(limit, 500)).to_list(500)
    return {"items": rows}


# ---------------------------------------------------------------------------
# Fase 7 — Screening: resolución y bloqueo manual de hits
# ---------------------------------------------------------------------------
class HitResolveIn(BaseModel):
    decision: str = Field(..., description="confirmed | false_positive")
    notes: str = Field(..., min_length=20, max_length=2000)


async def _hit(hit_id: str) -> dict:
    hit = await col(KYB_SCREENING_HITS).find_one({"hit_id": hit_id},
                                                 {"_id": 0})
    if not hit:
        raise HTTPException(404, "Hit no encontrado")
    return hit


@router.post("/hits/{hit_id}/resolve")
async def resolve_hit(hit_id: str, body: HitResolveIn, request: Request,
                      user: CurrentUser = Depends(require_compliance)):
    hit = await _hit(hit_id)
    if body.decision not in ("confirmed", "false_positive"):
        raise HTTPException(422, "decision debe ser confirmed o "
                                 "false_positive")
    if (hit.get("resolution") or {}).get("decision"):
        raise HTTPException(409, "El hit ya está resuelto")
    now = utc_now()
    resolution = {"decision": body.decision, "notes": body.notes.strip(),
                  "by": user.user_id, "at": now}
    # Sync con proveedor: solo aplica a hits `provider`. Los manuales
    # no se propagan a ningún lado.
    sync_state: Optional[dict] = None
    if hit.get("source") == "provider" and hit.get("provider_hit_id"):
        sync_state = {"pending": True, "attempts": 0,
                      "scheduled_at": now, "last_error": None}
    await col(KYB_SCREENING_HITS).update_one(
        {"hit_id": hit_id},
        {"$set": {"resolution": resolution,
                  "provider_sync": sync_state,
                  "updated_at": now}})
    await kyb_audit("kyb.hit.resolved", case_id=hit["case_id"], actor=user,
                    request=request,
                    metadata={"hit_id": hit_id, "decision": body.decision,
                              "notes": body.notes.strip(),
                              "source": hit.get("source"),
                              "provider_sync": bool(sync_state)})
    if sync_state:
        # Fire-and-forget: la resolución local NO se bloquea por red.
        # Con proveedor ausente (Fase 5b postergada) el schedule queda
        # anotado pero no se dispara nada — el worker se conecta cuando
        # llegue el provider real.
        await kyb_audit("kyb.hit.provider_sync_scheduled",
                        case_id=hit["case_id"], actor=user, request=request,
                        metadata={"hit_id": hit_id})
    return {"ok": True, "resolution": resolution,
            "provider_sync": sync_state}


class HitBlockingIn(BaseModel):
    reason: str = Field(..., min_length=10, max_length=500)


@router.post("/hits/{hit_id}/promote-blocking")
async def promote_hit_blocking(hit_id: str, body: HitBlockingIn,
                               request: Request,
                               user: CurrentUser =
                               Depends(require_compliance)):
    hit = await _hit(hit_id)
    if hit.get("is_blocking"):
        raise HTTPException(409, "El hit ya es bloqueante")
    await col(KYB_SCREENING_HITS).update_one(
        {"hit_id": hit_id},
        {"$set": {"is_blocking": True, "updated_at": utc_now()}})
    await kyb_audit("kyb.hit.blocking_promoted", case_id=hit["case_id"],
                    actor=user, request=request,
                    metadata={"hit_id": hit_id, "reason": body.reason.strip()})
    return {"ok": True, "is_blocking": True}


@router.post("/hits/{hit_id}/demote-blocking")
async def demote_hit_blocking(hit_id: str, body: HitBlockingIn,
                              request: Request,
                              user: CurrentUser =
                              Depends(require_compliance)):
    hit = await _hit(hit_id)
    if not hit.get("is_blocking"):
        raise HTTPException(409, "El hit no es bloqueante")
    await col(KYB_SCREENING_HITS).update_one(
        {"hit_id": hit_id},
        {"$set": {"is_blocking": False, "updated_at": utc_now()}})
    await kyb_audit("kyb.hit.blocking_demoted", case_id=hit["case_id"],
                    actor=user, request=request,
                    metadata={"hit_id": hit_id, "reason": body.reason.strip()})
    return {"ok": True, "is_blocking": False}


@router.get("/cases/{case_id}/screening")
async def screening_view(case_id: str,
                         _: CurrentUser = Depends(require_compliance)):
    """Hits agrupados por sujeto (empresa, rep. legal, cada UBO)."""
    await _case(case_id)
    hits = await col(KYB_SCREENING_HITS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(500)
    # Sujetos base del caso, para mostrar los que aún no tienen hits.
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case_id}, {"_id": 0}) or {}
    ubos = await col(KYB_BENEFICIAL_OWNERS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(200)
    groups = [{"subject_type": "company", "subject_id": case_id,
               "subject_name": profile.get("legal_name")
               or "Empresa", "hits": []}]
    rep = profile.get("legal_representative") or {}
    if rep.get("full_name"):
        groups.append({"subject_type": "legal_representative",
                       "subject_id": "legal_representative",
                       "subject_name": rep["full_name"], "hits": []})
    for u in ubos:
        groups.append({"subject_type": "ubo", "subject_id": u["ubo_id"],
                       "subject_name": f"{u.get('first_name', '')} "
                       f"{u.get('last_name', '')}".strip(), "hits": []})
    idx = {(g["subject_type"], g["subject_id"]): g for g in groups}
    for h in hits:
        key = (h.get("subject_type"), h.get("subject_id"))
        g = idx.get(key)
        if g is None:
            g = {"subject_type": h.get("subject_type"),
                 "subject_id": h.get("subject_id"),
                 "subject_name": h.get("subject_name"), "hits": []}
            groups.append(g)
            idx[key] = g
        g["hits"].append(h)
    return {"case_id": case_id, "groups": groups,
            "blocking_hits": await _blocking_hits(case_id)}


# ---------------------------------------------------------------------------
# Fase 7 — Registro: comparación declarado ↔ verificado (manual o proveedor)
# ---------------------------------------------------------------------------
REGISTRY_FIELDS = ("legal_name", "registration_number", "registration_date",
                   "registered_address", "legal_structure",
                   "activity_description", "authorities", "shareholders")


def _flatten_address(addr: Optional[dict]) -> Optional[str]:
    if not addr:
        return None
    if addr.get("raw"):
        return addr["raw"]
    parts = [addr.get("street"), addr.get("number"), addr.get("city"),
             addr.get("state"), addr.get("postal_code"), addr.get("country")]
    return ", ".join(p for p in parts if p) or None


def _authorities_from_profile(profile: dict) -> Optional[str]:
    rep = profile.get("legal_representative") or {}
    if not rep.get("full_name"):
        return None
    return rep["full_name"] + (f" (tax_id={rep['tax_id']})"
                               if rep.get("tax_id") else "")


def _shareholders_from_ubos(ubos: List[dict]) -> Optional[str]:
    parts = []
    for u in ubos:
        name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
        if not name:
            continue
        pct = u.get("ownership_percentage")
        parts.append(f"{name}: {pct}%" if pct is not None else name)
    return "; ".join(parts) or None


def _declared_fields(profile: dict, ubos: List[dict]) -> dict:
    return {
        "legal_name": profile.get("legal_name"),
        "registration_number": profile.get("registration_number"),
        "registration_date": profile.get("registration_date"),
        "registered_address":
            _flatten_address(profile.get("registered_address")),
        "legal_structure": profile.get("legal_structure"),
        "activity_description": profile.get("activity_description"),
        "authorities": _authorities_from_profile(profile),
        "shareholders": _shareholders_from_ubos(ubos),
    }


def _verified_from_manual(checks: List[dict]) -> dict:
    """Extrae valores observados del checklist manual company_registry.

    Convención: el item_key del template mapea al campo. Notas del ítem
    son el valor observado por el analista. Si un ítem quedó vacío,
    devuelve None y el ítem sigue disponible en el checklist."""
    out: dict = {k: None for k in REGISTRY_FIELDS}
    for c in checks:
        if c.get("category") != "company_registry":
            continue
        for item in c.get("items") or []:
            k = item.get("item_key")
            if k in out and item.get("notes"):
                out[k] = item.get("notes")
    return out


@router.get("/cases/{case_id}/registry")
async def registry_view(case_id: str,
                        _: CurrentUser = Depends(require_compliance)):
    case = await _case(case_id)
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case_id}, {"_id": 0}) or {}
    ubos = await col(KYB_BENEFICIAL_OWNERS).find(
        {"case_id": case_id}, {"_id": 0}).to_list(200)
    modes = case.get("verification_modes") or {}
    company_registry_mode = modes.get("company_registry", "manual")
    checks = await col(KYB_MANUAL_CHECKS).find(
        {"case_id": case_id, "category": "company_registry"},
        {"_id": 0}).to_list(50)
    # 5b postergada: la comparación se arma sobre lo declarado + notas
    # del checklist manual. Cuando llegue el proveedor, `verified` viene
    # del `normalized_result` de `kyb_verifications`.
    ver = await col(KYB_VERIFICATIONS).find_one(
        {"case_id": case_id, "kind": "company_registry",
         "status": "completed"},
        {"_id": 0}, sort=[("completed_at", -1)])
    provider_outcome = (ver or {}).get("outcome")
    declared = _declared_fields(profile, ubos)
    verified = _verified_from_manual(checks)
    reviews = await col("kyb_registry_reviews").find(
        {"case_id": case_id}, {"_id": 0}).to_list(50)
    reviews_by_field = {r["field"]: r for r in reviews}
    fields = []
    for f in REGISTRY_FIELDS:
        d, v = declared.get(f), verified.get(f)
        match = None
        if d is not None and v is not None:
            match = (str(d).strip().lower() == str(v).strip().lower())
        fields.append({"field": f, "declared": d, "verified": v,
                       "match": match,
                       "review": reviews_by_field.get(f)})
    return {"case_id": case_id, "mode": company_registry_mode,
            "verified_source": "manual" if not provider_outcome else "provider",
            "provider_outcome": provider_outcome, "fields": fields,
            "checks": [{"check_id": c["check_id"], "status": c.get("status"),
                        "subject_type": c.get("subject_type")} for c in checks]}


class RegistryFieldIn(BaseModel):
    action: str = Field(..., description="accept | observe")
    notes: str = Field(..., min_length=10, max_length=2000)


@router.post("/cases/{case_id}/registry/{field}/accept")
async def registry_accept(case_id: str, field: str, body: RegistryFieldIn,
                          request: Request,
                          user: CurrentUser =
                          Depends(require_compliance)):
    case = await _case(case_id)
    if field not in REGISTRY_FIELDS:
        raise HTTPException(422,
                            f"field debe ser uno de {REGISTRY_FIELDS}")
    if body.action not in ("accept", "observe"):
        raise HTTPException(422, "action debe ser accept u observe")
    now = utc_now()
    review = {"case_id": case_id, "field": field, "action": body.action,
              "notes": body.notes.strip(), "by": user.user_id,
              "at": now, "updated_at": now}
    await col("kyb_registry_reviews").update_one(
        {"case_id": case_id, "field": field},
        {"$set": review, "$setOnInsert": {"created_at": now}},
        upsert=True)
    if body.action == "observe":
        # Mapea al campo del formulario del cliente por sección.
        section_map = {
            "legal_name": "company_data",
            "registration_number": "company_data",
            "registration_date": "company_data",
            "registered_address": "company_data",
            "legal_structure": "company_data",
            "activity_description": "company_data",
            "authorities": "legal_representative",
            "shareholders": "team",
        }
        sec = section_map.get(field, "company_data")
        prev = ((case.get("sections") or {}).get(sec) or {}).get(
            "observation") or ""
        combined = (prev + "\n" if prev else "") + \
                   f"[Registro/{field}] {body.notes.strip()}"
        await col(KYB_CASES).update_one(
            {"case_id": case_id},
            {"$set": {f"sections.{sec}.status": "observed",
                      f"sections.{sec}.observation": combined,
                      f"sections.{sec}.observed_by": user.user_id,
                      f"sections.{sec}.observed_at": now,
                      f"sections.{sec}.review_status": "observed",
                      "updated_at": now},
             "$addToSet": {"observers": user.user_id}})
        await kyb_audit("kyb.case.registry_field_observed", case_id=case_id,
                        actor=user, request=request,
                        org_id=case.get("org_id"),
                        metadata={"field": field, "section": sec,
                                  "notes": body.notes.strip()})
    else:
        await kyb_audit("kyb.case.registry_field_accepted", case_id=case_id,
                        actor=user, request=request,
                        org_id=case.get("org_id"),
                        metadata={"field": field,
                                  "notes": body.notes.strip()})
    return {"ok": True, "review": review}


# ---------------------------------------------------------------------------
# Fase 7 — Rerun de verificaciones
# ---------------------------------------------------------------------------
@router.post("/cases/{case_id}/rerun-verifications")
async def rerun_verifications(case_id: str, request: Request,
                              user: CurrentUser =
                              Depends(require_compliance)):
    """Regenera checklists faltantes por categoría en modo manual /
    fallback / forced. Idempotente: no toca ni duplica los ya existentes.

    Estructura lista para invocar orquestador cuando exista un proveedor
    configurado — hoy no hay proveedor (5b postergada), así que solo
    aplica a manuales."""
    case = await _case(case_id)
    from kyb.manual_checks import generate_checks
    created = await generate_checks(case, actor=user, request=request)
    provider_dispatch: list[dict] = []
    # Con provider real, aquí iría el dispatch a cada categoría automatic.
    # Se deja explícito para el día que llegue Sumsub — no es un "TODO":
    # el contrato es que rerun toca solo lo que su modo admite.
    modes = case.get("verification_modes") or {}
    for cat, mode in modes.items():
        if mode in ("automatic", "mock"):
            provider_dispatch.append({"category": cat, "mode": mode,
                                      "status": "skipped_no_provider"})
    await kyb_audit("kyb.case.rerun_verifications", case_id=case_id,
                    actor=user, request=request,
                    org_id=case.get("org_id"),
                    metadata={"checks_generated": len(created),
                              "provider_dispatch": provider_dispatch})
    return {"ok": True, "generated": len(created),
            "provider_dispatch": provider_dispatch}


# ---------------------------------------------------------------------------
# Fase 7 — Exportación del legajo (ZIP autocontenido)
# ---------------------------------------------------------------------------
@router.get("/cases/{case_id}/export")
async def export_case(case_id: str, request: Request,
                      user: CurrentUser = Depends(require_compliance)):
    case = await _case(case_id)
    from kyb.export import build_export_zip
    payload = await build_export_zip(case_id)
    await kyb_audit("kyb.case.exported", case_id=case_id, actor=user,
                    request=request, org_id=case.get("org_id"),
                    metadata={"size_bytes": len(payload),
                              "included": ["case.json", "resumen.pdf",
                                           "documents/", "manual_evidence/",
                                           "audit.jsonl"]})
    from fastapi.responses import Response
    return Response(
        content=payload, media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="kyb_{case_id}.zip"'})

