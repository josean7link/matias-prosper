"""Fase 5a — Checklists manuales: generación, normalización y maker-checker.

Diseño clave: un checklist completado produce EXACTAMENTE la misma forma
que producirá un proveedor externo (Fase 5b) — `kyb_verifications` con
`normalized_result` y, si hubo hits, `kyb_screening_hits`. El motor de
riesgo, el Portal Admin y la exportación del legajo no cambian según el
modo; solo cambia quién produjo el resultado.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from db import col
from models import utc_now
from kyb.audit import kyb_audit
from kyb.models import (KYB_BENEFICIAL_OWNERS, KYB_CASES,
                        KYB_COMPANY_PROFILES, KYB_MANUAL_CHECKS,
                        KYB_MANUAL_CHECK_TEMPLATES, KYB_SCREENING_HITS,
                        KYB_VERIFICATIONS, VERIFICATION_CATEGORIES,
                        KybManualCheck, KybScreeningHit, KybVerification)


async def _case_subjects(case: dict) -> list[dict]:
    """Sujetos verificables del caso: empresa, representante legal y UBOs."""
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case["case_id"]}, {"_id": 0}) or {}
    subjects = [{"subject_type": "company", "subject_id": case["case_id"],
                 "subject_name": profile.get("legal_name")
                 or case.get("company_name_declared") or "Empresa"}]
    rep = profile.get("legal_representative") or {}
    if rep.get("full_name"):
        subjects.append({"subject_type": "legal_representative",
                         "subject_id": "legal_representative",
                         "subject_name": rep["full_name"]})
    async for u in col(KYB_BENEFICIAL_OWNERS).find(
            {"case_id": case["case_id"]}, {"_id": 0}):
        subjects.append({"subject_type": "ubo", "subject_id": u["ubo_id"],
                         "subject_name": f"{u.get('first_name', '')} "
                         f"{u.get('last_name', '')}".strip()})
    return subjects


async def _pick_template(category: str, country: Optional[str],
                         subject_type: str) -> Optional[dict]:
    """Plantilla activa que matchea; país exacto le gana a country=None."""
    q = {"category": category, "active": True,
         "subject_types": subject_type,
         "country": {"$in": [country, None]}}
    rows = await col(KYB_MANUAL_CHECK_TEMPLATES).find(
        q, {"_id": 0}).sort("version", -1).to_list(50)
    exact = [r for r in rows if r.get("country") == country]
    pool = exact or rows
    return pool[0] if pool else None


async def generate_checks(case: dict, actor, request=None,
                          only_categories: Optional[set[str]] = None
                          ) -> list[dict]:
    """Genera un checklist por sujeto y por categoría en modo manual
    (o forzado). Idempotente: no duplica checks existentes.

    Fase 5a (sin orquestador): las categorías en modo automatic/mock NO
    generan checklist — el fallback estructurado (automatic_failed /
    inconclusive / not_found) llega con la Fase 5b. `force-manual` es el
    camino para convertirlas hoy.

    Fase 5b: cuando el ManualProvider ejerce el path por una capability
    puntual, se pasa `only_categories={"identity"}` (o la que
    corresponda). Sin ese parámetro, el comportamiento es idéntico al
    original — las 3 categorías se procesan. Retrocompat total con los
    3 callers existentes."""
    modes = case.get("verification_modes") or {}
    states = case.get("verification_states") or {}
    subjects = await _case_subjects(case)
    created = []
    for category in VERIFICATION_CATEGORIES:
        if only_categories is not None and category not in only_categories:
            continue
        state = (states.get(category) or {}).get("state")
        mode = modes.get(category, "manual")
        if state == "manual_forced":
            trigger = "forced_by_admin"
        elif state in ("automatic_failed", "automatic_inconclusive",
                       "automatic_not_found"):
            trigger = f"fallback_{state.split('_', 1)[1]}"
        elif mode == "manual" or state in ("manual", "not_configured"):
            trigger = "mode_manual"
        else:
            continue   # automatic/mock sin caída: sin checklist (5b)
        for s in subjects:
            dup = await col(KYB_MANUAL_CHECKS).find_one(
                {"case_id": case["case_id"], "category": category,
                 "subject_id": s["subject_id"]}, {"_id": 1})
            if dup:
                continue
            tpl = await _pick_template(category,
                                       case.get("country_of_incorporation"),
                                       s["subject_type"])
            if not tpl:
                continue   # sin plantilla aplicable: se reporta en la UI
            items = [{"item_key": i["item_key"], "label": i["label"],
                      "description": i.get("description"),
                      "source_url": i.get("source_url"),
                      "evidence_required": bool(i.get("evidence_required")),
                      "blocks_on_hit": bool(i.get("blocks_on_hit")),
                      "possible_outcomes": i.get("possible_outcomes") or [],
                      "order": i.get("order", 0),
                      "outcome": None, "notes": None,
                      "evidence_document_ids": [],
                      "completed_by": None, "completed_at": None}
                     for i in sorted(tpl["items"], key=lambda x:
                                     x.get("order", 0))]
            check = KybManualCheck(case_id=case["case_id"],
                                   category=category,
                                   subject_type=s["subject_type"],
                                   subject_id=s["subject_id"],
                                   subject_name=s["subject_name"],
                                   template_id=tpl["template_id"],
                                   template_version=tpl["version"],
                                   trigger=trigger, items=items)
            await col(KYB_MANUAL_CHECKS).insert_one(check.model_dump())
            created.append(check.model_dump())
            await kyb_audit("kyb.manual_check.generated",
                            case_id=case["case_id"], actor=actor,
                            request=request, org_id=case.get("org_id"),
                            metadata={"check_id": check.check_id,
                                      "category": category,
                                      "subject_type": s["subject_type"],
                                      "subject_id": s["subject_id"],
                                      "trigger": trigger,
                                      "template_id": tpl["template_id"],
                                      "template_version": tpl["version"]})
    return created


def build_normalized_result(check: dict) -> dict:
    """CONTRATO de salida normalizada — el camino automático (Fase 5b)
    debe producir esta MISMA forma. No cambiarla sin tocar ambos lados."""
    outcomes = [i.get("outcome") for i in check["items"]]
    if any(o == "hit" for o in outcomes):
        overall = "hit"
    elif any(o == "unavailable" for o in outcomes):
        overall = "review"
    else:
        overall = "clear"
    return {
        "provider": None,
        "kind": check["category"],
        "outcome": overall,
        "hit_count": sum(1 for o in outcomes if o == "hit"),
        "items": [{"item_key": i["item_key"], "label": i["label"],
                   "outcome": i.get("outcome"),
                   "source_url": i.get("source_url")}
                  for i in check["items"]],
        "template": {"template_id": check["template_id"],
                     "version": check["template_version"]},
        "checked_at": utc_now(),
    }


async def complete_check(check: dict, user, request=None) -> dict:
    """Marca el checklist completo y emite la salida normalizada:
    kyb_verifications (mode/source manual) + kyb_screening_hits por cada
    ítem con outcome hit."""
    case = await col(KYB_CASES).find_one({"case_id": check["case_id"]},
                                         {"_id": 0})
    normalized = build_normalized_result(check)
    ver = KybVerification(case_id=check["case_id"],
                          subject_type=check["subject_type"],
                          subject_id=check["subject_id"],
                          kind=check["category"], mode="manual",
                          source="manual", performed_by=user.user_id,
                          status="completed",
                          outcome=normalized["outcome"],
                          normalized_result=normalized,
                          requested_at=check.get("created_at"),
                          completed_at=utc_now())
    await col(KYB_VERIFICATIONS).insert_one(ver.model_dump())
    hit_ids = []
    for item in check["items"]:
        if item.get("outcome") != "hit":
            continue
        hit = KybScreeningHit(case_id=check["case_id"],
                              verification_id=ver.verification_id,
                              subject_type=check["subject_type"],
                              subject_id=check["subject_id"],
                              subject_name=check.get("subject_name"),
                              list_type=check["category"],
                              list_name=item["label"],
                              matched_name=check.get("subject_name"),
                              is_blocking=bool(item.get("blocks_on_hit")),
                              source="manual",
                              details={"item_key": item["item_key"],
                                       "notes": item.get("notes")})
        await col(KYB_SCREENING_HITS).insert_one(hit.model_dump())
        hit_ids.append(hit.hit_id)
    now = utc_now()
    await col(KYB_MANUAL_CHECKS).update_one(
        {"check_id": check["check_id"]},
        {"$set": {"status": "completed", "completed_by": user.user_id,
                  "completed_at": now, "updated_at": now}})
    await kyb_audit("kyb.manual_check.completed",
                    case_id=check["case_id"], actor=user, request=request,
                    org_id=(case or {}).get("org_id"),
                    metadata={"check_id": check["check_id"],
                              "category": check["category"],
                              "subject_id": check["subject_id"],
                              "verification_id": ver.verification_id,
                              "outcome": normalized["outcome"],
                              "hit_ids": hit_ids})
    return {"verification_id": ver.verification_id,
            "outcome": normalized["outcome"], "hit_ids": hit_ids}


async def enforce_maker_checker(case_id: str, user,
                                override_reason: Optional[str] = None,
                                request=None) -> None:
    """Maker-checker: quien figura en contributors de algún checklist del
    caso NO puede aprobarlo — 403 server-side, no un botón oculto.

    Override: solo super_admin, motivo ≥ 20 caracteres, auditado con
    kyb.approval.maker_checker_override.

    Fase 5a: dependencia reutilizable + tests directos. Se conecta al
    endpoint de decisión de la bandeja nueva en la Fase 6."""
    contributed = await col(KYB_MANUAL_CHECKS).find_one(
        {"case_id": case_id, "contributors": user.user_id}, {"_id": 1})
    if not contributed:
        return
    role = getattr(user.role, "value", user.role)
    if role == "super_admin" and len((override_reason or "").strip()) >= 20:
        case = await col(KYB_CASES).find_one({"case_id": case_id},
                                             {"_id": 0, "org_id": 1})
        await kyb_audit("kyb.approval.maker_checker_override",
                        case_id=case_id, actor=user, request=request,
                        org_id=(case or {}).get("org_id"),
                        metadata={"reason": override_reason.strip()})
        return
    raise HTTPException(403, "Maker-checker: participaste en la "
                             "verificación manual de este caso y no podés "
                             "aprobarlo. Solo super_admin puede saltear la "
                             "restricción, con motivo de al menos 20 "
                             "caracteres.")
