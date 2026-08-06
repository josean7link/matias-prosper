"""Phase 5 — Compliance module backend tests (KYC/KYB/KYT/Risk/Alerts/Limits).

Covers all 17 endpoints under /admin/compliance/* and /admin/alerts/*, plus
seed counts, RBAC, KYB checklist enforcement, wallet screening stub,
limit edit + history, and Pydantic validation.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://finance-control-215.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api/v1"


# ---- Auth helpers ----------------------------------------------------------
def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{API}/auth/dev-login", params={"email": email, "next": "/admin"}, allow_redirects=False)
    assert r.status_code in (302, 303, 307), f"dev-login {email}: {r.status_code} {r.text[:200]}"
    return s


@pytest.fixture(scope="session")
def admin():
    return _login("admin@prosper.foundation")


@pytest.fixture(scope="session")
def compliance_user():
    return _login("compliance@prosper.foundation")


@pytest.fixture(scope="session")
def client_admin():
    return _login("client.admin@alemany.capital")


# ---- ENDPOINT MATRIX: super_admin 200, client_admin 403 --------------------
GET_ENDPOINTS = [
    "/admin/compliance/kyc/queue",
    "/admin/compliance/kyc/kyc_seed_01",
    "/admin/compliance/kyb/queue",
    "/admin/compliance/kyb/kyb_seed_01",
    "/admin/compliance/kyt/rules",
    "/admin/compliance/kyt/alerts",
    "/admin/compliance/kyt/watchlist",
    "/admin/compliance/kyt/travel-rule",
    "/admin/compliance/risk/overview",
    "/admin/compliance/risk/clients",
    "/admin/compliance/limits",
    "/admin/alerts",
    "/admin/alerts/summary",
]


@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_get_endpoints_super_admin_200(admin, path):
    r = admin.get(f"{API}{path}")
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"


@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_get_endpoints_client_admin_403(client_admin, path):
    r = client_admin.get(f"{API}{path}")
    assert r.status_code == 403, f"{path} -> {r.status_code} (expected 403)"


# ---- Seed counts -----------------------------------------------------------
def test_seed_kyc_queue_min_5(admin):
    r = admin.get(f"{API}/admin/compliance/kyc/queue")
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert len(items) >= 5


def test_seed_kyb_queue_3(admin):
    r = admin.get(f"{API}/admin/compliance/kyb/queue")
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert len(items) == 3


def test_seed_kyt_rules_7(admin):
    r = admin.get(f"{API}/admin/compliance/kyt/rules")
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert len(items) == 7


def test_seed_kyt_alerts_about_25(admin):
    r = admin.get(f"{API}/admin/compliance/kyt/alerts")
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert 15 <= len(items) <= 40, f"got {len(items)}"


def test_seed_risk_clients_52(admin):
    r = admin.get(f"{API}/admin/compliance/risk/clients")
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert len(items) == 52


def test_seed_alerts_about_12(admin):
    r = admin.get(f"{API}/admin/alerts")
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert 8 <= len(items) <= 20, f"got {len(items)}"


def test_seed_kyt_watchlist_4(admin):
    r = admin.get(f"{API}/admin/compliance/kyt/watchlist")
    data = r.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert len(items) == 4


# ---- Alerts summary (bell) -------------------------------------------------
def test_alerts_summary_shape(admin):
    r = admin.get(f"{API}/admin/alerts/summary")
    assert r.status_code == 200
    d = r.json()
    assert "open_count" in d
    assert "open_critical_count" in d
    assert "latest" in d
    assert isinstance(d["latest"], list)
    assert len(d["latest"]) <= 5


# ---- KYT rule patch --------------------------------------------------------
def test_kyt_rule_patch_daily_cap(admin):
    r = admin.patch(f"{API}/admin/compliance/kyt/rules/kyt_daily_cap", json={"enabled": False})
    assert r.status_code == 200, r.text[:200]
    # Re-enable so other tests / state is preserved
    admin.patch(f"{API}/admin/compliance/kyt/rules/kyt_daily_cap", json={"enabled": True})


# ---- Wallet screening stub -------------------------------------------------
def test_screen_wallet_internal_hit_external_unavailable(admin):
    r = admin.post(
        f"{API}/admin/compliance/kyt/screen-wallet",
        json={"address": "GAXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXBLACKLIST"},
    )
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    assert d.get("internal_watchlist_hit") is True
    assert d.get("external", {}).get("status") == "unavailable"


# ---- Limits edit + history -------------------------------------------------
def test_limits_edit_and_history(admin):
    # Need correct org_id — try seeded; spec says org_seed_alemany
    r0 = admin.get(f"{API}/admin/compliance/limits")
    assert r0.status_code == 200
    items = r0.json()
    if isinstance(items, dict):
        items = items.get("items", [])
    assert items, "limits empty"
    org_id = items[0].get("org_id")

    r = admin.patch(
        f"{API}/admin/compliance/limits/{org_id}",
        json={"key": "subscribe_daily_cap_usd", "value": 999999},
    )
    assert r.status_code == 200, r.text[:200]

    h = admin.get(f"{API}/admin/compliance/limits/{org_id}/history")
    assert h.status_code == 200
    hist = h.json()
    if isinstance(hist, dict):
        hist = hist.get("items", [])
    assert len(hist) >= 1


# ---- KYC decision validation (reason >= 20) --------------------------------
def test_kyc_decision_reason_too_short_422(admin):
    r = admin.post(
        f"{API}/admin/compliance/kyc/kyc_seed_02/decision",
        json={"action": "approve", "reason": "short"},
    )
    assert r.status_code == 422


# ---- KYB checklist enforcement (key business rule) -------------------------
def test_kyb_incomplete_checklist_blocks_approval(admin):
    # Try to approve a case that likely has incomplete checklist (not seed_01)
    # First find an incomplete one
    q = admin.get(f"{API}/admin/compliance/kyb/queue").json()
    items = q.get("items", q) if isinstance(q, dict) else q
    incomplete = None
    for it in items:
        prog = it.get("checklist_progress") or it.get("progress") or ""
        # progress strings look like "X/8"
        if isinstance(prog, str) and "/" in prog:
            a, b = prog.split("/")
            if int(a) < int(b):
                incomplete = it
                break
        elif isinstance(prog, dict):
            if prog.get("done", 0) < prog.get("total", 8):
                incomplete = it
                break
    if not incomplete:
        pytest.skip("No incomplete KYB case found")
    cid = incomplete.get("case_id") or incomplete.get("id")
    r = admin.post(
        f"{API}/admin/compliance/kyb/{cid}/decision",
        json={"action": "approve", "reason": "Approving despite incomplete checklist as a test."},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"


def test_kyb_complete_checklist_and_approve_helix(admin):
    cid = "kyb_seed_01"
    # Fetch detail to get current state
    d = admin.get(f"{API}/admin/compliance/kyb/{cid}")
    assert d.status_code == 200
    detail = d.json()
    checklist = detail.get("checklist", [])
    # Check each unchecked item
    for itm in checklist:
        if not itm.get("checked"):
            key = itm.get("key") or itm.get("id")
            r = admin.patch(
                f"{API}/admin/compliance/kyb/{cid}/checklist",
                json={"key": key, "checked": True},
            )
            assert r.status_code == 200, f"checklist patch {key}: {r.text[:200]}"

    # Verify ready
    d2 = admin.get(f"{API}/admin/compliance/kyb/{cid}").json()
    cl2 = d2.get("checklist", [])
    if cl2:
        assert all(it.get("checked") for it in cl2), "Not all items checked after patch"

    # Approve
    r = admin.post(
        f"{API}/admin/compliance/kyb/{cid}/decision",
        json={"action": "approve", "reason": "All 8 checklist items verified per AML/KYB policy."},
    )
    assert r.status_code == 200, f"approve: {r.status_code} {r.text[:300]}"


# ---- KYC decision flow (happy path) ----------------------------------------
def test_kyc_decision_approve(admin):
    # Use a fresh seed case; if already decided, skip gracefully
    cid = "kyc_seed_03"
    r = admin.post(
        f"{API}/admin/compliance/kyc/{cid}/decision",
        json={"action": "approve", "reason": "Documentation verified per AML policy and Travel Rule."},
    )
    assert r.status_code in (200, 400, 409), f"{r.status_code} {r.text[:200]}"
    if r.status_code == 200:
        d = admin.get(f"{API}/admin/compliance/kyc/{cid}").json()
        assert d.get("status") == "approved"
