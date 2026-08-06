"""Phase 14 — Andes Adapter end-to-end tests.

Covers:
* GET /api/v1/ramp/accounts auth gate
* POST /api/v1/ramp/accounts as client_admin → creates account+wallet+CVU
* Idempotency on second POST
* GET /api/v1/ramp/accounts/{ec}/balances returns ARSa row with proper
  label/symbol/caption + chain=stellar
* Node gateway simulate-deposit increases the balance
* POST /retry returns the account doc
* super_admin ?org_id= override works (and is ignored for non-backoffice
  roles).
"""
from __future__ import annotations

import os
import time
import pytest
import requests

BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com",
).rstrip("/")
GATEWAY_URL = os.environ.get("ANDES_GATEWAY_URL", "http://localhost:8090")
GATEWAY_TOKEN = os.environ.get("GATEWAY_INTERNAL_TOKEN",
                                "dev-internal-token-change-me")

CLIENT_EMAIL = "client.admin@alemany.capital"
SUPER_EMAIL = "admin@prosper.foundation"
ALEMANY_ORG = "org_seed_alemany"


def _dev_login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email}, allow_redirects=False, timeout=15)
    assert r.status_code in (200, 302, 303, 307), \
        f"dev-login {email} -> {r.status_code} {r.text[:200]}"
    # cookie should be set
    return s


# ---------------------------------------------------------------------------
# 1) Auth gate
# ---------------------------------------------------------------------------
def test_list_accounts_requires_auth():
    r = requests.get(f"{BASE_URL}/api/v1/ramp/accounts", timeout=15)
    assert r.status_code in (401, 403), \
        f"expected 401/403 unauth, got {r.status_code} {r.text[:200]}"


# ---------------------------------------------------------------------------
# 2) client_admin → create account (idempotent)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client_session() -> requests.Session:
    return _dev_login(CLIENT_EMAIL)


@pytest.fixture(scope="module")
def super_session() -> requests.Session:
    return _dev_login(SUPER_EMAIL)


@pytest.fixture(scope="module")
def alemany_account(client_session) -> dict:
    """Create or fetch the ramp account for Alemany. Module-scoped."""
    r = client_session.post(f"{BASE_URL}/api/v1/ramp/accounts",
                              json={}, timeout=30)
    assert r.status_code == 200, f"create: {r.status_code} {r.text[:300]}"
    return r.json()


def test_create_account_shape(alemany_account):
    doc = alemany_account
    # status/onboarding
    assert doc.get("onboarding_status") in {
        "approved", "pending_approval", "kyc_pending_andes", "error"
    }, f"unexpected status: {doc.get('onboarding_status')}"
    # core IDs
    assert doc.get("end_customer_id"), doc
    assert doc.get("provider") == "andeslabs", doc
    assert doc.get("provider_user_id"), doc
    # If onboarding succeeded mock, we expect cvu+alias+wallet
    if doc.get("onboarding_status") == "approved":
        assert doc.get("cvu"), "approved account must expose a CVU"
        assert doc.get("alias"), "approved account must expose an alias"
        assert doc.get("wallet_address"), "approved account must have a wallet"


def test_create_account_idempotent(client_session, alemany_account):
    r2 = client_session.post(f"{BASE_URL}/api/v1/ramp/accounts",
                              json={}, timeout=30)
    assert r2.status_code == 200, r2.text[:300]
    doc2 = r2.json()
    # Same provider_user_id → idempotent
    assert doc2["provider_user_id"] == alemany_account["provider_user_id"]
    assert doc2["end_customer_id"] == alemany_account["end_customer_id"]


# ---------------------------------------------------------------------------
# 3) Balances row shape
# ---------------------------------------------------------------------------
def test_balances_arsa_row(client_session, alemany_account):
    ec = alemany_account["end_customer_id"]
    r = client_session.get(
        f"{BASE_URL}/api/v1/ramp/accounts/{ec}/balances", timeout=20)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["end_customer_id"] == ec
    assert body["provider"] == "andeslabs"
    items = body["items"]
    assert isinstance(items, list) and len(items) >= 1
    arsa = next((it for it in items if it["asset_code"] == "arsa"), None)
    assert arsa is not None, f"no arsa row in {items}"
    assert arsa["asset_label"] == "ARSa"
    assert arsa["asset_symbol"] == "$"
    assert arsa["asset_caption"] == "peso digital 1:1"
    assert arsa["chain"] == "stellar"
    # amount is a decimal string
    assert isinstance(arsa["amount"], str)
    float(arsa["amount"])  # parseable


# ---------------------------------------------------------------------------
# 4) Simulate deposit via Node gateway increases balance
# ---------------------------------------------------------------------------
def _gateway_alive() -> bool:
    try:
        rr = requests.get(f"{GATEWAY_URL}/health", timeout=3)
        return rr.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _gateway_alive(),
                       reason="andes-gateway not reachable")
def test_simulate_deposit_increases_balance(client_session, alemany_account):
    ec = alemany_account["end_customer_id"]
    user_id = alemany_account["provider_user_id"]

    # current balance
    r0 = client_session.get(
        f"{BASE_URL}/api/v1/ramp/accounts/{ec}/balances", timeout=20)
    arsa0 = next(it for it in r0.json()["items"] if it["asset_code"] == "arsa")
    before = float(arsa0["amount"])

    # simulate deposit (cumulative semantics handled gateway-side)
    bump = 1234.56
    sim = requests.post(
        f"{GATEWAY_URL}/dev/simulate-deposit",
        headers={"X-Internal-Token": GATEWAY_TOKEN,
                  "Content-Type": "application/json"},
        json={"user_id": user_id, "asset": "arsa", "amount": bump},
        timeout=10)
    assert sim.status_code in (200, 201, 204), \
        f"gateway simulate-deposit: {sim.status_code} {sim.text[:200]}"

    time.sleep(0.5)
    r1 = client_session.get(
        f"{BASE_URL}/api/v1/ramp/accounts/{ec}/balances", timeout=20)
    arsa1 = next(it for it in r1.json()["items"] if it["asset_code"] == "arsa")
    after = float(arsa1["amount"])
    assert after > before, \
        f"balance did not increase: before={before} after={after}"


# ---------------------------------------------------------------------------
# 5) Retry endpoint
# ---------------------------------------------------------------------------
def test_retry_returns_account(client_session, alemany_account):
    ec = alemany_account["end_customer_id"]
    r = client_session.post(
        f"{BASE_URL}/api/v1/ramp/accounts/{ec}/retry", timeout=30)
    assert r.status_code == 200, r.text[:300]
    doc = r.json()
    assert doc["end_customer_id"] == ec
    assert doc["provider"] == "andeslabs"
    assert "onboarding_status" in doc


# ---------------------------------------------------------------------------
# 6) Backoffice ?org_id= override (security boundary)
# ---------------------------------------------------------------------------
def test_super_admin_can_view_other_org(super_session, alemany_account):
    """super_admin may pass ?org_id=org_seed_alemany_capital and see Alemany's
    account."""
    r = super_session.get(f"{BASE_URL}/api/v1/ramp/accounts",
                            params={"org_id": ALEMANY_ORG}, timeout=15)
    assert r.status_code == 200, r.text[:300]
    rows = r.json()
    assert isinstance(rows, list)
    # find alemany row
    found = any(row.get("end_customer_id") == alemany_account["end_customer_id"]
                 and row.get("provider_user_id") == alemany_account["provider_user_id"]
                 for row in rows)
    assert found, f"super_admin override did not surface alemany account: {rows[:3]}"


def test_client_admin_org_override_ignored(client_session):
    """client_admin (non-backoffice) passing ?org_id=otherorg now gets a hard
    **403 ownership violation** (Phase 23 — explicit boundary). Previously
    the override was silently dropped; now we reject so an N1 attempting to
    operate on its N2's account fails visibly."""
    r = client_session.get(f"{BASE_URL}/api/v1/ramp/accounts",
                             params={"org_id": "org_seed_finpact"}, timeout=15)
    assert r.status_code == 403, r.text[:300]
    detail = (r.json().get("detail") or "").lower()
    assert "ownership" in detail or "cannot operate" in detail
    # The legitimate call (no override) still works.
    r2 = client_session.get(f"{BASE_URL}/api/v1/ramp/accounts", timeout=15)
    assert r2.status_code == 200, r2.text[:300]
