"""Tokens de signup/activación del KYB (Fase 2).

Dos clases de token, ambas `secrets.token_urlsafe(32)` y persistidas
SOLO como hash SHA-256 en `kyb_signup_tokens` (el claro nunca toca
Mongo; el de activación viaja únicamente en el email):

  * kind="signup"     — multi-uso hasta vencer (TTL corto, 2 h por
    defecto). Credencial de escritura pre-auth: SOLO habilita
    /signup/contact y /signup/country, y SOLO sobre su case_id.
  * kind="activation" — un solo uso (claim atómico), TTL configurable
    por KYB_ACTIVATION_TOKEN_TTL_HOURS (default 72).

Al emitir un token nuevo se revocan los anteriores de la misma clase
para el mismo caso: siempre hay a lo sumo un token vivo por clase.
`expires_at` es BSON Date — índice TTL en kyb/db_setup.py.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from db import col

KYB_SIGNUP_TOKENS = "kyb_signup_tokens"

SIGNUP_TTL_HOURS_DEFAULT = 2
ACTIVATION_TTL_HOURS_DEFAULT = 72


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def signup_ttl_hours() -> float:
    return float(os.environ.get("KYB_SIGNUP_TOKEN_TTL_HOURS",
                                SIGNUP_TTL_HOURS_DEFAULT))


def activation_ttl_hours() -> float:
    return float(os.environ.get("KYB_ACTIVATION_TOKEN_TTL_HOURS",
                                ACTIVATION_TTL_HOURS_DEFAULT))


async def mint_token(*, kind: str, case_id: str, email: str,
                     ttl_hours: float) -> str:
    """Emite un token nuevo y revoca los vivos anteriores (kind, case)."""
    assert kind in ("signup", "activation")
    raw = secrets.token_urlsafe(32)
    now = _now()
    await col(KYB_SIGNUP_TOKENS).update_many(
        {"kind": kind, "case_id": case_id, "revoked_at": None,
         "used_at": None},
        {"$set": {"revoked_at": now.isoformat()}})
    await col(KYB_SIGNUP_TOKENS).insert_one({
        "token_hash":  _hash(raw),
        "kind":        kind,
        "case_id":     case_id,
        "email":       email,
        "expires_at":  now + timedelta(hours=ttl_hours),  # BSON Date (TTL)
        "used_at":     None,
        "revoked_at":  None,
        "created_at":  now.isoformat(),
    })
    return raw


def _expired(row: dict) -> bool:
    exp = row["expires_at"]
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < _now()


async def check_signup_token(raw: str) -> Optional[dict]:
    """Valida un token kind=signup (multi-uso). Devuelve la fila o None.
    None es idéntico para no-existe / vencido / revocado."""
    if not raw or len(raw) < 20:
        return None
    row = await col(KYB_SIGNUP_TOKENS).find_one(
        {"token_hash": _hash(raw), "kind": "signup", "revoked_at": None})
    if not row or _expired(row):
        return None
    return row


async def consume_activation_token(raw: str) -> Optional[dict]:
    """Claim atómico de un token kind=activation (un solo uso).
    None idéntico para no-existe / vencido / usado / revocado."""
    if not raw or len(raw) < 20:
        return None
    row = await col(KYB_SIGNUP_TOKENS).find_one_and_update(
        {"token_hash": _hash(raw), "kind": "activation",
         "used_at": None, "revoked_at": None},
        {"$set": {"used_at": _now().isoformat()}})
    if not row or _expired(row):
        return None
    return row
