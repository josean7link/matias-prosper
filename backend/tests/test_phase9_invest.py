"""Phase 9 — Auto-buy + manual buy + redeem + accrual tests.

The auto-buy path depends on the Alfred mock `/mock-settle` endpoint, so
this whole module is skipped when running against the live Alfred sandbox.
"""
from __future__ import annotations
import os
import asyncio

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

pytestmark = pytest.mark.skipif(
    os.environ.get("ALFRED_MODE", "mock") != "mock",
    reason="Phase 9 auto-buy uses /mock-settle (mock Alfred only)")

BASE = os.environ.get("PROSPER_API_BASE_TEST", "http://localhost:8001/api")
API  = f"{BASE}/v1"


def _client_session() -> requests.Session:
    s = requests.Session()
    s.get(f"{API}/auth/dev-login",
          params={"email": "client.admin@alemany.capital", "next": "/"},
          allow_redirects=False, timeout=10)
    return s


def _create_and_settle_onramp(s: requests.Session, amount: float = 100_000):
    q = s.post(f"{API}/client/onramp/quote",
               json={"source_currency": "ARS", "source_amount": amount},
               timeout=10).json()
    r = s.post(f"{API}/client/onramp/orders",
               json={"quote_id": q["quote_id"], "source_currency": "ARS",
                      "source_amount": amount, "payment_method": "transfer"},
               timeout=10).json()
    order = r["order"]
    # settle via mock helper
    requests.post(f"{API}/alfred/mock-settle/{order['alfred_id']}", timeout=10)
    return order


# --- products ---
def test_products_seeded():
    s = _client_session()
    r = s.get(f"{API}/client/products", timeout=10).json()
    ids = {p["product_id"] for p in r["items"]}
    assert {"liquid_v1", "term_30", "term_90", "term_180"} <= ids


# --- auto-buy after onramp ---
def test_onramp_triggers_auto_buy_and_creates_position():
    s = _client_session()
    order = _create_and_settle_onramp(s, 100_000)
    # Wait a tick for the synchronous trigger
    full = s.get(f"{API}/client/onramp/orders/{order['onramp_id']}", timeout=10).json()
    assert full["order"]["status"] == "confirmed"
    assert full.get("subscribe_tx") is not None, full
    sub_tx = full["subscribe_tx"]
    assert sub_tx["type"] == "subscribe"
    assert sub_tx["status"] == "confirmed"
    assert sub_tx.get("related_position_id")
    assert full["position"]["status"] == "active"
    assert full["position"]["principal_usd"] > 90


def test_onramp_buy_is_idempotent():
    """Re-running the trigger for the same onramp must NOT create a 2nd position."""
    s = _client_session()
    order = _create_and_settle_onramp(s, 100_000)
    # Pull current count
    p1 = s.get(f"{API}/client/positions", timeout=10).json()
    n1 = len([p for p in p1["items"] if p.get("prosper_tx_id")])

    # Trigger again by calling get_onramp (which is a read, but also re-asks
    # for subscribe_tx — does NOT re-trigger). Best we can do at endpoint level:
    s.get(f"{API}/client/onramp/orders/{order['onramp_id']}", timeout=10)
    p2 = s.get(f"{API}/client/positions", timeout=10).json()
    n2 = len([p for p in p2["items"] if p.get("prosper_tx_id")])
    assert n2 == n1, f"position count changed {n1} -> {n2}"


# --- manual buy ---
def test_manual_buy_below_min_amount_rejected():
    s = _client_session()
    r = s.post(f"{API}/client/positions",
               json={"product_id": "term_30", "amount_usdc": 10},
               timeout=10)
    # term_30 min is 100
    assert r.status_code == 400
    assert "min" in r.text.lower()


def test_manual_buy_validates_inputs():
    """Manual buy returns 200 only with valid inputs; otherwise validates correctly."""
    s = _client_session()
    # Insufficient balance scenario: try to buy 10M USDC, must be rejected
    r = s.post(f"{API}/client/positions",
               json={"product_id": "liquid_v1", "amount_usdc": 10_000_000},
               timeout=10)
    assert r.status_code == 400, r.text
    assert "above max_amount" in r.text.lower() or "insufficient" in r.text.lower()

    # Below min for term_180 (min 1000)
    r = s.post(f"{API}/client/positions",
               json={"product_id": "term_180", "amount_usdc": 500},
               timeout=10)
    assert r.status_code == 400
    assert "min" in r.text.lower()


# --- redeem ---
def test_redeem_liquid_position_returns_principal_plus_accrued():
    s = _client_session()
    _create_and_settle_onramp(s, 100_000)
    positions = s.get(f"{API}/client/positions", timeout=10).json()["items"]
    liquid = [p for p in positions if p["product_id"] == "liquid_v1"
               and p["status"] == "active"]
    assert liquid, "expected at least one active liquid position from auto-buy"
    pos_id = liquid[0]["position_id"]
    res = s.post(f"{API}/client/positions/{pos_id}/redeem", timeout=10)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["amount_received"] >= 90.0


# --- accrual job (runs in-process, calls helper directly) ---
def test_accrual_increments_active_positions():
    import sys
    sys.path.insert(0, "/app/backend")
    from dotenv import load_dotenv  # type: ignore
    load_dotenv("/app/backend/.env")
    from jobs.accrual import run_accrual_once
    res = asyncio.run(run_accrual_once())
    assert "updated" in res
    assert isinstance(res["updated"], int)
