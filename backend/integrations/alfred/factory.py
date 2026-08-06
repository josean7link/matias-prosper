"""Factory that returns the active AlfredAdapter based on env."""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Literal

from .adapter import AlfredAdapter
from .mock import MockAlfredAdapter
from .real import RealAlfredAdapter

logger = logging.getLogger("prosper.alfred.factory")


def current_mode() -> Literal["mock", "sandbox", "production"]:
    raw = (os.environ.get("ALFRED_MODE") or "mock").lower()
    if raw not in ("mock", "sandbox", "production"):
        logger.warning("Unknown ALFRED_MODE=%r — falling back to mock", raw)
        return "mock"
    return raw  # type: ignore[return-value]


@lru_cache(maxsize=1)
def _cached_adapter(mode: str) -> AlfredAdapter:
    if mode == "mock":
        logger.info("Alfred adapter: MOCK")
        return MockAlfredAdapter()
    logger.info("Alfred adapter: REAL (%s)", mode)
    return RealAlfredAdapter(mode=mode)  # type: ignore[arg-type]


def get_adapter() -> AlfredAdapter:
    """Cached singleton for the process lifetime. Call `reset_cache()` from
    tests if you flip ALFRED_MODE at runtime."""
    return _cached_adapter(current_mode())


def reset_cache() -> None:
    _cached_adapter.cache_clear()


def verify_webhook(payload: bytes, signature: str) -> bool:
    return get_adapter().verify_webhook(payload=payload, signature=signature)
