"""Wrapper fino de auditoría para el módulo KYB (Fase 1).

Delega SIEMPRE en `audit.log_action` (backend/audit.py) — la colección
`audit_logs` ya es append-only con `AuditMutationError` en update y
delete. NO existe colección de auditoría paralela.

Normaliza IP (X-Forwarded-For: primer hop) y user agent, y valida que
el tipo de evento esté declarado en `KYB_EVENTS`.
"""
from __future__ import annotations

from typing import Optional

from audit import log_action

KYB_EVENTS = frozenset({
    "kyb.case.created",
    "kyb.case.section_saved",
    "kyb.case.submitted",
    "kyb.case.state_changed",
    "kyb.document.uploaded",
    "kyb.document.deleted",
    "kyb.ubo.created",
    "kyb.ubo.updated",
    "kyb.ubo.deleted",
    "kyb.ubo.confirmed",                 # DDJJ del cuadro societario
    "kyb.ubo.confirmation_invalidated",  # mutación posterior a la DDJJ
    # Fase 5a — verificación manual
    "kyb.verification_modes.updated",
    "kyb.template.created",
    "kyb.template.updated",
    "kyb.manual_check.generated",
    "kyb.manual_check.item_completed",
    "kyb.manual_check.completed",
    "kyb.manual_check.evidence_discarded",
    "kyb.case.forced_manual",
    "kyb.approval.maker_checker_override",
    # Fase 6 — Portal Admin
    "kyb.case.assigned",
    "kyb.section.reviewed",
    "kyb.case.request_info_sent",
    "kyb.case.approval_first_signature",
    "kyb.case.approved",
    "kyb.case.rejected",
    "kyb.case.suspended",
    "kyb.case.unsuspended",
    "kyb.case.risk_overridden",
    "kyb.case.contact_email_registered",
    # Fase 7 — Screening / Registro / Providers / Riesgo / Export
    "kyb.hit.resolved",
    "kyb.hit.blocking_promoted",
    "kyb.hit.blocking_demoted",
    "kyb.hit.provider_sync_scheduled",
    "kyb.hit.provider_sync_ok",
    "kyb.hit.provider_sync_failed",
    "kyb.case.registry_field_accepted",
    "kyb.case.registry_field_observed",
    "kyb.case.rerun_verifications",
    "kyb.case.exported",
    "kyb.provider.config_updated",
    "kyb.provider.health_check",
    "kyb.provider.enabled",
    "kyb.provider.disabled",
    "kyb.risk_model.updated",
    "kyb.risk_model.published",
    "kyb.case.risk_recomputed",
    # Fase 8 — Colaboración y comunicación
    "kyb.shared_link.created",
    "kyb.shared_link.revoked",
    "kyb.team.invitation_created",
    "kyb.team.invitation_accepted",
    "kyb.team.invitation_rejected",
    "kyb.team.invitation_revoked",
    "kyb.job.run",
    "kyb.document.confirmed",
    # F8-fix (post-diag 6 puntos) — orquestador de submit
    "kyb.case.dispatched",
    # Fase 5b — SumsubProvider
    "kyb.provider.applicant_created",
    "kyb.provider.token_generated",
    "kyb.provider.webhook_received",
    "kyb.provider.env_mismatch_rejected",



    "kyb.case.legacy_migrated",
    "kyb.case.legacy_rollback",
    # Fase 2 — signup pre-autenticado
    "kyb.signup.probe_attempt",          # sondeo: email registrado/resuelto
    "kyb.signup.reentry_name_mismatch",  # reingreso con nombre distinto
    "kyb.signup.contact_saved",
    "kyb.signup.country_saved",
    "kyb.signup.resend",
    "kyb.signup.activated",
})


def client_ip(request) -> Optional[str]:
    """IP real del cliente normalizando X-Forwarded-For (primer hop)."""
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    client = getattr(request, "client", None)
    return getattr(client, "host", None)


def client_user_agent(request) -> Optional[str]:
    if request is None:
        return None
    return request.headers.get("user-agent")


async def kyb_audit(event: str, *, case_id: str,
                    actor=None,
                    request=None,
                    org_id: Optional[str] = None,
                    metadata: Optional[dict] = None):
    """Registra un evento KYB en `audit_logs` vía log_action.

    * `actor`: CurrentUser o None (actor de sistema / script).
    * `request`: Request de FastAPI opcional — si el actor no trae
      ip/user_agent, se completan desde acá (XFF normalizado).
    """
    if event not in KYB_EVENTS:
        raise ValueError(f"evento KYB no declarado: {event!r}")

    meta = dict(metadata or {})
    ip = getattr(actor, "ip", None) or client_ip(request)
    ua = getattr(actor, "user_agent", None) or client_user_agent(request)
    if actor is None:
        meta.setdefault("actor_type", "system")
    if ip and getattr(actor, "ip", None) != ip:
        meta.setdefault("ip", ip)
    if ua and getattr(actor, "user_agent", None) != ua:
        meta.setdefault("user_agent", ua)

    return await log_action(actor=actor, action=event,
                            resource_type="kyb_case", resource_id=case_id,
                            metadata=meta, org_id_override=org_id)
