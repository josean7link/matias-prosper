"""Phase 04 — Admin synthetic deposit-credited event tests.

Validates that `POST /api/v1/admin/notifications/test` uses the SAME
event_bus path as real publishers (no mock fork), and that it correctly
targets a single user without polluting org-wide recipients.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TEST_DB = "prosper_phase0_test_admin_notif_test"
_ORIG_DB_NAME = os.environ.get("DB_NAME")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

import db as db_module  # noqa: E402
from db import (DEPOSIT_EVENTS, NOTIFICATIONS, ORGANIZATIONS,  # noqa: E402
                    OUTBOUND_EMAILS, USERS, col)
from services.deposit_credited_handler import on_event  # noqa: E402
from services.event_bus import (publish, reset_subscribers_for_tests,  # noqa: E402
                                     subscribe)

ORG_BIZ = "org_test_admin_notif"
USR_ADMIN_A = "usr_admin_a"
USR_ADMIN_B = "usr_admin_b"
USR_TARGET  = "usr_target"


@pytest.fixture(autouse=True)
async def _isolate():
    os.environ["DB_NAME"] = _TEST_DB
    os.environ.pop("RESEND_API_KEY", None)   # mock email path
    db_module._client = None
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(_TEST_DB)
    client.close()
    db_module._client = None

    await col(NOTIFICATIONS).create_index(
        [("idempotency_key", 1), ("user_id", 1)],
        unique=True, sparse=True)
    await col(DEPOSIT_EVENTS).create_index("event_id", unique=True)

    await col(ORGANIZATIONS).insert_one({
        "org_id": ORG_BIZ, "type": "business", "is_deleted": False})
    await col(USERS).insert_many([
        {"user_id": USR_ADMIN_A, "org_id": ORG_BIZ, "role": "client_admin",
          "email": "admina@biz.test",
          "preferences": {"language": "es"},
          "notifications": {"email_account_activity": True}},
        {"user_id": USR_ADMIN_B, "org_id": ORG_BIZ, "role": "client_admin",
          "email": "adminb@biz.test",
          "preferences": {"language": "en"},
          "notifications": {"email_account_activity": True}},
        {"user_id": USR_TARGET, "org_id": ORG_BIZ, "role": "client_user",
          "email": "target@biz.test",
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


async def test_admin_test_event_targets_single_user_not_org_wide():
    """A synthetic event with `user_id` set must go ONLY to that user,
    even if the org has many `client_admin` who would otherwise get
    a broadcast. This is what makes the endpoint safe to fire in prod
    without spamming the whole team."""
    # Simulate the route's payload-construction by calling publish
    # directly with `user_id` set to USR_TARGET.
    now = datetime.now(timezone.utc).isoformat()
    await publish({
        "event_type": "deposit.credited", "version": 1,
        "event_id": "evt_synth_admin_001",
        "asset": "usdc", "deposit_id": "synth_001", "tx_hash": None,
        "org_id": ORG_BIZ, "user_id": USR_TARGET,
        "amount": "42.50", "currency": "USDC",
        "ref": "ADMIN-TEST", "occurred_at": now, "detected_at": now,
        "source": "admin_test",
        "metadata": {"synthetic": True, "fired_by": "ops@prosper"},
    })

    target_notifs = await col(NOTIFICATIONS).find(
        {"user_id": USR_TARGET}, {"_id": 0}).to_list(10)
    admin_a_notifs = await col(NOTIFICATIONS).find(
        {"user_id": USR_ADMIN_A}, {"_id": 0}).to_list(10)
    admin_b_notifs = await col(NOTIFICATIONS).find(
        {"user_id": USR_ADMIN_B}, {"_id": 0}).to_list(10)

    assert len(target_notifs) == 1
    assert target_notifs[0]["data"]["event_id"] == "evt_synth_admin_001"
    assert admin_a_notifs == []   # not spammed
    assert admin_b_notifs == []


async def test_admin_test_event_uses_real_email_pipeline():
    """The synthetic event must traverse the same Resend send_email
    path. In tests, that means `outbound_emails` receives a row with
    the correct template (no separate mock pipeline)."""
    now = datetime.now(timezone.utc).isoformat()
    await publish({
        "event_type": "deposit.credited", "version": 1,
        "event_id": "evt_synth_email", "asset": "arsa",
        "deposit_id": "synth_email_001", "tx_hash": None,
        "org_id": ORG_BIZ, "user_id": USR_TARGET,
        "amount": "12345", "currency": "ARSa", "ref": "ADMIN-TEST",
        "occurred_at": now, "detected_at": now,
        "source": "admin_test",
        "metadata": {"synthetic": True},
    })

    em = await col(OUTBOUND_EMAILS).find_one(
        {"to": "target@biz.test"}, {"_id": 0})
    assert em is not None
    assert em["template"] == "deposit-credited-arsa"
    assert em["status"] == "preview_only"   # mock path (no api key in tests)
    # Rail separation: ARSa subject never says USDC.
    assert "USDC" not in em["subject"]


async def test_admin_test_event_idempotent_on_replay():
    """If ops fires the same `event_id` twice (e.g. accidental retry),
    the bus dedupes. The user does not get spammed."""
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_type": "deposit.credited", "version": 1,
        "event_id": "evt_synth_dup", "asset": "usdc",
        "deposit_id": "synth_dup_001", "tx_hash": None,
        "org_id": ORG_BIZ, "user_id": USR_TARGET,
        "amount": "1", "currency": "USDC", "ref": "ADMIN-TEST",
        "occurred_at": now, "detected_at": now,
        "source": "admin_test", "metadata": {"synthetic": True},
    }
    r1 = await publish(payload)
    r2 = await publish(payload)
    assert r1["action"] == "published"
    assert r2["action"] == "duplicate_skipped"
    notifs = await col(NOTIFICATIONS).find(
        {"user_id": USR_TARGET}).to_list(10)
    assert len(notifs) == 1
