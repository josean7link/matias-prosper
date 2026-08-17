"""Fase 8 — Scheduler KYB (APScheduler).

Se registra en el startup SOLO si `KYB_MODULE_ENABLED=true`. Mismo motor
que `jobs/accrual.py`. Nota: `jobs/deposit_watcher.py` existe pero
nadie lo llama desde `server.startup` — este módulo NO repite ese
patrón: se registra explícitamente y se auditan las corridas.

Tareas:
  1. `expire_inactive` — pasa a `expired` los casos en `in_progress` o
     `info_required` sin actividad por `KYB_INACTIVITY_DAYS` (default
     90). No borra nada; la reactivación es manual (`expired →
     in_progress`, ya en la state machine).
  2. `notify_expiring` — 7 días antes de expirar, dispara
     `kyb.case.expiring`. Idempotente por (case_id, days).
  3. `notify_manual_check_sla` — para cada checklist manual sin
     completar más allá de `KYB_SLA_HOURS` (default 72), dispara
     `kyb.manual_check.pending` al buzón de Compliance
     (`COMPLIANCE_INBOX_EMAIL`).

Todas las horas se derivan del entorno (`KYB_INACTIVITY_DAYS`,
`KYB_SLA_HOURS`) y se pueden inyectar en tests.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from db import col
from models import utc_now
from kyb.audit import kyb_audit
from kyb.models import (KYB_CASES, KYB_COMPANY_PROFILES,
                        KYB_MANUAL_CHECKS)
from kyb.notifications import notify
from kyb.state_machine import apply_transition

logger = logging.getLogger("kyb.jobs")

INACTIVITY_DAYS_DEFAULT = 90
EXPIRING_WARNING_DAYS = 7
SLA_HOURS_DEFAULT = 72


def _inactivity_days() -> int:
    try:
        return int(os.environ.get("KYB_INACTIVITY_DAYS", INACTIVITY_DAYS_DEFAULT))
    except ValueError:
        return INACTIVITY_DAYS_DEFAULT


def _sla_hours() -> int:
    try:
        return int(os.environ.get("KYB_SLA_HOURS", SLA_HOURS_DEFAULT))
    except ValueError:
        return SLA_HOURS_DEFAULT


def _compliance_inbox() -> Optional[str]:
    return (os.environ.get("COMPLIANCE_INBOX_EMAIL") or "").strip() or None


async def _company_name(case_id: str) -> str:
    prof = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case_id}, {"_id": 0, "legal_name": 1})
    return (prof or {}).get("legal_name") or "la empresa"


# ---------------------------------------------------------------------------
# Job 1 — expiración por inactividad
# ---------------------------------------------------------------------------
async def expire_inactive() -> dict:
    days = _inactivity_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = {"status": {"$in": ["in_progress", "info_required"]},
         "is_deleted": False,
         "verification_modes": {"$exists": True},
         "updated_at": {"$lt": cutoff}}
    expired = 0
    async for case in col(KYB_CASES).find(q, {"_id": 0}):
        try:
            await apply_transition(case, "expired", actor_type="system",
                                   actor=None, request=None,
                                   metadata={"trigger": "inactivity",
                                             "inactivity_days": days})
            expired += 1
        except Exception as e:
            logger.warning("expire_inactive falló case=%s err=%s",
                           case.get("case_id"), e)
    logger.info("kyb expire_inactive: %s cases expired (>= %sd)", expired, days)
    return {"expired": expired, "days": days}


# ---------------------------------------------------------------------------
# Job 2 — aviso 7 días antes de expirar
# ---------------------------------------------------------------------------
async def notify_expiring() -> dict:
    total = _inactivity_days()
    warn_at_days = total - EXPIRING_WARNING_DAYS
    if warn_at_days <= 0:
        return {"warned": 0, "reason": "inactivity_days <= 7"}
    upper = (datetime.now(timezone.utc)
             - timedelta(days=warn_at_days)).isoformat()
    lower = (datetime.now(timezone.utc)
             - timedelta(days=warn_at_days + 1)).isoformat()
    q = {"status": {"$in": ["in_progress", "info_required"]},
         "is_deleted": False,
         "verification_modes": {"$exists": True},
         "updated_at": {"$lt": upper, "$gte": lower}}
    warned = 0
    async for case in col(KYB_CASES).find(q, {"_id": 0}):
        recipient = case.get("applicant_email")
        if not recipient:
            continue
        company = await _company_name(case["case_id"])
        try:
            await notify("kyb.case.expiring", case_id=case["case_id"],
                         recipient=recipient,
                         context={"company_name": company,
                                  "days": EXPIRING_WARNING_DAYS},
                         discriminator=f"days={EXPIRING_WARNING_DAYS}")
            warned += 1
        except Exception as e:  # pragma: no cover
            logger.warning("notify_expiring falló case=%s: %s",
                           case["case_id"], e)
    return {"warned": warned}


# ---------------------------------------------------------------------------
# Job 3 — checklists manuales atrasados
# ---------------------------------------------------------------------------
async def notify_manual_check_sla() -> dict:
    inbox = _compliance_inbox()
    if not inbox:
        return {"notified": 0, "reason": "no COMPLIANCE_INBOX_EMAIL"}
    sla_h = _sla_hours()
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=sla_h)).isoformat()
    q = {"status": {"$in": ["pending", "in_progress"]},
         "created_at": {"$lt": cutoff}}
    seen_cases: set[str] = set()
    notified = 0
    async for chk in col(KYB_MANUAL_CHECKS).find(q, {"_id": 0}):
        cid = chk["case_id"]
        if cid in seen_cases:
            continue
        seen_cases.add(cid)
        overdue_h = int((datetime.now(timezone.utc)
                         - datetime.fromisoformat(
                             chk["created_at"].replace("Z", "+00:00"))
                         ).total_seconds() // 3600) - sla_h
        company = await _company_name(cid)
        try:
            await notify("kyb.manual_check.pending", case_id=cid,
                         recipient=inbox,
                         context={"company_name": company,
                                  "overdue_hours": max(overdue_h, 1)},
                         discriminator=f"overdue={overdue_h // 24}d")
            notified += 1
        except Exception as e:  # pragma: no cover
            logger.warning("notify_manual_check_sla falló case=%s: %s",
                           cid, e)
    return {"notified": notified}


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
_scheduler = None


def start_kyb_scheduler() -> Optional[object]:
    """Registra el scheduler. Tolerante a que APScheduler no esté
    (mismo patrón que jobs/accrual.py)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except Exception:
        logger.warning("APScheduler no instalado — jobs KYB deshabilitados")
        return None
    sched = AsyncIOScheduler(timezone="UTC")
    # Diario a las 03:00 UTC — misma ventana que el resto de crons.
    sched.add_job(expire_inactive, "cron", hour=3, minute=0,
                  id="kyb_expire_inactive")
    sched.add_job(notify_expiring, "cron", hour=3, minute=15,
                  id="kyb_notify_expiring")
    sched.add_job(notify_manual_check_sla, "cron", hour=3, minute=30,
                  id="kyb_notify_sla")
    sched.start()
    _scheduler = sched
    logger.info("KYB scheduler started: expire+expiring+sla @ 03:00 UTC")
    return sched


async def audit_run(name: str, result: dict, *, actor=None) -> None:
    await kyb_audit("kyb.job.run", case_id="__system__", actor=actor,
                    request=None,
                    metadata={"job": name, "result": result})
