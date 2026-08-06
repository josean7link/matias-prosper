"""Tests for the Prosper upstream diagnostic endpoint."""
import os
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://finance-control-215.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ.get("PROSPER_TEST_TOKEN", "test_session_prosper_super_admin")
CLIENT_TOKEN = os.environ.get("PROSPER_CLIENT_TOKEN", "test_session_prosper_client_admin")
HDR = {"Authorization": f"Bearer {TOKEN}"}
CLIENT_HDR = {"Authorization": f"Bearer {CLIENT_TOKEN}"}


def test_upstream_status_shape():
    r = requests.get(f"{BASE}/api/admin/prosper-upstream", headers=HDR, timeout=15)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    body = r.json()
    for key in ("enabled", "base_url", "reachable", "authenticated", "error"):
        assert key in body, f"missing {key}"
    assert isinstance(body["enabled"], bool)
    assert isinstance(body["reachable"], bool)
    assert isinstance(body["authenticated"], bool)
    assert body["base_url"].startswith("http")


def test_upstream_requires_role():
    """Non-internal client_admin must be blocked from the diagnostic."""
    r = requests.get(f"{BASE}/api/admin/prosper-upstream", headers=CLIENT_HDR, timeout=15)
    assert r.status_code == 403


def test_upstream_unauth_rejected():
    r = requests.get(f"{BASE}/api/admin/prosper-upstream", timeout=15)
    assert r.status_code in (401, 403)
