"""Phase 0 smoke tests — Prosper API."""
import os
import re
import requests

BASE = os.environ.get("API_BASE", "http://localhost:8001")


def test_health():
    r = requests.get(f"{BASE}/api/health", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["service"] == "prosper-api"


def test_passwordless_login_returns_continuation_code():
    r = requests.post(
        f"{BASE}/api/v1/auth/passwordless-login",
        json={"email": "smoke@prosper.foundation"},
        timeout=5,
    )
    assert r.status_code == 200
    body = r.json()
    assert "code" in body
    assert len(body["code"]) > 16  # opaque token


def test_passwordless_token_rejects_invalid_otp():
    r = requests.post(
        f"{BASE}/api/v1/auth/passwordless-login",
        json={"email": "wrong-otp@prosper.foundation"},
        timeout=5,
    )
    code = r.json()["code"]
    r2 = requests.post(
        f"{BASE}/api/v1/auth/passwordless-token",
        json={"code": code, "token": "0000"},
        timeout=5,
    )
    assert r2.status_code == 401
    assert "Invalid OTP" in r2.text


def test_me_requires_auth():
    r = requests.get(f"{BASE}/api/v1/auth/me", timeout=5)
    assert r.status_code == 401
