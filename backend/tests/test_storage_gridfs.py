"""Tests for the GridFS storage backend + signed URL tokens (Fase 0.5).

EN BASE SCRATCH (`prosper_tests_storage_scratch`): drop al inicio y en
finally. NUNCA toca las colecciones reales — a partir de la Fase 3 del
KYB, `prosper_files.*` guarda documentación societaria de clientes y
un delete_many({}) sobre la base real borraría los expedientes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SCRATCH_DB = "prosper_tests_storage_scratch"
_ORIG_DB_NAME = os.environ.get("DB_NAME")

import db as db_module                              # noqa: E402
from db import col                                   # noqa: E402


@pytest_asyncio.fixture()
async def _clean():
    """Base scratch dedicada + cleanup garantizado (drop en finally)."""
    os.environ["DB_NAME"] = _SCRATCH_DB
    db_module._client = None
    from services.storage.factory import reset_storage_cache
    reset_storage_cache()
    admin = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await admin.drop_database(_SCRATCH_DB)
    try:
        yield
    finally:
        await admin.drop_database(_SCRATCH_DB)
        admin.close()
        if _ORIG_DB_NAME is not None:
            os.environ["DB_NAME"] = _ORIG_DB_NAME
        else:
            os.environ.pop("DB_NAME", None)
        reset_storage_cache()
        db_module._client = None


PDF = b"%PDF-1.4\n" + b"\x00" * 200


@pytest.mark.asyncio
async def test_put_get_delete_exists_roundtrip(_clean):
    from services.storage import get_storage
    s = get_storage()
    key = await s.put(content=PDF, filename="a.pdf",
                        content_type="application/pdf",
                        metadata={"uploaded_by": "usr_test",
                                    "scope_kind": "unit_test",
                                    "scope_id": "case_1"})
    assert isinstance(key, str) and len(key) == 24  # ObjectId hex
    assert await s.exists(key) is True
    content, meta = await s.get(key)
    assert content == PDF
    assert meta["content_type"] == "application/pdf"
    assert meta["scope_kind"] == "unit_test"
    assert meta["sha256"]                         # sha256 stored
    assert await s.delete(key) is True
    assert await s.exists(key) is False


@pytest.mark.asyncio
async def test_single_use_token_fails_on_second_attempt(_clean):
    from services.storage import get_storage
    from services.storage.gridfs_backend import consume_access_token
    s = get_storage()
    key = await s.put(content=PDF, filename="a.pdf",
                        content_type="application/pdf",
                        metadata={"uploaded_by": "usr_test",
                                    "scope_kind": "unit_test",
                                    "scope_id": "case_1"})
    url = await s.signed_url(key, ttl_seconds=60, single_use=True)
    assert url.startswith("/api/v1/files/")
    raw_token = url.split("/api/v1/files/")[1]
    # First consume — resolves.
    got1 = await consume_access_token(raw_token)
    assert got1 == key
    # Second consume — one-shot, must fail.
    got2 = await consume_access_token(raw_token)
    assert got2 is None
    row = await col("file_access_tokens").find_one({})
    assert row["single_use"] is True
    assert row["use_count"] == 1          # failed 2nd attempt does not bump
    assert row["used_at"] is not None
    assert row["last_used_at"] is not None


@pytest.mark.asyncio
async def test_multi_use_token_works_n_times(_clean):
    from services.storage import get_storage
    from services.storage.gridfs_backend import consume_access_token
    s = get_storage()
    key = await s.put(content=PDF, filename="a.pdf",
                        content_type="application/pdf",
                        metadata={"uploaded_by": "usr_test",
                                    "scope_kind": "unit_test",
                                    "scope_id": "case_1"})
    # Default is multi-use (pdf.js range requests / page reloads).
    url = await s.signed_url(key, ttl_seconds=60)
    raw_token = url.split("/api/v1/files/")[1]
    for _ in range(5):
        assert await consume_access_token(raw_token) == key
    row = await col("file_access_tokens").find_one({})
    assert row["single_use"] is False
    assert row["use_count"] == 5
    assert row["last_used_at"] is not None


@pytest.mark.asyncio
async def test_multi_use_token_fails_after_expiry(_clean):
    from services.storage import get_storage
    from services.storage.gridfs_backend import consume_access_token
    s = get_storage()
    key = await s.put(content=PDF, filename="a.pdf",
                        content_type="application/pdf",
                        metadata={"uploaded_by": "usr_test",
                                    "scope_kind": "unit_test",
                                    "scope_id": "case_1"})
    url = await s.signed_url(key, ttl_seconds=1)
    raw_token = url.split("/api/v1/files/")[1]
    assert await consume_access_token(raw_token) == key
    import asyncio
    await asyncio.sleep(1.2)
    assert await consume_access_token(raw_token) is None


@pytest.mark.asyncio
async def test_none_is_identical_for_all_failure_modes(_clean):
    """not-found / expired / exhausted all resolve to plain None."""
    from services.storage import get_storage
    from services.storage.gridfs_backend import consume_access_token
    s = get_storage()
    key = await s.put(content=PDF, filename="a.pdf",
                        content_type="application/pdf",
                        metadata={"uploaded_by": "usr_test",
                                    "scope_kind": "unit_test",
                                    "scope_id": "case_1"})
    # exhausted single-use
    tok_used = (await s.signed_url(key, ttl_seconds=60,
                                     single_use=True)).split("/files/")[1]
    await consume_access_token(tok_used)
    # expired
    tok_expired = (await s.signed_url(key,
                                        ttl_seconds=-1)).split("/files/")[1]
    results = [await consume_access_token("nonexistent-token-1234567890"),
                await consume_access_token(tok_used),
                await consume_access_token(tok_expired)]
    assert results == [None, None, None]


@pytest.mark.asyncio
async def test_expires_at_stored_as_bson_date_for_ttl(_clean):
    """The TTL index needs a BSON Date — a str would silently disable it."""
    from datetime import datetime
    from services.storage import get_storage
    s = get_storage()
    key = await s.put(content=PDF, filename="a.pdf",
                        content_type="application/pdf",
                        metadata={"uploaded_by": "usr_test",
                                    "scope_kind": "unit_test",
                                    "scope_id": "case_1"})
    await s.signed_url(key, ttl_seconds=60)
    row = await col("file_access_tokens").find_one({})
    assert isinstance(row["expires_at"], datetime)


@pytest.mark.asyncio
async def test_signed_url_raw_token_never_stored(_clean):
    from services.storage import get_storage
    s = get_storage()
    key = await s.put(content=PDF, filename="a.pdf",
                        content_type="application/pdf",
                        metadata={"uploaded_by": "usr_test",
                                    "scope_kind": "unit_test",
                                    "scope_id": "case_1"})
    url = await s.signed_url(key, ttl_seconds=60)
    raw_token = url.split("/api/v1/files/")[1]
    # Row must NOT contain the raw token itself.
    row = await col("file_access_tokens").find_one({})
    assert row is not None
    assert row["token_hash"] != raw_token
    assert raw_token not in str(row)


@pytest.mark.asyncio
async def test_signed_url_expiry(_clean):
    from services.storage import get_storage
    from services.storage.gridfs_backend import consume_access_token
    s = get_storage()
    key = await s.put(content=PDF, filename="a.pdf",
                        content_type="application/pdf",
                        metadata={"uploaded_by": "usr_test",
                                    "scope_kind": "unit_test",
                                    "scope_id": "case_1"})
    url = await s.signed_url(key, ttl_seconds=-1)  # already expired
    raw_token = url.split("/api/v1/files/")[1]
    assert await consume_access_token(raw_token) is None
