"""Orquestador del ciclo de vida del expediente KYB.

Este es el ÚNICO punto que decide qué pasa cuando un expediente se
envía (o reenvía) a revisión. Reemplaza el atajo silencioso que
`_ensure_under_review` hacía dentro de los endpoints de decisión.

Diseño en dos capas separadas para que la Fase 5b (Sumsub) se enchufe
sin abrir un camino paralelo:

  1. `_dispatch_category(case, category, mode)` — decide qué pasa por
     categoría (identity / screening / company_registry) según su
     `verification_mode`:
       * "manual" / "not_configured"  → genera checklist manual
         (`kyb.manual_checks.generate_checks` es idempotente).
       * "automatic"                   → placeholder que devuelve
         "skipped_no_provider". CUANDO llegue la 5b, este es el punto
         de extensión: se llama al SDK del proveedor y se crean
         `kyb_verifications` con `source="provider"`, `status="pending"`.

  2. `dispatch_on_submit(case)` — coordina las tres categorías,
     acumula errores, transiciona el caso. Idempotente y resiliente:

       * llamar dos veces sobre el mismo caso NO duplica checklists ni
         verificaciones (delegado a `generate_checks` que ya deduplica
         por `(case_id, category, subject_id)`);
       * si una categoría explota, el error queda en `case.dispatch_state`
         y el resto sigue. La regla es: **un caso no se traba porque
         nosotros fallamos**. La transición ocurre igual.

Transición final:
  * si ninguna categoría automatic quedó `pending` en `kyb_verifications`,
    el caso avanza `submitted → screening → under_review` (todo el
    trabajo lo hace un humano completando checklists).
  * si al menos una categoría automatic quedó pendiente, el caso avanza
    solo a `screening`; los webhooks del proveedor invocan
    `resolve_pending()` cuando corresponda.

Cuando el orquestador se ejecuta sobre un caso que YA no está en
submitted (p.ej. porque otro request lo movió) es un no-op para las
transiciones — sigue siendo seguro llamarlo.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from db import col
from models import utc_now
from kyb.audit import kyb_audit
from kyb.manual_checks import generate_checks
from kyb.models import KYB_CASES, KYB_VERIFICATIONS, VERIFICATION_CATEGORIES
from kyb.state_machine import apply_transition

logger = logging.getLogger("kyb.orchestrator")

# El botón "Generar checklists" del portal admin llama al orquestador
# con este trigger; el envío del cliente con el otro. Ambos son la
# misma función.
TRIGGER_SUBMIT = "submit"
TRIGGER_RETRY  = "retry"


async def _dispatch_category(case: dict, category: str, mode: str, *,
                             trigger: str, actor, request) -> Dict[str, Any]:
    """Ejecuta el trabajo por categoría. NUNCA lanza — devuelve dict con
    `ok` + info para persistir en dispatch_state."""
    try:
        if mode in ("manual", "not_configured"):
            created = await generate_checks(case, actor=actor, request=request)
            # `generate_checks` recorre las 3 categorías; filtramos las
            # que pertenecen a esta llamada para devolver un conteo por
            # categoría.
            per_cat = sum(1 for c in created if c.get("category") == category)
            return {"category": category, "mode": mode, "ok": True,
                    "checks_created": per_cat, "provider_pending": False}
        if mode == "automatic":
            # Fase 5b — dispatch al proveedor resuelto por el registry.
            # Con KYB_PROVIDER_SUMSUB_ENABLED=false el registry lanza
            # ProviderNotConfigured y caemos al placeholder histórico.
            from kyb.providers.base import (ProviderNotConfigured,
                                             ProviderTransientError,
                                             SubjectRef)
            from kyb.providers.registry import get_provider
            try:
                provider = await get_provider(category)  # type: ignore
            except ProviderNotConfigured:
                return {"category": category, "mode": mode, "ok": True,
                        "checks_created": 0, "provider_pending": False,
                        "note": "skipped_no_provider"}
            # Un applicant por sujeto — company + legal_rep + UBOs.
            subjects = []
            subjects.append(SubjectRef(case_id=case["case_id"],
                                        subject_type="company"))
            if (case.get("legal_representative") or {}).get("full_name"):
                subjects.append(SubjectRef(case_id=case["case_id"],
                                            subject_type="legal_representative"))
            for u in case.get("ubos") or []:
                subjects.append(SubjectRef(case_id=case["case_id"],
                                            subject_type="ubo",
                                            subject_id=u.get("ubo_id")))
            transient = False
            errors = []
            for s in subjects:
                try:
                    app = await provider.ensure_applicant(
                        s, level_hint=category)  # type: ignore
                    await provider.start_verification(
                        app, capability=category, trigger=trigger)  # type: ignore
                except ProviderTransientError as e:
                    transient = True
                    errors.append(str(e))
                # otras excepciones caen al outer try/except → ok=False
            return {"category": category, "mode": mode, "ok": True,
                    "checks_created": 0,
                    "provider_pending": True,
                    "provider_transient": transient,
                    "errors": errors or None}
        # modo desconocido — no es error, pero lo marcamos.
        return {"category": category, "mode": mode, "ok": True,
                "checks_created": 0, "provider_pending": False,
                "note": f"unhandled_mode:{mode}"}
    except Exception as e:  # pragma: no cover — resiliencia
        logger.exception("dispatch %s/%s falló: %s", case.get("case_id"),
                         category, e)
        return {"category": category, "mode": mode, "ok": False,
                "checks_created": 0, "provider_pending": False,
                "error": f"{type(e).__name__}: {e}"}


async def _has_provider_pending(case_id: str) -> bool:
    """True si hay al menos una verificación de proveedor pendiente."""
    n = await col(KYB_VERIFICATIONS).count_documents(
        {"case_id": case_id, "source": "provider",
         "status": {"$in": ["pending", "in_progress"]}})
    return n > 0


async def dispatch_on_submit(case: dict, *,
                             actor=None, request=None,
                             trigger: str = TRIGGER_SUBMIT) -> Dict[str, Any]:
    """Punto único de entrada. Idempotente + resiliente. Ver docstring
    del módulo."""
    modes = case.get("verification_modes") or {}
    per_cat: list[dict] = []
    errors: list[dict] = []
    for cat in VERIFICATION_CATEGORIES:
        mode = modes.get(cat, "manual")
        res = await _dispatch_category(case, cat, mode, trigger=trigger,
                                       actor=actor, request=request)
        per_cat.append(res)
        if not res.get("ok"):
            errors.append({"category": cat, "mode": mode,
                           "error": res.get("error")})

    dispatch_state = {"trigger": trigger, "at": utc_now(),
                      "categories": per_cat, "errors": errors}
    await col(KYB_CASES).update_one(
        {"case_id": case["case_id"]},
        {"$set": {"dispatch_state": dispatch_state, "updated_at": utc_now()}})
    await kyb_audit("kyb.case.dispatched", case_id=case["case_id"],
                    actor=actor, request=request, org_id=case.get("org_id"),
                    metadata={"trigger": trigger, "errors": errors,
                              "per_category": per_cat})

    # Refrescar el caso — la transición se decide sobre el estado real.
    fresh = await col(KYB_CASES).find_one({"case_id": case["case_id"]},
                                          {"_id": 0})
    if not fresh:
        return {"ok": False, "reason": "case_disappeared",
                "dispatch_state": dispatch_state}
    to_under_review = not await _has_provider_pending(case["case_id"])
    await _advance_case(fresh, to_under_review=to_under_review,
                        actor=actor, request=request)
    return {"ok": True, "dispatch_state": dispatch_state,
            "advanced_to": "under_review" if to_under_review else "screening"}


async def _advance_case(case: dict, *, to_under_review: bool,
                        actor, request) -> None:
    """Avanza el caso lo más lejos posible según `to_under_review`.
    Idempotente: si el caso ya está en el destino (o más adelante) no
    hace nada. NUNCA se queda a mitad de camino por un error de
    transición — loguea y sigue.

    Este método no usa `_ensure_under_review` (removido): se queda con
    lo que la state machine autoriza y nada más.
    """
    status = case["status"]
    path = [("submitted", "screening")]
    if to_under_review:
        path.append(("screening", "under_review"))
    for from_status, to_status in path:
        if status != from_status:
            continue
        try:
            await apply_transition({**case, "status": status}, to_status,
                                   actor_type="system", actor=actor,
                                   request=request,
                                   metadata={"trigger": "orchestrator"})
            status = to_status
        except Exception as e:  # pragma: no cover
            logger.warning("orchestrator: transición %s → %s bloqueada: %s",
                           from_status, to_status, e)
            return


async def resolve_pending(case_id: str, *, actor=None, request=None) -> dict:
    """Hook que la Fase 5b invoca desde los webhooks del proveedor cuando
    una `kyb_verifications` pasa a `completed`. Si ya no hay pending,
    avanza `screening → under_review`.
    Hoy en Fase 5b postergada, sirve para tests y para el path de
    reintento manual."""
    case = await col(KYB_CASES).find_one({"case_id": case_id}, {"_id": 0})
    if not case:
        return {"ok": False, "reason": "not_found"}
    if case["status"] != "screening":
        return {"ok": True, "reason": "not_in_screening",
                "status": case["status"]}
    if await _has_provider_pending(case_id):
        return {"ok": True, "reason": "still_pending"}
    await _advance_case(case, to_under_review=True, actor=actor,
                        request=request)
    fresh = await col(KYB_CASES).find_one({"case_id": case_id},
                                          {"_id": 0, "status": 1})
    return {"ok": True, "status": (fresh or {}).get("status")}
