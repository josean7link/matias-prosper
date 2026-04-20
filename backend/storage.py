"""Emergent Object Storage helper.

Session-scoped storage_key is initialized once at startup and reused across requests.
Files are uploaded under the `prosper/` prefix to isolate this tenant's bucket namespace.
"""
from __future__ import annotations
import os
import logging
import requests
from typing import Tuple

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_NAME = "prosper"

_storage_key: str | None = None
_logger = logging.getLogger("prosper.storage")


def init_storage() -> str | None:
    """Initialise once at startup; returns the session storage key."""
    global _storage_key
    if _storage_key:
        return _storage_key
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        _logger.warning("EMERGENT_LLM_KEY not set — object storage disabled.")
        return None
    try:
        resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": key}, timeout=30)
        resp.raise_for_status()
        _storage_key = resp.json().get("storage_key")
        _logger.info("Object storage initialized.")
        return _storage_key
    except Exception as e:
        _logger.error(f"Storage init failed: {e}")
        return None


def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    if not key:
        raise RuntimeError("Object storage is not configured.")
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def get_object(path: str) -> Tuple[bytes, str]:
    key = init_storage()
    if not key:
        raise RuntimeError("Object storage is not configured.")
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key}, timeout=60,
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


MIME_MAP = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "csv": "text/csv",
    "txt": "text/plain",
    "json": "application/json",
}


def guess_mime(filename: str, fallback: str | None = None) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    return MIME_MAP.get(ext, fallback or "application/octet-stream")
