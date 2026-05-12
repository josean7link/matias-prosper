"""Phase 1 — multi-tenancy, role guards, audit log, impersonation, immutability."""
import os
import re
import time
import subprocess
import requests
from pymongo import MongoClient

BASE = os.environ.get("API_BASE", "http://localhost:8001")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME   = os.environ.get("DB_NAME", "prosper_phase0")

LOG_PATH = "/var/log/supervisor/backend.err.log"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _login(email: str) -> str:
    """Run the passwordless OTP flow end-to-end and return the JWT cookie value."""
    r = requests.post(f"{BASE}/api/v1/auth/passwordless-login", json={"email": email}, timeout=5)
    r.raise_for_status()
    cont = r.json()["code"]
    # The OTP is logged to backend stdout (no RESEND key in dev) — read it.
    time.sleep(0.2)
    out = subprocess.run(["tail", "-n", "60", LOG_PATH], capture_output=True, text=True).stdout
    m = re.findall(re.escape(email) + r" -> (\d{4})", out)
    assert m, f"OTP not found in log for {email}: {out[-1000:]}"
    otp = m[-1]
    r2 = requests.post(f"{BASE}/api/v1/auth/passwordless-token",
                       json={"code": cont, "token": otp}, timeout=5)
    r2.raise_for_status()
    # Cookie is httpOnly — pick it from response
    cookie = r2.cookies.get("prosper_session")
    assert cookie, f"no cookie set: {r2.headers}"
    return cookie


def _hdr(token: str, acting_as: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if acting_as:
        h["X-Acting-As-Org"] = acting_as
    return h


# ---------------------------------------------------------------------------
# 1. /me returns user + org + role + permissions + features
# ---------------------------------------------------------------------------
def test_me_endpoint_for_client_admin():
    tok = _login("client.admin@alemany.capital")
    r = requests.get(f"{BASE}/api/v1/me", headers=_hdr(tok), timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "client_admin"
    assert body["is_internal"] is False
    assert body["user"]["email"] == "client.admin@alemany.capital"
    assert body["org"]["org_id"] == "org_seed_alemany"
    assert body["org"]["kyb_status"] == "approved"
    assert "org:read:self" in body["permissions"]
    assert body["features"]["mfa_required"] is True
    assert body["features"]["kyb_locked"] is False  # Alemany is approved


# ---------------------------------------------------------------------------
# 2. test_cross_org_guard — client_user of org A receives 404 on org B's resource
# ---------------------------------------------------------------------------
def test_cross_org_guard_returns_404():
    tok = _login("client.admin@alemany.capital")
    # Try to read Finpact (other org). Same shape applies to /organizations/<id>.
    r = requests.get(f"{BASE}/api/v1/organizations/org_seed_finpact", headers=_hdr(tok), timeout=5)
    assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text[:200]}"

    # List view: client should ONLY see their own org, not the other one
    r2 = requests.get(f"{BASE}/api/v1/organizations", headers=_hdr(tok), timeout=5)
    body = r2.json()
    ids = [o["org_id"] for o in body["items"]]
    assert ids == ["org_seed_alemany"], f"client saw extra orgs: {ids}"


# ---------------------------------------------------------------------------
# 3. test_role_permissions — client_user cannot reach /admin/*
# ---------------------------------------------------------------------------
def test_client_blocked_from_admin_endpoints():
    tok = _login("client.admin@alemany.capital")
    r = requests.get(f"{BASE}/api/v1/admin/dashboard", headers=_hdr(tok), timeout=5)
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# 4. test_audit_log — admin writes are recorded
# ---------------------------------------------------------------------------
def test_admin_action_writes_audit():
    tok = _login("admin@prosper.foundation")
    # Create an organization
    r = requests.post(f"{BASE}/api/v1/organizations",
                      headers={**_hdr(tok), "Content-Type": "application/json"},
                      json={"legal_name": f"Audit Test Co {time.time()}",
                            "commercial_name": "AuditCo",
                            "country": "AR",
                            "type": "fintech",
                            "allowlist_domains": ["audit-test.co"]},
                      timeout=5)
    assert r.status_code == 200, r.text
    org_id = r.json()["org_id"]
    # Verify an audit log entry exists for organization.created
    r2 = requests.get(f"{BASE}/api/v1/audit-logs?limit=20", headers=_hdr(tok), timeout=5)
    items = r2.json()["items"]
    matching = [a for a in items if a["action"] == "organization.created"
                                 and a["resource_id"] == org_id]
    assert matching, f"no audit entry for org {org_id}: {items[:3]}"
    entry = matching[0]
    assert entry["actor_user_id"]  # super_admin's id
    assert entry["resource_type"] == "organization"


# ---------------------------------------------------------------------------
# 5. test_impersonation — super_admin with X-Acting-As-Org sees that org +
#    the action gets logged with `acting_as_org` metadata.
# ---------------------------------------------------------------------------
def test_impersonation_scopes_and_audits():
    tok = _login("admin@prosper.foundation")

    # /me reflects the impersonation
    r = requests.get(f"{BASE}/api/v1/me", headers=_hdr(tok, acting_as="org_seed_alemany"),
                     timeout=5)
    body = r.json()
    assert body["acting_as_org"] == "org_seed_alemany"
    assert body["org"]["org_id"] == "org_seed_alemany"

    # /organizations is now scoped to that single org
    r2 = requests.get(f"{BASE}/api/v1/organizations",
                      headers=_hdr(tok, acting_as="org_seed_alemany"), timeout=5)
    ids = [o["org_id"] for o in r2.json()["items"]]
    assert ids == ["org_seed_alemany"]

    # An admin action under impersonation tags the audit with acting_as_org
    r3 = requests.post(f"{BASE}/api/v1/organizations",
                       headers={**_hdr(tok, acting_as="org_seed_alemany"),
                                "Content-Type": "application/json"},
                       json={"legal_name": f"Impersonation Test {time.time()}",
                             "commercial_name": "ImpCo", "country": "AR",
                             "type": "fintech", "allowlist_domains": ["imp.co"]},
                       timeout=5)
    assert r3.status_code == 200
    org_id = r3.json()["org_id"]

    # Pull the latest audit entry for this resource
    r4 = requests.get(f"{BASE}/api/v1/audit-logs?limit=50", headers=_hdr(tok), timeout=5)
    matched = [a for a in r4.json()["items"]
               if a["resource_id"] == org_id and a["action"] == "organization.created"]
    assert matched, f"no audit for impersonated create: {r4.json()['items'][:3]}"
    audit = matched[0]
    assert audit["metadata"].get("acting_as_org") == "org_seed_alemany"


# ---------------------------------------------------------------------------
# 6. test_audit_immutable — direct Mongo mutation attempts should fail at the
#    helper level + the API rejects PATCH/DELETE.
# ---------------------------------------------------------------------------
def test_audit_is_immutable_via_api():
    tok = _login("admin@prosper.foundation")
    items = requests.get(f"{BASE}/api/v1/audit-logs?limit=1", headers=_hdr(tok), timeout=5)\
              .json()["items"]
    assert items, "audit log empty — earlier tests should have populated it"
    aid = items[0]["audit_id"]
    r1 = requests.patch(f"{BASE}/api/v1/audit-logs/{aid}", headers=_hdr(tok),
                        json={"action": "tampered"}, timeout=5)
    assert r1.status_code == 405
    r2 = requests.delete(f"{BASE}/api/v1/audit-logs/{aid}", headers=_hdr(tok), timeout=5)
    assert r2.status_code == 405


def test_audit_helper_raises_on_mutation_calls():
    """The Mongo collection itself is technically mutable — the codebase enforces
    immutability by routing all writes through the `write_audit` helper, and the
    public API blocks PATCH/DELETE. This in-process test asserts the explicit
    helpers raise."""
    import asyncio
    from db import audit_update_blocked, audit_delete_blocked, AuditMutationError

    async def run():
        for fn in (audit_update_blocked, audit_delete_blocked):
            try:
                await fn()
            except AuditMutationError:
                return True
            return False
        return False

    assert asyncio.run(run()) is True


# ---------------------------------------------------------------------------
# 7. Indexes exist
# ---------------------------------------------------------------------------
def test_required_indexes_present():
    client = MongoClient(MONGO_URL)
    dbh = client[DB_NAME]
    # email unique
    info = dbh["users"].index_information()
    assert any("email" in [f[0] for f in v.get("key", [])] and v.get("unique")
               for v in info.values()), info
    # prosper_tx_id unique
    info2 = dbh["transactions"].index_information()
    assert any("prosper_tx_id" in [f[0] for f in v.get("key", [])] and v.get("unique")
               for v in info2.values()), info2
    # org_id index on users
    info3 = dbh["users"].index_information()
    assert any(any(f[0] == "org_id" for f in v.get("key", [])) for v in info3.values()), info3
