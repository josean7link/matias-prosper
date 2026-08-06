"""Phase 11A — Extra regression tests for client developer endpoints.

Covers gaps not in test_phase11_developer.py:
- Non-admin role gets 403 on mutations
- Webhook PATCH (pause/activate, events, description)
- Webhook deliveries are scoped to the webhook
- list_api_keys never leaks secret_hash and never includes _id
- list_webhooks exposes available_events
- feature-interest GET returns previously-registered features
"""
from __future__ import annotations
import os
import requests

BASE = os.environ.get("PROSPER_API_BASE_TEST", "http://localhost:8001/api")
API  = f"{BASE}/v1"


def _session(email: str) -> requests.Session:
    s = requests.Session()
    s.get(f"{API}/auth/dev-login",
          params={"email": email, "next": "/"},
          allow_redirects=False, timeout=10)
    return s


# ---------- API KEY LISTING SHAPE ----------
def test_list_api_keys_never_leaks_hash_or_objectid():
    s = _session("client.admin@alemany.capital")
    # ensure at least one key exists
    created = s.post(f"{API}/client/api-keys",
                     json={"name": "TEST_listshape", "scope": "sandbox"},
                     timeout=10).json()
    key_id = created["key_id"]
    listing = s.get(f"{API}/client/api-keys", timeout=10).json()
    assert "items" in listing and "total" in listing
    for k in listing["items"]:
        assert "secret_hash" not in k
        assert "plaintext" not in k
        assert "_id" not in k
        assert "key_id" in k and "prefix" in k
    s.delete(f"{API}/client/api-keys/{key_id}", timeout=10)


# ---------- WEBHOOK PATCH (pause/activate/events/description) ----------
def test_webhook_patch_pause_activate_and_update_events():
    s = _session("client.admin@alemany.capital")
    created = s.post(f"{API}/client/webhooks", json={
        "url": "https://httpbin.org/anything",
        "events": ["onramp.confirmed"],
        "description": "patch-test",
    }, timeout=10).json()
    wh_id = created["webhook"]["webhook_id"]

    # pause
    r = s.patch(f"{API}/client/webhooks/{wh_id}",
                json={"status": "paused"}, timeout=10)
    assert r.status_code == 200, r.text
    items = s.get(f"{API}/client/webhooks", timeout=10).json()["items"]
    wh = next(w for w in items if w["webhook_id"] == wh_id)
    assert wh["status"] == "paused"

    # update events + description
    r = s.patch(f"{API}/client/webhooks/{wh_id}",
                json={"events": ["redeem.confirmed", "kyc.approved"],
                      "description": "updated"}, timeout=10)
    assert r.status_code == 200, r.text
    items = s.get(f"{API}/client/webhooks", timeout=10).json()["items"]
    wh = next(w for w in items if w["webhook_id"] == wh_id)
    assert set(wh["events"]) == {"redeem.confirmed", "kyc.approved"}
    assert wh["description"] == "updated"

    # invalid event -> 400
    r = s.patch(f"{API}/client/webhooks/{wh_id}",
                json={"events": ["bogus.event"]}, timeout=10)
    assert r.status_code == 400

    # reactivate
    r = s.patch(f"{API}/client/webhooks/{wh_id}",
                json={"status": "active"}, timeout=10)
    assert r.status_code == 200

    # cleanup
    s.delete(f"{API}/client/webhooks/{wh_id}", timeout=10)


# ---------- WEBHOOK LIST EXPOSES available_events ----------
def test_list_webhooks_has_available_events():
    s = _session("client.admin@alemany.capital")
    out = s.get(f"{API}/client/webhooks", timeout=10).json()
    assert isinstance(out.get("available_events"), list)
    assert "onramp.confirmed" in out["available_events"]


# ---------- WEBHOOK DELIVERIES SCOPED TO WEBHOOK ----------
def test_webhook_deliveries_scoped_to_webhook():
    s = _session("client.admin@alemany.capital")
    created = s.post(f"{API}/client/webhooks", json={
        "url": "https://httpbin.org/anything",
        "events": ["onramp.confirmed"],
        "description": "deliveries-test",
    }, timeout=10).json()
    wh_id = created["webhook"]["webhook_id"]
    # fire test to generate one delivery
    s.post(f"{API}/client/webhooks/{wh_id}/test", timeout=20)
    out = s.get(f"{API}/client/webhooks/{wh_id}/deliveries", timeout=10).json()
    assert "items" in out
    # All deliveries must belong to this webhook
    for d in out["items"]:
        assert d.get("webhook_id") == wh_id
    s.delete(f"{API}/client/webhooks/{wh_id}", timeout=10)


# ---------- FEATURE INTEREST GET ----------
def test_feature_interest_listing_includes_registered():
    s = _session("client.admin@alemany.capital")
    s.post(f"{API}/client/feature-interest",
           json={"feature": "card"}, timeout=10)
    out = s.get(f"{API}/client/feature-interest", timeout=10).json()
    assert "card" in out.get("registered", [])
    for r in out["items"]:
        assert "_id" not in r


# ---------- NON-ADMIN ROLE GETS 403 ON MUTATIONS ----------
def test_non_admin_role_blocked_on_mutations(monkeypatch=None):
    """Internal staff (compliance_officer) is not a client_admin → 403 on POST.

    We use a compliance_officer session which has no org_id but DOES authenticate.
    Since _assert_admin checks role not in (client_admin, super_admin), the
    compliance role should be rejected with 403.
    """
    s = _session("compliance@prosper.foundation")
    r = s.post(f"{API}/client/api-keys",
               json={"name": "should-fail", "scope": "sandbox"}, timeout=10)
    assert r.status_code in (401, 403), r.text
    r = s.post(f"{API}/client/webhooks", json={
        "url": "https://httpbin.org/anything",
        "events": ["onramp.confirmed"]}, timeout=10)
    assert r.status_code in (401, 403), r.text
