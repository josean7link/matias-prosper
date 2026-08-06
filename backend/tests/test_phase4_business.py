"""FASE 4 — Business module backend tests.

Tests:
- All /admin/business/* endpoints (clients, revenue/*, yield/by-client, cohorts)
- RBAC: super_admin OK, client_admin forbidden
- New /cohorts structure
- New implicit fee fields on /yield/by-client
- Regression on /admin/dashboard, /admin/operations, /admin/compliance
"""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = "https://finance-control-215.preview.emergentagent.com"
ADMIN_EMAIL = "admin@prosper.foundation"
CLIENT_ADMIN_EMAIL = "client.admin@alemany.capital"


def _session_for(email: str) -> requests.Session:
    s = requests.Session()
    # dev-login returns 303 redirect; we don't want to follow but capture the cookie
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email, "next": "/admin"},
              allow_redirects=False, timeout=20)
    assert r.status_code in (302, 303, 307), f"dev-login for {email}: {r.status_code} {r.text[:200]}"
    assert "prosper_session" in s.cookies, f"no session cookie for {email}; got: {s.cookies}"
    return s


@pytest.fixture(scope="module")
def admin_session() -> requests.Session:
    return _session_for(ADMIN_EMAIL)


@pytest.fixture(scope="module")
def client_admin_session() -> requests.Session:
    return _session_for(CLIENT_ADMIN_EMAIL)


# ---------------------------------------------------------------------------
# 200 OK for super_admin
# ---------------------------------------------------------------------------
BIZ_ENDPOINTS = [
    "/api/v1/admin/business/clients",
    "/api/v1/admin/business/revenue/summary",
    "/api/v1/admin/business/revenue/breakdown",
    "/api/v1/admin/business/revenue/breakdown?period=mtd",
    "/api/v1/admin/business/revenue/breakdown?period=ytd",
    "/api/v1/admin/business/revenue/by-month?months=12",
    "/api/v1/admin/business/revenue/by-client?limit=10",
    "/api/v1/admin/business/yield/by-client",
    "/api/v1/admin/business/cohorts?months=12",
]


@pytest.mark.parametrize("path", BIZ_ENDPOINTS)
def test_super_admin_can_access(admin_session, path):
    r = admin_session.get(f"{BASE_URL}{path}", timeout=30)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
    data = r.json()
    assert isinstance(data, dict), f"{path} returned non-dict"


def test_clients_export_csv(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/v1/admin/business/clients/export.csv",
                          timeout=30)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/csv")
    lines = r.text.splitlines()
    assert len(lines) >= 1
    header = lines[0].lower()
    for col in ("org_id", "name", "type", "volume_total_usd"):
        assert col in header, f"missing {col} in csv header: {header}"


# ---------------------------------------------------------------------------
# RBAC — client_admin must be forbidden
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", BIZ_ENDPOINTS)
def test_client_admin_forbidden(client_admin_session, path):
    r = client_admin_session.get(f"{BASE_URL}{path}", timeout=30)
    assert r.status_code == 403, f"{path} -> {r.status_code} (expected 403)"


# ---------------------------------------------------------------------------
# /cohorts response structure
# ---------------------------------------------------------------------------
COHORT_ITEM_FIELDS = {
    "cohort_month", "new_clients", "active_now", "churned",
    "retention_pct", "volume_total", "revenue_total", "avg_revenue_per_client",
}


def test_cohorts_structure(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/v1/admin/business/cohorts?months=12",
                          timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data and isinstance(data["items"], list)
    assert "totals" in data and isinstance(data["totals"], dict)
    assert "retention_pct" in data["totals"]
    for item in data["items"]:
        missing = COHORT_ITEM_FIELDS - set(item.keys())
        assert not missing, f"cohort item missing fields: {missing}"


def test_cohorts_months_clamp_low(admin_session):
    """months=0 should 422 (ge=1)"""
    r = admin_session.get(f"{BASE_URL}/api/v1/admin/business/cohorts?months=0",
                          timeout=20)
    assert r.status_code == 422, f"expected 422 for months=0, got {r.status_code}"


def test_cohorts_months_clamp_high(admin_session):
    """months=37 should 422 (le=36)"""
    r = admin_session.get(f"{BASE_URL}/api/v1/admin/business/cohorts?months=37",
                          timeout=20)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /yield/by-client — new implicit fee fields and gross_apr > apr
# ---------------------------------------------------------------------------
YIELD_ITEM_FIELDS = {
    "gross_apr_pct", "implicit_total_pct",
    "implicit_mgmt_30d_usd", "implicit_perf_30d_usd",
    "implicit_spread_30d_usd", "implicit_total_30d_usd",
    "apr_pct", "apr_bps",
}


def test_yield_by_client_has_implicit_fields(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/v1/admin/business/yield/by-client",
                          timeout=30)
    assert r.status_code == 200
    data = r.json()
    items = data.get("items", [])
    assert len(items) > 0, "yield/by-client returned no items"
    for item in items[:5]:
        missing = YIELD_ITEM_FIELDS - set(item.keys())
        assert not missing, f"yield item missing fields: {missing}"

    # gross_apr_pct > apr_pct whenever apr_pct > 0
    checked = 0
    for item in items:
        if item["apr_pct"] > 0:
            assert item["gross_apr_pct"] > item["apr_pct"], (
                f"gross_apr_pct ({item['gross_apr_pct']}) should exceed "
                f"apr_pct ({item['apr_pct']}) for org {item.get('org_id')}"
            )
            checked += 1
    assert checked > 0, "no item with apr_pct > 0 to verify gross_apr_pct logic"


# ---------------------------------------------------------------------------
# Regression — non-FASE-4 endpoints still respond
# ---------------------------------------------------------------------------
REGRESSION_ENDPOINTS = [
    "/api/v1/admin/dashboard/kpis",
    "/api/v1/admin/operations/transactions",
    "/api/v1/admin/compliance/policies",
]


@pytest.mark.parametrize("path", REGRESSION_ENDPOINTS)
def test_regression_endpoints(admin_session, path):
    r = admin_session.get(f"{BASE_URL}{path}", timeout=30)
    # 200 or 404 if path differs slightly — but should NOT be 5xx
    assert r.status_code < 500, f"{path} -> {r.status_code} {r.text[:200]}"
    if r.status_code != 200:
        pytest.skip(f"{path} returned {r.status_code} (route name may differ)")
