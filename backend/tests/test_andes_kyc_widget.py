"""Phase 22+ — AiPrise KYC neutralization for personal orgs + Andes
activation parity tests.

Coverage:
1. AiPrise simulator /onboarding/apply/simulate with sim_kyc_* refuses
   with 400 deprecated message (NOT a 500, NOT activates anything).
2. on_identity_approved sets the audit fields (kyc_decision,
   kyc_decided_at, kyc_raw) that AiPrise used to set, so admin readers
   keep working.
3. Client widget endpoint /api/v1/client/me/andes-kyc-docs:
   - returns 401 unauthenticated
   - returns 409 individual_only for business orgs
4. Admin retry-with-docs endpoint exists and gates on auth.
"""
import os
import secrets
import time
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL",
                          "http://localhost:8001").rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME   = os.environ["DB_NAME"]

mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]


def _admin_session():
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": "admin@prosper.foundation", "next": "/admin"},
              allow_redirects=False, timeout=30)
    assert r.status_code in (302, 303), r.text
    return s


def _client_session(email):
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email, "next": "/client"},
              allow_redirects=False, timeout=30)
    assert r.status_code in (302, 303), r.text
    return s


# ---------- Test 1: simulator path is dead for personal ----------
def test_simulator_sim_kyc_rejects_with_400_for_personal():
    """/onboarding/apply/simulate with a sim_kyc_* session must refuse
    with 400 and a clear deprecation message. NO activation runs."""
    r = requests.post(f"{BASE_URL}/api/v1/onboarding/apply/simulate",
                      json={"session_id": "sim_kyc_deadbeefdeadbeef",
                            "decision": "approved"},
                      timeout=15)
    assert r.status_code == 400, r.text
    body = r.json()
    msg = body.get("detail") or body.get("message") or str(body)
    assert "deprecated" in msg.lower() or "andes" in msg.lower(), msg


# ---------- Test 2: on_identity_approved sets audit fields ----------
def test_on_identity_approved_sets_users_kyc_audit_fields():
    """When Andes activates an individual, users.kyc_decision /
    kyc_decided_at / kyc_raw must be populated (parity with old AiPrise
    path) so admin tools reading those fields keep working."""
    import asyncio
    import sys
    sys.path.insert(0, "/app/backend")
    from services.activation import on_identity_approved

    org_id = f"org_test_{secrets.token_hex(4)}"
    user_id = f"usr_test_{secrets.token_hex(4)}"

    db.organizations.insert_one({
        "org_id": org_id, "type": "personal", "legal_name": "Test Indiv",
        "kyb_status": "pending", "sanctions_status": "clear",
        "travel_rule_status": "clear",
        "primary_email": f"test.{secrets.token_hex(4)}@example.com",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_deleted": False,
    })
    db.users.insert_one({
        "user_id": user_id, "org_id": org_id, "role": "client_admin",
        "email": f"test.{user_id}@example.com",
        "status": "invited", "kyc_status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_deleted": False,
    })

    try:
        result = asyncio.run(on_identity_approved(
            org_id=org_id,
            andes_user_id="andes_user_test_xyz",
            cvu="0001234567890123456789",
            alias="test.alias",
            fiat_account_id="fa_test_abc",
            source="test_parity",
        ))
        # The audit fields must be set REGARDLESS of full activation.
        # (sanctions enqueue may flip sanctions_status mid-call; we only
        # care that kyc_decision / kyc_decided_at / kyc_raw land.)
        assert result.get("ok") is True, result
        user_after = db.users.find_one({"user_id": user_id})
        assert user_after["kyc_status"] == "approved"
        assert user_after["kyc_decision"] == "approved"
        assert user_after["kyc_decided_at"]
        assert user_after["kyc_raw"]["source"] == "andes"
        assert user_after["kyc_raw"]["andes_user_id"] == "andes_user_test_xyz"
        assert user_after["kyc_raw"]["fiat_account_id"] == "fa_test_abc"
    finally:
        db.organizations.delete_one({"org_id": org_id})
        db.users.delete_one({"user_id": user_id})


# ---------- Test 3: client widget gates ----------
def test_client_widget_unauthenticated_401():
    r = requests.post(
        f"{BASE_URL}/api/v1/client/me/andes-kyc-docs",
        files={"face": ("f.jpg", b"x"*2048, "image/jpeg"),
               "id_front": ("a.jpg", b"x"*2048, "image/jpeg"),
               "id_back": ("b.jpg", b"x"*2048, "image/jpeg")},
        timeout=15)
    assert r.status_code in (401, 403), r.text


def test_client_widget_business_gets_409():
    """A business org admin hitting the widget gets 409 individual_only.

    Seeds a synthetic business org + client_admin user (no AiPrise/Andes
    side-effects, just DB rows that match the gate logic). Tears down
    on completion.
    """
    org_id = f"org_biz_test_{secrets.token_hex(4)}"
    user_id = f"usr_biz_test_{secrets.token_hex(4)}"
    email = f"biz.{secrets.token_hex(4)}@example.com"
    iso = datetime.now(timezone.utc).isoformat()
    db.organizations.insert_one({
        "org_id": org_id, "type": "business",
        "legal_name": "Test Business SA", "country": "AR",
        "kyb_status": "pending", "primary_email": email,
        "created_at": iso, "is_deleted": False,
    })
    db.users.insert_one({
        "user_id": user_id, "org_id": org_id, "role": "client_admin",
        "email": email, "status": "active", "kyc_status": "approved",
        "created_at": iso, "is_deleted": False,
    })
    try:
        s2 = _client_session(email)
        fake_files = {
            "face": ("f.jpg", b"\xff\xd8\xff" + b"x"*2048, "image/jpeg"),
            "id_front": ("a.jpg", b"\xff\xd8\xff" + b"x"*2048, "image/jpeg"),
            "id_back": ("b.jpg", b"\xff\xd8\xff" + b"x"*2048, "image/jpeg"),
        }
        r = s2.post(f"{BASE_URL}/api/v1/client/me/andes-kyc-docs",
                    files=fake_files, timeout=15)
        assert r.status_code == 409, r.text
        body = r.json()
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
        msg = str(detail).lower()
        assert "individual" in msg or "personas" in msg or "business" in msg, msg
    finally:
        db.organizations.delete_one({"org_id": org_id})
        db.users.delete_one({"user_id": user_id})


# ---------- Test 4: admin endpoint exists ----------
def test_admin_retry_with_docs_route_exists():
    r = requests.post(
        f"{BASE_URL}/api/v1/ramp/accounts/foo/retry-with-docs",
        timeout=15)
    assert r.status_code in (401, 403, 422), r.text
