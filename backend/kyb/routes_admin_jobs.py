"""Fase 8 — Endpoints admin para operar los jobs KYB.

Solo super_admin. `POST /admin/compliance/kyb/jobs/run-expiration`
fuerza la corrida de expiración de expedientes en preview. Rechaza
con 409 en producción — un endpoint que fuerza la expiración de
expedientes no puede estar disponible en producción, ni siquiera para
super_admin. Reusa la misma derivación de entorno que
`verification_modes.kyb_environment()`.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from auth import CurrentUser, requires_role
from kyb.audit import kyb_audit
from kyb.jobs_scheduler import (expire_inactive, notify_expiring,
                                notify_manual_check_sla)
from kyb.verification_modes import kyb_environment
from roles import Role

router = APIRouter(prefix="/admin/compliance/kyb/jobs",
                   tags=["kyb-admin-jobs"])

require_super_admin = requires_role(Role.super_admin)


def _guard_prod():
    if kyb_environment() == "production":
        raise HTTPException(409,
                            "Este endpoint no está disponible en "
                            "producción — los jobs se disparan por el "
                            "scheduler diario")


@router.post("/run-expiration")
async def run_expiration(request: Request,
                         user: CurrentUser = Depends(require_super_admin)):
    _guard_prod()
    result = await expire_inactive()
    await kyb_audit("kyb.job.run", case_id="__system__", actor=user,
                    request=request,
                    metadata={"job": "expire_inactive", "result": result})
    return result


@router.post("/run-expiring-warning")
async def run_expiring_warning(request: Request,
                               user: CurrentUser =
                               Depends(require_super_admin)):
    _guard_prod()
    result = await notify_expiring()
    await kyb_audit("kyb.job.run", case_id="__system__", actor=user,
                    request=request,
                    metadata={"job": "notify_expiring", "result": result})
    return result


@router.post("/run-manual-check-sla")
async def run_manual_check_sla(request: Request,
                               user: CurrentUser =
                               Depends(require_super_admin)):
    _guard_prod()
    result = await notify_manual_check_sla()
    await kyb_audit("kyb.job.run", case_id="__system__", actor=user,
                    request=request,
                    metadata={"job": "notify_manual_check_sla",
                              "result": result})
    return result
