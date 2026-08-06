"""Horizon adapter factory — process-cached, env-driven.

Toggle via `HORIZON_MODE`:
  * "mock"  (default) — fixture-driven, no network.
  * "real"            — httpx against STELLAR_HORIZON_URL.

Cache rationale: MockHorizonAdapter loads the fixture on init, and we
want a single in-memory list so `inject_payment()` from tests is visible
to the watcher's next call. Real mode also benefits from a singleton
(connection pooling implicit in httpx is per-call, but the adapter
itself is cheap to keep).

Call `reset_adapter_cache()` from tests when switching modes or
reloading fixtures.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .adapter import HorizonAdapter

logger = logging.getLogger("prosper.horizon.factory")

_cached: Optional[HorizonAdapter] = None


def get_adapter() -> HorizonAdapter:
    """Return the (possibly cached) HorizonAdapter for the current mode."""
    global _cached
    if _cached is not None:
        return _cached
    mode = (os.environ.get("HORIZON_MODE") or "mock").lower().strip()
    if mode == "real":
        from .real import RealHorizonAdapter
        _cached = RealHorizonAdapter()
    else:
        from .mock import MockHorizonAdapter
        _cached = MockHorizonAdapter()
    logger.info("Horizon adapter initialized (mode=%s)", _cached.mode)
    return _cached


def reset_adapter_cache() -> None:
    """Drop the singleton. Next `get_adapter()` re-reads `HORIZON_MODE`
    and (for mock) reloads the fixture from disk."""
    global _cached
    _cached = None
