"""Fase 5a — Modos de verificación por categoría.

El documento único de `kyb_verification_modes` guarda SOLO los tres
modos. `environment` NO se persiste ni se configura desde la app: se
deriva del entorno del proceso (KYB_ENVIRONMENT > PROSPER_MODE >
default "production") y se inyecta read-only en las respuestas. Así el
mock funciona en preview y está bloqueado en producción POR
CONSTRUCCIÓN, no por una configuración clickeable.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException

from db import col
from models import utc_now
from kyb.models import (CATEGORY_MODES, KYB_VERIFICATION_MODES,
                        VERIFICATION_CATEGORIES)

_SANDBOX_MODES = ("development", "dev", "sandbox", "preview", "test",
                  "staging")


def kyb_environment() -> str:
    env = (os.environ.get("KYB_ENVIRONMENT") or "").strip().lower()
    if env in ("sandbox", "production"):
        return env
    mode = (os.environ.get("PROSPER_MODE") or "").strip().lower()
    return "sandbox" if mode in _SANDBOX_MODES else "production"


async def get_verification_modes() -> dict:
    """Doc único con defaults `manual`. `environment` computado, nunca
    leído de la colección."""
    doc = await col(KYB_VERIFICATION_MODES).find_one({"doc_id": "singleton"},
                                                     {"_id": 0})
    if not doc:
        doc = {"doc_id": "singleton",
               **{c: {"mode": "manual", "updated_by": None,
                      "updated_at": utc_now()}
                  for c in VERIFICATION_CATEGORIES}}
        await col(KYB_VERIFICATION_MODES).update_one(
            {"doc_id": "singleton"}, {"$setOnInsert": dict(doc)},
            upsert=True)
    doc.pop("environment", None)   # jamás fuente de verdad
    doc["environment"] = kyb_environment()
    return doc


async def set_verification_mode(category: str, mode: str,
                                user_id: Optional[str]) -> dict:
    if category not in VERIFICATION_CATEGORIES:
        raise HTTPException(422, f"category debe ser una de "
                                 f"{VERIFICATION_CATEGORIES}")
    if mode not in CATEGORY_MODES:
        raise HTTPException(422, f"mode debe ser uno de {CATEGORY_MODES}")
    if mode == "mock" and kyb_environment() == "production":
        # Regla dura: un mock en producción produce expedientes aprobados
        # con verificaciones que dicen «pasó» y nunca ocurrieron.
        raise HTTPException(409, "El modo simulado (mock) no es "
                                 "seleccionable en producción. Esta regla "
                                 "no es configurable: se deriva del entorno "
                                 "del proceso.")
    await get_verification_modes()   # asegura el doc
    await col(KYB_VERIFICATION_MODES).update_one(
        {"doc_id": "singleton"},
        {"$set": {category: {"mode": mode, "updated_by": user_id,
                             "updated_at": utc_now()}}})
    return await get_verification_modes()
