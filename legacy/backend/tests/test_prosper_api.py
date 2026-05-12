"""
Prosper backend API tests.
Covers: health, auth, dashboard, orgs, onboarding, compliance, funds, products,
positions, treasury, transactions, reconciliation, integrations, alerts,
reports, audit-logs, users.
"""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


# ---------- Health ----------
class TestHealth:
    def test_health(self, api_client):
        r = api_client.get(f"{API}/health")
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ---------- Auth ----------
class TestAuth:
    def test_me_no_token(self, api_client):
        r = api_client.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_with_token(self, auth_client):
        r = auth_client.get(f"{API}/auth/me")
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == "demo.admin@prosper.foundation"
        assert data["platform_role"] == "super_admin"
        assert data["user_id"] == "user_demo_prosper_admin"
        assert data["is_internal"] is True
        assert "_id" not in data


# ---------- Dashboard ----------
class TestDashboard:
    def test_overview_production(self, auth_client):
        r = auth_client.get(f"{API}/dashboard/overview", params={"env": "production"})
        assert r.status_code == 200
        d = r.json()
        assert d["environment"] == "production"
        assert "aum_usd" in d["kpis"] and d["kpis"]["aum_usd"] > 0
        assert "circulating_supply" in d["kpis"]
        assert isinstance(d.get("nav_series"), list) and len(d["nav_series"]) > 0
        assert isinstance(d.get("volume_series"), list)

    def test_overview_sandbox(self, auth_client):
        r = auth_client.get(f"{API}/dashboard/overview", params={"env": "sandbox"})
        assert r.status_code == 200
        assert r.json()["environment"] == "sandbox"


# ---------- Organizations ----------
class TestOrganizations:
    def test_list_orgs(self, auth_client):
        r = auth_client.get(f"{API}/organizations")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", data.get("organizations", []))
        assert len(items) >= 5
        # ensure no mongo _id leaked
        for o in items:
            assert "_id" not in o
            assert "org_id" in o or "id" in o

    def test_get_org_detail(self, auth_client):
        lst = auth_client.get(f"{API}/organizations").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        assert len(items) > 0
        oid = items[0].get("org_id") or items[0].get("id")
        r = auth_client.get(f"{API}/organizations/{oid}")
        assert r.status_code == 200
        d = r.json()
        assert "_id" not in d
        # expect counts
        assert any(k in d for k in ("positions_count", "transactions_count", "counts", "stats"))


# ---------- Onboarding & Compliance ----------
class TestOnboarding:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/onboarding")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert isinstance(items, list)

    def test_detail(self, auth_client):
        lst = auth_client.get(f"{API}/onboarding").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        if not items:
            pytest.skip("no onboarding cases")
        cid = items[0].get("case_id") or items[0].get("id")
        r = auth_client.get(f"{API}/onboarding/{cid}")
        assert r.status_code == 200


class TestCompliance:
    def test_queue(self, auth_client):
        r = auth_client.get(f"{API}/compliance/queue")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert isinstance(items, list)
        for it in items:
            assert "_id" not in it


# ---------- Funds, Products, Positions ----------
class TestFunds:
    def test_list_funds(self, auth_client):
        r = auth_client.get(f"{API}/funds")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert len(items) >= 1
        # expect products joined
        assert any(("products" in it) or ("product_ids" in it) for it in items)


class TestProducts:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/products")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert len(items) == 5


class TestPositions:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/positions")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert len(items) >= 1

    def test_filter_status(self, auth_client):
        r = auth_client.get(f"{API}/positions", params={"status": "active"})
        assert r.status_code == 200


# ---------- Treasury ----------
class TestTreasury:
    def test_accounts(self, auth_client):
        r = auth_client.get(f"{API}/treasury/accounts", params={"env": "production"})
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        roles = {a.get("kind") or a.get("role") or a.get("account_type") for a in items}
        for needed in ("issuer", "treasury", "reward_pool", "fee"):
            assert needed in roles, f"missing role {needed}, got {roles}"


# ---------- Transactions ----------
class TestTransactions:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/transactions")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert len(items) >= 1
        # prosperTxId must exist and be unique
        ptx = [it.get("prosperTxId") or it.get("prosper_tx_id") for it in items]
        ptx = [p for p in ptx if p]
        assert len(ptx) > 0
        assert len(set(ptx)) == len(ptx)

    def test_filter_search(self, auth_client):
        r = auth_client.get(f"{API}/transactions", params={"type": "mint"})
        assert r.status_code == 200

    def test_mint_requires_role(self, auth_client):
        payload = {
            "org_id": "org_demo_1",
            "amount": 1000.0,
            "product_id": "product_demo_liquid",
            "env": "production",
        }
        r = auth_client.post(f"{API}/transactions/mint", json=payload)
        # super_admin role so should succeed (200/201) or validation error (422); not 403
        assert r.status_code in (200, 201, 400, 422), f"got {r.status_code}: {r.text[:200]}"
        if r.status_code in (200, 201):
            d = r.json()
            assert d.get("prosperTxId") or d.get("prosper_tx_id") or "transaction" in d


# ---------- Reconciliation ----------
class TestReconciliation:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/reconciliation")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert len(items) >= 1

    def test_resolve(self, auth_client):
        lst = auth_client.get(f"{API}/reconciliation").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        unresolved = [i for i in items if i.get("status") != "resolved"]
        target = unresolved[0] if unresolved else items[0]
        rid = target.get("recon_id") or target.get("record_id") or target.get("id")
        r = auth_client.post(f"{API}/reconciliation/{rid}/resolve", json={"note": "TEST_resolved"})
        assert r.status_code in (200, 204)


# ---------- Integrations ----------
class TestIntegrations:
    def test_apps(self, auth_client):
        r = auth_client.get(f"{API}/integrations/apps")
        assert r.status_code == 200

    def test_keys_list(self, auth_client):
        r = auth_client.get(f"{API}/integrations/keys")
        assert r.status_code == 200

    def test_webhooks_list(self, auth_client):
        r = auth_client.get(f"{API}/integrations/webhooks")
        assert r.status_code == 200

    def test_create_and_revoke_key(self, auth_client):
        # pick an app
        apps = auth_client.get(f"{API}/integrations/apps").json()
        apps = apps if isinstance(apps, list) else apps.get("items", [])
        if not apps:
            pytest.skip("no apps")
        app_id = apps[0].get("app_id") or apps[0].get("id")
        org_id = apps[0].get("org_id")
        if not org_id:
            orgs = auth_client.get(f"{API}/organizations").json()
            orgs = orgs if isinstance(orgs, list) else orgs.get("items", [])
            org_id = orgs[0].get("org_id") or orgs[0].get("id")
        payload = {"app_id": app_id, "org_id": org_id, "name": "TEST_key", "label": "TEST_key", "scopes": ["read"]}
        r = auth_client.post(f"{API}/integrations/keys", json=payload)
        assert r.status_code in (200, 201), f"create key failed: {r.status_code} {r.text[:200]}"
        d = r.json()
        # plaintext returned once
        assert d.get("api_key_plaintext") or d.get("plaintext") or d.get("api_key") or d.get("key") or d.get("secret")
        kid = d.get("key_id") or d.get("id")
        if kid:
            rv = auth_client.post(f"{API}/integrations/keys/{kid}/revoke")
            assert rv.status_code in (200, 204)


# ---------- Alerts ----------
class TestAlerts:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/alerts")
        assert r.status_code == 200
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        assert len(items) >= 1

    def test_resolve(self, auth_client):
        lst = auth_client.get(f"{API}/alerts").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        if not items:
            pytest.skip("no alerts")
        aid = items[0].get("alert_id") or items[0].get("id")
        r = auth_client.post(f"{API}/alerts/{aid}/resolve", json={})
        assert r.status_code in (200, 204)


# ---------- Reports & Audit ----------
class TestReports:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/reports")
        assert r.status_code == 200
        data = r.json()
        # may be grouped dict by kind or a flat list
        if isinstance(data, dict) and "items" not in data:
            kinds = set(data.keys())
            assert kinds & {"daily_nav", "audit", "performance", "tax"}
        else:
            items = data if isinstance(data, list) else data.get("items", [])
            assert len(items) >= 1


class TestAudit:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/audit-logs")
        assert r.status_code == 200


# ---------- Users ----------
class TestUsers:
    def test_list(self, auth_client):
        r = auth_client.get(f"{API}/users")
        assert r.status_code == 200
