"""Receptor HTTP de webhooks Sumsub (Fase 5b, Bloque 3).

Ruta: `POST /api/v1/kyb/webhooks/sumsub`. Público (Sumsub lo llama sin
credenciales del lado nuestro; la autoridad es la firma HMAC del body,
validada por `SumsubProvider.validate_webhook` contra el secret del
ambiente del applicant referenciado en el evento, NO contra el ambiente
global).

Reglas de este receptor:
  - Idempotencia por (provider_event_id, provider_reference) — índice
    único sparse `uniq_provider_event_idempotency` (db_setup.py:5b).
  - Ordenamiento: descarta eventos con provider_event_ts < último
    aplicado sobre el mismo applicant. Descarte auditado.
  - Toda transición de estado del caso pasa por `apply_transition` con
    `actor_type="system"`. Ningún `$set` directo sobre `kyb_cases.status`.
  - No transiciona el caso a `approved`/`rejected` desde acá — sólo
    reabre `approved → under_review` con `reopen_reason=provider_alert`
    cuando llega revisión post-aprobación.
  - Respuesta rápida: valida + persiste evidencia + procesa
    idempotentemente + responde 200. En caso de firma inválida o
    ambiente cruzado, devuelve 401/409 sin persistir nada."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from db import col
from kyb.audit import kyb_audit
from kyb.flags import kyb_enabled
from kyb.models import (KYB_CASES, KYB_SCREENING_HITS, KYB_VERIFICATIONS)
from kyb.providers.base import (ProviderEnvironmentMismatch, ProviderError,
                                 ProviderSignatureInvalid, SubjectRef,
                                 VerificationSnapshot, WebhookPayload)
from kyb.state_machine import apply_transition
from models import utc_now


logger = logging.getLogger("prosper.kyb.webhooks_sumsub")

router = APIRouter(prefix="/kyb/webhooks", tags=["kyb-webhooks"])


async def _get_provider_from_env():
    """Instancia lazy — evita fallos si el flag está apagado."""
    import os
    if os.environ.get("KYB_PROVIDER_SUMSUB_ENABLED", "false") \
            .strip().lower() != "true":
        raise HTTPException(404, "Not Found")
    from kyb.providers.sumsub import SumsubProvider
    env_ = os.environ.get("SUMSUB_ENVIRONMENT", "").strip().lower() \
        or "sandbox"
    return SumsubProvider(environment=env_)


@router.post("/sumsub")
async def sumsub_webhook(request: Request):
    if not kyb_enabled():
        raise HTTPException(404, "Not Found")

    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    provider = await _get_provider_from_env()

    # 1) Validar firma + parsear + reglas de ambiente.
    try:
        applicant, snapshot = await provider.validate_webhook(
            WebhookPayload(raw_body=raw_body, headers=headers))
    except ProviderSignatureInvalid:
        await kyb_audit(event="kyb.provider.webhook_received",
                         case_id="unknown", actor=None,
                         metadata={"provider": "sumsub",
                                    "outcome": "signature_invalid"})
        raise HTTPException(401, "unauthorized")
    except ProviderEnvironmentMismatch as e:
        await kyb_audit(event="kyb.provider.env_mismatch_rejected",
                         case_id="unknown", actor=None,
                         metadata={"provider": "sumsub",
                                    "detail": str(e)})
        raise HTTPException(409, "environment mismatch")
    except ProviderError as e:
        raise HTTPException(400, f"bad webhook: {e}")

    # 2) Persistir la evidencia y disparar la transición si corresponde,
    #    en segundo plano. Devolvemos 200 rápido.
    asyncio.create_task(_process_snapshot(applicant, snapshot, raw_body))
    return {"ok": True}


async def _process_snapshot(applicant, snapshot: VerificationSnapshot,
                             raw_body: bytes) -> None:
    case_id = applicant.subject.case_id
    provider_reference = snapshot.provider_reference
    provider_event_id = snapshot.provider_event_id
    provider_event_ts = snapshot.provider_event_ts

    # 2.a) IDEMPOTENCIA — llave (provider_event_id, provider_reference).
    #      El índice unique+sparse creado en Bloque 1 (db_setup.py) es
    #      la fuente de verdad.
    if provider_event_id is None:
        logger.warning("[SUMSUB webhook] event without provider_event_id — "
                        "cannot enforce idempotency; dropping")
        return

    # 2.b) ORDEN — descartar si es anterior al último aplicado.
    last = await col(KYB_VERIFICATIONS).find_one({
        "case_id": case_id, "provider": "sumsub",
        "provider_reference": provider_reference,
        "provider_event_ts": {"$ne": None},
    }, {"_id": 0, "provider_event_ts": 1},
       sort=[("provider_event_ts", -1)])
    if last and provider_event_ts is not None \
            and last["provider_event_ts"] > provider_event_ts:
        await kyb_audit(event="kyb.provider.webhook_received",
                         case_id=case_id, actor=None,
                         metadata={"provider": "sumsub",
                                    "outcome": "out_of_order_dropped",
                                    "event_ts": provider_event_ts,
                                    "last_ts": last["provider_event_ts"],
                                    "provider_reference": provider_reference,
                                    "event_id": provider_event_id})
        return

    # 2.c) Guardar el body crudo (raw_response_ref) — única forma de
    #      reconstruir un veredicto disputado.
    from services.storage.factory import get_storage
    storage = get_storage()
    storage_key = await storage.put(
        content=raw_body,
        filename=f"sumsub-{provider_event_id}.json",
        content_type="application/json",
        metadata={"scope": "kyb", "scope_id": case_id,
                   "provider": "sumsub",
                   "provider_event_id": provider_event_id,
                   "provider_reference": provider_reference})

    now = utc_now()
    doc = {
        "verification_id":
            f"ver_sumsub_{provider_reference}_{provider_event_id}",
        "case_id": case_id,
        "subject_type": applicant.subject.subject_type,
        "subject_id": applicant.subject.subject_id,
        "kind": snapshot.capability, "mode": "automatic",
        "source": "provider", "provider": "sumsub",
        "provider_reference": provider_reference,
        "status": snapshot.status, "outcome": snapshot.outcome,
        "normalized_result": snapshot.normalized_result,
        "raw_response_ref": storage_key,
        "provider_event_id": provider_event_id,
        "provider_event_ts": provider_event_ts,
        "requested_at": now, "completed_at": now, "updated_at": now,
    }
    try:
        await col(KYB_VERIFICATIONS).insert_one(doc)
    except DuplicateKeyError:
        # Índice único (provider_event_id, provider_reference) sparse.
        # Duplicado esperado (reintento del proveedor) → auditamos y
        # salimos sin reprocesar.
        await kyb_audit(event="kyb.provider.webhook_received",
                         case_id=case_id, actor=None,
                         metadata={"provider": "sumsub",
                                    "outcome": "duplicate_dropped",
                                    "provider_reference": provider_reference,
                                    "event_id": provider_event_id})
        return

    # 2.d) Persistir screening hits (si vinieron).
    for h in snapshot.screening_hits or []:
        await col(KYB_SCREENING_HITS).insert_one({
            "case_id": case_id,
            "verification_id": doc["verification_id"],
            "subject_name": (h.matched_name or ""),
            "list_type": h.list_type, "list_name": h.list_name,
            "matched_name": h.matched_name, "match_score": h.match_score,
            "is_blocking": h.is_blocking, "source": "sumsub",
            "provider_hit_id": h.provider_hit_id, "details": h.details})

    await kyb_audit(event="kyb.provider.webhook_received",
                     case_id=case_id, actor=None,
                     metadata={"provider": "sumsub",
                                "outcome": "applied",
                                "capability": snapshot.capability,
                                "status": snapshot.status,
                                "verdict": snapshot.outcome,
                                "provider_event_id": provider_event_id,
                                "provider_reference": provider_reference})

    # 3) Transición del caso — SÓLO cuando llega revisión post-aprobación.
    if snapshot.status != "completed" or snapshot.outcome is None:
        return
    case = await col(KYB_CASES).find_one({"case_id": case_id})
    if not case:
        return
    if case["status"] == "approved":
        # Revisión post-aprobación → approved → under_review con
        # reopen_reason=provider_alert. Pasa por apply_transition
        # (actor_type=system).
        try:
            await apply_transition(
                case, to_status="under_review",
                actor=None, actor_type="system",
                reopen_reason="provider_alert",
                metadata={"provider": "sumsub",
                          "capability": snapshot.capability,
                          "verdict": snapshot.outcome,
                          "provider_event_id": provider_event_id})
        except Exception as _e:
            logger.warning("[SUMSUB webhook] apply_transition rejected "
                            "approved→under_review for case=%s "
                            "(state machine refused: %s)", case_id, _e)