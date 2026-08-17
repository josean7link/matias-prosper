"""Fase 7 — Modelo de riesgo KYB (super_admin).

Documento único `kyb_risk_model_versions`: cada guardado incrementa
`version` y activa la nueva. Solo hay una versión con `active=true`
en cualquier momento. El motor vive en `kyb.risk_engine` — este archivo
solo persiste, versiona y expone la vista previa.

Cada `kyb_cases.risk` guarda `model_version` para saber con qué versión
se evaluó cada caso (F7). El recompute usa la versión activa por default;
se puede pedir una versión específica por parámetro.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import CurrentUser, requires_role
from db import col
from models import utc_now
from roles import Role
from kyb.audit import kyb_audit
from kyb.models import (KYB_BENEFICIAL_OWNERS, KYB_CASES,
                        KYB_COMPANY_PROFILES, KYB_RISK_MODEL_VERSIONS,
                        KYB_SCREENING_HITS)
from kyb.risk_engine import compare_levels, compute, default_model

require_super_admin = requires_role(Role.super_admin)

router = APIRouter(prefix="/admin/compliance/kyb/settings/risk-model",
                   tags=["kyb-admin-risk-model"])

OPEN_STATUSES = ("draft", "in_progress", "submitted", "screening",
                 "under_review", "info_required")


async def _active_model() -> dict:
    row = await col(KYB_RISK_MODEL_VERSIONS).find_one(
        {"active": True}, {"_id": 0})
    if row:
        return row
    # Bootstrap: guarda el modelo por defecto como v1 activa.
    seed = default_model()
    seed["created_at"] = utc_now()
    seed["updated_at"] = seed["created_at"]
    await col(KYB_RISK_MODEL_VERSIONS).insert_one(dict(seed))
    return await col(KYB_RISK_MODEL_VERSIONS).find_one(
        {"version": seed["version"]}, {"_id": 0})


async def _model_by_version(version: int) -> Optional[dict]:
    return await col(KYB_RISK_MODEL_VERSIONS).find_one(
        {"version": version}, {"_id": 0})


async def _load_case_ctx(case: dict) -> dict:
    hits = await col(KYB_SCREENING_HITS).find(
        {"case_id": case["case_id"]}, {"_id": 0}).to_list(500)
    ubos = await col(KYB_BENEFICIAL_OWNERS).find(
        {"case_id": case["case_id"]}, {"_id": 0}).to_list(200)
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case["case_id"]}, {"_id": 0}) or {}
    return {"hits": hits, "ubos": ubos, "profile": profile}


@router.get("")
async def get_model(version: Optional[int] = None,
                    _: CurrentUser = Depends(require_super_admin)):
    if version is not None:
        m = await _model_by_version(version)
        if not m:
            raise HTTPException(404, f"Versión {version} no existe")
        return m
    return await _active_model()


@router.get("/history")
async def list_history(_: CurrentUser = Depends(require_super_admin)):
    rows = await col(KYB_RISK_MODEL_VERSIONS).find({}, {"_id": 0}) \
        .sort("version", -1).to_list(100)
    return {"items": rows}


class RiskModelIn(BaseModel):
    factors: List[Dict[str, Any]]
    thresholds: Dict[str, Any]
    review_months: Dict[str, int]


@router.post("/preview")
async def preview_impact(body: RiskModelIn,
                         _: CurrentUser = Depends(require_super_admin)):
    """Compara el modelo propuesto contra los casos abiertos. Devuelve
    el cambio de nivel por caso (sin escribir nada)."""
    proposed = {"version": -1, "factors": body.factors,
                "thresholds": body.thresholds,
                "review_months": body.review_months}
    cases = await col(KYB_CASES).find(
        {"status": {"$in": list(OPEN_STATUSES)}, "is_deleted": False,
         "verification_modes": {"$exists": True}},
        {"_id": 0}).to_list(1000)
    changes: list = []
    stayed = 0
    for c in cases:
        ctx = await _load_case_ctx(c)
        r = compute(c, proposed, **ctx)
        old_level = (c.get("risk") or {}).get("level")
        diff = compare_levels(old_level, r["level"])
        if diff:
            changes.append({"case_id": c["case_id"],
                            "company_name": c.get("company_name_declared"),
                            "from": old_level, "to": r["level"],
                            "old_score": (c.get("risk") or {}).get("score"),
                            "new_score": r["score"]})
        else:
            stayed += 1
    return {"cases_evaluated": len(cases), "changed": changes,
            "stayed": stayed}


@router.put("")
async def save_model(body: RiskModelIn, request: Request,
                     user: CurrentUser = Depends(require_super_admin)):
    active = await _active_model()
    new_version = int(active["version"]) + 1
    now = utc_now()
    doc = {"version": new_version, "active": True,
           "factors": body.factors, "thresholds": body.thresholds,
           "review_months": body.review_months,
           "updated_by": user.user_id, "created_at": now, "updated_at": now}
    # Desactivar la actual y activar la nueva de forma atómica lógica.
    await col(KYB_RISK_MODEL_VERSIONS).update_many(
        {"active": True},
        {"$set": {"active": False, "updated_at": now}})
    await col(KYB_RISK_MODEL_VERSIONS).insert_one(dict(doc))
    await kyb_audit("kyb.risk_model.published", case_id="__system__",
                    actor=user, request=request,
                    metadata={"version": new_version,
                              "previous_version": active["version"]})
    return {"ok": True, "version": new_version}


@router.post("/recompute/{case_id}")
async def recompute_case(case_id: str, request: Request,
                         user: CurrentUser =
                         Depends(require_super_admin)):
    """Recalcula el riesgo de un caso con el modelo activo. Persiste
    en `kyb_cases.risk`, incluyendo `model_version` para trazabilidad."""
    case = await col(KYB_CASES).find_one(
        {"case_id": case_id, "is_deleted": False,
         "verification_modes": {"$exists": True}}, {"_id": 0})
    if not case:
        raise HTTPException(404, "Caso no encontrado")
    model = await _active_model()
    ctx = await _load_case_ctx(case)
    result = compute(case, model, **ctx)
    prev = (case.get("risk") or {}).get("level")
    await col(KYB_CASES).update_one(
        {"case_id": case_id},
        {"$set": {"risk": result, "updated_at": utc_now()}})
    await kyb_audit("kyb.case.risk_recomputed", case_id=case_id,
                    actor=user, request=request,
                    org_id=case.get("org_id"),
                    metadata={"model_version": result["model_version"],
                              "from": prev, "to": result["level"],
                              "score": result["score"]})
    return {"ok": True, "risk": result}
