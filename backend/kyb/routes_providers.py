"""Fase 7 — Configuración de proveedores KYB (super_admin).

Cada proveedor es un doc en `kyb_provider_configs` por (category, provider).
Credenciales cifradas con `INTEGRATIONS_FERNET_KEY` (Fase 0.5). El texto
completo NUNCA se devuelve por API — solo `credentials_last4`.

Regla de transición a producción: no se puede activar (`enabled=true`)
un proveedor en `environment="production"` sin health check exitoso
previo. El backend rechaza la activación con 409 si falta el health OK.
Toda modificación queda auditada. Con Fase 5b postergada, no hay
proveedores conectados — la pantalla existe para el día que lleguen
credenciales.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import CurrentUser, requires_role
from db import col
from models import utc_now
from roles import Role
from kyb.audit import kyb_audit
from kyb.models import KYB_PROVIDER_CALLS, KYB_PROVIDER_CONFIGS

require_super_admin = requires_role(Role.super_admin)

router = APIRouter(prefix="/admin/compliance/kyb/settings/providers",
                   tags=["kyb-admin-providers"])

CATEGORIES = ["identity", "screening", "company"]
# F8-fix (post-diag 6 puntos): "manual" es la AUSENCIA de proveedor, no
# un proveedor. Solo listamos categorías donde existe al menos un
# proveedor conectable. `company` se suma acá cuando llegue Cepop /
# Boletín Oficial u otra fuente automática.
KNOWN_PROVIDERS = {"identity": ["sumsub"], "screening": ["sumsub"]}
ENVIRONMENTS = ["sandbox", "production"]


def _prosper_mode() -> str:
    return (os.environ.get("PROSPER_MODE") or "development").lower()


async def _cfg(category: str, provider: str) -> Optional[dict]:
    return await col(KYB_PROVIDER_CONFIGS).find_one(
        {"category": category, "provider": provider}, {"_id": 0})


def _sanitize(cfg: dict) -> dict:
    """API-safe: nunca devolver el texto claro de credenciales."""
    out = dict(cfg)
    out.pop("credentials_encrypted", None)
    return out


@router.get("")
async def list_configs(_: CurrentUser = Depends(require_super_admin)):
    rows = await col(KYB_PROVIDER_CONFIGS).find({}, {"_id": 0}).to_list(50)
    # Merge con proveedores conocidos aún no configurados.
    seen = {(r["category"], r["provider"]): r for r in rows}
    items = []
    for cat, provs in KNOWN_PROVIDERS.items():
        for p in provs:
            base = seen.get((cat, p)) or {"category": cat, "provider": p,
                                          "enabled": False,
                                          "environment": None,
                                          "credentials_last4": None,
                                          "settings": {},
                                          "last_health_check": None}
            items.append(_sanitize(base))
    # Extras que estuvieran registrados con otro provider.
    for (cat, p), r in seen.items():
        if p not in KNOWN_PROVIDERS.get(cat, []):
            items.append(_sanitize(r))
    # Contador de webhooks con firma inválida (últimos 30 días — TTL).
    invalid_wh = await col(KYB_PROVIDER_CALLS).count_documents(
        {"direction": "webhook", "signature_valid": False})
    return {"items": items, "prosper_mode": _prosper_mode(),
            "webhook_invalid_signatures_30d": invalid_wh}


class ProviderUpdateIn(BaseModel):
    environment: Optional[str] = None
    credentials: Optional[str] = Field(
        None, description="Se cifra con INTEGRATIONS_FERNET_KEY. Nunca "
                          "se devuelve en claro.")
    settings: Optional[Dict[str, Any]] = None


@router.put("/{category}/{provider}")
async def upsert_config(category: str, provider: str,
                        body: ProviderUpdateIn, request: Request,
                        user: CurrentUser = Depends(require_super_admin)):
    if category not in CATEGORIES:
        raise HTTPException(422, f"category debe ser una de {CATEGORIES}")
    if body.environment and body.environment not in ENVIRONMENTS:
        raise HTTPException(422,
                            f"environment debe ser una de {ENVIRONMENTS}")
    now = utc_now()
    upd: Dict[str, Any] = {"updated_at": now, "updated_by": user.user_id}
    if body.environment is not None:
        upd["environment"] = body.environment
    if body.settings is not None:
        upd["settings"] = body.settings
    audit_meta: Dict[str, Any] = {"category": category, "provider": provider,
                                  "fields": []}
    if body.credentials:
        from services.secret_box import encrypt as _encrypt, last4 as _last4
        upd["credentials_encrypted"] = _encrypt(body.credentials).decode()
        upd["credentials_last4"] = _last4(body.credentials)
        # Rotar credenciales invalida el último health check.
        upd["last_health_check"] = None
        audit_meta["fields"].append("credentials")
        audit_meta["last4"] = upd["credentials_last4"]
    if body.environment is not None:
        audit_meta["fields"].append("environment")
        audit_meta["environment"] = body.environment
    if body.settings is not None:
        audit_meta["fields"].append("settings")
    await col(KYB_PROVIDER_CONFIGS).update_one(
        {"category": category, "provider": provider},
        {"$set": upd, "$setOnInsert": {"created_at": now, "enabled": False}},
        upsert=True)
    await kyb_audit("kyb.provider.config_updated", case_id="__system__",
                    actor=user, request=request, metadata=audit_meta)
    row = await _cfg(category, provider)
    return _sanitize(row or {})


@router.post("/{category}/{provider}/health-check")
async def health_check(category: str, provider: str, request: Request,
                       user: CurrentUser = Depends(require_super_admin)):
    """Con Fase 5b postergada no existe cliente SDK. El health check
    valida que la config sea CONSISTENTE (env + credenciales) y deja el
    resultado registrado en `last_health_check` para poder habilitar
    producción. Cuando llegue Sumsub, este endpoint hace la llamada real
    (server time + endpoint /me) y registra latencia + deriva de reloj."""
    cfg = await _cfg(category, provider)
    if not cfg:
        raise HTTPException(404, "Proveedor no configurado")
    t0 = time.time()
    ok = bool(cfg.get("credentials_encrypted")) and bool(cfg.get("environment"))
    error: Optional[str] = None
    if not ok:
        error = "Faltan credenciales o environment"
    latency_ms = round((time.time() - t0) * 1000, 2)
    result = {"ok": ok, "latency_ms": latency_ms,
              "clock_skew_ms": None,     # sin proveedor: null
              "checked_at": utc_now(), "checked_by": user.user_id,
              "error": error}
    await col(KYB_PROVIDER_CONFIGS).update_one(
        {"category": category, "provider": provider},
        {"$set": {"last_health_check": result, "updated_at": utc_now()}})
    # Telemetría en kyb_provider_calls (TTL 30 días).
    from datetime import datetime as _dt, timezone as _tz
    await col(KYB_PROVIDER_CALLS).insert_one({
        "provider": provider, "direction": "outbound",
        "endpoint": "health_check", "status_code": 200 if ok else 0,
        "latency_ms": latency_ms, "ok": ok, "error_code": error,
        "signature_valid": None,
        "created_at": _dt.now(_tz.utc)})
    await kyb_audit("kyb.provider.health_check", case_id="__system__",
                    actor=user, request=request,
                    metadata={"category": category, "provider": provider,
                              "result": result})
    return result


class EnableIn(BaseModel):
    enabled: bool
    confirmation: Optional[str] = None


@router.post("/{category}/{provider}/enable")
async def toggle_enable(category: str, provider: str, body: EnableIn,
                        request: Request,
                        user: CurrentUser = Depends(require_super_admin)):
    cfg = await _cfg(category, provider)
    if not cfg:
        raise HTTPException(404, "Proveedor no configurado")
    if body.enabled:
        env = cfg.get("environment")
        if env == "production":
            hc = cfg.get("last_health_check") or {}
            if not hc.get("ok"):
                raise HTTPException(409,
                                    "No se puede activar en producción sin "
                                    "un health check exitoso previo")
    await col(KYB_PROVIDER_CONFIGS).update_one(
        {"category": category, "provider": provider},
        {"$set": {"enabled": body.enabled, "updated_at": utc_now(),
                  "updated_by": user.user_id}})
    ev = "kyb.provider.enabled" if body.enabled else "kyb.provider.disabled"
    await kyb_audit(ev, case_id="__system__", actor=user, request=request,
                    metadata={"category": category, "provider": provider,
                              "environment": cfg.get("environment")})
    return {"ok": True, "enabled": body.enabled}


@router.get("/{category}/{provider}/calls")
async def provider_calls(category: str, provider: str,
                         _: CurrentUser = Depends(require_super_admin)):
    outbound = await col(KYB_PROVIDER_CALLS).find(
        {"provider": provider, "direction": "outbound"},
        {"_id": 0}).sort("created_at", -1).limit(20).to_list(20)
    webhooks = await col(KYB_PROVIDER_CALLS).find(
        {"provider": provider, "direction": "webhook"},
        {"_id": 0}).sort("created_at", -1).limit(20).to_list(20)
    invalid = await col(KYB_PROVIDER_CALLS).count_documents(
        {"provider": provider, "direction": "webhook",
         "signature_valid": False})
    return {"outbound": outbound, "webhooks": webhooks,
            "invalid_signatures_30d": invalid}
