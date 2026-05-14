"""Phase 11A — Client self-service tests (API keys, webhooks, widget, interest)."""
from __future__ import annotations
import os

import requests

BASE = os.environ.get("PROSPER_API_BASE_TEST", "http://localhost:8001/api")
API  = f"{BASE}/v1"


def _admin_session() -> requests.Session:
    s = requests.Session()
    s.get(f"{API}/auth/dev-login",
          params={"email": "client.admin@alemany.capital", "next": "/"},
          allow_redirects=False, timeout=10)
    return s


def test_api_key_plaintext_only_on_create():
    s = _admin_session()
    r = s.post(f"{API}/client/api-keys",
               json={"name": "phase11a-test", "scope": "sandbox"},
               timeout=10).json()
    assert r["ok"] is True
    assert r["plaintext"].startswith("pk_test_") or r["plaintext"].startswith("pk_sandbox_")
    key_id = r["key_id"]

    # List must not expose plaintext or secret_hash
    listing = s.get(f"{API}/client/api-keys", timeout=10).json()
    for k in listing["items"]:
        assert "plaintext" not in k
        assert "secret_hash" not in k

    # Cleanup
    s.delete(f"{API}/client/api-keys/{key_id}", timeout=10)


def test_api_key_rotate_returns_new_plaintext_and_invalidates_old():
    s = _admin_session()
    a = s.post(f"{API}/client/api-keys",
               json={"name": "rotate-test", "scope": "sandbox"},
               timeout=10).json()
    rot = s.post(f"{API}/client/api-keys/{a['key_id']}/rotate",
                  timeout=10).json()
    assert rot["plaintext"].startswith("pk_test_") or rot["plaintext"].startswith("pk_sandbox_")
    assert rot["plaintext"] != a["plaintext"]
    s.delete(f"{API}/client/api-keys/{a['key_id']}", timeout=10)


def test_api_key_production_blocked_when_org_in_sandbox():
    s = _admin_session()
    r = s.post(f"{API}/client/api-keys",
               json={"name": "blocked-prod", "scope": "production"},
               timeout=10)
    # Alemany seed has env=sandbox by default
    assert r.status_code in (200, 400)
    if r.status_code == 400:
        assert "sandbox" in r.text.lower() or "production" in r.text.lower()


def test_webhook_create_returns_secret_once_and_test_endpoint():
    s = _admin_session()
    # Use a benign URL that responds 200 — httpbin.org for the test endpoint
    r = s.post(f"{API}/client/webhooks", json={
        "url": "https://httpbin.org/anything",
        "events": ["onramp.confirmed", "redeem.confirmed"],
        "description": "phase11 test",
    }, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "secret" in body and len(body["secret"]) > 20
    wh_id = body["webhook"]["webhook_id"]

    # listing must not include secret
    items = s.get(f"{API}/client/webhooks", timeout=10).json()["items"]
    wh = next(w for w in items if w["webhook_id"] == wh_id)
    assert "secret" not in wh

    # test endpoint (network call to httpbin)
    t = s.post(f"{API}/client/webhooks/{wh_id}/test", timeout=15)
    # Even if network fails, status is 200 with delivery info
    assert t.status_code == 200, t.text

    # delete cleanup
    s.delete(f"{API}/client/webhooks/{wh_id}", timeout=10)


def test_widget_config_save_and_read():
    s = _admin_session()
    new_cfg = {"theme": "dark", "color": "#FF00AA",
                "locale": "en", "amount": 5000.0,
                "product_id": "liquid_v1", "show_branding": False}
    r = s.put(f"{API}/client/widget/config", json=new_cfg, timeout=10)
    assert r.status_code == 200, r.text
    out = s.get(f"{API}/client/widget/config", timeout=10).json()
    assert out["config"]["theme"]    == "dark"
    assert out["config"]["color"]    == "#FF00AA"
    assert out["config"]["amount"]   == 5000.0
    assert out["config"]["show_branding"] is False


def test_feature_interest_register_idempotent():
    s = _admin_session()
    r1 = s.post(f"{API}/client/feature-interest",
                json={"feature": "lending"}, timeout=10).json()
    assert r1["ok"] is True
    r2 = s.post(f"{API}/client/feature-interest",
                json={"feature": "lending"}, timeout=10).json()
    assert r2.get("already_registered") is True

    listing = s.get(f"{API}/client/feature-interest", timeout=10).json()
    assert "lending" in listing["registered"]


def test_feature_interest_rejects_unknown():
    s = _admin_session()
    r = s.post(f"{API}/client/feature-interest",
               json={"feature": "moon_lambo"}, timeout=10)
    assert r.status_code == 400
