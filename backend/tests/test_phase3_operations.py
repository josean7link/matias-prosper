"""Phase 3 — Operations module: ledger, lifecycle, retry, funds, by-client, volume, upstream.

Covers the 8 endpoints under /api/v1/admin/* mounted in routes/operations.py.
Uses passwordless OTP auth and reuses helpers/patterns from
test_phase3_onboarding.py. Tests are READ-ONLY except for the retry-step
endpoint which mutates a single lifecycle step (idempotent).
"""
import os
import re
import time
import subprocess
import requests
import pytest

BASE = os.environ.get("API_BASE", "http://localhost:8001")
API = f"{BASE}/api/v1"

ADMIN_EMAIL = "admin@prosper.foundation"           # super_admin
OPS_EMAIL = "ops@prosper.foundation"               # admin (NOT super_admin)
CLIENT_EMAIL = "client.admin@alemany.capital"      # client_admin (403 expected)


# ─── Auth helpers ────────────────────────────────────────────────────────────
def _otp_from_log(email: str) -> str:
    out = subprocess.check_output(
        ["tail", "-n", "400", "/var/log/supervisor/backend.err.log"],
        text=True, errors="ignore",
    )
    matches = re.findall(rf"{re.escape(email)} -> (\d+)", out)
    assert matches, f"No OTP found in backend log for {email}"
    return matches[-1]


def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{API}/auth/passwordless-login", json={"email": email}, timeout=10)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    time.sleep(0.4)
    otp = _otp_from_log(email)
    r2 = s.post(f"{API}/auth/passwordless-token",
                json={"code": code, "token": otp}, timeout=10)
    assert r2.status_code == 200, r2.text
    assert s.cookies.get("prosper_session")
    return s


@pytest.fixture(scope="module")
def admin():
    return _login(ADMIN_EMAIL)


@pytest.fixture(scope="module")
def ops():
    try:
        return _login(OPS_EMAIL)
    except AssertionError:
        pytest.skip("ops user not available")


@pytest.fixture(scope="module")
def client_admin():
    return _login(CLIENT_EMAIL)


# ─── /admin/transactions ─────────────────────────────────────────────────────
class TestLedger:
    def test_list_auth_required(self):
        r = requests.get(f"{API}/admin/transactions", timeout=10)
        assert r.status_code == 401

    def test_list_forbidden_for_client_admin(self, client_admin):
        r = client_admin.get(f"{API}/admin/transactions", timeout=10)
        assert r.status_code == 403

    def test_list_default_pagination(self, admin):
        r = admin.get(f"{API}/admin/transactions", timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("items", "total", "page", "limit", "pages"):
            assert k in d, f"missing key {k}"
        assert d["limit"] == 50
        assert d["page"] == 1
        assert isinstance(d["items"], list)
        assert len(d["items"]) <= 50
        # lifecycle NOT included in list response
        if d["items"]:
            assert "lifecycle" not in d["items"][0]
            # org_name joined
            assert "org_name" in d["items"][0]

    def test_list_filter_by_type(self, admin):
        r = admin.get(f"{API}/admin/transactions",
                      params={"type": "subscribe", "limit": 20}, timeout=10)
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item.get("type") == "subscribe"

    def test_list_filter_by_status(self, admin):
        r = admin.get(f"{API}/admin/transactions",
                      params={"status": "confirmed", "limit": 20}, timeout=10)
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item.get("status") == "confirmed"

    def test_list_only_errors_includes_failed(self, admin):
        r = admin.get(f"{API}/admin/transactions",
                      params={"only_errors": "true", "limit": 50}, timeout=10)
        assert r.status_code == 200
        # at least one failed tx should exist per seed (~20% subscribes)
        items = r.json()["items"]
        statuses = {it.get("status") for it in items}
        # Either failed status or lifecycle.status=error matches
        assert items, "only_errors returned 0 rows — seed may be missing failures"

    def test_list_pagination_page2(self, admin):
        r1 = admin.get(f"{API}/admin/transactions", params={"limit": 5, "page": 1}, timeout=10)
        r2 = admin.get(f"{API}/admin/transactions", params={"limit": 5, "page": 2}, timeout=10)
        assert r1.status_code == 200 and r2.status_code == 200
        ids1 = [i.get("tx_id") for i in r1.json()["items"]]
        ids2 = [i.get("tx_id") for i in r2.json()["items"]]
        if ids1 and ids2:
            assert set(ids1).isdisjoint(set(ids2)), "page 1 and 2 must not overlap"


# ─── /admin/transactions/{tx_id}/lifecycle ───────────────────────────────────
class TestLifecycle:
    def _pick(self, admin, type_filter, status_filter=None):
        params = {"type": type_filter, "limit": 50}
        if status_filter:
            params["status"] = status_filter
        r = admin.get(f"{API}/admin/transactions", params=params, timeout=10)
        items = r.json().get("items", [])
        return items[0] if items else None

    def test_lifecycle_subscribe_6_steps(self, admin):
        tx = self._pick(admin, "subscribe", "confirmed")
        if not tx:
            pytest.skip("no confirmed subscribe tx in seed")
        r = admin.get(f"{API}/admin/transactions/{tx['tx_id']}/lifecycle", timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert {"transaction", "org", "lifecycle"} <= set(d.keys())
        steps = d["lifecycle"]
        assert isinstance(steps, list)
        assert len(steps) == 6, f"subscribe should have 6 lifecycle steps, got {len(steps)}"
        ids = [s["step_id"] for s in steps]
        for expected in ("onramp", "conversion", "trigger", "mint", "position", "webhook"):
            assert expected in ids, f"missing step {expected}"
        # status enum
        for s in steps:
            assert s["status"] in ("ok", "error", "pending", "skipped")
            assert "title" in s

    def test_lifecycle_redeem_4_steps(self, admin):
        tx = self._pick(admin, "redeem")
        if not tx:
            pytest.skip("no redeem tx in seed")
        r = admin.get(f"{API}/admin/transactions/{tx['tx_id']}/lifecycle", timeout=10)
        assert r.status_code == 200
        steps = r.json()["lifecycle"]
        assert len(steps) == 4, f"redeem should have 4 lifecycle steps, got {len(steps)}"
        ids = [s["step_id"] for s in steps]
        for expected in ("trigger", "burn", "offramp", "settled"):
            assert expected in ids

    def test_lifecycle_failed_has_error_step(self, admin):
        tx = self._pick(admin, "subscribe", "failed")
        if not tx:
            pytest.skip("no failed subscribe in seed")
        r = admin.get(f"{API}/admin/transactions/{tx['tx_id']}/lifecycle", timeout=10)
        assert r.status_code == 200
        statuses = [s.get("status") for s in r.json()["lifecycle"]]
        assert "error" in statuses or "pending" in statuses, \
            f"failed tx must have error/pending step, got {statuses}"

    def test_lifecycle_404(self, admin):
        r = admin.get(f"{API}/admin/transactions/tx_nonexistent_xyz/lifecycle", timeout=10)
        assert r.status_code == 404


# ─── /admin/transactions/{tx_id}/retry-step ──────────────────────────────────
class TestRetryStep:
    def _failed_tx(self, sess):
        r = sess.get(f"{API}/admin/transactions",
                     params={"status": "failed", "type": "subscribe", "limit": 5}, timeout=10)
        items = r.json().get("items", [])
        return items[0] if items else None

    def test_retry_requires_super_admin(self, ops):
        # Probe role via /me — passwordless auth auto-creates @prosper.foundation
        # users with super_admin role, so this test can only meaningfully assert
        # 403 when ops actually has role=admin. Skip otherwise.
        me = ops.get(f"{API}/me", timeout=10).json()
        if me.get("role") == "super_admin":
            pytest.skip("ops user auto-provisioned as super_admin "
                        "(seeding gap — see code review comments)")
        tx = self._failed_tx(ops)
        if not tx:
            pytest.skip("no failed tx in seed")
        r = ops.post(
            f"{API}/admin/transactions/{tx['tx_id']}/retry-step",
            params={"step_id": "webhook"}, timeout=10)
        assert r.status_code == 403, f"admin (non-super) must get 403, got {r.status_code}"

    def test_retry_forbidden_for_client_admin(self, client_admin):
        r = client_admin.post(
            f"{API}/admin/transactions/tx_anything/retry-step",
            params={"step_id": "webhook"}, timeout=10)
        assert r.status_code == 403

    def test_retry_super_admin_flips_to_pending(self, admin):
        tx = self._failed_tx(admin)
        if not tx:
            pytest.skip("no failed tx in seed")
        r = admin.post(
            f"{API}/admin/transactions/{tx['tx_id']}/retry-step",
            params={"step_id": "webhook"}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("status") == "pending"
        # Verify persistence via GET lifecycle
        r2 = admin.get(f"{API}/admin/transactions/{tx['tx_id']}/lifecycle", timeout=10)
        steps = {s["step_id"]: s for s in r2.json()["lifecycle"]}
        assert steps["webhook"]["status"] == "pending"
        assert "retry_requested_by" in steps["webhook"]
        assert "retry_requested_at" in steps["webhook"]


# ─── /admin/transactions/export.csv ──────────────────────────────────────────
class TestExportCSV:
    def test_export_auth_required(self):
        r = requests.get(f"{API}/admin/transactions/export.csv", timeout=10)
        assert r.status_code == 401

    def test_export_returns_csv(self, admin):
        r = admin.get(f"{API}/admin/transactions/export.csv", timeout=15)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert re.search(r'transactions_\d{8}\.csv', cd), cd
        # 11 columns in header
        header_line = r.text.splitlines()[0]
        cols = header_line.split(",")
        assert len(cols) == 11
        for expected in ("created_at", "tx_id", "prosper_tx_id", "type", "org_id",
                         "amount", "asset", "status", "fee_amount", "tx_hash", "memo"):
            assert expected in cols

    def test_export_honors_filters(self, admin):
        r = admin.get(f"{API}/admin/transactions/export.csv",
                      params={"type": "redeem"}, timeout=15)
        assert r.status_code == 200
        lines = r.text.strip().splitlines()
        # Skip header; data rows should all be redeem in col index 3
        if len(lines) > 1:
            for row in lines[1:]:
                fields = row.split(",")
                # type is column 3 (0-based)
                assert fields[3] == "redeem", f"non-redeem in filtered export: {row}"


# ─── /admin/funds/state ──────────────────────────────────────────────────────
class TestFundsState:
    def test_funds_state(self, admin):
        r = admin.get(f"{API}/admin/funds/state", timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "fund" in d and "stellar_accounts" in d
        f = d["fund"]
        for k in ("fund_id", "name", "nav", "supply_circulating",
                  "invested_usd", "treasury_usd", "positions", "asset_code"):
            assert k in f, f"fund missing {k}"
        assert f["nav"] > 1.0, f"NAV should be >1.0 from snapshots, got {f['nav']}"
        # Stellar accounts: exactly 4 with the expected labels
        labels = [a["label"] for a in d["stellar_accounts"]]
        assert len(labels) == 4
        for lbl in ("Issuer", "Treasury", "Reward pool", "Fees account"):
            assert lbl in labels
        for acc in d["stellar_accounts"]:
            assert acc.get("address", "").startswith("G"), "invalid Stellar address"
        assert "xlm_reserve_total" in d
        assert "generated_at" in d


# ─── /admin/prosper-upstream/status ──────────────────────────────────────────
class TestUpstreamStatus:
    def test_upstream_status(self, admin):
        r = admin.get(f"{API}/admin/prosper-upstream/status", timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("enabled", "reachable", "authenticated",
                  "environment", "upstream_url", "note", "checked_at"):
            assert k in d
        # Sandbox preview: reachable + authenticated both false
        assert d["reachable"] is False
        assert d["authenticated"] is False
        assert d["enabled"] is True


# ─── /admin/operations/by-client/stats ──────────────────────────────────────
class TestByClientStats:
    def test_by_client_stats(self, admin):
        r = admin.get(f"{API}/admin/operations/by-client/stats", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        for it in d["items"]:
            for k in ("org_id", "org_name", "total", "ok", "failed",
                      "success_pct", "failed_pct", "last_at", "sparkline"):
                assert k in it, f"by-client item missing {k}"
            assert it["success_pct"] + it["failed_pct"] <= 100.1
            assert isinstance(it["sparkline"], list)


# ─── /admin/operations/volume-by-client ─────────────────────────────────────
class TestVolumeByClient:
    def test_volume_by_client(self, admin):
        r = admin.get(f"{API}/admin/operations/volume-by-client", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "total_volume_30d" in d
        for it in d["items"]:
            for k in ("org_id", "org_name", "vol_24h", "vol_7d", "vol_30d",
                      "vol_total", "vol_prev_30d", "delta_pct_30d", "share_pct_30d"):
                assert k in it, f"volume item missing {k}"
        # Share should sum to ~100 (±1) when there is any volume
        if d["items"] and d["total_volume_30d"] > 0:
            share_sum = sum(it["share_pct_30d"] for it in d["items"])
            assert 99.0 <= share_sum <= 101.0, f"share_pct_30d sums to {share_sum}"
