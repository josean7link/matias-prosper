"""Sprint 12.6 — Alfred Hybrid KYB + KYC integration tests."""
import os
import time

import jwt
import pytest
import requests

BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api/v1"


def _jwt_secret() -> str:
    # Read JWT_SECRET from backend .env (auth module reads same)
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith("JWT_SECRET="):
                return line.strip().split("=", 1)[1]
    raise RuntimeError("JWT_SECRET not found")


def _make_kyb_token(org_id="org_seed_alemany", purpose="kyb", expired=False) -> str:
    now = int(time.time())
    payload = {
        "link_id": "slk_test",
        "purpose": purpose,
        "org_id":  org_id,
        "iat": now,
        "exp": now - 60 if expired else now + 3600,
        "iss": "prosper-admin",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


# -- Ensure signed_link row exists (insert_one once via the admin path is non-trivial; use mongo)
def _ensure_signed_link(link_id="slk_test", org_id="org_seed_alemany"):
    from pymongo import MongoClient
    mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mc[os.environ.get("DB_NAME", "prosper_phase0")]
    db.signed_links.update_one(
        {"link_id": link_id},
        {"$set": {"link_id": link_id, "org_id": org_id, "purpose": "kyb",
                  "status": "pending", "is_deleted": False}},
        upsert=True,
    )


@pytest.fixture(scope="module", autouse=True)
def _setup():
    _ensure_signed_link()
    yield


# ---------------------------------------------------------------------------
# KYB start
# ---------------------------------------------------------------------------
class TestAlfredKyb:
    def test_kyb_start_invalid_token(self):
        r = requests.post(f"{API}/onboarding/alfred/kyb/start",
                          json={"token": "not-a-token"}, timeout=15)
        assert r.status_code == 401, r.text

    def test_kyb_start_expired_token(self):
        tok = _make_kyb_token(expired=True)
        r = requests.post(f"{API}/onboarding/alfred/kyb/start",
                          json={"token": tok}, timeout=15)
        assert r.status_code == 401, r.text

    def test_kyb_start_success_and_persists(self):
        tok = _make_kyb_token()
        r = requests.post(f"{API}/onboarding/alfred/kyb/start",
                          json={"token": tok}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "customer_id" in data and data["customer_id"]
        assert "iframe_url" in data and "mock-kyc" in data["iframe_url"]
        assert data["status"] == "pending"
        assert data["mode"] == "mock"

        # Persisted on the org
        from pymongo import MongoClient
        mc = MongoClient(os.environ.get("MONGO_URL"))
        db = mc[os.environ.get("DB_NAME", "prosper_phase0")]
        org = db.organizations.find_one({"org_id": "org_seed_alemany"})
        assert org is not None
        assert org.get("alfred_customer_id") == data["customer_id"]

        # Idempotent
        r2 = requests.post(f"{API}/onboarding/alfred/kyb/start",
                           json={"token": tok}, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["customer_id"] == data["customer_id"]
        # store for downstream tests
        TestAlfredKyb.cid = data["customer_id"]


# ---------------------------------------------------------------------------
# KYC start (auth required)
# ---------------------------------------------------------------------------
class TestAlfredKyc:
    def test_kyc_no_auth(self):
        r = requests.post(f"{API}/onboarding/alfred/kyc/start", json={}, timeout=15)
        assert r.status_code in (401, 403), r.text

    def test_kyc_with_auth(self):
        s = requests.Session()
        # dev-login as client_admin
        r = s.get(f"{API}/auth/dev-login",
                  params={"email": "client.admin@alemany.capital", "next": "/"},
                  allow_redirects=False, timeout=15)
        assert r.status_code in (200, 302, 303, 307), r.text

        r = s.post(f"{API}/onboarding/alfred/kyc/start", json={}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "mock"
        assert data["status"] == "pending"
        assert "mock-kyc" in data["iframe_url"]
        cid = data["customer_id"]

        # Idempotent
        r2 = s.post(f"{API}/onboarding/alfred/kyc/start", json={}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["customer_id"] == cid


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------
class TestAlfredStatus:
    def test_status_unknown(self):
        r = requests.get(f"{API}/onboarding/alfred/status",
                         params={"customer_id": "alfc_does_not_exist_zzz"}, timeout=10)
        assert r.status_code == 404

    def test_status_kyb(self):
        cid = getattr(TestAlfredKyb, "cid", None)
        if not cid:
            pytest.skip("KYB test did not run")
        r = requests.get(f"{API}/onboarding/alfred/status",
                         params={"customer_id": cid}, timeout=10)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["kind"] == "kyb"
        assert "alfred_status" in j


# ---------------------------------------------------------------------------
# Mock widget + settle (approve/reject) — drives webhook
# ---------------------------------------------------------------------------
class TestAlfredMock:
    def test_mock_widget_html(self):
        cid = getattr(TestAlfredKyb, "cid", None)
        if not cid:
            pytest.skip("KYB test did not run")
        r = requests.get(f"{API}/alfred/mock-kyc/{cid}",
                         params={"kind": "kyb"}, timeout=10)
        assert r.status_code == 200
        assert "alfred-mock-approve" in r.text
        assert "text/html" in r.headers.get("content-type", "")

    def test_mock_settle_approve_provisions_wallet(self):
        # Create a fresh KYB so we can approve cleanly
        tok = _make_kyb_token()
        r = requests.post(f"{API}/onboarding/alfred/kyb/start",
                          json={"token": tok}, timeout=20)
        assert r.status_code == 200
        cid = r.json()["customer_id"]

        s = requests.post(f"{API}/alfred/mock-kyc/{cid}/settle",
                          params={"decision": "approve"}, timeout=30)
        assert s.status_code == 200, s.text
        body = s.json()
        assert body.get("ok") is True
        assert body.get("status") == "approved"

        # Check org kyb_status + stellar address provisioned
        from pymongo import MongoClient
        mc = MongoClient(os.environ.get("MONGO_URL"))
        db = mc[os.environ.get("DB_NAME", "prosper_phase0")]
        org = db.organizations.find_one({"alfred_customer_id": cid})
        assert org is not None
        assert org.get("kyb_status") == "approved"
        assert org.get("alfred_kyb_status") == "approved"
        # Prosper wallet should have been provisioned (best-effort)
        assert org.get("stellar_address"), "stellar_address should be provisioned"

    def test_mock_settle_reject(self):
        tok = _make_kyb_token(org_id="org_seed_finpact")
        # Need a finpact signed link too
        _ensure_signed_link(link_id="slk_test", org_id="org_seed_finpact")
        r = requests.post(f"{API}/onboarding/alfred/kyb/start",
                          json={"token": tok}, timeout=20)
        assert r.status_code == 200, r.text
        cid = r.json()["customer_id"]
        # If idempotent returned old approved cid, reject will still update.
        s = requests.post(f"{API}/alfred/mock-kyc/{cid}/settle",
                          params={"decision": "reject"}, timeout=20)
        assert s.status_code == 200, s.text
        assert s.json().get("status") == "rejected"
