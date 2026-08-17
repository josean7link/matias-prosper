"""Storage backend factory (Fase 0.5).

Selection by env `STORAGE_BACKEND`. Default `gridfs`.

Extension point for S3 / GCS: implement `services/storage/s3_backend.py`
that satisfies `StorageBackend`, then wire it here. Requirements:

  * `put` should upload to the configured bucket, key-prefixed by scope,
    and return the object key (not a URL).
  * `signed_url` should return the provider's native pre-signed URL —
    NOT `/api/v1/files/{token}` (that endpoint is GridFS-only).
  * S3 credentials must arrive via `INTEGRATIONS_FERNET_KEY`-encrypted
    values in `integration_settings`, never plaintext env vars.

This factory is intentionally the only place that decides which
backend runs.
"""
from __future__ import annotations

import os
from functools import lru_cache

from .backend import StorageBackend
from .gridfs_backend import GridFSStorageBackend


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    kind = (os.environ.get("STORAGE_BACKEND") or "gridfs").lower()
    if kind == "gridfs":
        return GridFSStorageBackend()
    # Extension point — see module docstring.
    raise RuntimeError(f"unknown STORAGE_BACKEND={kind!r}")


def reset_storage_cache() -> None:
    get_storage.cache_clear()
