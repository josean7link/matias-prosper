"""Phase 13 — RampProviderRegistry (PRD §2).

Resolves which adapter is active for a given org:

    registry = get_registry()
    provider = await registry.resolve(org_id="org_seed_alemany")
    caps = provider.capabilities()

Read order:
  1. Per-org override row in `ramp_provider_config` (scope == org_id, enabled=true)
  2. Global row (scope == 'global', enabled=true)
  3. Env vars RAMP_PROVIDER / RAMP_PROVIDER_MODE (default: alfred / mock)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from db import col

from .provider import RampProvider

logger = logging.getLogger("prosper.ramp.registry")

RAMP_PROVIDER_CONFIG = "ramp_provider_config"

_DEFAULT_PROVIDER = "alfred"
_DEFAULT_MODE     = "mock"


class RampProviderRegistry:
    """Process-wide singleton; resolves the active adapter per call."""

    def __init__(self) -> None:
        # Cache of (provider_id, mode) → adapter instance. Adapters are
        # cheap to build (no I/O in __init__), so this cache is small.
        self._adapters: dict[tuple[str, str], RampProvider] = {}

    # ---------------------------------------------------------------- public
    async def resolve(self, org_id: Optional[str] = None) -> RampProvider:
        provider_id, mode = await self._read_config(org_id)
        return self._adapter(provider_id, mode)

    def adapter_for(self, provider_id: str, mode: str) -> RampProvider:
        """Direct (sync) access — useful for tests and webhook routing."""
        return self._adapter(provider_id, mode)

    # ---------------------------------------------------------------- helpers
    async def _read_config(self, org_id: Optional[str]
                              ) -> tuple[str, str]:
        # 1) Per-org override
        if org_id:
            row = await col(RAMP_PROVIDER_CONFIG).find_one(
                {"scope": org_id, "enabled": True},
                {"_id": 0, "provider": 1, "mode": 1})
            if row:
                return (row.get("provider") or _DEFAULT_PROVIDER,
                          row.get("mode")     or _DEFAULT_MODE)

        # 2) Global row
        row = await col(RAMP_PROVIDER_CONFIG).find_one(
            {"scope": "global", "enabled": True},
            {"_id": 0, "provider": 1, "mode": 1})
        if row:
            return (row.get("provider") or _DEFAULT_PROVIDER,
                      row.get("mode")     or _DEFAULT_MODE)

        # 3) Env-var fallback (also covers fresh installs without the seed row)
        return (
            (os.environ.get("RAMP_PROVIDER") or _DEFAULT_PROVIDER).lower(),
            (os.environ.get("RAMP_PROVIDER_MODE") or _DEFAULT_MODE).lower(),
        )

    def _adapter(self, provider_id: str, mode: str) -> RampProvider:
        key = (provider_id, mode)
        if key in self._adapters:
            return self._adapters[key]

        # Import inside method to avoid a circular at module import-time
        # (adapters → ramp/__init__ → registry).
        if mode == "mock":
            from .adapters.mock import RampMockAdapter
            inst: RampProvider = RampMockAdapter(provider_id=provider_id)  # type: ignore[arg-type]
        elif provider_id == "alfred":
            from .adapters.alfred import AlfredRampAdapter
            inst = AlfredRampAdapter()
        elif provider_id == "andeslabs":
            from .adapters.andes import AndesAdapter
            inst = AndesAdapter()
        else:
            raise ValueError(
                f"Unknown ramp provider {provider_id!r} (mode={mode!r})")

        self._adapters[key] = inst
        logger.info("ramp registry resolved %s/%s → %s",
                     provider_id, mode, type(inst).__name__)
        return inst


# ---------------------------------------------------------------------------
# Singleton accessor (FastAPI Depends-friendly)
# ---------------------------------------------------------------------------
_singleton: Optional[RampProviderRegistry] = None


def get_registry() -> RampProviderRegistry:
    global _singleton
    if _singleton is None:
        _singleton = RampProviderRegistry()
    return _singleton


def reset_registry() -> None:
    """Test helper — clear the cached singleton + adapter cache."""
    global _singleton
    _singleton = None


# ---------------------------------------------------------------------------
# Seed — invoked from server startup so a fresh DB has a sensible default
# ---------------------------------------------------------------------------
async def ensure_default_provider_config() -> None:
    """Upsert a `scope=global, provider=alfred, mode=mock, enabled=true` row
    if there isn't any global row yet. Never overwrites a manual override.
    Phase 18 — also ensures the global ARSa chain default is set to Stellar
    (with both chains allowed) if missing."""
    from datetime import datetime, timezone
    existing = await col(RAMP_PROVIDER_CONFIG).find_one({"scope": "global"})
    now = datetime.now(timezone.utc).isoformat()
    if not existing:
        await col(RAMP_PROVIDER_CONFIG).insert_one({
            "scope":      "global",
            "provider":   _DEFAULT_PROVIDER,
            "mode":       _DEFAULT_MODE,
            "enabled":    True,
            "default_arsa_chain":  "stellar",
            "allowed_arsa_chains": ["stellar", "base"],
            "updated_by": "system:seed",
            "updated_at": now,
        })
        logger.info("seeded ramp_provider_config (global, %s, %s, arsa=stellar)",
                       _DEFAULT_PROVIDER, _DEFAULT_MODE)
        return
    # Backfill ARSa chain defaults if absent on existing config (phase 18)
    patch = {}
    if not existing.get("default_arsa_chain"):
        patch["default_arsa_chain"] = "stellar"
    if not existing.get("allowed_arsa_chains"):
        patch["allowed_arsa_chains"] = ["stellar", "base"]
    if patch:
        patch["updated_at"] = now
        await col(RAMP_PROVIDER_CONFIG).update_one(
            {"scope": "global"}, {"$set": patch})
        logger.info("backfilled ramp_provider_config global with %s", patch)
