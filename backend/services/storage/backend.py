"""Storage abstract interface + shared types (Fase 0.5)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


DEFAULT_TTL_SECONDS = 300


class StorageError(RuntimeError):
    """Any failure raised from a storage backend."""


@dataclass
class StoredFileMeta:
    storage_key: str
    filename: str
    content_type: str
    size: int
    sha256: str
    uploaded_by_user_id: str
    uploaded_at: str            # ISO-8601 UTC
    scope_kind: str             # e.g. "kyb_case", "kyc_case"
    scope_id: str
    extra: dict


class StorageBackend(ABC):
    @abstractmethod
    async def put(self, *, content: bytes, filename: str,
                    content_type: str, metadata: dict) -> str: ...

    @abstractmethod
    async def get(self, storage_key: str) -> tuple[bytes, dict]: ...

    @abstractmethod
    async def delete(self, storage_key: str) -> bool: ...

    @abstractmethod
    async def exists(self, storage_key: str) -> bool: ...

    @abstractmethod
    async def signed_url(self, storage_key: str,
                            ttl_seconds: int = DEFAULT_TTL_SECONDS,
                            single_use: bool = False) -> str:
        """Mint a temporary access URL.

        single_use=False (default): the token can be consumed any number
        of times until it expires — required for in-app viewers (pdf.js
        range requests, page reloads). single_use=True: one-shot token
        for links that leave the platform (e.g. email).
        """
        ...
