"""Backend-agnostic file storage abstraction (Fase 0.5, Aug 2026).

New code stores files through this interface. **No migration of
existing data.** The Andes KYC path stays as-is: files travel through
memory and are forwarded to Andes without local persistence — that
production flow is untouched by this module.

Selection is by env `STORAGE_BACKEND` (default `gridfs`). Only the
GridFS backend is implemented in Fase 0.5. Extension points for S3 /
GCS are documented in `factory.py`.

Access model:
  * `put(content, filename, content_type, metadata) -> storage_key`
    persists the bytes + attaches structured metadata.
  * `get(storage_key)` opens the blob for internal use.
  * `signed_url(storage_key, ttl_seconds)` returns a URL to
    `GET /api/v1/files/{token}` where the token is a one-shot,
    hashed-at-rest, short-lived credential. `storage_key` never
    reaches the client.
"""
from .backend import (StorageBackend, StorageError, StoredFileMeta,
                       DEFAULT_TTL_SECONDS)
from .factory import get_storage, reset_storage_cache

__all__ = ["StorageBackend", "StorageError", "StoredFileMeta",
             "DEFAULT_TTL_SECONDS", "get_storage", "reset_storage_cache"]
