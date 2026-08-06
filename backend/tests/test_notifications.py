"""PR — deposit_credited notifications E2E.

Coverage from the spec's DoD:
  * Per-recipient idempotency: business org with 2 client_admin → 2 notifs.
  * Same event redelivered → 1 notif per recipient (not 2 or 4).
  * Scope cross-user: user A cannot mark-read user B's notification.
  * Scope cross-org: user A cannot list user B's notifications.
  * Email toggle off → in-app yes, email skipped_toggle_off.
  * No email → skipped_no_email.
  * Resend failure → in-app intact, email status=failed.
  * Rail separation: ARSa copy never says "USDC" and vice versa.
  * Bilingual (es + en).
  * Personal org → one recipient.
  * Amount formatting (thousands separator).
  * Email respected for ARSa (real-prod path).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TEST_DB = "prosper_phase0_test_notifications"
_ORIG_DB_NAME = os.environ.get("DB_NAME")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

import db as db_module  # noqa: E402
from db import (NOTIFICATIONS, ORGANIZATIONS, OUTBOUND_EMAILS, USERS,  # noqa: E402
                    col)
from services.event_bus import (publish, reset_subscribers_for_tests,  # noqa: E402
                                     subscribe)
from services.deposit_credited_handler import on_event  # noqa: E402
from services.notifications import (list_for_user, mark_read,  # noqa: E402
                                         unread_count, mark_all_read)
from services.notifications_emails import (  # noqa: E402
    inapp_copy_deposit_credited, t_deposit_credited_arsa,
    t_deposit_credited_usdc)


ORG_BUSINESS = "org_test_biz"
ORG_PERSONAL = "org_test_per"
USR_ADMIN_A  = "usr_test_admin_a"
USR_ADMIN_B  = "usr_test_admin_b"
USR_PERSONAL = "usr_test_personal"
USR_OUTSIDER = "usr_test_outsider"   # different org, used for scope checks


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _arsa_event(deposit_id: str = "tx_arsa_001", org_id: str = ORG_BUSINESS
                 ) -> dict:
    return {
        "event_type": "deposit.credited", "version": 1,
        "event_id": f"evt_dep_arsa_{deposit_id}",
        "asset": "arsa", "deposit_id": deposit_id, "tx_hash": None,
        "org_id": org_id, "user_id": None,
        "amount": "12345", "currency": "ARSa", "ref": "REF-ARS-001",
        "occurred_at": _now(), "detected_at": _now(),
        "source": "andes_webhook",
        "metadata": {"chain": "stellar"},
    }


def _usdc_event(deposit_id: str = "u" * 64, org_id: str = ORG_BUSINESS
                 ) -> dict:
    return {
        "event_type": "deposit.credited", "version": 1,
        "event_id": f"evt_dep_usdc_{deposit_id}",
        "asset": "usdc", "deposit_id": deposit_id, "tx_hash": deposit_id,
        "org_id": org_id, "user_id": None,
        "amount": "1234.5000000", "currency": "USDC", "ref": "1739100099",
        "occurred_at": _now(), "detected_at": _now(),
        "source": "stellar_watcher",
        "metadata": {},
    }


@pytest.fixture(autouse=True)
async def _isolate():
    os.environ["DB_NAME"] = _TEST_DB
    os.environ.pop("RESEND_API_KEY", None)
    os.environ["RESEND_FROM"] = "test@example.com"
    db_module._client = None

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(_TEST_DB)
    client.close()
    db_module._client = None

    # Indexes (db.ensure_indexes isn't running in tests)
    await col(NOTIFICATIONS).create_index(
        [("idempotency_key", 1), ("user_id", 1)],
        unique=True, sparse=True, name="idempotency_per_user")
    await col(NOTIFICATIONS).create_index(
        [("user_id", 1), ("read", 1), ("created_at", -1)])

    # Seed orgs
    await col(ORGANIZATIONS).insert_many([
        {"org_id": ORG_BUSINESS, "type": "business",
          "name": "Test Biz", "is_deleted": False},
        {"org_id": ORG_PERSONAL, "type": "personal",
          "name": "Test Per", "is_deleted": False,
          "owner_user_id": USR_PERSONAL},
        {"org_id": "org_test_other", "type": "business",
          "name": "Test Other", "is_deleted": False},
    ])

    # Seed users — 2 client_admin in the business org, 1 in personal, 1 outsider.
    await col(USERS).insert_many([
        {"user_id": USR_ADMIN_A, "org_id": ORG_BUSINESS,
          "email": "alice@biz.test", "role": "client_admin",
          "preferences": {"language": "es"},
          "notifications": {"email_account_activity": True}},
        {"user_id": USR_ADMIN_B, "org_id": ORG_BUSINESS,
          "email": "bob@biz.test", "role": "client_admin",
          "preferences": {"language": "en"},
          "notifications": {"email_account_activity": True}},
        {"user_id": USR_PERSONAL, "org_id": ORG_PERSONAL,
          "email": "personal@user.test", "role": "client_user",
          "preferences": {"language": "es"},
          "notifications": {"email_account_activity": True}},
        {"user_id": USR_OUTSIDER, "org_id": "org_test_other",
          "email": "out@other.test", "role": "client_admin",
          "preferences": {"language": "es"},
          "notifications": {"email_account_activity": True}},
    ])

    reset_subscribers_for_tests()
    subscribe("deposit.credited", on_event)

    yield

    reset_subscribers_for_tests()
    if db_module._client is not None:
        db_module._client.close()
        db_module._client = None
    if _ORIG_DB_NAME is not None:
        os.environ["DB_NAME"] = _ORIG_DB_NAME
    else:
        os.environ.pop("DB_NAME", None)


# ---------------------------------------------------------------------------
# Recipient resolution + per-recipient idempotency (THE key invariant)
# ---------------------------------------------------------------------------
async def test_business_org_two_client_admins_get_two_notifications():
    """The critical correctness test: a single deposit event to a
    business-org with 2 client_admin recipients yields 2 notifications,
    one per user. Idempotency is per-recipient, not global."""
    await publish(_arsa_event(deposit_id="multi_admin_001"))
    a = await list_for_user(user_id=USR_ADMIN_A)
    b = await list_for_user(user_id=USR_ADMIN_B)
    assert len(a["items"]) == 1
    assert len(b["items"]) == 1
    assert a["items"][0]["org_id"] == ORG_BUSINESS
    assert b["items"][0]["org_id"] == ORG_BUSINESS
    # Both share the same idempotency_key (same event) but live in
    # different rows because of the per-user unique index.
    assert a["items"][0]["idempotency_key"] \
        == b["items"][0]["idempotency_key"]
    assert a["items"][0]["notification_id"] \
        != b["items"][0]["notification_id"]


async def test_redelivery_same_event_does_not_duplicate_per_user():
    await publish(_arsa_event(deposit_id="redeliver_x"))
    # Force re-trigger via on_event directly (bypassing the event_bus
    # dedupe), to verify that the per-recipient unique index is the
    # actual guarantee.
    await on_event(_arsa_event(deposit_id="redeliver_x"))
    a = await list_for_user(user_id=USR_ADMIN_A)
    b = await list_for_user(user_id=USR_ADMIN_B)
    assert len(a["items"]) == 1
    assert len(b["items"]) == 1


async def test_personal_org_resolves_owner_only():
    await publish(_arsa_event(deposit_id="personal_001",
                                  org_id=ORG_PERSONAL))
    p = await list_for_user(user_id=USR_PERSONAL)
    assert len(p["items"]) == 1
    # Outsider gets nothing
    out = await list_for_user(user_id=USR_OUTSIDER)
    assert len(out["items"]) == 0


# ---------------------------------------------------------------------------
# Scope guards — cross-user and cross-org
# ---------------------------------------------------------------------------
async def test_user_a_cannot_mark_user_b_notification_read():
    await publish(_arsa_event(deposit_id="scope_test"))
    b_list = await list_for_user(user_id=USR_ADMIN_B)
    target_id = b_list["items"][0]["notification_id"]
    # User A attempts to mark B's notif read → must return False (= 404
    # at the HTTP layer).
    ok = await mark_read(user_id=USR_ADMIN_A,
                            notification_id=target_id)
    assert ok is False
    # B's notification is STILL unread
    refreshed = await list_for_user(user_id=USR_ADMIN_B)
    assert refreshed["items"][0]["read"] is False


async def test_user_a_does_not_see_user_b_or_outsider_notifications():
    await publish(_arsa_event(deposit_id="scope_list_001"))
    await publish(_arsa_event(deposit_id="scope_list_002",
                                  org_id="org_test_other"))
    a = await list_for_user(user_id=USR_ADMIN_A)
    out = await list_for_user(user_id=USR_OUTSIDER)
    # A sees only the business-org event
    assert {i["data"]["deposit_id"] for i in a["items"]} == {"scope_list_001"}
    # Outsider sees only their own
    assert {i["data"]["deposit_id"] for i in out["items"]} == {"scope_list_002"}


async def test_unread_count_is_user_scoped():
    await publish(_arsa_event(deposit_id="unr_001"))
    await publish(_arsa_event(deposit_id="unr_002"))
    a = await unread_count(user_id=USR_ADMIN_A)
    out = await unread_count(user_id=USR_OUTSIDER)
    assert a == 2
    assert out == 0


async def test_mark_all_read_only_affects_caller():
    await publish(_arsa_event(deposit_id="all_001"))
    n = await mark_all_read(user_id=USR_ADMIN_A)
    assert n == 1
    assert await unread_count(user_id=USR_ADMIN_A) == 0
    # B is untouched
    assert await unread_count(user_id=USR_ADMIN_B) == 1


# ---------------------------------------------------------------------------
# Channel rules
# ---------------------------------------------------------------------------
async def test_email_toggle_off_creates_inapp_only():
    await col(USERS).update_one(
        {"user_id": USR_ADMIN_A},
        {"$set": {"notifications.email_account_activity": False}})
    await publish(_arsa_event(deposit_id="toggle_off"))
    rows = await col(NOTIFICATIONS).find(
        {"user_id": USR_ADMIN_A}, {"_id": 0}).to_list(10)
    assert len(rows) == 1
    assert rows[0]["channels"]["inapp"] == "delivered"
    assert rows[0]["channels"]["email"] == "skipped_toggle_off"
    # No email row was created
    em = await col(OUTBOUND_EMAILS).find(
        {"user_id": USR_ADMIN_A}).to_list(5)
    assert em == []


async def test_user_without_email_gets_skipped_no_email():
    await col(USERS).update_one(
        {"user_id": USR_ADMIN_A}, {"$set": {"email": ""}})
    await publish(_arsa_event(deposit_id="no_email"))
    rows = await col(NOTIFICATIONS).find(
        {"user_id": USR_ADMIN_A}).to_list(10)
    assert len(rows) == 1
    assert rows[0]["channels"]["email"] == "skipped_no_email"


async def test_resend_unavailable_falls_back_to_preview_only():
    """`RESEND_API_KEY` is unset in this fixture → email_sender takes
    the mock path. The notification's channels.email reflects that."""
    await publish(_arsa_event(deposit_id="preview_001"))
    rows = await col(NOTIFICATIONS).find(
        {"user_id": USR_ADMIN_A}).to_list(10)
    assert rows[0]["channels"]["email"] == "preview_only"
    em = await col(OUTBOUND_EMAILS).find_one(
        {"to": "alice@biz.test"}, {"_id": 0})
    assert em is not None
    assert em["status"] == "preview_only"
    assert em["template"] == "deposit-credited-arsa"


async def test_resend_500_marks_email_failed_inapp_intact():
    os.environ["RESEND_API_KEY"] = "test-key"

    class _Resp:
        status_code = 500
        text = "internal error"
        def json(self): return {}

    async def _fake_post(self, *args, **kwargs):
        return _Resp()

    # Patch httpx — short backoffs to keep the test quick.
    with patch("httpx.AsyncClient.post", new=_fake_post), \
         patch("integrations.email_sender._RETRY_BACKOFFS_S", (0.0, 0.0)):
        await publish(_arsa_event(deposit_id="resend_fail"))

    rows = await col(NOTIFICATIONS).find(
        {"user_id": USR_ADMIN_A}).to_list(10)
    assert rows[0]["channels"]["inapp"] == "delivered"
    assert rows[0]["channels"]["email"] == "failed"
    em = await col(OUTBOUND_EMAILS).find_one(
        {"to": "alice@biz.test"}, {"_id": 0})
    assert em["status"] == "failed"
    assert em["attempts"] == 3   # all retries consumed

    os.environ.pop("RESEND_API_KEY", None)


# ---------------------------------------------------------------------------
# Rail separation — copy never crosses
# ---------------------------------------------------------------------------
async def test_arsa_copy_never_references_usdc():
    subj_es, html_es = t_deposit_credited_arsa(
        lang="es", amount="100", ref=None,
        date_iso="2026-02-09 12:00", portal_url="https://x.test/client")
    subj_en, html_en = t_deposit_credited_arsa(
        lang="en", amount="100", ref=None,
        date_iso="2026-02-09 12:00", portal_url="https://x.test/client")
    for s in (subj_es, html_es, subj_en, html_en):
        assert "USDC" not in s and "usdc" not in s
        assert "ARSa" in s or "arsa" in s.lower()


async def test_usdc_copy_never_references_arsa():
    subj_es, html_es = t_deposit_credited_usdc(
        lang="es", amount="100", ref=None,
        date_iso="2026-02-09 12:00", portal_url="https://x.test/client")
    subj_en, html_en = t_deposit_credited_usdc(
        lang="en", amount="100", ref=None,
        date_iso="2026-02-09 12:00", portal_url="https://x.test/client")
    for s in (subj_es, html_es, subj_en, html_en):
        assert "ARSa" not in s and "ARSA" not in s and "arsa" not in s.lower()
        assert "USDC" in s


async def test_inapp_copy_rail_separated():
    arsa_title, arsa_body = inapp_copy_deposit_credited(
        lang="es", asset="arsa", amount="100")
    usdc_title, usdc_body = inapp_copy_deposit_credited(
        lang="es", asset="usdc", amount="100")
    assert "ARSa" in arsa_title and "USDC" not in arsa_title
    assert "USDC" in usdc_title and "ARSa" not in usdc_title
    assert "USDC" not in arsa_body
    assert "ARSa" not in usdc_body


# ---------------------------------------------------------------------------
# Amount formatting — thousands separator
# ---------------------------------------------------------------------------
async def test_amount_formatting_arsa_es():
    title, body = inapp_copy_deposit_credited(
        lang="es", asset="arsa", amount="12345")
    assert "12.345" in body   # es thousands separator
    assert "12,345" not in body


async def test_amount_formatting_usdc_en():
    title, body = inapp_copy_deposit_credited(
        lang="en", asset="usdc", amount="1234.5")
    assert "1,234.50" in body   # en thousands + 2 decimals


async def test_amount_formatting_usdc_es():
    title, body = inapp_copy_deposit_credited(
        lang="es", asset="usdc", amount="1234.5")
    assert "1.234,50" in body


# ---------------------------------------------------------------------------
# Bilingual subject
# ---------------------------------------------------------------------------
async def test_bilingual_subject_via_user_preference():
    """USR_ADMIN_A is es, USR_ADMIN_B is en. Same event → 2 emails with
    different subjects."""
    await publish(_arsa_event(deposit_id="bilingual_001"))
    a_email = await col(OUTBOUND_EMAILS).find_one(
        {"to": "alice@biz.test"}, {"_id": 0})
    b_email = await col(OUTBOUND_EMAILS).find_one(
        {"to": "bob@biz.test"}, {"_id": 0})
    assert "Depósito acreditado" in a_email["subject"]
    assert "Deposit credited" in b_email["subject"]


# ---------------------------------------------------------------------------
# USDC end-to-end (mirror of ARSa flow)
# ---------------------------------------------------------------------------
async def test_usdc_event_creates_notifications_with_usdc_copy():
    await publish(_usdc_event(deposit_id="a" * 64))
    a = await list_for_user(user_id=USR_ADMIN_A)
    assert len(a["items"]) == 1
    n = a["items"][0]
    assert n["type"] == "deposit_credited_usdc"
    assert n["data"]["asset"] == "usdc"
    assert "USDC" in n["title"]
    assert "ARSa" not in n["title"]
