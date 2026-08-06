"""Phase 16 — Admin Ramp backoffice tests.

Sections:
  A. Provider switch (global + per-org overrides) + connectivity + capabilities
  B. Accounts monitoring (list + KPIs + drill-down)
  C. Movements feed (list + CSV export)
  D. Project stats (proxy to gateway)
  E. Webhook events (db + andes deliveries cross-check)
  + Auth gate: client_admin → 403, super_admin → 200
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

import pytest
import requests

BASE_URL = "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com".rstrip("/")
GATEWAY_URL = os.environ.get("ANDES_GATEWAY_URL", "http://localhost:8090")
TOKEN = os.environ.get("GATEWAY_INTERNAL_TOKEN", "dev-internal-token-change-me")

ADMIN_EMAIL = "admin@prosper.foundation"
CLIENT_EMAIL = "client.admin@alemany.capital"
TARGET_ORG = "org_seed_alemany"


def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email}, allow_redirects=False, timeout=15)
    assert r.status_code in (200, 302, 303, 307), r.text[:200]
    return s


@pytest.fixture(scope="module")
def admin_sess() -> requests.Session:
    return _login(ADMIN_EMAIL)


@pytest.fixture(scope="module")
def client_sess() -> requests.Session:
    return _login(CLIENT_EMAIL)


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------
def test_auth_gate_blocks_client_admin(client_sess):
    r = client_sess.get(f"{BASE_URL}/api/v1/admin/ramp/provider-config", timeout=15)
    assert r.status_code == 403, r.text[:200]


def test_auth_gate_allows_super_admin(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/provider-config", timeout=15)
    assert r.status_code == 200, r.text[:200]


# ---------------------------------------------------------------------------
# Section A — Provider config + audit logs
# ---------------------------------------------------------------------------
def test_provider_config_list_shape(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/provider-config", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and "org_names" in body
    # global row must exist
    global_row = next((row for row in body["rows"] if row["scope"] == "global"), None)
    assert global_row is not None, body
    assert global_row["provider"] in ("alfred", "andeslabs")


def _read_audit_logs_count(action: str) -> int:
    """Direct DB lookup via sync pymongo (avoids motor event-loop reuse issues)."""
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    from pymongo import MongoClient
    mc = MongoClient(os.environ["MONGO_URL"])
    try:
        return mc[os.environ["DB_NAME"]]["audit_logs"].count_documents(
            {"action": action})
    finally:
        mc.close()


def test_provider_config_global_update_with_audit_log(admin_sess):
    before_audit = _read_audit_logs_count("admin.ramp.provider_config.update")
    # capture before state
    g0 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/provider-config").json()
    original = next(r for r in g0["rows"] if r["scope"] == "global")

    # change to alfred/mock
    r = admin_sess.put(f"{BASE_URL}/api/v1/admin/ramp/provider-config",
                       json={"provider": "alfred", "mode": "mock", "enabled": True},
                       timeout=15)
    assert r.status_code == 200, r.text[:300]
    payload = r.json()
    assert payload["after"]["provider"] == "alfred"
    assert payload["after"]["mode"] == "mock"

    # verify GET reflects change
    g1 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/provider-config").json()
    cur = next(r for r in g1["rows"] if r["scope"] == "global")
    assert cur["provider"] == "alfred" and cur["mode"] == "mock"

    # audit log count grew
    after_audit = _read_audit_logs_count("admin.ramp.provider_config.update")
    assert after_audit > before_audit

    # restore — IMPORTANT: leave global at andeslabs/sandbox/enabled (Phase 16 default)
    r2 = admin_sess.put(
        f"{BASE_URL}/api/v1/admin/ramp/provider-config",
        json={"provider": "andeslabs", "mode": "sandbox", "enabled": True},
        timeout=15)
    assert r2.status_code == 200


def test_provider_config_org_override_create_and_delete(admin_sess):
    # ensure clean (no leftover)
    admin_sess.delete(
        f"{BASE_URL}/api/v1/admin/ramp/provider-config/{TARGET_ORG}", timeout=15)

    before_create = _read_audit_logs_count("admin.ramp.provider_config.create")
    before_delete = _read_audit_logs_count("admin.ramp.provider_config.delete")

    # create override
    r = admin_sess.put(
        f"{BASE_URL}/api/v1/admin/ramp/provider-config/{TARGET_ORG}",
        json={"provider": "alfred", "mode": "mock", "enabled": True},
        timeout=15)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["after"]["scope"] == TARGET_ORG

    # verify present
    rows = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/provider-config").json()["rows"]
    assert any(r["scope"] == TARGET_ORG for r in rows)

    # audit create grew
    assert _read_audit_logs_count("admin.ramp.provider_config.create") > before_create

    # delete it
    rd = admin_sess.delete(
        f"{BASE_URL}/api/v1/admin/ramp/provider-config/{TARGET_ORG}", timeout=15)
    assert rd.status_code == 200, rd.text[:300]
    assert rd.json().get("removed") is True

    # verify gone + audit delete grew
    rows2 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/provider-config").json()["rows"]
    assert not any(r["scope"] == TARGET_ORG for r in rows2)
    assert _read_audit_logs_count("admin.ramp.provider_config.delete") > before_delete


def test_connectivity_probe(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/connectivity", timeout=20)
    assert r.status_code == 200, r.text[:300]
    items = r.json()
    assert isinstance(items, list) and len(items) == 2
    by_provider = {x["provider"]: x for x in items}
    assert "alfred" in by_provider and "andeslabs" in by_provider
    andes = by_provider["andeslabs"]
    assert andes["reachable"] is True, andes
    assert andes["authenticated"] is True, andes
    assert andes.get("latency_ms") is not None


def test_capabilities(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/capabilities", timeout=15)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert "alfred" in body and "andeslabs" in body
    assert "_gateway" in body
    for k in ("alfred", "andeslabs"):
        for fld in ("producedAssets", "chains", "onrampModel"):
            assert fld in body[k] or fld.lower() in body[k] or any(
                f.lower() == fld.lower() for f in body[k]
            ), f"missing {fld} for {k}: {body[k]}"


# ---------------------------------------------------------------------------
# Section B — Accounts
# ---------------------------------------------------------------------------
def test_accounts_kpis(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/accounts/kpis", timeout=15)
    assert r.status_code == 200, r.text[:300]
    k = r.json()
    assert "total_arsa_under_management" in k
    assert k["accounts_active"] >= 1, k
    # parseable float
    float(k["total_arsa_under_management"])


def test_accounts_list_and_filters(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/accounts", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body
    assert len(body["items"]) >= 1
    # each item has arsa_balance hydrated
    for it in body["items"]:
        assert "arsa_balance" in it

    # status filter
    r1 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/accounts",
                        params={"status": "approved"}, timeout=15)
    assert r1.status_code == 200
    for it in r1.json()["items"]:
        assert it.get("onboarding_status") == "approved"

    # q filter
    r2 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/accounts",
                        params={"q": "org_seed"}, timeout=15)
    assert r2.status_code == 200


def test_account_detail(admin_sess):
    # Need an existing end_customer_id; pull one from list
    lst = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/accounts", timeout=15).json()
    assert lst["items"], "no accounts to drill into"
    ec = lst["items"][0]["end_customer_id"]
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/accounts/{ec}/detail",
                       timeout=15)
    assert r.status_code == 200, r.text[:300]
    d = r.json()
    assert d["account"] is not None
    assert "wallets" in d and "balances" in d
    assert "fiat_account" in d and "recent_movements" in d


# ---------------------------------------------------------------------------
# Section C — Movements + CSV
# ---------------------------------------------------------------------------
def test_movements_list_with_filters_and_is_stale(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/movements", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body
    for it in body["items"]:
        assert "is_stale" in it
        assert isinstance(it["is_stale"], bool)

    r2 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/movements",
                        params={"status": "Success"}, timeout=15)
    assert r2.status_code == 200
    for it in r2.json()["items"]:
        assert it["status"] == "Success"

    r3 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/movements",
                        params={"kind": "withdrawal"}, timeout=15)
    assert r3.status_code == 200
    for it in r3.json()["items"]:
        assert it["kind"] == "withdrawal"


def test_movements_csv_export_and_audit(admin_sess):
    before = _read_audit_logs_count("admin.ramp.movements.export_csv")
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/movements.csv",
                       params={"limit": 100}, timeout=20)
    assert r.status_code == 200, r.text[:200]
    assert "text/csv" in r.headers.get("content-type", "")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and "filename" in cd
    # header + at least one row
    lines = r.text.strip().splitlines()
    assert len(lines) >= 2, lines[:3]
    assert "created_at" in lines[0]

    after = _read_audit_logs_count("admin.ramp.movements.export_csv")
    assert after > before


# ---------------------------------------------------------------------------
# Section D — Stats proxy
# ---------------------------------------------------------------------------
def test_stats_basic(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/stats", timeout=15)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("mode") == "mock", body
    for k in ("tvl_arsa", "accounts", "wallets",
              "deposit_count_30d", "withdrawal_count_30d"):
        assert k in body, (k, body)


def test_stats_timeseries(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/stats/timeseries",
                       timeout=15)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("window") == "30d"
    assert body.get("bucket") == "1d"
    pts = body.get("points") or []
    assert 25 <= len(pts) <= 35, len(pts)


# ---------------------------------------------------------------------------
# Section E — Webhooks
# ---------------------------------------------------------------------------
def test_webhooks_list_and_filters(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/webhooks", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body

    r1 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/webhooks",
                        params={"processed": "true"}, timeout=15)
    assert r1.status_code == 200
    for it in r1.json()["items"]:
        assert it.get("processed") is True

    r2 = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/webhooks",
                        params={"signature_valid": "true"}, timeout=15)
    assert r2.status_code == 200


def test_webhooks_deliveries_crosscheck(admin_sess):
    r = admin_sess.get(f"{BASE_URL}/api/v1/admin/ramp/webhooks/deliveries",
                       timeout=15)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert "items" in body
    assert "delivered_count" in body and "received_count" in body
    # In mock mode delivered_count is typically 0 with a note
    for it in body["items"]:
        assert "received" in it
        assert isinstance(it["received"], bool)
