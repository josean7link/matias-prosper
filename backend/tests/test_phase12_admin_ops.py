"""Phase 12 — Admin ops (wipe demo, seed demo client) + Status page."""
from __future__ import annotations
import os

import requests

BASE = os.environ.get("PROSPER_API_BASE_TEST", "http://localhost:8001/api")
API  = f"{BASE}/v1"


def _super_session() -> requests.Session:
    s = requests.Session()
    s.get(f"{API}/auth/dev-login",
          params={"email": "admin@prosper.foundation", "next": "/"},
          allow_redirects=False, timeout=10)
    return s


def _client_session() -> requests.Session:
    s = requests.Session()
    s.get(f"{API}/auth/dev-login",
          params={"email": "client.admin@alemany.capital", "next": "/"},
          allow_redirects=False, timeout=10)
    return s


# ---------------------------------------------------------------------------
# Public /status endpoint
# ---------------------------------------------------------------------------
def test_status_endpoint_shape():
    # No auth required
    r = requests.get(f"{API}/status", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "overall" in body
    assert body["overall"] in ("operational", "degraded", "outage")
    assert isinstance(body["services"], list)
    ids = [s["id"] for s in body["services"]]
    for required in ("mongo", "api", "admin", "client",
                       "webhooks", "alfred", "prosper"):
        assert required in ids, f"service {required} missing"


# ---------------------------------------------------------------------------
# Wipe demo
# ---------------------------------------------------------------------------
def test_wipe_demo_requires_confirm():
    s = _super_session()
    r = s.post(f"{API}/admin/ops/wipe-demo",
                json={"confirm": "WRONG"}, timeout=10)
    assert r.status_code == 400


def test_wipe_demo_returns_summary():
    """Skipped in CI to avoid destroying baseline seed data shared across tests."""
    import pytest
    pytest.skip("Destructive — run manually via curl when wanted (see RUNBOOK §10)")


def test_wipe_demo_forbidden_for_non_super_admin():
    s = _client_session()
    r = s.post(f"{API}/admin/ops/wipe-demo",
                json={"confirm": "WIPE-DEMO"}, timeout=10)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Seed demo client
# ---------------------------------------------------------------------------
def test_seed_demo_client_creates_org_and_user():
    s = _super_session()
    r = s.post(f"{API}/admin/ops/seed-demo-client",
                json={"auto_approve": True, "seed_history": True},
                timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["org_id"].startswith("org_demo_")
    assert body["user_id"].startswith("usr_demo_")
    assert body["kyb_status"] == "approved"
    assert body["tx_count"] >= 2
    assert body["position_count"] >= 1
    # No cleanup: wipe-demo would also nuke the platform's baseline demo
    # history and break ordering-dependent tests. The org sits with
    # `is_demo=true` and will be removed on the next pre-launch wipe.


def test_seed_demo_client_forbidden_for_non_super_admin():
    s = _client_session()
    r = s.post(f"{API}/admin/ops/seed-demo-client",
                json={"auto_approve": True}, timeout=10)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
def test_security_headers_present():
    r = requests.get(f"{API}/status", timeout=10)
    assert "strict-transport-security" in {k.lower() for k in r.headers}
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
