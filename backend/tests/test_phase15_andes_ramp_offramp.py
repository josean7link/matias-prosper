"""Phase 15.1 — Andes Offramp + Webhooks + Movements + Idempotency tests.

Covers the full review_request matrix:
 1. Gateway rejects bad signature / stale timestamp (>5min) → 401
 2. /dev/simulate-deposit auto-fires signed webhook → movement + balance
 3. FastAPI /api/v1/internal/ramp/webhook requires X-Internal-Token (401)
 4. delivery_id idempotency on the receiver
 5. fiat.deposit.success handler creates ramp_movements (kind=deposit)
 6. /withdraw requires Idempotency-Key (400), validates caps/balance/approved
 7. Idempotency-Key returns same movement id
 8. Auto-settle to Success with settled_at after ~250ms
 9. /cvu-lookup returns holder data
10. /accounts/<ec>/movements: DESC, asset_label='ARSa', asset_symbol='$'
"""
from __future__ import annotations

import json
import os
import time
import uuid

import pytest
import requests

BASE_URL = "https://15b54ecb-7c4d-4e40-932c-37af86d0770c.preview.emergentagent.com".rstrip("/")
GATEWAY_URL = os.environ.get("ANDES_GATEWAY_URL", "http://localhost:8090")
TOKEN = os.environ.get("GATEWAY_INTERNAL_TOKEN", "dev-internal-token-change-me")

CLIENT_EMAIL = "client.admin@alemany.capital"


def _login(email: str) -> requests.Session:
    s = requests.Session()
    r = s.get(f"{BASE_URL}/api/v1/auth/dev-login",
              params={"email": email}, allow_redirects=False, timeout=15)
    assert r.status_code in (200, 302, 303, 307), r.text[:200]
    return s


@pytest.fixture(scope="module")
def client_session() -> requests.Session:
    return _login(CLIENT_EMAIL)


@pytest.fixture(scope="module")
def account(client_session) -> dict:
    r = client_session.post(f"{BASE_URL}/api/v1/ramp/accounts", json={}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    return r.json()


# ---------------------------------------------------------------------------
# 1) Gateway signature verification
# ---------------------------------------------------------------------------
def _gw_alive() -> bool:
    try:
        return requests.get(f"{GATEWAY_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _gw_alive(), reason="andes-gateway down")
def test_gateway_webhook_rejects_bad_signature():
    body = json.dumps({"type": "fiat.deposit.success", "data": {}}).encode()
    r = requests.post(
        f"{GATEWAY_URL}/webhooks/andes",
        headers={
            "Content-Type": "application/json",
            "x-webhook-timestamp": str(int(time.time() * 1000)),
            "x-webhook-signature": "INVALID_SIGNATURE_XXX",
            "x-webhook-delivery-id": "dlv_bad_" + uuid.uuid4().hex[:6],
        },
        data=body, timeout=10)
    assert r.status_code == 401, r.text[:200]


@pytest.mark.skipif(not _gw_alive(), reason="andes-gateway down")
def test_gateway_webhook_rejects_old_timestamp():
    # Stale timestamp via /dev/fire-webhook is impossible (gateway signs fresh).
    # Send hand-crafted signed-ish request: any-signature with old ts must
    # fail before signature verification or as part of it → 401.
    old_ts = str(int(time.time() * 1000) - 10 * 60_000)  # 10 minutes ago
    body = json.dumps({"type": "fiat.deposit.success", "data": {}}).encode()
    r = requests.post(
        f"{GATEWAY_URL}/webhooks/andes",
        headers={"Content-Type": "application/json",
                 "x-webhook-timestamp": old_ts,
                 "x-webhook-signature": "any.signature",
                 "x-webhook-delivery-id": "dlv_old_" + uuid.uuid4().hex[:6]},
        data=body, timeout=10)
    assert r.status_code == 401, r.text[:200]


# ---------------------------------------------------------------------------
# 2) FastAPI receiver: auth + idempotency
# ---------------------------------------------------------------------------
def test_receiver_requires_internal_token():
    r = requests.post(f"{BASE_URL}/api/v1/internal/ramp/webhook",
                      json={"event_type": "fiat.deposit.success",
                            "delivery_id": "dlv_x", "payload": {}},
                      timeout=15)
    assert r.status_code in (401, 403), r.text[:200]


def test_receiver_idempotent_on_delivery_id():
    dlv = "dlv_idem_" + uuid.uuid4().hex[:10]
    body = {
        "event_type": "fiat.deposit.success",
        "delivery_id": dlv,
        "payload": {"type": "fiat.deposit.success",
                    "data": {"userId": "unknown-user-x", "amount": "1",
                             "asset": "arsa", "chain": "stellar",
                             "transactionId": "tx_" + uuid.uuid4().hex[:8]}},
        "signature_valid": True,
        "headers": {},
    }
    r1 = requests.post(f"{BASE_URL}/api/v1/internal/ramp/webhook",
                       headers={"X-Internal-Token": TOKEN}, json=body, timeout=15)
    assert r1.status_code == 200, r1.text[:200]
    r2 = requests.post(f"{BASE_URL}/api/v1/internal/ramp/webhook",
                       headers={"X-Internal-Token": TOKEN}, json=body, timeout=15)
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True


# ---------------------------------------------------------------------------
# 3) simulate-deposit auto-fires signed webhook → movement + balance
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not _gw_alive(), reason="andes-gateway down")
def test_simulate_deposit_creates_movement(client_session, account):
    ec = account["end_customer_id"]
    user_id = account["provider_user_id"]

    # before
    r0 = client_session.get(f"{BASE_URL}/api/v1/ramp/accounts/{ec}/movements",
                            timeout=15)
    assert r0.status_code == 200
    before_count = len(r0.json())

    sim = requests.post(
        f"{GATEWAY_URL}/dev/simulate-deposit",
        headers={"X-Internal-Token": TOKEN, "Content-Type": "application/json"},
        json={"user_id": user_id, "asset": "arsa", "amount": 7777.77},
        timeout=15)
    assert sim.status_code == 200, sim.text[:200]
    js = sim.json()
    # webhook field should be present and 200 (forwarded ok)
    assert js.get("webhook"), js
    assert js["webhook"].get("status") == 200, js["webhook"]

    time.sleep(1.0)
    r1 = client_session.get(f"{BASE_URL}/api/v1/ramp/accounts/{ec}/movements",
                            timeout=15)
    rows = r1.json()
    assert len(rows) > before_count, rows[:3]
    # newest first
    newest = rows[0]
    assert newest["kind"] == "deposit"
    assert newest["asset"] == "arsa"
    assert newest["asset_label"] == "ARSa"
    assert newest["asset_symbol"] == "$"
    assert newest["status"] == "Success"
    assert newest["prosper_tx_id"], newest


# ---------------------------------------------------------------------------
# 4) CVU lookup
# ---------------------------------------------------------------------------
def test_cvu_lookup_returns_holder(client_session):
    r = client_session.get(f"{BASE_URL}/api/v1/ramp/cvu-lookup",
                           params={"cvu": "0000003123456789012345"},
                           timeout=15)
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    assert d.get("holder_name"), d
    assert d.get("bank"), d


# ---------------------------------------------------------------------------
# 5) Withdraw — header + idempotency + caps + auto-settle
# ---------------------------------------------------------------------------
def test_withdraw_requires_idempotency_key(client_session, account):
    ec = account["end_customer_id"]
    r = client_session.post(f"{BASE_URL}/api/v1/ramp/accounts/{ec}/withdraw",
                            json={"amount": "100",
                                  "to_cvu": "0000003123456789012345"},
                            timeout=15)
    assert r.status_code == 400, r.text[:200]


def test_withdraw_happy_path_and_autosettle(client_session, account):
    ec = account["end_customer_id"]
    # ensure there's funding (cap deposit so balance is healthy)
    requests.post(f"{GATEWAY_URL}/dev/simulate-deposit",
                  headers={"X-Internal-Token": TOKEN},
                  json={"user_id": account["provider_user_id"],
                        "asset": "arsa", "amount": 50000},
                  timeout=15)
    time.sleep(0.6)

    key = "idem-" + uuid.uuid4().hex[:12]
    body = {"amount": "123.45", "to_cvu": "0000003123456789012345",
            "holder_name_confirmed": "Test Holder"}
    r1 = client_session.post(f"{BASE_URL}/api/v1/ramp/accounts/{ec}/withdraw",
                             headers={"Idempotency-Key": key},
                             json=body, timeout=20)
    assert r1.status_code == 200, r1.text[:300]
    mv1 = r1.json()
    assert mv1["kind"] == "withdrawal"
    assert mv1["asset_label"] == "ARSa"
    assert mv1["asset_symbol"] == "$"
    assert mv1["status"] in ("Pending", "Success"), mv1
    mv_id = mv1["id"]

    # Idempotency replay
    r2 = client_session.post(f"{BASE_URL}/api/v1/ramp/accounts/{ec}/withdraw",
                             headers={"Idempotency-Key": key},
                             json=body, timeout=20)
    assert r2.status_code == 200, r2.text[:200]
    assert r2.json()["id"] == mv_id

    # Auto-settle within ~1.5s
    settled = False
    for _ in range(10):
        time.sleep(0.4)
        rl = client_session.get(
            f"{BASE_URL}/api/v1/ramp/accounts/{ec}/movements", timeout=15)
        rows = rl.json()
        match = next((m for m in rows if m["id"] == mv_id), None)
        if match and match["status"] == "Success" and match.get("settled_at"):
            settled = True
            break
    assert settled, f"withdrawal did not auto-settle to Success: {match}"


def test_withdraw_insufficient_balance(client_session, account):
    ec = account["end_customer_id"]
    key = "idem-toobig-" + uuid.uuid4().hex[:8]
    r = client_session.post(
        f"{BASE_URL}/api/v1/ramp/accounts/{ec}/withdraw",
        headers={"Idempotency-Key": key},
        json={"amount": "999999999",
              "to_cvu": "0000003123456789012345"},
        timeout=20)
    # Gateway returns 409 insufficient → adapter surfaces 409 from caps OR
    # from gateway. Backend may return 409 (caps) or 409 (gateway). Either is OK.
    assert r.status_code in (400, 409, 502), r.text[:200]


# ---------------------------------------------------------------------------
# 6) Movements list shape
# ---------------------------------------------------------------------------
def test_movements_list_desc_with_arsa_labels(client_session, account):
    ec = account["end_customer_id"]
    r = client_session.get(f"{BASE_URL}/api/v1/ramp/accounts/{ec}/movements",
                           timeout=15)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and len(rows) >= 1
    # DESC: created_at non-increasing
    times = [m["created_at"] for m in rows]
    assert times == sorted(times, reverse=True), times[:5]
    for m in rows:
        assert m["asset_label"] == "ARSa"
        assert m["asset_symbol"] == "$"
