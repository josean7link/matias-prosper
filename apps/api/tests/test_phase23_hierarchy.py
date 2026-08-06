"""Phase 23 — N1/N2 sub-client hierarchy security DoD.

The PRD's two non-negotiable rules:

    Rule 1: An **N2** sub-client MUST NOT be able to create further
            sub-clients. The backend rejects the create call with **403**,
            regardless of whether the frontend hides the button.

    Rule 2: An **N1** parent CAN read its N2 children's summary balances,
            but MUST NOT be able to operate on the N2's money (cash-in /
            invest / withdraw / international off-ramp / transfer). The
            ownership boundary is enforced server-side.

These tests exercise the live endpoints over HTTP — no in-process imports —
so they prove the end-to-end behavior a real attacker would see.
"""
from __future__ import annotations

import os
import secrets
import uuid
import pytest
import requests

# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com",
).rstrip("/")

SUPER_EMAIL = "admin@prosper.foundation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dev_login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email}, allow_redirects=False, timeout=15)
    assert r.status_code in (200, 302, 303, 307), \
        f"dev-login {email} -> {r.status_code} {r.text[:300]}"
    return s


def _mongo():
    """Direct Mongo access (motor sync wrapper) for test fixtures only."""
    from pymongo import MongoClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli[os.environ["DB_NAME"]]


# ---------------------------------------------------------------------------
# Fixture — create an N1 org + its client_admin
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def n1_setup():
    """Bootstrap a fresh N1 client_admin and Org seeded via super_admin.

    Returns dict with org_id, email, session for the N1.
    """
    tag = secrets.token_hex(4)
    n1_email = f"n1.admin+{tag}@phase23test.io"
    n1_org_id = f"org_phase23n1_{tag}"

    db = _mongo()
    iso_now = "2026-02-10T12:00:00Z"
    # N1 org — level=1, no parent
    db.organizations.insert_one({
        "org_id":            n1_org_id,
        "legal_name":        f"Phase23 N1 Ltd {tag}",
        "commercial_name":   f"Phase23-N1-{tag}",
        "country":           "AR",
        "tax_id":            f"30-{tag}-9",
        "type":              "fintech",
        "kyb_status":        "approved",
        "risk_score":        10,
        "risk_profile":      "low",
        "allowlist_domains": ["phase23test.io"],
        "caps":              {},
        "parent_org_id":     None,
        "level":             1,
        "env":               "sandbox",
        "tier":              "T2",
        "created_at":        iso_now,
        "updated_at":        iso_now,
        "is_deleted":        False,
    })
    # N1 client_admin
    db.users.insert_one({
        "user_id":      f"usr_phase23n1_{tag}",
        "email":        n1_email,
        "full_name":    f"N1 admin {tag}",
        "role":         "client_admin",
        "org_id":       n1_org_id,
        "status":       "active",
        "kyc_status":   "pending",
        "mfa_enabled":  False,
        "created_at":   iso_now,
        "updated_at":   iso_now,
        "is_deleted":   False,
    })

    yield {
        "org_id":  n1_org_id,
        "email":   n1_email,
        "session": _dev_login(n1_email),
        "tag":     tag,
    }

    # Cleanup — drop the artifacts we created
    db.organizations.delete_many({"$or": [
        {"org_id": n1_org_id},
        {"parent_org_id": n1_org_id},
    ]})
    db.users.delete_many({"email": {"$regex": f"\\+{tag}.*@phase23test\\.io$"}})
    db.users.delete_many({"org_id": n1_org_id})
    db.audit_logs.delete_many({"metadata.parent_org_id": n1_org_id})


# ---------------------------------------------------------------------------
# Setup — N1 creates an N2 via the public endpoint
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def n2_setup(n1_setup):
    """N1's client_admin calls POST /clients/{n1_org}/subclients → creates N2."""
    s    = n1_setup["session"]
    tag2 = secrets.token_hex(4)
    n2_email = f"n2.admin+{n1_setup['tag']}{tag2}@phase23test.io"

    r = s.post(f"{BASE_URL}/api/v1/clients/{n1_setup['org_id']}/subclients",
               json={
                   "legal_name":      f"Phase23 N2 Ltd {tag2}",
                   "commercial_name": f"Phase23-N2-{tag2}",
                   "country":         "AR",
                   "contact_email":   n2_email,
                   "contact_full_name": f"N2 owner {tag2}",
                   "org_type":        "fintech",
               }, timeout=20)
    assert r.status_code == 200, f"create N2 failed: {r.status_code} {r.text[:300]}"
    body = r.json()

    # Mark N2 as approved KYB + activate the invited user so they can log in.
    db = _mongo()
    db.organizations.update_one({"org_id": body["org_id"]},
                                 {"$set": {"kyb_status": "approved"}})
    db.users.update_one({"email": n2_email},
                          {"$set": {"status": "active"}})

    return {
        "n2_org_id":  body["org_id"],
        "n2_email":   n2_email,
        "n2_session": _dev_login(n2_email),
    }


# ===========================================================================
# Hierarchy meta — sanity checks
# ===========================================================================
def test_n2_is_linked_to_n1(n1_setup, n2_setup):
    """The created N2 has parent_org_id pointing to N1 and level=2."""
    db = _mongo()
    n2 = db.organizations.find_one({"org_id": n2_setup["n2_org_id"]},
                                     {"_id": 0})
    assert n2 is not None
    assert n2["parent_org_id"] == n1_setup["org_id"], \
        f"N2.parent_org_id should be N1 ({n1_setup['org_id']}); got {n2.get('parent_org_id')}"
    assert n2["level"] == 2, f"N2.level should be 2; got {n2.get('level')}"


# ===========================================================================
# RULE 1: N2 cannot create further sub-clients (DEPTH ENFORCEMENT)
# ===========================================================================
def test_rule1_n2_cannot_create_subclient_under_itself(n1_setup, n2_setup):
    """An N2 client_admin tries to create an N3 under their own org.

    Backend MUST reject with 403 (max depth reached). This proves the
    server enforces the rule even if the frontend forgot to hide the button.
    """
    s = n2_setup["n2_session"]
    r = s.post(f"{BASE_URL}/api/v1/clients/{n2_setup['n2_org_id']}/subclients",
               json={
                   "legal_name":      "Should-Not-Be-Created N3",
                   "commercial_name": "n3-attempt-" + secrets.token_hex(3),
                   "country":         "AR",
                   "contact_email":   f"n3.attempt+{secrets.token_hex(3)}@phase23test.io",
                   "contact_full_name": "N3 attacker",
                   "org_type":        "fintech",
               }, timeout=15)
    assert r.status_code == 403, \
        f"N2 must be denied with 403; got {r.status_code} {r.text[:300]}"
    detail = (r.json().get("detail") or "").lower()
    assert "maximum hierarchy depth" in detail or "depth" in detail, \
        f"403 reason should mention depth/hierarchy; got: {detail}"


def test_rule1_n2_cannot_create_subclient_under_n1(n1_setup, n2_setup):
    """An N2 client_admin tries to call the create endpoint passing the N1
    org_id in the URL. Backend MUST reject with 403 (cross-tenant blocked)
    BEFORE checking depth — the actor's JWT scopes them to their own org."""
    s = n2_setup["n2_session"]
    r = s.post(f"{BASE_URL}/api/v1/clients/{n1_setup['org_id']}/subclients",
               json={
                   "legal_name":      "Should-Not-Be-Created Sibling",
                   "commercial_name": "sibling-attempt-" + secrets.token_hex(3),
                   "country":         "AR",
                   "contact_email":   f"sibling+{secrets.token_hex(3)}@phase23test.io",
                   "contact_full_name": "Sibling attacker",
                   "org_type":        "fintech",
               }, timeout=15)
    assert r.status_code == 403, \
        f"N2 trying N1's URL must get 403; got {r.status_code} {r.text[:300]}"
    detail = (r.json().get("detail") or "").lower()
    assert "cross-tenant" in detail or "own org" in detail, \
        f"403 reason should mention cross-tenant; got: {detail}"


# ===========================================================================
# RULE 2: N1 reads N2 summary (OK), cannot operate on N2 money
# ===========================================================================
def test_rule2a_n1_can_read_n2_summary(n1_setup, n2_setup):
    """N1 lists its N2s via /api/v1/clients/{n1_org}/subclients and sees
    the freshly-created N2 with balances + position counts.

    READ on the SUMMARY is allowed (this is the legitimate use case for
    /client/mis-clientes)."""
    s = n1_setup["session"]
    r = s.get(f"{BASE_URL}/api/v1/clients/{n1_setup['org_id']}/subclients",
              timeout=15)
    assert r.status_code == 200, f"list subclients failed: {r.status_code} {r.text[:300]}"
    rows = r.json()
    assert isinstance(rows, list), "subclients listing must be a list"
    ids = [row.get("org_id") for row in rows]
    assert n2_setup["n2_org_id"] in ids, \
        f"N1 must see its own N2 in the list; got: {ids}"
    # The summary row must expose balance + position fields (read-only view).
    n2_row = next(r for r in rows if r["org_id"] == n2_setup["n2_org_id"])
    assert "arsa_balance"   in n2_row
    assert "position_count" in n2_row
    assert "total_aum_usd"  in n2_row


def test_rule2b_n1_cannot_create_ramp_account_for_n2(n1_setup, n2_setup):
    """N1's client_admin attempts to create an Andes ramp account under the
    N2 org by passing ?org_id=<N2_org>. Backend MUST reject with 403
    (ownership violation) — _resolve_org_scope blocks non-backoffice users
    from operating on other orgs."""
    s = n1_setup["session"]
    r = s.post(f"{BASE_URL}/api/v1/ramp/accounts",
               params={"org_id": n2_setup["n2_org_id"]},
               json={"end_customer_id": n2_setup["n2_org_id"],
                       "display_name": "Hijack attempt"},
               timeout=20)
    assert r.status_code == 403, \
        f"N1 cross-org ramp.create must be 403; got {r.status_code} {r.text[:300]}"
    detail = (r.json().get("detail") or "").lower()
    assert "ownership" in detail or "cannot operate" in detail, \
        f"403 reason should mention ownership; got: {detail}"


def test_rule2c_n1_cannot_withdraw_from_n2(n1_setup, n2_setup):
    """N1 tries to call POST /ramp/accounts/{n2_ecid}/withdraw?org_id=N2 →
    403. Cash-out on N2's account is denied by ownership boundary."""
    s = n1_setup["session"]
    r = s.post(f"{BASE_URL}/api/v1/ramp/accounts/{n2_setup['n2_org_id']}/withdraw",
               params={"org_id": n2_setup["n2_org_id"]},
               headers={"Idempotency-Key": str(uuid.uuid4())},
               json={"amount": "100", "to_cvu": "0000003735177792176817"},
               timeout=20)
    assert r.status_code == 403, \
        f"N1 cross-org withdraw must be 403; got {r.status_code} {r.text[:300]}"
    detail = (r.json().get("detail") or "").lower()
    assert "ownership" in detail or "cannot operate" in detail, \
        f"403 reason should mention ownership; got: {detail}"


def test_rule2d_n1_cannot_read_n2_balances(n1_setup, n2_setup):
    """Even READ on the raw balances endpoint (different from the summary
    /clients/{id}/subclients) is denied when N1 tries to scope to N2 via
    ?org_id. The legit read path is the subclients summary; the raw
    per-account balance feed is per-tenant."""
    s = n1_setup["session"]
    r = s.get(f"{BASE_URL}/api/v1/ramp/accounts/{n2_setup['n2_org_id']}/balances",
              params={"org_id": n2_setup["n2_org_id"]}, timeout=20)
    assert r.status_code == 403, \
        f"N1 cross-org balances read must be 403; got {r.status_code} {r.text[:300]}"


def test_rule2e_n1_cannot_invest_on_behalf_of_n2(n1_setup, n2_setup):
    """The /client/positions (invest) endpoint scopes to actor.org_id —
    there's no way to pass an org_id override. The action falls back to the
    N1's own org, but to prove the boundary is hard we also check that
    after the call (which may fail for missing KYB/balance), the N2's
    position count stays at 0 (N1 cannot inject positions into N2)."""
    s = n1_setup["session"]
    # Either rejects (KYB/balance/etc) or accepts under N1 — either way,
    # the N2 must not gain a position from this call.
    s.post(f"{BASE_URL}/api/v1/client/positions",
           json={"product_id": "usdc_end", "amount_usdc": 10},
           timeout=15)
    db = _mongo()
    n2_positions = db.positions.count_documents({
        "org_id": n2_setup["n2_org_id"], "is_deleted": False})
    assert n2_positions == 0, \
        f"N1 must not be able to create positions for N2; found {n2_positions}"


def test_rule2f_n1_cannot_list_n2_ramp_movements(n1_setup, n2_setup):
    """`GET /ramp/accounts/{n2_ecid}/movements?org_id=N2` → 403."""
    s = n1_setup["session"]
    r = s.get(f"{BASE_URL}/api/v1/ramp/accounts/{n2_setup['n2_org_id']}/movements",
              params={"org_id": n2_setup["n2_org_id"]}, timeout=15)
    assert r.status_code == 403, \
        f"N1 cross-org movements read must be 403; got {r.status_code} {r.text[:300]}"


# ===========================================================================
# DoD: Backoffice listing exposes the hierarchy (parent_org_id + level)
# ===========================================================================
def test_dod_backoffice_listing_exposes_hierarchy(n1_setup, n2_setup):
    """super_admin GET /admin/clients?parent_org_id=<n1_org> returns the
    N2 with parent_org_id+level set. This is what powers the "Parent"
    column + hierarchy filter in /admin/business/clients."""
    s = _dev_login(SUPER_EMAIL)
    r = s.get(f"{BASE_URL}/api/v1/admin/clients",
              params={"parent_org_id": n1_setup["org_id"]}, timeout=15)
    assert r.status_code == 200, f"admin list: {r.status_code} {r.text[:300]}"
    rows = r.json().get("items", [])
    assert len(rows) >= 1
    n2_row = next((r for r in rows if r["org_id"] == n2_setup["n2_org_id"]),
                   None)
    assert n2_row is not None, "N2 missing from filtered listing"
    assert n2_row["parent_org_id"] == n1_setup["org_id"]
    assert n2_row["level"] == 2

    # And the inverse filter (parent_org_id=none) returns only true N1s.
    r2 = s.get(f"{BASE_URL}/api/v1/admin/clients",
               params={"parent_org_id": "none"}, timeout=15)
    assert r2.status_code == 200
    rows2 = r2.json().get("items", [])
    n2_in_top = any(r["org_id"] == n2_setup["n2_org_id"] for r in rows2)
    assert not n2_in_top, "N2 must not appear when filtering parent_org_id=none"


def test_dod_business_listing_exposes_hierarchy(n1_setup, n2_setup):
    """super_admin GET /admin/business/clients exposes parent_org_id +
    parent_name + level so the /admin/business/clients UI can render the
    Parent column."""
    s = _dev_login(SUPER_EMAIL)
    r = s.get(f"{BASE_URL}/api/v1/admin/business/clients", timeout=15)
    assert r.status_code == 200, f"biz list: {r.status_code} {r.text[:300]}"
    rows = r.json().get("items", [])
    n2_row = next((r for r in rows if r["org_id"] == n2_setup["n2_org_id"]),
                   None)
    assert n2_row is not None, \
        "N2 must appear in /admin/business/clients listing"
    assert n2_row.get("parent_org_id") == n1_setup["org_id"]
    assert n2_row.get("level") == 2
    assert n2_row.get("parent_name"), \
        "business listing must expose parent_name for the Parent column"
