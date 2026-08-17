"""Máquina de estados del caso KYB (Fase 1).

Diseño en dos capas:
  * capa pura (`validate_transition`, `transition_fields`) — sin I/O,
    testeable unitariamente.
  * capa persistente (`apply_transition`) — escribe en `kyb_cases` y
    registra auditoría. Fase 1 no expone endpoints; esta función es la
    única puerta de entrada que usarán las fases siguientes.
"""
from __future__ import annotations

from typing import Optional

from models import utc_now

STATES = frozenset({
    "draft", "in_progress", "submitted", "screening", "under_review",
    "info_required", "approved", "rejected", "expired",
})

# (from, to) declaradas. Cualquier par fuera de este set lanza excepción.
TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("draft",         "in_progress"),   # primera sección guardada
    ("in_progress",   "submitted"),     # enviar a revisión
    ("submitted",     "screening"),     # automático
    ("screening",     "under_review"),  # caso disponible
    ("under_review",  "info_required"), # observa
    ("info_required", "submitted"),     # reenvía
    ("under_review",  "approved"),      # aprueba
    ("under_review",  "rejected"),      # rechaza
    ("in_progress",   "expired"),       # inactividad
    ("info_required", "expired"),       # inactividad
    ("expired",       "in_progress"),   # reactivación manual
    ("approved",      "under_review"),  # re-KYB | alerta proveedor | admin
})

# Reapertura de un caso terminal: NO es parte del grafo normal. Solo
# super_admin puede sacarlo de `rejected` (vuelve a under_review).
REOPEN_REJECTED_TARGET = "under_review"

REOPEN_REASONS = ("periodic_review", "provider_alert", "admin")

ACTOR_TYPES = ("system", "client", "internal")

# En estos estados el expediente es read-only para el cliente.
CLIENT_READONLY_STATES = frozenset(
    {"submitted", "screening", "under_review", "approved"})


class KybStateError(Exception):
    """Base de errores de la máquina de estados."""


class InvalidTransitionError(KybStateError):
    def __init__(self, from_status: str, to_status: str, detail: str = ""):
        self.from_status, self.to_status = from_status, to_status
        msg = f"transición no declarada: {from_status!r} → {to_status!r}"
        if detail:
            msg = f"{msg} ({detail})"
        super().__init__(msg)


class ForbiddenTransitionError(KybStateError):
    """Transición declarada pero prohibida para este actor/contexto."""


def validate_transition(from_status: str, to_status: str, *,
                        actor_type: str,
                        actor_role: Optional[str] = None,
                        reopen_reason: Optional[str] = None) -> None:
    """Lanza excepción si la transición no puede ejecutarse. No hace I/O."""
    if actor_type not in ACTOR_TYPES:
        raise KybStateError(f"actor_type inválido: {actor_type!r}")
    if from_status not in STATES:
        raise KybStateError(f"estado origen desconocido: {from_status!r}")
    if to_status not in STATES:
        raise KybStateError(f"estado destino desconocido: {to_status!r}")

    # Ningún actor system puede llegar a rejected — jamás.
    if to_status == "rejected" and actor_type == "system":
        raise ForbiddenTransitionError(
            "ninguna automatización puede rechazar un caso; "
            "rejected requiere una persona")

    # rejected es terminal: reabrir solo super_admin, y solo a under_review.
    if from_status == "rejected":
        if to_status == REOPEN_REJECTED_TARGET and actor_role == "super_admin":
            return
        raise ForbiddenTransitionError(
            "rejected es terminal — reabrir requiere super_admin "
            f"(y solo hacia {REOPEN_REJECTED_TARGET!r})")

    if (from_status, to_status) not in TRANSITIONS:
        raise InvalidTransitionError(from_status, to_status)

    # approved → under_review exige motivo de reapertura tipado.
    if from_status == "approved" and to_status == "under_review":
        if reopen_reason not in REOPEN_REASONS:
            raise ForbiddenTransitionError(
                "approved → under_review requiere reopen_reason en "
                f"{REOPEN_REASONS}")


def transition_fields(from_status: str, to_status: str, *,
                      reopen_reason: Optional[str] = None) -> dict:
    """Campos a setear en el doc al aplicar la transición (parte pura)."""
    now = utc_now()
    fields: dict = {"status": to_status, "updated_at": now}
    if to_status == "submitted":
        fields["submitted_at"] = now
    if to_status in ("approved", "rejected"):
        fields["resolved_at"] = now
    if from_status == "approved" and to_status == "under_review":
        fields["reopen_reason"] = reopen_reason
    if from_status == "expired" and to_status == "in_progress":
        fields["expires_at"] = None
    return fields


def client_can_edit(status: str) -> bool:
    """El cliente NO puede editar en submitted/screening/under_review/
    approved (ni en terminales)."""
    if status in CLIENT_READONLY_STATES or status == "rejected":
        return False
    return status in ("draft", "in_progress", "info_required", "expired")


def editable_sections(case: dict) -> list[str]:
    """Secciones que el cliente puede editar según el estado del caso.

    En `info_required` solo las secciones con status == "observed"."""
    status = case.get("status")
    sections = case.get("sections") or {}
    if not client_can_edit(status):
        return []
    if status == "info_required":
        return [k for k, v in sections.items()
                if (v or {}).get("status") == "observed"]
    if status == "expired":
        return []  # primero reactivar (expired → in_progress)
    return list(sections.keys())


async def apply_transition(case: dict, to_status: str, *,
                           actor_type: str,
                           actor=None,
                           actor_role: Optional[str] = None,
                           reopen_reason: Optional[str] = None,
                           request=None,
                           metadata: Optional[dict] = None) -> dict:
    """Valida, persiste y audita una transición. Devuelve los campos seteados.

    `actor` es un CurrentUser (o None para system). Toda transición escribe
    kyb.case.state_changed en auditoría.
    """
    from db import col
    from kyb.audit import kyb_audit
    from kyb.models import KYB_CASES

    from_status = case["status"]
    role = actor_role or (getattr(actor, "role", None)
                          and getattr(actor.role, "value", actor.role))
    validate_transition(from_status, to_status, actor_type=actor_type,
                        actor_role=role, reopen_reason=reopen_reason)
    fields = transition_fields(from_status, to_status,
                               reopen_reason=reopen_reason)
    await col(KYB_CASES).update_one({"case_id": case["case_id"]},
                                    {"$set": fields})
    await kyb_audit("kyb.case.state_changed",
                    case_id=case["case_id"], actor=actor, request=request,
                    org_id=case.get("org_id"),
                    metadata={"from": from_status, "to": to_status,
                              "actor_type": actor_type,
                              "reopen_reason": reopen_reason,
                              **(metadata or {})})
    return fields
