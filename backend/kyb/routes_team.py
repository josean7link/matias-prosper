"""Fase 8 — Sección Equipo del wizard KYB.

Mapeo de roles (opción B confirmada por el usuario):
  ADMINISTRADOR  → users.role="client_admin",  intended_role="administrator"
  OPERADOR       → users.role="client_user",   intended_role="operator"
  SÓLO LECTURA   → users.role="client_user",   intended_role="read_only"

La intención se guarda aparte para migrarla cuando cerremos el modelo
real. Documentado en `docs/kyb/roles_mapping.md`.

Control clave (spec Fase 8): `POST /kyb/team/accept` valida que el CUIT
del usuario que acepta coincida con el de la invitación. Eso impide que
una invitación reenviada termine habilitando a otra persona.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from auth import CurrentUser, get_current_user
from db import col, ORGANIZATIONS, USERS
from models import utc_now
from roles import Role
from kyb.audit import kyb_audit
from kyb.models import (KYB_CASES, KYB_COMPANY_PROFILES,
                        KYB_TEAM_INVITATIONS)
from kyb.notifications import notify

router = APIRouter(prefix="/kyb", tags=["kyb-team"])

INTENDED_ROLES = ("administrator", "operator", "read_only")
DEFAULT_TTL_DAYS = 7


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _norm_tax(v: str) -> str:
    return re.sub(r"\D", "", v or "")


def _map_role(intended: str) -> str:
    return {"administrator": Role.client_admin.value,
            "operator": Role.client_user.value,
            "read_only": Role.client_user.value}[intended]


async def _case_of_user(user: CurrentUser) -> dict:
    if not user.org_id:
        raise HTTPException(403, "Sesión sin organización")
    org = await col(ORGANIZATIONS).find_one({"org_id": user.org_id},
                                            {"_id": 0, "kyb_case_id": 1})
    case_id = (org or {}).get("kyb_case_id")
    case = case_id and await col(KYB_CASES).find_one(
        {"case_id": case_id, "is_deleted": False,
         "verification_modes": {"$exists": True}}, {"_id": 0})
    if not case:
        raise HTTPException(404, "Tu organización no tiene un expediente "
                                 "KYB del módulo nuevo")
    return case


def _require_admin(user: CurrentUser) -> None:
    if user.role != Role.client_admin:
        raise HTTPException(403, "Solo el administrador puede gestionar el "
                                 "equipo")


# ---------------------------------------------------------------------------
# GET /kyb/case/team — representante + invitaciones + miembros activos
# ---------------------------------------------------------------------------
@router.get("/case/team")
async def list_team(user: CurrentUser = Depends(get_current_user)):
    _require_admin(user)
    case = await _case_of_user(user)
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case["case_id"]},
        {"_id": 0, "legal_representative": 1}) or {}
    invitations = await col(KYB_TEAM_INVITATIONS).find(
        {"case_id": case["case_id"]},
        {"_id": 0, "token_hash": 0}).sort("created_at", -1).to_list(100)
    members = await col(USERS).find(
        {"org_id": user.org_id, "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 1, "email": 1, "role": 1,
         "intended_role": 1, "full_name": 1,
         "tax_id": 1}).to_list(100)
    return {"case_id": case["case_id"],
            "legal_representative": profile.get("legal_representative"),
            "invitations": invitations, "members": members,
            "banner": ("El representante legal será administrador de la "
                       "organización. Puedes añadir más administradores o "
                       "miembros solo lectura ahora o más adelante.")}


class InviteIn(BaseModel):
    country_of_residence: Literal["AR"] = "AR"     # solo AR en esta fase
    email: EmailStr
    tax_id: str = Field(..., min_length=8, max_length=13)
    intended_role: Literal["administrator", "operator", "read_only"]
    full_name: Optional[str] = Field(None, max_length=160)


@router.post("/case/team")
async def create_invitation(body: InviteIn, request: Request,
                            user: CurrentUser =
                            Depends(get_current_user)):
    _require_admin(user)
    case = await _case_of_user(user)
    tax_id = _norm_tax(body.tax_id)
    if len(tax_id) != 11:
        raise HTTPException(422, "El CUIT/CUIL debe tener 11 dígitos")
    email = body.email.lower()
    # Duplicados: mismo email o mismo CUIT, invitación pendiente
    dup = await col(KYB_TEAM_INVITATIONS).find_one(
        {"case_id": case["case_id"], "status": "pending",
         "$or": [{"email": email}, {"tax_id": tax_id}]}, {"_id": 1})
    if dup:
        raise HTTPException(409, "Ya existe una invitación pendiente para "
                                 "este email o CUIT")
    # ¿usuario ya activo en la org?
    exist_user = await col(USERS).find_one(
        {"org_id": user.org_id, "is_deleted": {"$ne": True},
         "$or": [{"email": email}, {"tax_id": tax_id}]}, {"_id": 1})
    if exist_user:
        raise HTTPException(409, "Ya hay un miembro con ese email o CUIT")

    raw = secrets.token_urlsafe(32)
    now = utc_now()
    expires = (datetime.fromisoformat(now.replace("Z", "+00:00"))
               + timedelta(days=DEFAULT_TTL_DAYS)).isoformat()
    inv = {"invitation_id": f"inv_{secrets.token_urlsafe(8)}",
           "case_id": case["case_id"], "org_id": user.org_id,
           "email": email, "tax_id": tax_id,
           "full_name": (body.full_name or "").strip() or None,
           "intended_role": body.intended_role,
           "role": _map_role(body.intended_role),
           "country_of_residence": body.country_of_residence,
           "token_hash": _hash(raw), "status": "pending",
           "invited_by": user.user_id, "expires_at": expires,
           "created_at": now, "updated_at": now}
    await col(KYB_TEAM_INVITATIONS).insert_one(dict(inv))
    await kyb_audit("kyb.team.invitation_created", case_id=case["case_id"],
                    actor=user, request=request, org_id=user.org_id,
                    metadata={"invitation_id": inv["invitation_id"],
                              "email": email, "tax_id": tax_id,
                              "intended_role": body.intended_role,
                              "role": inv["role"]})
    # Notificación al invitado — visible el CUIT requerido.
    profile = await col(KYB_COMPANY_PROFILES).find_one(
        {"case_id": case["case_id"]},
        {"_id": 0, "legal_name": 1}) or {}
    from kyb.notifications import _base_url as _bu
    accept_url = f"{_bu()}/kyb/team/accept?token={raw}"
    await notify("kyb.team.invitation", case_id=case["case_id"],
                 recipient=email,
                 context={"company_name": profile.get("legal_name"),
                          "inviter": user.email, "tax_id": tax_id,
                          "accept_url": accept_url},
                 discriminator=inv["invitation_id"])
    out = {k: v for k, v in inv.items() if k != "token_hash"}
    return out


@router.delete("/case/team/{invitation_id}")
async def revoke_invitation(invitation_id: str, request: Request,
                            user: CurrentUser =
                            Depends(get_current_user)):
    _require_admin(user)
    case = await _case_of_user(user)
    r = await col(KYB_TEAM_INVITATIONS).find_one_and_update(
        {"invitation_id": invitation_id, "case_id": case["case_id"],
         "status": "pending"},
        {"$set": {"status": "revoked", "updated_at": utc_now()}},
        return_document=True)
    if not r:
        raise HTTPException(404, "Invitación no encontrada o ya resuelta")
    await kyb_audit("kyb.team.invitation_revoked", case_id=case["case_id"],
                    actor=user, request=request, org_id=user.org_id,
                    metadata={"invitation_id": invitation_id})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Público: aceptar invitación — CUIT del usuario debe coincidir
# ---------------------------------------------------------------------------
class AcceptIn(BaseModel):
    token: str
    tax_id: str = Field(..., min_length=8, max_length=13)
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=160)


@router.post("/team/accept")
async def accept_invitation(body: AcceptIn, request: Request):
    from server import rate_limit
    rate_limit(request, scope="kyb-team-accept", per_min=30)
    inv = await col(KYB_TEAM_INVITATIONS).find_one(
        {"token_hash": _hash(body.token)}, {"_id": 0})
    now = utc_now()
    if not inv or inv.get("status") != "pending" \
            or (inv.get("expires_at") and inv["expires_at"] < now):
        raise HTTPException(404, "Invitación inválida o vencida")
    # Control clave: el CUIT ingresado debe coincidir con el de la
    # invitación. Impide reenvíos a otra persona.
    provided_tax = _norm_tax(body.tax_id)
    if provided_tax != inv["tax_id"]:
        await kyb_audit("kyb.team.invitation_rejected",
                        case_id=inv["case_id"], actor=None, request=request,
                        org_id=inv.get("org_id"),
                        metadata={"invitation_id": inv["invitation_id"],
                                  "reason": "tax_id_mismatch"})
        raise HTTPException(403, "El CUIT/CUIL ingresado no coincide con la "
                                 "invitación")
    # Alta o vinculación del usuario. Si el email difiere del invitado y
    # el usuario provee uno, exigimos que sea el mismo (evita hijack por
    # forward).
    email = (body.email or inv["email"]).lower()
    if email != inv["email"].lower():
        raise HTTPException(403, "El correo debe coincidir con el de la "
                                 "invitación")
    role = inv["role"]
    intended = inv["intended_role"]
    existing = await col(USERS).find_one({"email": email},
                                         {"_id": 0, "user_id": 1,
                                          "org_id": 1, "is_deleted": 1})
    if existing and existing.get("org_id") and \
            existing["org_id"] != inv["org_id"]:
        raise HTTPException(409, "Este usuario ya pertenece a otra "
                                 "organización")
    user_id = existing["user_id"] if existing else \
        f"usr_{secrets.token_urlsafe(6)}"
    await col(USERS).update_one(
        {"email": email},
        {"$set": {"role": role, "intended_role": intended,
                  "org_id": inv["org_id"], "tax_id": inv["tax_id"],
                  "country_of_residence": inv["country_of_residence"],
                  "full_name": (body.full_name or inv.get("full_name")
                                or "").strip() or None,
                  "status": "active", "is_deleted": False,
                  "updated_at": now},
         "$setOnInsert": {"user_id": user_id, "email": email,
                          "kyc_status": "pending", "mfa_enabled": False,
                          "created_at": now}}, upsert=True)
    await col(KYB_TEAM_INVITATIONS).update_one(
        {"invitation_id": inv["invitation_id"]},
        {"$set": {"status": "accepted", "accepted_at": now,
                  "accepted_by": user_id, "updated_at": now}})
    await kyb_audit("kyb.team.invitation_accepted",
                    case_id=inv["case_id"], actor=None, request=request,
                    org_id=inv["org_id"],
                    metadata={"invitation_id": inv["invitation_id"],
                              "email": email, "role": role,
                              "intended_role": intended,
                              "user_id": user_id})
    return {"ok": True, "user_id": user_id, "role": role,
            "intended_role": intended}
