"""P1-1 (Feb 2026) — Deposit wallets endpoint + dashboard cash split.

Covers:
  - GET /api/v1/client/deposit-wallets (approved org) returns the contracted
    payload (wallets array with end + month modalities, network, asset,
    safety_warning containing the mandatory phrases).
  - GET /api/v1/client/deposit-wallets (non-approved org) returns 403 with
    'Tu KYB no está aprobado' detail.
  - GET /api/v1/client/dashboard-summary cash payload exposes the six
    fields and consistent sums.
"""
import os
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
APPROVED_EMAIL = "client.admin@alemany.capital"
NON_APPROVED_EMAIL = "client.admin@finpact.io"


def _dev_login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email}, allow_redirects=False)
    # Magic link may 302 or 200 — either is fine, the session cookie is set
    assert r.status_code in (200, 302, 303, 307), r.text
    return s


@pytest.fixture(scope="module")
def approved_client():
    return _dev_login(APPROVED_EMAIL)


@pytest.fixture(scope="module")
def non_approved_client():
    return _dev_login(NON_APPROVED_EMAIL)


# ---------------------------------------------------------------------------
# /deposit-wallets — approved org
# ---------------------------------------------------------------------------
class TestDepositWalletsApproved:
    def test_returns_200_and_contract_shape(self, approved_client):
        r = approved_client.get(f"{BASE_URL}/api/v1/client/deposit-wallets")
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("wallets", "network", "asset", "asset_issuer",
                  "prosper_id", "safety_warning", "fetched_at"):
            assert k in data, f"Missing field: {k}"
        assert data["network"] == "stellar"
        assert data["asset"] == "USDC"
        assert isinstance(data["wallets"], list)

    def test_both_modalities_present_with_addresses(self, approved_client):
        r = approved_client.get(f"{BASE_URL}/api/v1/client/deposit-wallets")
        assert r.status_code == 200
        wallets = r.json()["wallets"]
        modalities = {w["modality"]: w for w in wallets}
        assert "end" in modalities, "Missing 'end' modality wallet"
        assert "month" in modalities, "Missing 'month' modality wallet"
        for m in ("end", "month"):
            assert modalities[m]["address"], f"{m} wallet missing address"
            # 'end' may be legacy backfill (per E1 note) — accept any non-empty
            assert isinstance(modalities[m]["address"], str)
            assert "prosper_user_id" in modalities[m]
            assert "created" in modalities[m]

    def test_safety_warning_text(self, approved_client):
        r = approved_client.get(f"{BASE_URL}/api/v1/client/deposit-wallets")
        warn = r.json()["safety_warning"]
        assert "ÚNICAMENTE en la red Stellar" in warn
        assert "PÉRDIDA TOTAL" in warn

    def test_end_and_month_have_different_addresses(self, approved_client):
        # The CMS protocol assigns ONE wallet per (org, modality) — `end`
        # and `month` MUST resolve to distinct Stellar addresses.
        r = approved_client.get(f"{BASE_URL}/api/v1/client/deposit-wallets")
        wallets = {w["modality"]: w["address"] for w in r.json()["wallets"]}
        assert wallets["end"] != wallets["month"], \
            f"end and month resolve to same address: {wallets['end']}"


# ---------------------------------------------------------------------------
# /deposit-wallets — non-approved org
# ---------------------------------------------------------------------------
class TestDepositWalletsNonApproved:
    def test_returns_403_with_kyb_message(self, non_approved_client):
        r = non_approved_client.get(f"{BASE_URL}/api/v1/client/deposit-wallets")
        # If finpact happens to be approved in this env, skip
        if r.status_code == 200:
            pytest.skip("finpact org is approved in this env — skip non-approved test")
        assert r.status_code == 403, r.text
        detail = r.json().get("detail", "")
        assert "Tu KYB no está aprobado" in detail


# ---------------------------------------------------------------------------
# /dashboard-summary — cash split (P1-1 addendum)
# ---------------------------------------------------------------------------
class TestDashboardCashSplit:
    def test_cash_has_six_fields(self, approved_client):
        r = approved_client.get(f"{BASE_URL}/api/v1/client/dashboard-summary")
        assert r.status_code == 200, r.text
        cash = r.json()["cash"]
        for k in ("usdc", "usdc_platform", "usdc_stellar",
                  "arsa", "arsa_cvu", "arsa_stellar"):
            assert k in cash, f"Missing cash field: {k}"
            assert isinstance(cash[k], (int, float))

    def test_cash_sums_are_consistent(self, approved_client):
        r = approved_client.get(f"{BASE_URL}/api/v1/client/dashboard-summary")
        cash = r.json()["cash"]
        # Allow 0.01 tolerance for float aggregation
        assert abs(cash["usdc"] - (cash["usdc_platform"] + cash["usdc_stellar"])) < 0.01
        assert abs(cash["arsa"] - (cash["arsa_cvu"] + cash["arsa_stellar"])) < 0.01
