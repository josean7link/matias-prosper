"""Sprint 12.4 — Onramp E2E plumbing tests.

Validates the small pure-logic helpers that glue Alfred + Prosper together.
The full live integration (KYB approve → provision wallet → onramp → auto-buy)
is best exercised through the E2E Playwright suite in `/app/e2e/`.
"""
from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def test_alfred_status_mapping_covers_mock_and_penny():
    from routes.onramp_flow import alfred_status_to_internal as m
    # Mock (Phase 8 legacy)
    assert m("order.pending")    == "pending"
    assert m("order.confirmed")  == "confirmed"
    assert m("order.completed")  == "completed"
    assert m("order.failed")     == "failed"
    # Penny live (case-insensitive)
    assert m("FIAT_DEPOSIT_RECEIVED") == "pending"
    assert m("TRADE_COMPLETED")        == "confirmed"
    assert m("ON_CHAIN_INITIATED")     == "confirmed"
    assert m("ON_CHAIN_COMPLETED")     == "completed"
    assert m("FAILED")                 == "failed"
    assert m("EXPIRED")                == "failed"
    assert m("CANCELLED")              == "failed"
    # Unknown / empty → None (caller skips silently)
    assert m("")        is None
    assert m("foo.bar") is None


def test_ensure_org_prosper_wallet_skips_when_already_provisioned(monkeypatch):
    """Returns immediately when the org doc already has a `prosper_user_id`,
    without hitting Prosper. Uses Motor by injecting a fake."""
    import asyncio
    from routes import onramp_flow

    class _FakeCol:
        async def find_one(self, *_a, **_k):
            return {"prosper_user_id": "px_existing",
                     "stellar_address": "GABCD..."}

    # Patch `col(ORGANIZATIONS)` to return our fake.
    monkeypatch.setattr(onramp_flow, "col", lambda _n: _FakeCol())
    # Adapter must NOT be called — if it is, this would raise.
    def _no_adapter():
        raise AssertionError("Prosper adapter should not be called when wallet exists")
    monkeypatch.setattr(onramp_flow, "prosper_adapter", _no_adapter)

    res = asyncio.get_event_loop().run_until_complete(
        onramp_flow.ensure_org_prosper_wallet("org_test"))
    assert res == {
        "prosper_user_id": "px_existing",
        "stellar_address": "GABCD...",
        "created":         False,
    }
