"""Phase 3 — Onboarding (AiPrise simulated mode) + Compliance + Webhooks.

End-to-end coverage of the SIMULATED path (no real AiPrise calls). All tests
share auth helpers and use TEST_ prefixed legal_name / contact_email so they
can be identified and cleaned up.
"""
import os
import re
import time
import uuid
import json
import hmac
import hashlib
import subprocess
import requests
import pytest

BASE = os.environ.get("API_BASE", "http://localhost:8001")
API = f"{BASE}/api/v1"

ADMIN_EMAIL  = "admin@prosper.foundation"          # super_admin
CLIENT_EMAIL = "client.admin@alemany.capital"      # client_admin


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────
def _otp_from_log(email: str) -> str:
    # backend logs OTP as "<email> -> <6 digit otp>"
    out = subprocess.check_output(
        ["tail", "-n", "200", "/var/log/supervisor/backend.err.log"],
        text=True, errors="ignore",
    )
    matches = re.findall(rf"{re.escape(email)} -> (\d+)", out)
    assert matches, f"No OTP found in backend log for {email}"
    return matches[-1]


def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/passwordless-login", json={"email": email}, timeout=10)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    time.sleep(0.3)  # give logger time to flush
    otp = _otp_from_log(email)
    r2 = s.post(f"{API}/auth/passwordless-token",
                json={"code": code, "token": otp}, timeout=10)
    assert r2.status_code == 200, r2.text
    return s


@pytest.fixture(scope="session")
def admin():
    return _login(ADMIN_EMAIL)


@pytest.fixture(scope="session")
def client_admin():
    return _login(CLIENT_EMAIL)


# ─────────────────────────────────────────────────────────────────────────────
# Test data
# ─────────────────────────────────────────────────────────────────────────────
def _app_payload(suffix: str = ""):
    sid = suffix or uuid.uuid4().hex[:8]
    domain = f"testholdings-{sid}.example"
    return {
        "legal_name": f"TEST_Holdings_{sid}",
        "commercial_name": "TEST Holdings",
        "country": "US",
        "jurisdiction": "DE",
        "incorporation_date": "2020-01-01",
        "registration_number": "TEST-12345",
        "contact_name": "Maria Test",
        "contact_email": f"maria@{domain}",
        "contact_phone": "+15551234567",
        "website": f"https://{domain}",
        "expected_monthly_volume_usd": 250000,
        "use_case": "Treasury management",
        "ubos": [
            {"full_name": "Maria Test", "ownership_pct": 60.0,
             "role": "Director", "country": "US"},
            {"full_name": "John Test", "ownership_pct": 40.0,
             "role": "Director", "country": "US"},
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# /apply
# ─────────────────────────────────────────────────────────────────────────────
class TestApplyPublic:

    def test_apply_returns_simulated_session(self):
        r = requests.post(f"{API}/onboarding/apply", json=_app_payload(), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "in_review"
        assert data["kyb_status"] == "pending"
        assert data["mode"] == "simulated"
        assert data["hosted_url"].startswith("/apply/simulate?session_id=sim_kyb_")
        assert data["application_id"].startswith("app_")
        assert data["org_id"].startswith("org_")

    def test_apply_no_auth_required(self):
        # ensure no Authorization header is needed
        r = requests.post(f"{API}/onboarding/apply", json=_app_payload(),
                          headers={"Authorization": ""}, timeout=10)
        assert r.status_code == 200

    def test_get_application_sanitized(self):
        payload = _app_payload()
        r = requests.post(f"{API}/onboarding/apply", json=payload, timeout=10)
        app_id = r.json()["application_id"]
        g = requests.get(f"{API}/onboarding/apply/{app_id}", timeout=10)
        assert g.status_code == 200
        data = g.json()
        # No PII leakage
        assert "ubos" not in data
        assert "contact_phone" not in data
        assert "contact_email" not in data
        # Expected fields present
        assert data["application_id"] == app_id
        assert data["status"] == "in_review"
        assert data["kyb_status"] == "pending"
        assert data["aiprise_mode"] == "simulated"

    def test_get_application_404(self):
        r = requests.get(f"{API}/onboarding/apply/app_does_not_exist", timeout=5)
        assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# /apply/simulate
# ─────────────────────────────────────────────────────────────────────────────
class TestSimulate:

    def _new(self):
        r = requests.post(f"{API}/onboarding/apply", json=_app_payload(), timeout=10)
        app = r.json()
        session_id = app["hosted_url"].split("session_id=", 1)[1].split("&", 1)[0]
        return app, session_id

    def test_rejects_non_sim_sessions(self):
        r = requests.post(f"{API}/onboarding/apply/simulate",
                          json={"session_id": "real_xyz", "decision": "approved"}, timeout=5)
        assert r.status_code == 400

    def test_rejects_invalid_decision(self):
        _, sid = self._new()
        r = requests.post(f"{API}/onboarding/apply/simulate",
                          json={"session_id": sid, "decision": "foo"}, timeout=5)
        assert r.status_code == 400

    def test_approved_flow_updates_app_org_and_audit(self):
        app, sid = self._new()
        r = requests.post(f"{API}/onboarding/apply/simulate",
                          json={"session_id": sid, "decision": "approved"}, timeout=10)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["ok"] is True
        assert out["kyb_status"] == "approved"

        # Verify persistence via GET
        g = requests.get(f"{API}/onboarding/apply/{app['application_id']}", timeout=5)
        body = g.json()
        assert body["status"] == "approved"
        assert body["kyb_status"] == "approved"

    def test_rejected_flow(self):
        app, sid = self._new()
        r = requests.post(f"{API}/onboarding/apply/simulate",
                          json={"session_id": sid, "decision": "rejected"}, timeout=10)
        assert r.status_code == 200
        g = requests.get(f"{API}/onboarding/apply/{app['application_id']}", timeout=5)
        assert g.json()["kyb_status"] == "rejected"
        assert g.json()["status"] == "rejected"

    def test_pending_review_maps_to_in_review(self):
        app, sid = self._new()
        r = requests.post(f"{API}/onboarding/apply/simulate",
                          json={"session_id": sid, "decision": "pending_review"}, timeout=10)
        assert r.status_code == 200
        g = requests.get(f"{API}/onboarding/apply/{app['application_id']}", timeout=5)
        assert g.json()["kyb_status"] == "in_review"


# ─────────────────────────────────────────────────────────────────────────────
# Webhooks — HMAC (empty secret → accept any signature)
# ─────────────────────────────────────────────────────────────────────────────
class TestWebhooks:

    def test_kyb_webhook_accepts_unsigned_in_sim_mode(self):
        # New app
        r = requests.post(f"{API}/onboarding/apply", json=_app_payload(), timeout=10)
        app = r.json()
        sid = app["hosted_url"].split("session_id=", 1)[1].split("&", 1)[0]
        wb = requests.post(
            f"{API}/webhooks/aiprise/kyb",
            json={"verification_session_id": sid, "decision": "approved"},
            timeout=10,
        )
        assert wb.status_code == 200, wb.text
        g = requests.get(f"{API}/onboarding/apply/{app['application_id']}", timeout=5)
        assert g.json()["kyb_status"] == "approved"

    def test_kyb_webhook_invalid_json(self):
        r = requests.post(
            f"{API}/webhooks/aiprise/kyb",
            data="not-json{{{",
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
        assert r.status_code == 400

    def test_kyb_webhook_missing_fields(self):
        r = requests.post(f"{API}/webhooks/aiprise/kyb", json={}, timeout=5)
        assert r.status_code == 400

    def test_kyc_webhook_unknown_session_404(self):
        r = requests.post(
            f"{API}/webhooks/aiprise/kyc",
            json={"verification_session_id": "sim_kyc_zzz",
                  "decision": "approved",
                  "client_reference_id": "user_does_not_exist"},
            timeout=5,
        )
        assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Compliance endpoints
# ─────────────────────────────────────────────────────────────────────────────
class TestCompliance:

    def test_summary_requires_auth(self):
        r = requests.get(f"{API}/compliance/summary", timeout=5)
        assert r.status_code == 401

    def test_summary_admin_ok(self, admin):
        r = admin.get(f"{API}/compliance/summary", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "kyb" in data and "kyc" in data
        for k in ("pending", "approved", "rejected"):
            assert k in data["kyb"]
        assert "pending" in data["kyc"]

    def test_client_admin_forbidden(self, client_admin):
        r = client_admin.get(f"{API}/compliance/summary", timeout=10)
        assert r.status_code == 403
        r2 = client_admin.get(f"{API}/compliance/applications", timeout=10)
        assert r2.status_code == 403

    def test_list_applications_in_review(self, admin):
        # Seed one
        requests.post(f"{API}/onboarding/apply", json=_app_payload(), timeout=10)
        r = admin.get(f"{API}/compliance/applications?status=in_review", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body["items"], list)
        assert body["total"] >= 1

    def test_decide_application_approved(self, admin):
        # Submit
        r = requests.post(f"{API}/onboarding/apply", json=_app_payload(), timeout=10)
        app_id = r.json()["application_id"]
        # Decide
        d = admin.post(f"{API}/compliance/applications/{app_id}/decide",
                       json={"decision": "approved", "note": "ok"}, timeout=10)
        assert d.status_code == 200, d.text
        body = d.json()
        assert body["kyb_status"] == "approved"
        # Persistence
        g = requests.get(f"{API}/onboarding/apply/{app_id}", timeout=5)
        assert g.json()["kyb_status"] == "approved"

    def test_decide_application_client_admin_forbidden(self, client_admin):
        r = requests.post(f"{API}/onboarding/apply", json=_app_payload(), timeout=10)
        app_id = r.json()["application_id"]
        d = client_admin.post(f"{API}/compliance/applications/{app_id}/decide",
                              json={"decision": "approved"}, timeout=10)
        assert d.status_code == 403

    def test_kyc_cases_list(self, admin):
        r = admin.get(f"{API}/compliance/kyc-cases", timeout=10)
        assert r.status_code == 200
        assert "items" in r.json()


# ─────────────────────────────────────────────────────────────────────────────
# /onboarding/me/kyc
# ─────────────────────────────────────────────────────────────────────────────
class TestMyKyc:

    def test_requires_auth(self):
        r = requests.post(f"{API}/onboarding/me/kyc", timeout=5)
        assert r.status_code == 401

    def test_client_admin_starts_kyc(self, client_admin):
        r = client_admin.post(f"{API}/onboarding/me/kyc", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        # Either freshly started in_review (simulated) or already approved (skipped)
        assert data["mode"] in ("simulated", "skipped", "live")
        assert data["kyc_status"] in ("in_review", "approved")
        if data["mode"] == "simulated":
            assert data["hosted_url"].startswith("/apply/simulate?")
