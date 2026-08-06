"""Phase 17 — ARSa chain selection (Stellar | Base).

E2E backend tests for the new /api/v1/admin/ramp/arsa-chain endpoints +
chain-resolver integration with the create-account flow.

Pre-conditions:
  * org_seed_alemany has an existing ramp account with a wallet bound to
    Andes Prod (REAL mode). We never delete it.
  * For the chain-resolver test we temporarily switch provider mode to mock
    and create a throw-away end_customer_id, then restore everything.
"""
from __future__ import annotations

import os
import secrets
import time

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com",
).rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "prosper_phase0")
ORG = "org_seed_alemany"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email, "next": "/admin"}, timeout=20,
              allow_redirects=True)
    assert r.status_code == 200, f"dev-login failed for {email}: {r.status_code}"
    me = s.get(f"{BASE_URL}/api/v1/auth/me", timeout=10).json()
    assert me["user"]["email"] == email
    return s


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    return _login("admin@prosper.foundation")


@pytest.fixture(scope="module")
def ops_session() -> requests.Session:
    # role = "admin" (NOT super_admin / finance_admin) → cannot mutate
    return _login("ops@prosper.foundation")


@pytest.fixture(scope="module")
def mongo() -> MongoClient:
    c = MongoClient(MONGO_URL)
    yield c
    c.close()


# --------------------------------------------------------------------------- #
# Section F.1 — Global ARSa chain config (GET / PUT)
# --------------------------------------------------------------------------- #
class TestGlobalArsaChain:
    def test_get_global_returns_default_allowed_source(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/arsa-chain", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert set(data) >= {"default", "allowed", "source"}
        assert data["default"] in ("stellar", "base")
        assert isinstance(data["allowed"], list) and data["allowed"]
        assert data["source"] in ("global", "env_default")

    def test_put_sets_global_default_base(self, admin_session, mongo):
        before = mongo[DB_NAME].audit_logs.count_documents(
            {"action": "admin.ramp.arsa_chain.set_global"})
        r = admin_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/arsa-chain",
            json={"default": "base", "allowed": ["stellar", "base"]},
            timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["default"] == "base"
        assert body["source"] == "global"
        assert set(body["allowed"]) == {"stellar", "base"}

        # GET again → reflects new default
        r2 = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/arsa-chain", timeout=10).json()
        assert r2["default"] == "base"
        assert r2["source"] == "global"

        # Audit log was written
        after = mongo[DB_NAME].audit_logs.count_documents(
            {"action": "admin.ramp.arsa_chain.set_global"})
        assert after == before + 1, \
            f"expected 1 new audit entry, got {after - before}"

    def test_put_global_invalid_chain_400(self, admin_session):
        r = admin_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/arsa-chain",
            json={"default": "worldchain"}, timeout=10)
        # FastAPI validation triggers 422 from pydantic pattern, or 400 from
        # the explicit guard. Both are acceptable.
        assert r.status_code in (400, 422)

    def test_put_global_forbidden_for_ops_role(self, ops_session):
        r = ops_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/arsa-chain",
            json={"default": "stellar"}, timeout=10)
        assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Section F.2 — Per-account ARSa chain override
# --------------------------------------------------------------------------- #
class TestAccountArsaChain:
    def test_get_account_returns_effective_chain_and_source(self,
                                                              admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/accounts/{ORG}/arsa-chain",
            params={"org_id": ORG}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["end_customer_id"] == ORG
        assert d["effective_chain"] in ("stellar", "base")
        assert d["source"] in (
            "account_override", "org_override", "global", "env_default")
        assert "override" in d
        assert "has_wallet_on_other_chain" in d

    def test_put_account_override_then_clear(self, admin_session, mongo):
        before_acc = mongo[DB_NAME].audit_logs.count_documents(
            {"action": "admin.ramp.arsa_chain.set_account"})

        # Set override
        r = admin_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/accounts/{ORG}/arsa-chain",
            params={"org_id": ORG},
            json={"override": "stellar"}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["override"] == "stellar"
        assert d["effective_chain"] == "stellar"
        assert d["source"] == "account_override"

        # GET reflects override
        g = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/accounts/{ORG}/arsa-chain",
            params={"org_id": ORG}, timeout=10).json()
        assert g["source"] == "account_override"
        assert g["override"] == "stellar"

        # Clear override
        r2 = admin_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/accounts/{ORG}/arsa-chain",
            params={"org_id": ORG},
            json={"override": None}, timeout=10)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["override"] is None
        assert d2["source"] in ("global", "env_default", "org_override")

        # 2 audit log entries created (set + clear)
        after_acc = mongo[DB_NAME].audit_logs.count_documents(
            {"action": "admin.ramp.arsa_chain.set_account"})
        assert after_acc == before_acc + 2, \
            f"expected 2 new entries, got {after_acc - before_acc}"

    def test_put_account_unknown_ecid_404(self, admin_session):
        r = admin_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/accounts/__doesnotexist__/arsa-chain",
            params={"org_id": ORG},
            json={"override": "base"}, timeout=10)
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Section F.3 — Chain-resolver integration with create-account flow
# Uses mock provider mode so we can create a throw-away wallet.
# --------------------------------------------------------------------------- #
class TestChainResolverInRampRoutes:
    """Switch to mock mode, set global=base, create a new account, verify the
    resulting ramp_wallets row uses chain='base'."""

    @pytest.fixture(autouse=True)
    def _switch_to_mock(self, admin_session, mongo):
        # 1) Snapshot current provider config + global chain
        g = mongo[DB_NAME].ramp_provider_config.find_one({"scope": "global"})
        original = {
            "provider": (g or {}).get("provider", "andeslabs"),
            "mode":     (g or {}).get("mode", "real"),
            "enabled":  (g or {}).get("enabled", True),
            "default":  (g or {}).get("default_arsa_chain"),
            "allowed":  (g or {}).get("allowed_arsa_chains"),
        }

        # 2) Flip to mock
        r = admin_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/provider-config",
            json={"provider": "andeslabs", "mode": "mock", "enabled": True},
            timeout=10)
        assert r.status_code in (200, 201), r.text

        # 3) Ensure global default = base
        r2 = admin_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/arsa-chain",
            json={"default": "base", "allowed": ["stellar", "base"]},
            timeout=10)
        assert r2.status_code == 200, r2.text

        yield

        # Teardown — restore provider mode and global default
        admin_session.put(
            f"{BASE_URL}/api/v1/admin/ramp/provider-config",
            json={"provider": original["provider"],
                    "mode": original["mode"],
                    "enabled": original["enabled"]},
            timeout=10)
        if original["default"]:
            admin_session.put(
                f"{BASE_URL}/api/v1/admin/ramp/arsa-chain",
                json={"default": original["default"],
                        "allowed": original["allowed"] or ["stellar", "base"]},
                timeout=10)

    def test_new_wallet_uses_resolved_base_chain(self, admin_session, mongo):
        ecid = f"test_phase17_{secrets.token_hex(4)}"
        try:
            # Create the account in mock mode
            r = admin_session.post(
                f"{BASE_URL}/api/v1/ramp/accounts",
                params={"org_id": ORG},
                json={"end_customer_id": ecid,
                        "display_name": "Phase 17 test",
                        "account_type": "business",
                        "holder_name": "Phase 17 Tester"},
                timeout=30)
            assert r.status_code == 200, r.text
            assert r.json()["end_customer_id"] == ecid

            # Inspect the wallet doc in Mongo
            acc = mongo[DB_NAME].ramp_accounts.find_one(
                {"org_id": ORG, "end_customer_id": ecid})
            assert acc is not None, "ramp_accounts row missing"
            wallets = list(mongo[DB_NAME].ramp_wallets.find(
                {"ramp_account_id": acc["id"], "asset": "arsa"}))
            assert wallets, "expected at least 1 ARSa wallet"
            chains = {w.get("chain") for w in wallets}
            assert "base" in chains, \
                f"expected base wallet, got chains={chains}"

            # GET balances → the endpoint should return something
            # (the actual chain in the response can be either the resolved
            # chain or the upstream provider's reply; mock gateway tends to
            # return 'stellar' for ARSa regardless of the minted wallet chain,
            # which is a gateway-side quirk, not a chain-resolver bug)
            b = admin_session.get(
                f"{BASE_URL}/api/v1/ramp/accounts/{ecid}/balances",
                params={"org_id": ORG}, timeout=20)
            assert b.status_code == 200, b.text
        finally:
            # Cleanup — remove the throw-away docs we created
            acc = mongo[DB_NAME].ramp_accounts.find_one(
                {"org_id": ORG, "end_customer_id": ecid})
            if acc:
                mongo[DB_NAME].ramp_wallets.delete_many(
                    {"ramp_account_id": acc["id"]})
                mongo[DB_NAME].ramp_balances.delete_many(
                    {"ramp_account_id": acc["id"]})
                mongo[DB_NAME].ramp_fiat_accounts.delete_many(
                    {"ramp_account_id": acc["id"]})
                mongo[DB_NAME].ramp_accounts.delete_one({"id": acc["id"]})


# --------------------------------------------------------------------------- #
# Smoke — confirm Phase 14/15/16 touched endpoints still respond
# --------------------------------------------------------------------------- #
class TestPhase14To16Smoke:
    def test_provider_config_list(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/provider-config", timeout=10)
        assert r.status_code == 200
        body = r.json()
        # Endpoint may return list-of-rows or dict-of-rows
        assert body is not None

    def test_admin_accounts_list(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/admin/ramp/accounts", timeout=15)
        assert r.status_code == 200

    def test_ramp_accounts_alemany_balances(self, admin_session):
        r = admin_session.get(
            f"{BASE_URL}/api/v1/ramp/accounts/{ORG}/balances",
            params={"org_id": ORG}, timeout=20)
        # 200 (with balances) or 404 (no account yet) are both acceptable
        # depending on whether the seed account exists at run time
        assert r.status_code in (200, 404), r.text
