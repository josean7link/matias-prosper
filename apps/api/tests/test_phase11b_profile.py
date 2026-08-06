"""Sprint 11B — Profile hardening tests (extended profile, MFA, sessions, deletion)."""
from __future__ import annotations
import os

import pyotp
import requests

BASE = os.environ.get("PROSPER_API_BASE_TEST", "http://localhost:8001/api")
API  = f"{BASE}/v1"


def _admin_session(email: str = "client.admin@finpact.io") -> requests.Session:
    """Always returns a fresh dev-login session for the given client_admin."""
    s = requests.Session()
    s.get(f"{API}/auth/dev-login",
          params={"email": email, "next": "/"},
          allow_redirects=False, timeout=10)
    return s


# ---------------------------------------------------------------------------
# Profile basics
# ---------------------------------------------------------------------------
def test_get_profile_shape():
    s = _admin_session()
    r = s.get(f"{API}/client/profile", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("user_id", "email", "language", "timezone", "mfa_enabled",
              "notifications", "role"):
        assert k in body, f"{k} missing in /profile response"


def test_patch_profile_updates_basics():
    s = _admin_session()
    r = s.patch(f"{API}/client/profile",
                 json={"full_name": "John Doe",
                       "phone":     "+54 11 5555-0000",
                       "language":  "en",
                       "timezone":  "America/Sao_Paulo"},
                 timeout=10)
    assert r.status_code == 200, r.text
    body = s.get(f"{API}/client/profile", timeout=10).json()
    assert body["full_name"] == "John Doe"
    assert body["language"]  == "en"
    assert body["timezone"]  == "America/Sao_Paulo"


def test_patch_profile_rejects_bad_timezone():
    s = _admin_session()
    r = s.patch(f"{API}/client/profile",
                 json={"timezone": "Mars/Olympus_Mons"}, timeout=10)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Avatar
# ---------------------------------------------------------------------------
_PNG_1x1 = ("data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


def test_avatar_upload_and_delete():
    s = _admin_session()
    r = s.post(f"{API}/client/avatar", json={"data_url": _PNG_1x1}, timeout=10)
    assert r.status_code == 200, r.text
    assert s.get(f"{API}/client/profile",
                  timeout=10).json()["avatar_url"].startswith("data:image/")
    s.delete(f"{API}/client/avatar", timeout=10)
    assert s.get(f"{API}/client/profile", timeout=10).json()["avatar_url"] is None


def test_avatar_rejects_oversize():
    s = _admin_session()
    huge = "data:image/png;base64," + ("A" * (400 * 1024))  # ~300 KB raw, > 256 KB
    r = s.post(f"{API}/client/avatar", json={"data_url": huge}, timeout=10)
    assert r.status_code in (400, 413)


# ---------------------------------------------------------------------------
# MFA TOTP full happy path
# ---------------------------------------------------------------------------
def test_mfa_setup_verify_disable_full_cycle():
    s = _admin_session("client.admin@alemany.capital")

    # 1. setup
    setup = s.post(f"{API}/client/mfa/setup", timeout=10).json()
    assert "provisioning_uri" in setup and "secret" in setup
    assert setup["qr_data_url"].startswith("data:image/png;base64,")
    secret = setup["secret"]

    # 2. verify with TOTP
    code = pyotp.TOTP(secret).now()
    r = s.post(f"{API}/client/mfa/verify",
                json={"code": code}, timeout=10)
    assert r.status_code == 200, r.text
    codes = r.json()["backup_codes"]
    assert len(codes) == 10
    assert all(len(c) == 9 and "-" in c for c in codes)  # XXXX-XXXX

    # 3. profile flips
    assert s.get(f"{API}/client/profile", timeout=10).json()["mfa_enabled"]

    # 4. disable using a backup code (consumes one)
    r = s.post(f"{API}/client/mfa/disable",
                json={"backup_code": codes[0]}, timeout=10)
    assert r.status_code == 200, r.text
    assert not s.get(f"{API}/client/profile", timeout=10).json()["mfa_enabled"]


def test_mfa_verify_bad_code_rejected():
    s = _admin_session("client.admin@alemany.capital")
    s.post(f"{API}/client/mfa/setup", timeout=10)
    r = s.post(f"{API}/client/mfa/verify",
                json={"code": "000000"}, timeout=10)
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Sessions list + revoke
# ---------------------------------------------------------------------------
def test_sessions_listed_and_revoke_self():
    s = _admin_session("client.admin@finpact.io")
    sessions = s.get(f"{API}/client/sessions", timeout=10).json()
    assert sessions["total"] >= 1
    cur = next((it for it in sessions["items"] if it["is_current"]), None)
    assert cur is not None, "current session missing is_current flag"

    # Revoke current
    s.delete(f"{API}/client/sessions/" + cur["session_id"], timeout=10)
    # Subsequent call should now 401 because session revoked
    r = s.get(f"{API}/client/sessions", timeout=10)
    assert r.status_code == 401


def test_revoke_others_keeps_current():
    s1 = _admin_session("client.admin@alemany.capital")  # session 1
    _ = _admin_session("client.admin@alemany.capital")    # session 2 (different cookies)
    listing = s1.get(f"{API}/client/sessions", timeout=10).json()
    assert listing["total"] >= 2
    r = s1.post(f"{API}/client/sessions/revoke-others", timeout=10).json()
    assert r["ok"] and r["revoked"] >= 1
    # s1 still works
    listing = s1.get(f"{API}/client/sessions", timeout=10).json()
    assert listing["total"] == 1
    assert listing["items"][0]["is_current"]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def test_notifications_patch_persists():
    s = _admin_session()
    r = s.patch(f"{API}/client/notifications",
                 json={"email_marketing": True, "inapp_alerts": False},
                 timeout=10).json()
    assert r["email_marketing"]   is True
    assert r["inapp_alerts"]      is False
    # cleanup
    s.patch(f"{API}/client/notifications",
             json={"email_marketing": False, "inapp_alerts": True}, timeout=10)


# ---------------------------------------------------------------------------
# Account deletion request flow
# ---------------------------------------------------------------------------
def test_deletion_request_and_cancel():
    s = _admin_session("client.admin@finpact.io")

    # Reject when confirm_email mismatches
    bad = s.post(f"{API}/client/account/request-deletion",
                  json={"confirm_email": "wrong@example.com"}, timeout=10)
    assert bad.status_code == 400

    # Accept with matching email
    r = s.post(f"{API}/client/account/request-deletion",
                json={"confirm_email": "client.admin@finpact.io",
                      "reason": "test"}, timeout=10)
    assert r.status_code == 200, r.text
    p = s.get(f"{API}/client/profile", timeout=10).json()
    assert p["deletion_requested"] is True
    assert p["deletion_effective_at"]

    # Cancel
    s.post(f"{API}/client/account/cancel-deletion", timeout=10)
    p = s.get(f"{API}/client/profile", timeout=10).json()
    assert p["deletion_requested"] is False
