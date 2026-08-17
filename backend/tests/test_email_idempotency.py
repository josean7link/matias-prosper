"""Tests for send_email idempotency (Fase 0.5)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db as db_module               # noqa: E402
from db import OUTBOUND_EMAILS, col   # noqa: E402


@pytest_asyncio.fixture()
async def _clean():
    db_module._client = None
    await col(OUTBOUND_EMAILS).delete_many({"template": "test_idempotency"})
    yield
    await col(OUTBOUND_EMAILS).delete_many({"template": "test_idempotency"})
    db_module._client = None


@pytest.mark.asyncio
async def test_no_key_inserts_two_rows(_clean):
    from integrations.email_sender import send_email
    a = await send_email(to="a@x.io", subject="s", html="h",
                          template="test_idempotency")
    b = await send_email(to="a@x.io", subject="s", html="h",
                          template="test_idempotency")
    assert a["email_id"] != b["email_id"]


@pytest.mark.asyncio
async def test_same_key_returns_prior_record(_clean):
    from integrations.email_sender import send_email
    key = "kyb_case_123::approved::a@x.io"
    a = await send_email(to="a@x.io", subject="s", html="h",
                          template="test_idempotency", idempotency_key=key)
    b = await send_email(to="a@x.io", subject="s2", html="h2",
                          template="test_idempotency", idempotency_key=key)
    assert a["email_id"] == b["email_id"]
    assert b["subject"] == a["subject"]     # returned as-is, not overwritten


@pytest.mark.asyncio
async def test_different_recipients_can_share_event_root(_clean):
    """Same event about same case → two people. Distinct keys. Both sent."""
    from integrations.email_sender import send_email
    a = await send_email(to="a@x.io", subject="s", html="h",
                          template="test_idempotency",
                          idempotency_key="case_1::approved::a@x.io")
    b = await send_email(to="b@x.io", subject="s", html="h",
                          template="test_idempotency",
                          idempotency_key="case_1::approved::b@x.io")
    assert a["email_id"] != b["email_id"]
    assert a["to"] == "a@x.io" and b["to"] == "b@x.io"
