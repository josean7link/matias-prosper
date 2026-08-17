"""Feature flag del módulo KYB (Fase 1)."""
from __future__ import annotations

import os


def kyb_enabled() -> bool:
    """Lee `KYB_MODULE_ENABLED` del entorno en cada llamada (sin cache),
    default false. Con el flag apagado el módulo no ejecuta nada."""
    return os.environ.get("KYB_MODULE_ENABLED", "false").strip().lower() \
        in ("true", "1", "yes")
