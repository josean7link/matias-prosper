"""Sprint A — Recent Activity, NAV snapshots (real), WebSocket ops-queue.

Tests:
- GET /admin/dashboard/recent-activity (200 admin / 401 anon / 403 client / limit param / shape)
- NAV history items now come from nav_snapshots (non-trivial variation / idempotent count = 180)
- WebSocket /admin/dashboard/ws/ops-queue (auth, snapshot frame)
  WS is tested against localhost:8001 because the preview ingress likely doesn't forward WS frames.
"""
import json
import os
import re
import subprocess
import time

import pytest
import requests
import websockets

BASE_PUBLIC = os.environ.get("API_BASE", "https://finance-control-215.preview.emergentagent.com")
API = f"{BASE_PUBLIC}/api/v1"
LOCAL_BASE = "http://localhost:8001"
LOCAL_API = f"{LOCAL_BASE}/api/v1"
LOG_PATH = "/var/log/supervisor/backend.err.log"

ADMIN_EMAIL = "admin@prosper.foundation"
CLIENT_EMAIL = "client.admin@alemany.capital"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _login_session(email: str, base_api: str = API) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{base_api}/auth/passwordless-login", json={"email": email}, timeout=10)
    r.raise_for_status()
    cont = r.json()["code"]
    time.sleep(0.4)
    out = subprocess.run(["tail", "-n", "120", LOG_PATH], capture_output=True, text=True).stdout
    m = re.findall(re.escape(email) + r" -> (\d{4})", out)
    assert m, f"OTP not found in log for {email}"
    otp = m[-1]
    r2 = s.post(f"{base_api}/auth/passwordless-token", json={"code": cont, "token": otp}, timeout=10)
    r2.raise_for_status()
    assert s.cookies.get("prosper_session"), "missing prosper_session cookie"
    return s


@pytest.fixture(scope="module")
def admin_session():
    return _login_session(ADMIN_EMAIL)


@pytest.fixture(scope="module")
def client_session():
    return _login_session(CLIENT_EMAIL)


# ---------------------------------------------------------------------------
# Recent Activity endpoint
# ---------------------------------------------------------------------------
def test_recent_activity_requires_auth():
    r = requests.get(f"{API}/admin/dashboard/recent-activity", timeout=10)
    assert r.status_code == 401


def test_recent_activity_forbids_client_role(client_session):
    r = client_session.get(f"{API}/admin/dashboard/recent-activity", timeout=10)
    assert r.status_code == 403


def test_recent_activity_returns_items(admin_session):
    r = admin_session.get(f"{API}/admin/dashboard/recent-activity?limit=8", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body
    assert isinstance(body["items"], list)
    assert body["total"] == len(body["items"])
    assert len(body["items"]) > 0, "expected at least one seeded transaction"
    sample = body["items"][0]
    expected_keys = {"tx_id", "org_id", "org_name", "type", "amount",
                     "asset", "fee_amount", "prosper_tx_id", "tx_hash",
                     "created_at", "memo"}
    missing = expected_keys - set(sample.keys())
    assert not missing, f"missing keys in recent-activity item: {missing}"
    # org_name should be joined from organizations.commercial_name (not raw org_id)
    assert sample["org_name"] and sample["org_name"] != sample["org_id"], \
        f"org_name not joined: {sample}"


def test_recent_activity_limit_respected(admin_session):
    r = admin_session.get(f"{API}/admin/dashboard/recent-activity?limit=3", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) <= 3


# ---------------------------------------------------------------------------
# NAV history is now real (from nav_snapshots collection)
# ---------------------------------------------------------------------------
def test_nav_history_has_real_variation(admin_session):
    r = admin_session.get(f"{API}/admin/dashboard/nav-history?days=90", timeout=10)
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert len(items) == 90
    navs = [it["nav"] for it in items]
    # Compute day-over-day deltas. Synthetic series had constant delta = 0.085/365.
    # With ±5e-5 noise the deltas must vary (std > 1e-6).
    deltas = [navs[i + 1] - navs[i] for i in range(len(navs) - 1)]
    mean = sum(deltas) / len(deltas)
    var = sum((d - mean) ** 2 for d in deltas) / len(deltas)
    std = var ** 0.5
    assert std > 1e-6, f"NAV deltas look synthetic (std={std}). Likely still using 1.0*(1+0.085/365)^d."
    # Source marker present
    assert body.get("source") == "nav_snapshots"


def test_nav_snapshots_idempotent_count():
    """Verify the backfill is idempotent — db has exactly 180 snapshots after startup
    (helper backfills 180 days; restarting backend should NOT duplicate).
    We probe via days=180 (the API caps the slice to last 180 items)."""
    s = _login_session(ADMIN_EMAIL)
    r = s.get(f"{API}/admin/dashboard/nav-history?days=180", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 180, f"expected 180 snapshots got {len(body['items'])}"
    # dates must be unique
    dates = [it["date"] for it in body["items"]]
    assert len(set(dates)) == len(dates), "duplicate dates in nav_snapshots"


# ---------------------------------------------------------------------------
# WebSocket — tested via localhost (preview ingress likely doesn't forward WS)
# ---------------------------------------------------------------------------
def _login_local(email: str) -> str:
    """Login against localhost backend and return prosper_session cookie value."""
    s = _login_session(email, base_api=LOCAL_API)
    return s.cookies.get("prosper_session")


@pytest.mark.asyncio
async def test_ws_ops_queue_admin_receives_snapshot():
    cookie = _login_local(ADMIN_EMAIL)
    assert cookie
    url = f"ws://localhost:8001/api/v1/admin/dashboard/ws/ops-queue"
    headers = [("Cookie", f"prosper_session={cookie}")]
    try:
        async with websockets.connect(url, additional_headers=headers, open_timeout=5) as ws:
            msg = await ws.recv()
            data = json.loads(msg)
            for key in ("approvals", "kyb", "alerts", "webhook_failing", "reconciliation"):
                assert key in data, f"ws snapshot missing {key}: {data}"
    except TypeError:
        # Older websockets API used `extra_headers`
        async with websockets.connect(url, extra_headers=headers, open_timeout=5) as ws:
            msg = await ws.recv()
            data = json.loads(msg)
            for key in ("approvals", "kyb", "alerts", "webhook_failing", "reconciliation"):
                assert key in data


@pytest.mark.asyncio
async def test_ws_ops_queue_no_cookie_rejected():
    url = f"ws://localhost:8001/api/v1/admin/dashboard/ws/ops-queue"
    with pytest.raises(Exception) as exc:
        async with websockets.connect(url, open_timeout=5) as ws:
            await ws.recv()
    # close code 4401
    s = str(exc.value)
    assert "4401" in s or "rejected" in s.lower() or "closed" in s.lower(), \
        f"expected 4401/close, got {s}"


@pytest.mark.asyncio
async def test_ws_ops_queue_client_role_rejected():
    cookie = _login_local(CLIENT_EMAIL)
    url = f"ws://localhost:8001/api/v1/admin/dashboard/ws/ops-queue"
    headers = [("Cookie", f"prosper_session={cookie}")]
    with pytest.raises(Exception) as exc:
        try:
            async with websockets.connect(url, additional_headers=headers, open_timeout=5) as ws:
                await ws.recv()
        except TypeError:
            async with websockets.connect(url, extra_headers=headers, open_timeout=5) as ws:
                await ws.recv()
    s = str(exc.value)
    assert "4403" in s or "rejected" in s.lower() or "closed" in s.lower(), \
        f"expected 4403/close for client_admin, got {s}"
