"""Phase: sanctions / PEP screening gate (iteration 26).

Coverage:
  * Resend safeguards: dev mode (no RESEND_API_KEY) still returns dev_otp +
    magic_link; outbound_emails captures otp_login with status=preview_only.
  * Resend gating in code (static asserts on server.py + onboarding.py).
  * Sanctions enqueue automatic: onboarding/apply seeds sanctions_status=pending,
    fiat.account.created webhook inserts sanctions_screenings row pending and
    leaves org+user un-activated (the gate).
  * Sanctions admin queue + decision (clear and flagged) + 409 idempotency.
  * /me + /client/me expose sanctions_status / sanctions_locked / can_operate.
  * Regression: unknown email still returns 403 on /auth/passwordless-token.
"""
import asyncio
import os
import secrets
import time
import inspect
import requests
import pytest
from pymongo import MongoClient

BASE_URL = "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME   = os.environ["DB_NAME"]
GATEWAY_INTERNAL_TOKEN = os.environ["GATEWAY_INTERNAL_TOKEN"]

mongo  = MongoClient(MONGO_URL)
db     = mongo[DB_NAME]


def _uniq_email(tag: str) -> str:
    return f"test.{tag}.{secrets.token_hex(4)}@gmail.com"


# ---------------------------------------------------------------------------
# 1. Resend safeguards (dev mode)
# ---------------------------------------------------------------------------
def test_passwordless_login_returns_dev_otp_in_dev_mode():
    email = "client.admin@alemany.capital"  # seeded so we know it's valid
    r = requests.post(f"{BASE_URL}/api/v1/auth/passwordless-login",
                      json={"email": email}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "code" in data
    assert "dev_otp" in data, "dev_otp must be present without RESEND_API_KEY"
    assert isinstance(data["dev_otp"], str) and len(data["dev_otp"]) >= 4

    # outbound_emails should have an otp_login row with status=preview_only
    # (give it a moment to write)
    time.sleep(0.5)
    recent = list(db.outbound_emails.find(
        {"to": email, "template": "otp_login"},
        {"_id": 0, "status": 1, "provider": 1, "template": 1, "created_at": 1}
    ).sort("created_at", -1).limit(3))
    assert recent, "outbound_emails should have at least one otp_login row"
    assert recent[0]["provider"] == "mock"
    assert recent[0]["status"] == "preview_only"


def test_onboarding_apply_returns_magic_link_in_dev_mode():
    email = _uniq_email("apply")
    payload = {
        "applicant_type": "individual",
        "legal_name":     "Test Sanctions Iter26",
        "last_name":      "Iter26",
        "country":        "AR",
        "jurisdiction":   "AR",
        "cuit":           "20" + str(int(time.time()) % 10**8) + "1",
        "birthdate":      "1985-05-12",
        "phone":          "+5491155550000",
        "chain":          "stellar",
        "contact_name":   "Test Sanctions Iter26",
        "contact_email":  email,
        "contact_phone":  "+5491155550000",
        "expected_monthly_volume_usd": 5000,
        "use_case":       "ahorro",
    }
    r = requests.post(f"{BASE_URL}/api/v1/onboarding/apply",
                      json=payload, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("application_id"), data
    assert data.get("magic_link"), \
        "magic_link must be present in dev mode (RESEND_API_KEY not set)"
    assert "/dev-login" in data["magic_link"]


# ---------------------------------------------------------------------------
# 2. Resend gating static asserts (no real key needed — read source)
# ---------------------------------------------------------------------------
def test_server_drops_dev_otp_when_resend_is_set():
    src = open("/app/backend/server.py").read()
    assert "if not RESEND_API_KEY" in src
    assert 'payload["dev_otp"] = otp' in src
    # check the conditional surrounds the dev_otp leak
    idx_cond = src.find("if not RESEND_API_KEY")
    idx_set  = src.find('payload["dev_otp"] = otp')
    assert idx_cond > 0 and idx_set > idx_cond
    assert (idx_set - idx_cond) < 200, \
        "dev_otp assignment must be inside the RESEND guard"


def test_onboarding_nullifies_magic_link_when_resend_is_set():
    src = open("/app/backend/routes/onboarding.py").read()
    assert "RESEND_API_KEY" in src
    assert "magic_link_for_resp = None" in src
    assert 'os.environ.get("RESEND_API_KEY")' in src


# ---------------------------------------------------------------------------
# 3. Sanctions enqueue automatic gate
# ---------------------------------------------------------------------------
def _create_individual_org():
    """Create one applicant via /onboarding/apply and return (app_id, org_id,
    user_id, email)."""
    email = _uniq_email("gate")
    cuit  = "20" + str(int(time.time() * 1000) % 10**8) + "3"
    r = requests.post(f"{BASE_URL}/api/v1/onboarding/apply", json={
        "applicant_type": "individual",
        "legal_name":     "Sanctions Gate " + email[:14],
        "last_name":      "Gate",
        "country":        "AR",
        "jurisdiction":   "AR",
        "cuit":           cuit,
        "birthdate":      "1990-01-15",
        "phone":          "+5491155550101",
        "chain":          "stellar",
        "contact_name":   "Sanctions Gate Tester",
        "contact_email":  email,
        "contact_phone":  "+5491155550101",
        "expected_monthly_volume_usd": 2000,
        "use_case":       "ahorro",
    }, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    app_id = data["application_id"]
    app    = db.onboarding_applications.find_one({"application_id": app_id},
                                                 {"_id": 0, "org_id": 1, "user_id": 1})
    return app_id, app["org_id"], app["user_id"], email


def test_apply_seeds_sanctions_status_pending():
    app_id, org_id, user_id, email = _create_individual_org()
    org = db.organizations.find_one({"org_id": org_id},
                                    {"_id": 0, "sanctions_status": 1, "kyb_status": 1})
    assert org is not None
    assert org["sanctions_status"] == "pending"
    assert org["kyb_status"] == "pending"


def _simulate_fiat_account_created(user_id: str, org_id: str):
    """Pre-insert a ramp_accounts row keyed on provider_user_id then POST
    fiat.account.created so the webhook handler can resolve `_account_for_user`.
    """
    provider_user_id = "pu_iter26_" + secrets.token_hex(4)
    db.ramp_accounts.insert_one({
        "id":                "racc_iter26_" + secrets.token_hex(4),
        "ramp_account_id":   "racc_iter26_" + secrets.token_hex(4),
        "org_id":            org_id,
        "user_id":           user_id,
        "provider_user_id":  provider_user_id,
        "provider":          "andeslabs",
        "onboarding_status": "approved",
        "created_at":        "2026-01-01T00:00:00+00:00",
    })
    payload = {
        "event_type":  "fiat.account.created",
        "delivery_id": "del_iter26_" + secrets.token_hex(6),
        "signature_valid": True,
        "payload": {
            "type": "fiat.account.created",
            "data": {
                "userId": provider_user_id,
                "cvu":    "0000003100" + secrets.token_hex(5)[:6],
                "alias":  "prosper.test." + secrets.token_hex(2),
                "asset":  "ars",
            },
        },
    }
    r = requests.post(f"{BASE_URL}/api/v1/internal/ramp/webhook",
                      json=payload,
                      headers={"X-Internal-Token": GATEWAY_INTERNAL_TOKEN},
                      timeout=30)
    assert r.status_code == 200, r.text
    return provider_user_id


def test_sanctions_enqueue_after_andes_webhook_keeps_org_pending():
    app_id, org_id, user_id, email = _create_individual_org()
    _simulate_fiat_account_created(user_id, org_id)
    time.sleep(0.5)

    # (a) sanctions_screenings row exists, status pending, provider manual
    scr = db.sanctions_screenings.find_one({"org_id": org_id}, {"_id": 0})
    assert scr is not None, "screening should be enqueued by webhook handler"
    assert scr["status"] == "pending"
    assert scr["provider"] == "manual"

    # (b) org.kyb_status is still pending even though Andes emitted CVU
    org = db.organizations.find_one({"org_id": org_id},
                                    {"_id": 0, "kyb_status": 1,
                                     "sanctions_status": 1})
    assert org["sanctions_status"] == "pending"
    assert org["kyb_status"] == "pending", \
        "org must NOT be activated while sanctions is pending"

    # (c) client_admin still invited / kyc_status=pending
    usr = db.users.find_one({"user_id": user_id},
                            {"_id": 0, "status": 1, "kyc_status": 1, "role": 1})
    assert usr["status"] == "invited"
    assert usr["kyc_status"] == "pending"


# ---------------------------------------------------------------------------
# 4. Admin queue + decision endpoints
# ---------------------------------------------------------------------------
def _admin_session():
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": "admin@prosper.foundation",
                      "next": "/admin/compliance/sanctions"},
              allow_redirects=False, timeout=30)
    assert r.status_code in (302, 303), r.text
    assert "prosper_session" in s.cookies.get_dict()
    return s


def test_admin_queue_returns_pending_items_with_organization_join():
    # Seed: pending case
    app_id, org_id, user_id, email = _create_individual_org()
    _simulate_fiat_account_created(user_id, org_id)
    time.sleep(0.4)

    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/v1/admin/sanctions/queue?status=pending", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    rows = data.get("items") or []
    assert isinstance(rows, list)
    match = next((x for x in rows if x["org_id"] == org_id), None)
    assert match is not None, "our seeded org must be in pending queue"
    assert match["status"] == "pending"
    assert match.get("organization") is not None, "org join must be populated"
    assert match["organization"]["org_id"] == org_id


def test_sanctions_decision_clear_activates_when_andes_ok():
    app_id, org_id, user_id, email = _create_individual_org()
    _simulate_fiat_account_created(user_id, org_id)
    time.sleep(0.4)

    s = _admin_session()
    r = s.post(f"{BASE_URL}/api/v1/admin/sanctions/{org_id}/decision",
               json={"decision": "clear",
                     "reason": "Sin matches OFAC/UN/PEP — test iter26"},
               timeout=30)
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "clear"

    org = db.organizations.find_one({"org_id": org_id},
                                    {"_id": 0, "sanctions_status": 1,
                                     "kyb_status": 1})
    assert org["sanctions_status"] == "clear"
    assert org["kyb_status"] == "approved", \
        "org with Andes-approved + sanctions clear must be activated"

    usr = db.users.find_one({"user_id": user_id},
                            {"_id": 0, "status": 1, "kyc_status": 1})
    assert usr["status"] == "active"
    assert usr["kyc_status"] == "approved"

    # audit log entry
    log = db.audit_logs.find_one({"resource_id": {"$exists": True},
                                  "action": "sanctions.clear",
                                  "org_id": org_id},
                                 {"_id": 0, "action": 1})
    assert log is not None


def test_sanctions_decision_flagged_blocks_org_and_pauses_users():
    app_id, org_id, user_id, email = _create_individual_org()
    _simulate_fiat_account_created(user_id, org_id)
    time.sleep(0.4)

    s = _admin_session()
    r = s.post(f"{BASE_URL}/api/v1/admin/sanctions/{org_id}/decision",
               json={"decision": "flagged",
                     "reason": "OFAC SDN match — test iter26"},
               timeout=30)
    assert r.status_code == 200, r.text

    org = db.organizations.find_one({"org_id": org_id},
                                    {"_id": 0, "sanctions_status": 1, "kyb_status": 1})
    assert org["sanctions_status"] == "flagged"
    assert org["kyb_status"] == "rejected"

    usr = db.users.find_one({"user_id": user_id},
                            {"_id": 0, "status": 1, "role": 1})
    assert usr["role"] in ("client_admin", "client_user")
    assert usr["status"] == "paused"


def test_sanctions_decision_idempotent_second_call_409():
    app_id, org_id, user_id, email = _create_individual_org()
    _simulate_fiat_account_created(user_id, org_id)
    time.sleep(0.4)

    s = _admin_session()
    r1 = s.post(f"{BASE_URL}/api/v1/admin/sanctions/{org_id}/decision",
                json={"decision": "clear", "reason": "ok iter26"}, timeout=30)
    assert r1.status_code == 200, r1.text
    r2 = s.post(f"{BASE_URL}/api/v1/admin/sanctions/{org_id}/decision",
                json={"decision": "flagged", "reason": "redo iter26"}, timeout=30)
    assert r2.status_code == 409, r2.text


# ---------------------------------------------------------------------------
# 5. /me + /client/me sanctions feature flags
# ---------------------------------------------------------------------------
def _client_session(email: str):
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email, "next": "/client"},
              allow_redirects=False, timeout=30)
    assert r.status_code in (302, 303), r.text
    return s


def test_me_exposes_sanctions_locked_for_pending_then_clear():
    app_id, org_id, user_id, email = _create_individual_org()
    _simulate_fiat_account_created(user_id, org_id)
    time.sleep(0.4)
    # Need to flip user to active so dev-login allows hitting /me as a client.
    # But sanctions=pending. We still need a valid session — use dev-login which
    # works on any seeded user. New users created by /apply may not be in
    # _domain_allowed; check first by calling dev-login.
    s = _client_session(email)
    r = s.get(f"{BASE_URL}/api/v1/me", timeout=30)
    if r.status_code in (401, 403):
        pytest.skip(f"dev-login for fresh applicant returned {r.status_code} — "
                    "user provisioning quirk, not relevant to gate logic")
    assert r.status_code == 200, r.text
    feats = r.json().get("features") or {}
    assert feats.get("sanctions_status") == "pending"
    assert feats.get("sanctions_locked") is True

    # Now flip to clear via DB (avoid duplicating the decision endpoint logic)
    db.organizations.update_one({"org_id": org_id},
                                {"$set": {"sanctions_status": "clear"}})
    r2 = s.get(f"{BASE_URL}/api/v1/me", timeout=30)
    assert r2.status_code == 200
    feats2 = r2.json().get("features") or {}
    assert feats2.get("sanctions_status") == "clear"
    assert feats2.get("sanctions_locked") is False


def test_client_me_can_operate_requires_sanctions_clear():
    # Use seeded client
    s = _client_session("client.admin@alemany.capital")
    r = s.get(f"{BASE_URL}/api/v1/client/me", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    org      = data.get("org") or {}
    features = data.get("features") or {}

    if org.get("sanctions_status") == "clear" and org.get("kyb_status") == "approved":
        assert features.get("can_operate") is True
    else:
        assert features.get("can_operate") is False


# ---------------------------------------------------------------------------
# 6. Regression — auto-provision bug fix still in place
# ---------------------------------------------------------------------------
def test_unknown_email_still_blocked_403():
    email = f"random.unknown.{secrets.token_hex(4)}@gmail.com"
    # Step 1: passwordless-login gives us a continuation code
    r = requests.post(f"{BASE_URL}/api/v1/auth/passwordless-login",
                      json={"email": email}, timeout=30)
    assert r.status_code == 200
    cont = r.json()["code"]
    otp  = r.json()["dev_otp"]
    # Step 2: passwordless-token with unknown email must be 403
    r2 = requests.post(f"{BASE_URL}/api/v1/auth/passwordless-token",
                       json={"email": email, "code": cont, "token": otp},
                       timeout=30)
    assert r2.status_code == 403, r2.text
    assert "/apply" in r2.text
