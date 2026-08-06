"""Phase: self-service funnel.

Tests:
- BUG FIX: passwordless-token with unknown email -> 403 with /apply hint
- BUG FIX: dev-login with unknown email -> 403 with /apply hint
- Seeded client.admin@alemany.capital dev-login still works (303 redirect)
- /api/v1/onboarding/apply individual returns mode=andes-direct + application_id
"""
import os
import secrets
import requests

BASE_URL = "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com"


# ---- Bug fix: unknown email must NOT be auto-provisioned ----------
def test_passwordless_login_unknown_email_still_returns_dev_otp():
    email = f"random.unknown.{secrets.token_hex(4)}@gmail.com"
    r = requests.post(
        f"{BASE_URL}/api/v1/auth/passwordless-login",
        json={"email": email},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "dev_otp" in data, "dev_otp must still be present in dev/preview"
    assert isinstance(data["dev_otp"], str) and len(data["dev_otp"]) >= 4


def test_passwordless_token_unknown_email_returns_403():
    email = f"random.unknown.{secrets.token_hex(4)}@gmail.com"
    # request OTP first
    r1 = requests.post(
        f"{BASE_URL}/api/v1/auth/passwordless-login",
        json={"email": email},
        timeout=30,
    )
    assert r1.status_code == 200
    cont = r1.json()["code"]
    otp = r1.json()["dev_otp"]

    # Now exchange — must be rejected with 403 referencing /apply
    r2 = requests.post(
        f"{BASE_URL}/api/v1/auth/passwordless-token",
        json={"email": email, "code": cont, "token": otp},
        timeout=30,
    )
    assert r2.status_code == 403, f"expected 403 got {r2.status_code}: {r2.text}"
    body = r2.text.lower()
    assert "/apply" in body or "no está registrado" in body, body


def test_dev_login_unknown_email_returns_403():
    email = f"random.unknown.{secrets.token_hex(4)}@gmail.com"
    r = requests.get(
        f"{BASE_URL}/api/v1/auth/dev-login",
        params={"email": email, "next": "/client"},
        allow_redirects=False,
        timeout=30,
    )
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"
    body = r.text.lower()
    assert "/apply" in body or "no está registrado" in body, body


def test_dev_login_seeded_client_still_works():
    r = requests.get(
        f"{BASE_URL}/api/v1/auth/dev-login",
        params={"email": "client.admin@alemany.capital", "next": "/client"},
        allow_redirects=False,
        timeout=30,
    )
    # Either 303/302/307 (redirect) or 200 — both OK; reject 4xx/5xx
    assert r.status_code in (200, 302, 303, 307), f"got {r.status_code}: {r.text}"


def test_dev_login_seeded_admin_still_works():
    r = requests.get(
        f"{BASE_URL}/api/v1/auth/dev-login",
        params={"email": "admin@prosper.foundation", "next": "/admin"},
        allow_redirects=False,
        timeout=30,
    )
    assert r.status_code in (200, 302, 303, 307), f"got {r.status_code}: {r.text}"


# ---- Self-service funnel: POST /onboarding/apply individuo ----------
def test_onboarding_apply_individual_returns_andes_direct_mode():
    email = f"juan.test.{secrets.token_hex(4)}@gmail.com"
    body = {
        "applicant_type": "individual",
        "legal_name": "Juan Test",
        "country": "AR",
        "jurisdiction": "AR",
        "contact_name": "Juan",
        "contact_email": email,
        "contact_phone": "+5491122334455",
        "last_name": "Test",
        "cuit": "20123456789",
        "birthdate": "1990-05-15",
        "phone": "+5491122334455",
        "chain": "stellar",
        "use_case": "yield",
        "ubos": [],
    }
    r = requests.post(
        f"{BASE_URL}/api/v1/onboarding/apply",
        json=body,
        timeout=60,
    )
    assert r.status_code in (200, 201), f"{r.status_code}: {r.text}"
    data = r.json()
    assert "application_id" in data, data
    assert data.get("mode") == "andes-direct", f"mode={data.get('mode')} expected andes-direct: {data}"
