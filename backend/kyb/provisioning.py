"""Fase 6 — Evento de dominio kyb.case.approved.

El handler de provisioning (wallets + CVU) queda ESCRITO pero
DESACTIVADO por KYB_AUTO_PROVISIONING_ENABLED (default false): el
auto-sync de CVU post-onboarding sigue sin resolverse estructuralmente
y no se propaga esa falla. NADA acá toca organizations.kyb_status.

Decisión deliberada: NO se usa services/event_bus.py — ese bus persiste
en la colección de eventos de depósitos y el detector de depósitos no
debe recibir tipos ajenos. El evento queda en la auditoría inmutable
(kyb.case.approved, emitido por routes_admin_cases) y este módulo decide
si además invoca el handler.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("prosper.kyb.provisioning")


def auto_provisioning_enabled() -> bool:
    return os.environ.get("KYB_AUTO_PROVISIONING_ENABLED", "false") \
        .strip().lower() in ("true", "1", "yes")


async def emit_case_approved(case: dict, *, approved_by: str) -> None:
    if not auto_provisioning_enabled():
        logger.info("kyb.case.approved emitido para %s — provisioning "
                    "handler desactivado (KYB_AUTO_PROVISIONING_ENABLED"
                    "=false)", case["case_id"])
        return
    await _handle_provisioning(case, approved_by=approved_by)


async def _handle_provisioning(case: dict, *, approved_by: str) -> None:
    """Stub documentado del provisioning post-aprobación (wallets/CVU).
    Se activará en una fase futura cuando el auto-sync de CVU esté
    resuelto estructuralmente. Hoy NO hace nada aunque el flag esté on."""
    logger.warning("KYB_AUTO_PROVISIONING_ENABLED=true pero el handler es "
                   "un stub deliberado: provisioning de %s NO ejecutado",
                   case["case_id"])
