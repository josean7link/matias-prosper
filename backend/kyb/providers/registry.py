"""Registry — resuelve `VerificationProvider` para una `(capability,)`
consultando `kyb_provider_configs`. Devuelve una instancia por proceso
(cache), reusable entre requests."""
from __future__ import annotations

import os
from typing import Optional

from kyb.providers.base import (Capability, ProviderNotConfigured,
                                VerificationProvider)


# Cache in-process: (provider_id, environment) → instancia.
_INSTANCES: dict[tuple[str, Optional[str]], VerificationProvider] = {}


def _reset_cache_for_tests():
    """Sólo para tests: limpia el cache."""
    _INSTANCES.clear()


async def get_provider(capability: Capability) -> VerificationProvider:
    """Devuelve la implementación activa para la capability solicitada.

    Reglas:
      - Se lee `kyb_provider_configs` con `category == capability` y se
        toma la fila con `enabled=True`.
      - Si no hay fila habilitada → `ProviderNotConfigured`.
      - Si `provider=="sumsub"` y `KYB_PROVIDER_SUMSUB_ENABLED != "true"`
        → `ProviderNotConfigured` (feature flag global).
      - Si `provider=="manual"` → siempre devuelve `ManualProvider`.

    Con `KYB_PROVIDER_SUMSUB_ENABLED=false` (default), sumsub queda
    invisible: la fila puede existir habilitada, pero el orquestador
    igual cae al `note: skipped_no_provider`. Es lo que preserva el
    comportamiento actual."""
    from db import col
    from kyb.models import KYB_PROVIDER_CONFIGS

    # `category` en el modelo puede ser "identity"|"screening"|"company"
    # — normalizamos: capability="company_registry" ↔ category="company".
    cat = "company" if capability == "company_registry" else capability
    doc = await col(KYB_PROVIDER_CONFIGS).find_one(
        {"category": cat, "enabled": True}, {"_id": 0})
    if not doc:
        raise ProviderNotConfigured(
            f"no enabled provider config for capability={capability!r}")

    provider_id = doc.get("provider", "")
    environment = doc.get("environment")

    if provider_id == "sumsub":
        if os.environ.get("KYB_PROVIDER_SUMSUB_ENABLED", "false") \
                .strip().lower() != "true":
            raise ProviderNotConfigured(
                "sumsub provider disabled by KYB_PROVIDER_SUMSUB_ENABLED "
                "flag")
        # SumsubProvider se importa lazy — todavía no está escrito
        # (bloque 2 del PR). Cuando aparezca, se resuelve acá.
        try:
            from kyb.providers.sumsub import SumsubProvider  # noqa: F401
        except ImportError as e:
            raise ProviderNotConfigured(
                f"sumsub provider not yet available: {e}") from e
        key = (provider_id, environment)
        if key not in _INSTANCES:
            _INSTANCES[key] = SumsubProvider(environment=environment)
        return _INSTANCES[key]

    if provider_id == "manual":
        from kyb.providers.manual import ManualProvider
        key = (provider_id, None)
        if key not in _INSTANCES:
            _INSTANCES[key] = ManualProvider()
        return _INSTANCES[key]

    raise ProviderNotConfigured(
        f"unknown provider {provider_id!r} for capability={capability!r}")
