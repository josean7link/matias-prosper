"""Prosper adapter factory."""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from .adapter import ProsperAdapter
from .mock import MockProsperAdapter
from .real import RealProsperAdapter

logger = logging.getLogger("prosper.factory")


def current_mode() -> str:
    raw = (os.environ.get("PROSPER_MODE") or "mock").lower()
    if raw not in ("mock", "development", "production"):
        logger.warning("Unknown PROSPER_MODE=%r — falling back to mock", raw)
        return "mock"
    return raw


@lru_cache(maxsize=1)
def _cached(mode: str) -> ProsperAdapter:
    if mode == "mock":
        logger.info("Prosper adapter: MOCK")
        return MockProsperAdapter()
    logger.info("Prosper adapter: REAL (%s)", mode)
    return RealProsperAdapter(mode=mode)


def get_adapter() -> ProsperAdapter:
    return _cached(current_mode())


def reset_cache() -> None:
    _cached.cache_clear()
