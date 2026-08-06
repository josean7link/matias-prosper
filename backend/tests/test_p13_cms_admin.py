"""P1-3 CMS migration: admin treasury, stakings, sync endpoints + 410 Gone bridge."""
import os, time, pytest, requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com",
).rstrip("/")


def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login", params={"email": email}, allow_redirects=False)
    assert r.status_code in (200, 302, 303), f"dev-login failed: {r.status_code} {r.text[:200]}"
    return s


@pytest.fixture(scope="module")
def admin():
    return _login("admin@prosper.foundation")


@pytest.fixture(scope="module")
def client_user():
    return _login("client.admin@alemany.capital")


# === Treasury ===
def test_treasury_admin_ok(admin):
    r = admin.get(f"{BASE_URL}/api/v1/admin/prosper/treasury")
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("address", "balanceUSDC", "balanceARSA", "balanceXLM", "mode", "refreshed_at"):
        assert k in d, f"missing {k}: {d}"
    assert d["balanceUSDC"] is not None
    assert d["balanceARSA"] is not None
    assert str(d["balanceUSDC"]) not in ("0", "", "None")
    assert str(d["balanceARSA"]) not in ("0", "", "None")


def test_treasury_client_forbidden(client_user):
    r = client_user.get(f"{BASE_URL}/api/v1/admin/prosper/treasury")
    assert r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}"


# === Sync status ===
def test_sync_status(admin):
    r = admin.get(f"{BASE_URL}/api/v1/admin/prosper/staking-sync/status")
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("enabled", "mode", "interval_minutes", "last_run"):
        assert k in d, f"missing {k}: {d}"
    # last_run may be None on a fresh DB, but ideally has summary fields
    if d["last_run"]:
        for fk in ("processed", "created", "updated", "external_total"):
            assert fk in d["last_run"], f"last_run missing {fk}: {d['last_run']}"


# === Sync run ===
def test_sync_run_then_status(admin):
    before = admin.get(f"{BASE_URL}/api/v1/admin/prosper/staking-sync/status").json()
    before_finished = (before.get("last_run") or {}).get("finished_at")

    r = admin.post(f"{BASE_URL}/api/v1/admin/prosper/staking-sync/run")
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary.get("ok") is True, summary
    # summary may be top-level or nested
    proc = summary.get("processed") or (summary.get("summary") or {}).get("processed")
    assert proc is not None

    time.sleep(1)
    after = admin.get(f"{BASE_URL}/api/v1/admin/prosper/staking-sync/status").json()
    after_finished = (after.get("last_run") or {}).get("finished_at")
    assert after_finished is not None
    if before_finished:
        assert after_finished >= before_finished


# === Stakings ===
def test_stakings_all(admin):
    r = admin.get(f"{BASE_URL}/api/v1/admin/prosper/stakings", params={"scope": "all"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "ours" in d and "external" in d and "total" in d and "fetched_at" in d
    assert "items" in d["ours"] and "by_org" in d["ours"] and "total" in d["ours"]
    assert "items" in d["external"] and "total" in d["external"]
    # Expected: 8 external, 0 ours
    assert d["external"]["total"] == 8, f"expected 8 external, got {d['external']['total']}"
    assert d["ours"]["total"] == 0, f"expected 0 ours, got {d['ours']['total']}"
    assert d["external"]["items"][0].get("external") is True


def test_stakings_external_arsa_filter(admin):
    r = admin.get(
        f"{BASE_URL}/api/v1/admin/prosper/stakings",
        params={"scope": "external", "asset": "arsa"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    # ours should be empty/absent
    if "ours" in d:
        assert d["ours"].get("total", 0) == 0
    items = d["external"]["items"]
    assert len(items) > 0
    for it in items:
        asset = (it.get("asset") or "").lower()
        assert asset == "arsa", f"non-arsa item leaked: {it}"


# === P0-4 bridge still 410 ===
def test_investments_intent_410(admin):
    r = admin.post(
        f"{BASE_URL}/api/v1/investments/intent",
        json={"direction": "in", "amount_arsa": 1000},
    )
    assert r.status_code == 410, f"expected 410 Gone, got {r.status_code}: {r.text[:200]}"
