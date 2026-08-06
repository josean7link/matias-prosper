"""P1-2 (Feb 2026) — Multi-asset client dashboard summary tests.

Tests the new aggregator endpoint:
  GET /api/v1/client/dashboard-summary

Validates:
  - Shape: {aum:{arsa,usdc}, cash:{arsa,usdc}, breakdown:[], fetched_at}
  - As client.admin@alemany.capital: ARSa=0 positions, USDC has positions
  - cash.arsa ≈ 601234.56 (seeded ramp_balances)
  - External=true positions do NOT count in aum/breakdown
  - As admin@prosper.foundation (no org): must not crash
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com"

ENDPOINT = f"{BASE_URL}/api/v1/client/dashboard-summary"


def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email}, allow_redirects=False, timeout=15)
    assert r.status_code in (200, 302, 303, 307), f"dev-login failed {r.status_code}: {r.text[:200]}"
    return s


@pytest.fixture(scope="module")
def client_session():
    return _login("client.admin@alemany.capital")


@pytest.fixture(scope="module")
def super_admin_session():
    return _login("admin@prosper.foundation")


class TestDashboardSummaryShape:
    """Shape + invariants for the client.admin@alemany.capital response."""

    def test_status_and_top_keys(self, client_session):
        r = client_session.get(ENDPOINT, timeout=20)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()
        for key in ("aum", "cash", "breakdown", "fetched_at"):
            assert key in body, f"missing key {key}: keys={list(body.keys())}"

    def test_aum_buckets(self, client_session):
        body = client_session.get(ENDPOINT, timeout=20).json()
        aum = body["aum"]
        assert set(aum.keys()) == {"arsa", "usdc"}
        for asset in ("arsa", "usdc"):
            b = aum[asset]
            for f in ("principal", "yield_accrued", "yield_claimed",
                      "positions", "active"):
                assert f in b, f"missing {asset}.{f}"
            assert isinstance(b["positions"], int)
            assert isinstance(b["active"], int)

    def test_cash_buckets(self, client_session):
        body = client_session.get(ENDPOINT, timeout=20).json()
        cash = body["cash"]
        assert set(cash.keys()) == {"usdc", "arsa"}
        assert isinstance(cash["usdc"], (int, float))
        assert isinstance(cash["arsa"], (int, float))

    def test_breakdown_is_list(self, client_session):
        body = client_session.get(ENDPOINT, timeout=20).json()
        assert isinstance(body["breakdown"], list)
        for row in body["breakdown"]:
            assert {"asset", "modality", "count", "principal"} <= set(row.keys())


class TestAlemanyExpectedValues:
    """The seed has 59 USDC positions (36 active) and 0 ARSa positions
    for org_seed_alemany; cash.arsa should be ≈601234.56."""

    def test_usdc_has_positions(self, client_session):
        body = client_session.get(ENDPOINT, timeout=20).json()
        usdc = body["aum"]["usdc"]
        assert usdc["positions"] > 0, f"expected usdc.positions>0 got {usdc}"
        assert usdc["principal"] > 0, f"expected usdc.principal>0 got {usdc}"

    def test_arsa_zero_positions(self, client_session):
        # External positions (8 ARSa historical) must be excluded.
        body = client_session.get(ENDPOINT, timeout=20).json()
        arsa = body["aum"]["arsa"]
        assert arsa["positions"] == 0, (
            f"ARSa positions must be 0 (externals excluded): got {arsa}")
        assert arsa["principal"] == 0, f"expected arsa.principal==0 got {arsa}"

    def test_cash_arsa_ramp_balance(self, client_session):
        body = client_session.get(ENDPOINT, timeout=20).json()
        # Seed value approx 601234.56; allow a wide tolerance just in case
        # other tests bumped it slightly.
        assert body["cash"]["arsa"] > 600_000, (
            f"expected cash.arsa>600k got {body['cash']['arsa']}")
        assert abs(body["cash"]["arsa"] - 601234.56) < 5000, (
            f"cash.arsa not near seed: {body['cash']['arsa']}")

    def test_breakdown_excludes_externals(self, client_session):
        body = client_session.get(ENDPOINT, timeout=20).json()
        # Breakdown should only contain USDC entries (since arsa is all external).
        for row in body["breakdown"]:
            if row["asset"] == "arsa":
                # If arsa is in breakdown, that means non-external arsa positions exist
                # which contradicts the expected state.
                pytest.fail(
                    f"breakdown contains arsa entry (externals leaked?): {row}")
        assert any(r["asset"] == "usdc" for r in body["breakdown"]), \
            "breakdown should contain usdc rows"


class TestSuperAdminNoCrash:
    """admin@prosper.foundation has no org — endpoint must not 500."""

    def test_super_admin_does_not_crash(self, super_admin_session):
        r = super_admin_session.get(ENDPOINT, timeout=20)
        # 4xx OR 200 with empty buckets are both acceptable
        assert r.status_code < 500, f"server crash: {r.status_code}: {r.text[:300]}"
        if r.status_code == 200:
            body = r.json()
            assert "aum" in body
            # Either empty buckets or zero values
            assert body["aum"]["arsa"]["principal"] == 0
            assert body["aum"]["usdc"]["principal"] == 0
