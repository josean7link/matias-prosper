"""GridFS-backed StorageBackend + companion signed-URL token store.

The signed URL is served by `routes/files.py` — this module only owns
persistence and token bookkeeping.

Metadata layout on each GridFS entry:
    {
      "content_type": "...",
      "sha256":       "...",
      "uploaded_by":  "usr_...",
      "uploaded_at":  "2026-...Z",
      "scope_kind":   "kyb_case" | ...,
      "scope_id":     "kyb_...",
      "extra":        {…}
    }

Signed-URL tokens live in `file_access_tokens` with the token hash as
key. The raw token never touches Mongo.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from db import col, db as get_db

from .backend import StorageBackend, StorageError, DEFAULT_TTL_SECONDS


FILE_ACCESS_TOKENS = "file_access_tokens"


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GridFSStorageBackend(StorageBackend):
    def __init__(self, bucket_name: str = "prosper_files") -> None:
        self._bucket_name = bucket_name

    def _bucket(self) -> AsyncIOMotorGridFSBucket:
        return AsyncIOMotorGridFSBucket(get_db(),
                                          bucket_name=self._bucket_name)

    async def put(self, *, content: bytes, filename: str,
                    content_type: str, metadata: dict) -> str:
        stored_meta = {
            "content_type":  content_type,
            "sha256":        _sha256(content),
            "uploaded_by":   metadata.get("uploaded_by"),
            "uploaded_at":   metadata.get("uploaded_at")
                                or _now().isoformat(),
            "scope_kind":    metadata.get("scope_kind"),
            "scope_id":      metadata.get("scope_id"),
            "extra":         metadata.get("extra") or {},
        }
        oid = await self._bucket().upload_from_stream(
            filename=filename, source=content, metadata=stored_meta)
        return str(oid)

    async def get(self, storage_key: str) -> tuple[bytes, dict]:
        try:
            oid = ObjectId(storage_key)
        except Exception:
            raise StorageError(f"invalid storage_key {storage_key!r}")
        stream = await self._bucket().open_download_stream(oid)
        content = await stream.read()
        # `stream.metadata` includes filename via GridFS internals; we
        # merge for callers.
        meta = dict(stream.metadata or {})
        meta.setdefault("filename", stream.filename)
        meta.setdefault("length", stream.length)
        return content, meta

    async def delete(self, storage_key: str) -> bool:
        try:
            oid = ObjectId(storage_key)
        except Exception:
            return False
        try:
            await self._bucket().delete(oid)
            return True
        except Exception:
            return False

    async def exists(self, storage_key: str) -> bool:
        try:
            oid = ObjectId(storage_key)
        except Exception:
            return False
        cur = self._bucket().find({"_id": oid}).limit(1)
        async for _ in cur:
            return True
        return False

    async def signed_url(self, storage_key: str,
                            ttl_seconds: int = DEFAULT_TTL_SECONDS,
                            single_use: bool = False) -> str:
        if not await self.exists(storage_key):
            raise StorageError(f"storage_key {storage_key!r} not found")
        raw_token = secrets.token_urlsafe(32)
        expires = _now() + timedelta(seconds=ttl_seconds)
        await col(FILE_ACCESS_TOKENS).insert_one({
            "token_hash":   _hash_token(raw_token),
            "storage_key":  storage_key,
            "single_use":   bool(single_use),
            # BSON Date on purpose — the TTL index on `expires_at`
            # (db.ensure_indexes) purges expired tokens automatically.
            "expires_at":   expires,
            "used_at":      None,
            "last_used_at": None,
            "use_count":    0,
            "created_at":   _now().isoformat(),
        })
        return f"/api/v1/files/{raw_token}"


async def consume_access_token(raw_token: str) -> str | None:
    """Return the `storage_key` a raw token resolves to.

    * single_use tokens: atomically claimed on first hit; every later
      attempt returns None.
    * multi-use tokens (default): valid any number of times until
      `expires_at`.
    Both modes bump `use_count` and stamp `last_used_at`. Returns None
    for not-found, expired and exhausted alike — indistinguishable to
    the caller.
    """
    thash = _hash_token(raw_token)
    now = _now()
    stamp = now.isoformat()
    # Atomic claim for single-use tokens: first request wins.
    row = await col(FILE_ACCESS_TOKENS).find_one_and_update(
        {"token_hash": thash, "single_use": True, "used_at": None},
        {"$set": {"used_at": stamp, "last_used_at": stamp},
         "$inc": {"use_count": 1}})
    if row is None:
        # Multi-use path (also: consumed single-use → no match → None).
        row = await col(FILE_ACCESS_TOKENS).find_one_and_update(
            {"token_hash": thash, "single_use": {"$ne": True}},
            {"$set": {"last_used_at": stamp},
             "$inc": {"use_count": 1}})
    if not row:
        return None
    exp = row["expires_at"]
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        return None
    return row["storage_key"]
