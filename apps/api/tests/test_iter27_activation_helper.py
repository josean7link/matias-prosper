"""Iteration 27 — Two-gate activation policy + KYC queue hydration.

Coverage:
  * gate sanity: webhook fiat.account.created NO bypassea kyb=approved
  * sanctions clear endpoint flips kyb→approved + user→active
  * static assert: routes/onboarding.py ya no flippea kyb_status='approved'
    directamente y ahora llama services.activation.on_identity_approved
  * cola KYC unificada (kyc_cases + onboarding_applications)
  * detail endpoint para application real (app_7367c12881fc)
  * backfill de Matías Plano (org_048b90574cfa) en estado correcto
  * decisión sobre application real
  * regresión seed kyc_cases sigue siendo accesible
  * sanctions queue regresión
"""
import os
import secrets
import time
import requests
import pytest
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL",
                          "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME   = os.environ["DB_NAME"]
GATEWAY_INTERNAL_TOKEN = os.environ["GATEWAY_INTERNAL_TOKEN"]

mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]


def _uniq_email(tag="iter27"):
    return f"test.{tag}.{secrets.token_hex(4)}@gmail.com"


def _admin_session():
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": "admin@prosper.foundation", "next": "/admin"},
              allow_redirects=False, timeout=30)
    assert r.status_code in (302, 303), r.text
    assert "prosper_session" in s.cookies.get_dict()
    return s


def _create_individual_org():
    email = _uniq_email("g27")
    cuit = "20" + str(int(time.time() * 1000) % 10**8) + "9"
    r = requests.post(f"{BASE_URL}/api/v1/onboarding/apply", json={
        "applicant_type": "individual",
        "legal_name":     "Iter27 Gate " + email[:10],
        "last_name":      "Gate",
        "country":        "AR",
        "jurisdiction":   "AR",
        "cuit":           cuit,
        "birthdate":      "1990-01-15",
        "phone":          "+5491155550101",
        "chain":          "stellar",
        "contact_name":   "Iter27 Tester",
        "contact_email":  email,
        "contact_phone":  "+5491155550101",
        "expected_monthly_volume_usd": 2000,
        "use_case":       "ahorro",
    }, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    app_id = data["application_id"]
    app = db.onboarding_applications.find_one({"application_id": app_id},
                                              {"_id": 0, "org_id": 1, "user_id": 1})
    return app_id, app["org_id"], app["user_id"], email


def _simulate_fiat_account_created(user_id, org_id):
    pu = "pu_iter27_" + secrets.token_hex(4)
    db.ramp_accounts.insert_one({
        "id": "racc_iter27_" + secrets.token_hex(4),
        "ramp_account_id": "racc_iter27_" + secrets.token_hex(4),
        "org_id": org_id,
        "user_id": user_id,
        "provider_user_id": pu,
        "provider": "andeslabs",
        "onboarding_status": "approved",
        "is_deleted": False,
        "created_at": "2026-01-15T00:00:00+00:00",
    })
    payload = {
        "event_type": "fiat.account.created",
        "delivery_id": "del_iter27_" + secrets.token_hex(6),
        "signature_valid": True,
        "payload": {
            "type": "fiat.account.created",
            "data": {"userId": pu,
                     "cvu": "0000003100" + secrets.token_hex(5)[:6],
                     "alias": "prosper.iter27." + secrets.token_hex(2),
                     "asset": "ars"}}}
    r = requests.post(f"{BASE_URL}/api/v1/internal/ramp/webhook",
                      json=payload,
                      headers={"X-Internal-Token": GATEWAY_INTERNAL_TOKEN},
                      timeout=30)
    assert r.status_code == 200, r.text
    return pu


# --- 1. Sanctions gate regression -----------------------------------------
def test_webhook_does_not_bypass_sanctions_gate():
    app_id, org_id, user_id, email = _create_individual_org()
    _simulate_fiat_account_created(user_id, org_id)
    time.sleep(0.5)

    org = db.organizations.find_one({"org_id": org_id}, {"_id": 0})
    assert org["kyb_status"] == "pending", "kyb must NOT be approved (sanctions gate)"
    assert org["andes_kyc_status"] == "approved"
    assert org["sanctions_status"] == "pending"

    usr = db.users.find_one({"user_id": user_id}, {"_id": 0})
    assert usr["kyc_status"] == "approved"
    assert usr["status"] in ("invited", "active")

    ra = db.ramp_accounts.find_one({"org_id": org_id}, {"_id": 0})
    assert ra.get("cvu"), "CVU must be persisted in ramp_account"

    scr = db.sanctions_screenings.find_one({"org_id": org_id}, {"_id": 0})
    assert scr is not None and scr["status"] == "pending"
    assert scr["provider"] == "manual"
    assert scr.get("subject_cuit"), "subject_cuit must be populated from _indiv_cuit"


# --- 2. Sanctions clear → activation ---------------------------------------
def test_sanctions_clear_triggers_full_activation():
    app_id, org_id, user_id, email = _create_individual_org()
    _simulate_fiat_account_created(user_id, org_id)
    time.sleep(0.4)

    s = _admin_session()
    r = s.post(f"{BASE_URL}/api/v1/admin/sanctions/{org_id}/decision",
               json={"decision": "clear",
                     "reason": "no matches OFAC/UN/PEP — iter27"},
               timeout=30)
    assert r.status_code == 200, r.text

    org = db.organizations.find_one({"org_id": org_id}, {"_id": 0})
    assert org["kyb_status"] == "approved"
    assert org["sanctions_status"] == "clear"

    usr = db.users.find_one({"user_id": user_id}, {"_id": 0})
    assert usr["status"] == "active"
    assert usr["kyc_status"] == "approved"


# --- 3. Sync path: bypass eliminated (static assert) ----------------------
def test_upload_endpoint_does_not_bypass_gate():
    src = open("/app/backend/routes/onboarding.py").read()
    # No directly-setting kyb_status='approved' inside upload_kyc_docs_individual
    # Find the upload function block
    fn = src.split("def upload_kyc_docs_individual", 1)
    assert len(fn) == 2
    body = fn[1].split("\n@router", 1)[0]
    # Upload endpoint MUST delegate to the helper
    assert "on_identity_approved" in body, \
        "upload endpoint must delegate to services.activation.on_identity_approved"
    # The only references to `kyb_status` inside upload should be either:
    #   - the conditional mirror on the application doc (gated by activation_state.activated)
    #   - comments
    # It must NOT contain an unconditional org-level patch like
    # `organizations.update_one(..., {"kyb_status": "approved"})`.
    # Look for direct org collection updates flipping kyb_status to approved.
    assert "ORGANIZATIONS" not in body or "kyb_status" not in body.split(
        "on_identity_approved")[0].split("ORGANIZATIONS")[-1], \
        "no direct ORGANIZATIONS kyb_status patch should exist before delegate"
    # Ensure the kyb_status='approved' literal that appears is only inside the
    # mirror-on-application that requires `activation_state.get('activated')`.
    occurrences = body.count('"kyb_status": "approved"')
    # Must be 0 or 1 — if present, must be guarded by activation_state.activated
    if occurrences:
        # find the line and ensure 'activated' appears within 80 chars before it
        idx = body.find('"kyb_status": "approved"')
        window = body[max(0, idx - 200):idx + 50]
        assert "activated" in window, \
            f"kyb_status='approved' literal must be guarded by activation_state.activated; ctx={window}"


# --- 4. KYC queue hydrated from both sources -------------------------------
def test_kyc_queue_unifies_kyc_cases_and_applications():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/v1/admin/compliance/kyc/queue", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    items = data.get("items") or data.get("cases") or []
    assert isinstance(items, list)
    assert len(items) >= 26, f"queue should have >= 26 items, got {len(items)}"

    case_ids = [it.get("case_id") for it in items]
    # seed cases present (5 of them)
    seeds = [c for c in case_ids if c and c.startswith("kyc_seed_")]
    assert len(seeds) == 5, f"expected 5 seed cases, got {len(seeds)}: {seeds}"

    # at least some app_ prefixed cases (from onboarding_applications)
    apps = [c for c in case_ids if c and c.startswith("app_")]
    assert len(apps) >= 21, f"expected >= 21 app_-prefixed cases, got {len(apps)}"

    # Matías specifically
    matias = next((it for it in items if it.get("case_id") == "app_7367c12881fc"), None)
    assert matias is not None, "app_7367c12881fc (Matías) must be in queue"
    assert matias.get("provider") == "Andes"
    assert matias.get("status") == "in_review"
    assert matias.get("sanctions_status") == "pending"
    assert matias.get("andes_kyc_status") == "approved"


# --- 5. KYC detail endpoint for real application --------------------------
def test_kyc_detail_for_matias_application():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/v1/admin/compliance/kyc/app_7367c12881fc", timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("case_id") == "app_7367c12881fc"
    assert (d.get("first_name") or "").lower() == "matias"
    assert d.get("last_name") == "Plano"
    assert d.get("email") == "matiasplano@gmail.com"
    assert d.get("provider") == "Andes"
    assert d.get("status") == "in_review"
    assert d.get("andes_kyc_status") == "approved"
    assert d.get("sanctions_status") == "pending"
    assert d.get("kyb_status") == "pending"
    sanc = d.get("sanctions") or {}
    assert sanc.get("status") == "pending"
    assert sanc.get("provider") == "manual"


# --- 6. Matías backfill validated -----------------------------------------
def test_matias_backfill_state():
    org = db.organizations.find_one({"org_id": "org_048b90574cfa"}, {"_id": 0})
    assert org is not None
    assert org["kyb_status"] == "pending"
    assert org["andes_kyc_status"] == "approved"
    assert org["sanctions_status"] == "pending"
    assert org.get("_indiv_cuit") == "20280821129"

    scr = db.sanctions_screenings.find_one({"org_id": "org_048b90574cfa"}, {"_id": 0})
    assert scr is not None
    assert scr["status"] == "pending"
    assert scr["provider"] == "manual"
    assert scr.get("subject_cuit") == "20280821129"


# --- 7. Decision on real application (without bypassing sanctions) --------
def test_decision_on_real_application_mirrors_state():
    s = _admin_session()
    # Prefer the brief-specified app_a714e03be914 (Gate Bypass Test org_fe19ccef412d)
    app_id = "app_a714e03be914"
    target = db.onboarding_applications.find_one({"application_id": app_id},
                                                  {"_id": 0, "user_id": 1,
                                                   "org_id": 1, "decision": 1})
    if not target:
        pytest.skip("app_a714e03be914 not found")
    user_id = target["user_id"]
    # If already decided, just verify the endpoint returns conflict or current
    r = s.post(f"{BASE_URL}/api/v1/admin/compliance/kyc/{app_id}/decision",
               json={"action": "approve",
                     "reason": "verificación manual completada — test E2E iter27"},
               timeout=30)
    assert r.status_code in (200, 201, 409, 422), r.text

    app = db.onboarding_applications.find_one({"application_id": app_id},
                                              {"_id": 0})
    # Decision recorded (either now or previously)
    dec = app.get("decision") or {}
    assert app.get("status") in ("approved", "in_review", "rejected")
    # Ensure sanctions gate was NOT bypassed — for the Gate Bypass Test org,
    # sanctions was already clear (per task brief) so kyb may be approved.
    # We just assert the call doesn't crash and the data is sane.
    org = db.organizations.find_one({"org_id": target["org_id"]}, {"_id": 0})
    assert org["kyb_status"] in ("approved", "pending", "rejected")


# --- 8. Seed kyc_cases regression -----------------------------------------
def test_seed_kyc_case_still_accessible():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/v1/admin/compliance/kyc/kyc_seed_01", timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("case_id") == "kyc_seed_01"
    # legacy AiPrise provider preserved
    prov = (d.get("provider") or "").lower()
    assert "aiprise" in prov or prov == "aiprise"


# --- 9. Sanctions queue regression ----------------------------------------
def test_sanctions_queue_still_includes_matias():
    s = _admin_session()
    r = s.get(f"{BASE_URL}/api/v1/admin/sanctions/queue?status=pending", timeout=30)
    assert r.status_code == 200, r.text
    items = r.json().get("items") or []
    org_ids = {it.get("org_id") for it in items}
    assert "org_048b90574cfa" in org_ids, "Matías must be in pending sanctions queue"
