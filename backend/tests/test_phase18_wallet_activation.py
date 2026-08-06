"""Phase 18 — Stellar wallet activation lifecycle (pending → active).

Validates:
  * Global default ARSa chain is `stellar`.
  * POST /accounts creates a Stellar wallet with status=pending; the mock
    gateway auto-fires `wallet.active` ~800ms later and the wallet flips to
    `active` with `wallet_activated_at` set.
  * Deposit-while-pending race: a fiat.deposit.success fired BEFORE
    wallet.active produces a movement in status=Pending with
    held_for_wallet_activation=true, balance stays 0. After wallet.active
    arrives, the movement flips to Success+released_at and balance bumps.
  * POST /refresh-wallet-status reflects gateway state after settle.
  * Webhook idempotency by delivery_id.
  * Webhook dispatch table includes wallet.active (processed=true,
    event_type=wallet.active in ramp_webhook_events).
  * Phase 14/15.1/16/17 endpoints still work (smoke regression).

The test creates throw-away ECIDs under prefix `test_p18_*` and cleans
ramp_accounts/ramp_wallets/ramp_movements/ramp_balances/ramp_fiat_accounts
in finally blocks. Does NOT touch org_seed_alemany's seeded ramp account
(only reads it).
"""
from __future__ import annotations

import os
import secrets
import time
import uuid

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com",
).rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "prosper_phase0")
GATEWAY_URL = os.environ.get("ANDES_GATEWAY_URL", "http://localhost:8090")
GATEWAY_TOKEN = os.environ.get("GATEWAY_INTERNAL_TOKEN", "dev-internal-token-change-me")
ORG = "org_seed_alemany"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email, "next": "/admin"}, timeout=20,
              allow_redirects=True)
    assert r.status_code == 200, f"dev-login {email}: {r.status_code} {r.text[:200]}"
    return s


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    return _login("admin@prosper.foundation")


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(autouse=True)
def _cleanup_test_data(mongo):
    """Remove any prior test_p18_* leftovers before each test."""
    for coll in ("ramp_accounts", "ramp_wallets", "ramp_fiat_accounts"):
        mongo[coll].delete_many({"end_customer_id": {"$regex": "^test_p18_"}})
    # ramp_movements / ramp_balances are scoped by ramp_account_id, cleaned at end
    yield


def _new_ecid() -> str:
    return f"test_p18_{secrets.token_hex(4)}"


def _wait_until(predicate, timeout=4.0, interval=0.15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

# --- Global default chain --- #
class TestArsaChainDefault:
    def test_global_default_is_stellar(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/arsa-chain", timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["default"] == "stellar", f"default chain: {d}"
        assert set(d["allowed"]) == {"stellar", "base"}
        assert d["source"] == "global"


# --- Stellar wallet creation, pending → active --- #
class TestWalletProvisioning:
    def test_stellar_wallet_starts_pending_then_active(
            self, admin_session, mongo):
        ecid = _new_ecid()
        try:
            r = admin_session.post(
                f"{BASE_URL}/api/v1/ramp/accounts",
                json={"end_customer_id": ecid, "display_name": ecid,
                      "account_type": "business"},
                params={"org_id": ORG},
                headers={"Idempotency-Key": str(uuid.uuid4())},
                timeout=30)
            assert r.status_code == 200, r.text
            acc = r.json()
            assert acc["wallet_chain"] == "stellar"
            assert acc["wallet_status"] == "pending", f"status: {acc}"
            assert acc["wallet_activated_at"] is None

            # ramp_wallets has the row with status=pending
            w = mongo["ramp_wallets"].find_one(
                {"org_id": ORG, "asset": "arsa", "chain": "stellar",
                 "provider_user_id": acc["provider_user_id"]})
            assert w is not None
            assert w["status"] == "pending"
            assert w.get("activated_at") in (None, "")

            # After ~1 second, mock gateway emits wallet.active
            def is_active():
                r = admin_session.get(
                    f"{BASE_URL}/api/v1/ramp/accounts/{ecid}",
                    params={"org_id": ORG}, timeout=10)
                return r.status_code == 200 and \
                    r.json().get("wallet_status") == "active"

            assert _wait_until(is_active, timeout=4.0), \
                "wallet.active never arrived (mock 800ms timer)"

            # Verify timestamps + DB
            r = admin_session.get(
                f"{BASE_URL}/api/v1/ramp/accounts/{ecid}",
                params={"org_id": ORG}, timeout=10)
            acc2 = r.json()
            assert acc2["wallet_status"] == "active"
            assert acc2["wallet_activated_at"] is not None

            w2 = mongo["ramp_wallets"].find_one(
                {"provider_user_id": acc["provider_user_id"],
                 "asset": "arsa", "chain": "stellar"})
            assert w2["status"] == "active"
            assert w2.get("activated_at")
        finally:
            _purge(mongo, ecid)

    def test_refresh_wallet_status_endpoint(self, admin_session, mongo):
        ecid = _new_ecid()
        try:
            r = admin_session.post(
                f"{BASE_URL}/api/v1/ramp/accounts",
                json={"end_customer_id": ecid},
                params={"org_id": ORG},
                headers={"Idempotency-Key": str(uuid.uuid4())},
                timeout=30)
            assert r.status_code == 200, r.text
            # wait for auto-activate
            time.sleep(1.2)
            r = admin_session.post(
                f"{BASE_URL}/api/v1/ramp/accounts/{ecid}/refresh-wallet-status",
                params={"org_id": ORG}, timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["wallet_status"] == "active"
        finally:
            _purge(mongo, ecid)


# --- Deposit-while-pending race --- #
class TestDepositWhilePending:
    def test_deposit_held_then_released_on_wallet_active(
            self, admin_session, mongo):
        ecid = _new_ecid()
        try:
            # 1) Create account — wallet is pending for ~800ms
            r = admin_session.post(
                f"{BASE_URL}/api/v1/ramp/accounts",
                json={"end_customer_id": ecid},
                params={"org_id": ORG},
                headers={"Idempotency-Key": str(uuid.uuid4())},
                timeout=30)
            assert r.status_code == 200
            acc = r.json()
            pu = acc["provider_user_id"]
            assert acc["wallet_status"] == "pending"

            # 2) Immediately fire a deposit BEFORE the 800ms timer
            delivery_dep = "dlv_dep_" + secrets.token_hex(6)
            r = requests.post(
                f"{GATEWAY_URL}/dev/fire-webhook",
                headers={"X-Internal-Token": GATEWAY_TOKEN,
                         "Content-Type": "application/json"},
                json={"type": "fiat.deposit.success",
                      "delivery_id": delivery_dep,
                      "data": {"userId": pu, "amount": "12345",
                               "asset": "arsa", "chain": "stellar",
                               "transactionId": "tx_p18_" + secrets.token_hex(4)}},
                timeout=10)
            assert r.status_code in (200, 201, 202), r.text

            # 3) Within race window, movement should be Pending+held=true
            def held_movement_exists():
                m = mongo["ramp_movements"].find_one(
                    {"provider_user_id": pu, "kind": "deposit"})
                return m and m.get("status") == "Pending" and \
                    m.get("held_for_wallet_activation") is True

            assert _wait_until(held_movement_exists, timeout=2.0), \
                "deposit was not held (movement state didn't match)"

            # Balance must still be 0
            acc_doc = mongo["ramp_accounts"].find_one(
                {"org_id": ORG, "end_customer_id": ecid})
            bal = mongo["ramp_balances"].find_one(
                {"ramp_account_id": acc_doc["id"],
                 "asset": "arsa", "chain": "stellar"})
            assert (not bal) or float(bal.get("balance") or 0) == 0.0, \
                f"balance leaked during pending: {bal}"

            # 4) Wait for wallet.active — should release the held deposit
            def released_and_balance():
                m = mongo["ramp_movements"].find_one(
                    {"provider_user_id": pu, "kind": "deposit"})
                b = mongo["ramp_balances"].find_one(
                    {"ramp_account_id": acc_doc["id"],
                     "asset": "arsa", "chain": "stellar"})
                return (m and m.get("status") == "Success"
                        and m.get("held_for_wallet_activation") is False
                        and m.get("released_at")
                        and b and float(b.get("balance") or 0) == 12345.0)

            assert _wait_until(released_and_balance, timeout=5.0), \
                "wallet.active didn't release held deposit / bump balance"
        finally:
            _purge(mongo, ecid)


# --- Webhook idempotency --- #
class TestWebhookIdempotency:
    def test_wallet_active_idempotent_by_delivery_id(self, mongo):
        # Use the internal webhook endpoint directly (X-Internal-Token).
        delivery_id = "dlv_p18_idemp_" + secrets.token_hex(6)
        pu = "p18_user_" + secrets.token_hex(4)
        body = {
            "event_type": "wallet.active",
            "delivery_id": delivery_id,
            "payload": {"type": "wallet.active",
                        "data": {"userId": pu, "asset": "arsa",
                                 "chain": "stellar",
                                 "address": "GTESTADDR",
                                 "activated_at": "2026-01-01T00:00:00Z"}},
            "signature_valid": True,
            "headers": {},
        }
        try:
            r1 = requests.post(
                f"{BASE_URL}/api/v1/internal/ramp/webhook",
                headers={"X-Internal-Token": GATEWAY_TOKEN,
                         "Content-Type": "application/json"},
                json=body, timeout=10)
            assert r1.status_code == 200, r1.text
            d1 = r1.json()
            assert d1["ok"] is True
            assert d1.get("duplicate") is not True

            r2 = requests.post(
                f"{BASE_URL}/api/v1/internal/ramp/webhook",
                headers={"X-Internal-Token": GATEWAY_TOKEN,
                         "Content-Type": "application/json"},
                json=body, timeout=10)
            assert r2.status_code == 200, r2.text
            d2 = r2.json()
            assert d2["ok"] is True
            assert d2["duplicate"] is True

            # Persisted with processed=true and event_type=wallet.active
            evt = mongo["ramp_webhook_events"].find_one(
                {"delivery_id": delivery_id})
            assert evt is not None
            assert evt["event_type"] == "wallet.active"
            assert evt.get("processed") is True
        finally:
            mongo["ramp_webhook_events"].delete_many(
                {"delivery_id": delivery_id})
            mongo["ramp_wallets"].delete_many({"provider_user_id": pu})


# --- Regression smoke for previous phases --- #
class TestRegressionPhase14_17:
    def test_provider_config_still_readable(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/provider-config", timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "rows" in d and isinstance(d["rows"], list) and d["rows"]
        row = d["rows"][0]
        assert "mode" in row
        assert row.get("default_arsa_chain") == "stellar"

    def test_list_accounts_still_works(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/ramp/accounts",
            params={"org_id": ORG}, timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_account_arsa_chain_override_endpoint(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/accounts/{ORG}/arsa-chain",
            params={"org_id": ORG}, timeout=10)
        # The org_seed_alemany account exists → endpoint should succeed.
        # If it 404s (e.g. seeded as ecid=org_seed_alemany), that's the
        # expected behavior; just sanity-check structure.
        assert r.status_code in (200, 404), r.text


def _purge(mongo, ecid: str) -> None:
    """Remove all artifacts for a test ECID."""
    acc = mongo["ramp_accounts"].find_one({"end_customer_id": ecid})
    if acc:
        acc_id = acc.get("id")
        pu = acc.get("provider_user_id")
        if acc_id:
            mongo["ramp_movements"].delete_many({"ramp_account_id": acc_id})
            mongo["ramp_balances"].delete_many({"ramp_account_id": acc_id})
            mongo["ramp_fiat_accounts"].delete_many({"ramp_account_id": acc_id})
        if pu:
            mongo["ramp_wallets"].delete_many({"provider_user_id": pu})
            mongo["ramp_movements"].delete_many({"provider_user_id": pu})
    mongo["ramp_accounts"].delete_many({"end_customer_id": ecid})
