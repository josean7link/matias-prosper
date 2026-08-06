"""Phase 9 — Additional DoD coverage on top of test_phase9_invest.py.

NOTE (Feb 2026 / CMS migration): same as test_phase9_invest.py — the legacy
liquid_v1/term_30/… product IDs are gone; the buy/redeem flow is being
rewired against CMS (no direct mint API). Skipped pending rewrite.
"""
from __future__ import annotations
import asyncio
import os
import sys

import pytest
import requests

pytestmark = pytest.mark.skip(
    reason="Legacy catalog deprecated by CMS protocol migration (Feb 2026).")

BASE = os.environ.get("PROSPER_API_BASE_TEST", "http://localhost:8001/api")
API  = f"{BASE}/v1"


def _session(email: str) -> requests.Session:
    s = requests.Session()
    s.get(f"{API}/auth/dev-login",
          params={"email": email, "next": "/"},
          allow_redirects=False, timeout=10)
    return s


def _client_session() -> requests.Session:
    return _session("client.admin@alemany.capital")


def _finpact_session() -> requests.Session:
    return _session("client.admin@finpact.io")


def _create_and_settle_onramp(s: requests.Session, amount_ars: float):
    q = s.post(f"{API}/client/onramp/quote",
               json={"source_currency": "ARS", "source_amount": amount_ars},
               timeout=10).json()
    r = s.post(f"{API}/client/onramp/orders",
               json={"quote_id": q["quote_id"], "source_currency": "ARS",
                      "source_amount": amount_ars, "payment_method": "transfer"},
               timeout=10).json()
    order = r["order"]
    requests.post(f"{API}/alfred/mock-settle/{order['alfred_id']}", timeout=10)
    return order


# --- balances ---
def test_balances_endpoint_returns_mock_shape():
    s = _client_session()
    r = s.get(f"{API}/client/balances", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    # Required keys per DoD
    for key in ("available_usdc", "address", "balance_prosper",
                "balance_xlm", "mode"):
        assert key in body, f"missing key {key} in {body}"
    assert body["mode"] == "mock"
    # In mock mode the adapter should return a Stellar address
    assert isinstance(body["address"], str) and body["address"]
    assert isinstance(body["available_usdc"], (int, float))


# --- products: full schema ---
def test_products_have_min_max_apr_and_term():
    s = _client_session()
    items = s.get(f"{API}/client/products", timeout=10).json()["items"]
    by_id = {p["product_id"]: p for p in items}
    # liquid_v1: 600 bps, min 50
    assert by_id["liquid_v1"]["apr_bps"] == 600
    assert by_id["liquid_v1"]["min_amount"] == 50
    assert by_id["liquid_v1"]["term_days"] == 0
    # term_30: 750 bps, min 100
    assert by_id["term_30"]["apr_bps"] == 750
    assert by_id["term_30"]["min_amount"] == 100
    assert by_id["term_30"]["term_days"] == 30
    # term_90: 900 bps
    assert by_id["term_90"]["apr_bps"] == 900
    assert by_id["term_90"]["term_days"] == 90
    # term_180: 1100 bps, min 1000
    assert by_id["term_180"]["apr_bps"] == 1100
    assert by_id["term_180"]["min_amount"] == 1_000
    assert by_id["term_180"]["term_days"] == 180


# --- auto-buy skipped below min ---
def test_auto_buy_skipped_when_below_liquid_min():
    """40k ARS @ ~960 ARS/USD ≈ 40 USDC, below liquid_v1.min_amount=50."""
    s = _client_session()
    order = _create_and_settle_onramp(s, 40_000)
    full = s.get(f"{API}/client/onramp/orders/{order['onramp_id']}",
                  timeout=10).json()
    assert full["order"]["status"] == "confirmed"
    # No auto-buy expected because amount < 50 USDC
    assert full.get("subscribe_tx") is None, (
        f"unexpected subscribe_tx for sub-min onramp: {full}")
    assert full.get("position") is None, (
        f"unexpected position for sub-min onramp: {full}")


# --- position detail with events ---
def test_position_detail_returns_events_with_subscribe():
    s = _client_session()
    _create_and_settle_onramp(s, 100_000)
    positions = s.get(f"{API}/client/positions", timeout=10).json()["items"]
    assert positions, "expected at least one position after auto-buy"
    pid = positions[0]["position_id"]
    r = s.get(f"{API}/client/positions/{pid}", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["position"]["position_id"] == pid
    assert isinstance(body["events"], list) and body["events"]
    types = {e["type"] for e in body["events"]}
    assert "subscribe" in types, f"events missing subscribe: {body['events']}"


# --- non-matured term cannot redeem ---
def test_redeem_non_matured_term_returns_400():
    s = _client_session()
    # Onramp -> auto-buy creates a liquid position that consumes the balance.
    _create_and_settle_onramp(s, 200_000)
    # Redeem ALL active liquid positions in this org to free USDC balance
    # (in-memory mock state accumulates many subscribes from prior test runs).
    positions = s.get(f"{API}/client/positions", timeout=10).json()["items"]
    for p in positions:
        if p["product_id"] == "liquid_v1" and p["status"] == "active":
            s.post(f"{API}/client/positions/{p['position_id']}/redeem", timeout=10)
    bal = s.get(f"{API}/client/balances", timeout=10).json()
    if bal["available_usdc"] < 150:
        pytest.skip(
            f"balance still insufficient for term_30 (bal={bal['available_usdc']}) "
            f"— accumulated subscribes from prior runs exceed onramps+redeems"
        )
    buy = s.post(f"{API}/client/positions",
                  json={"product_id": "term_30", "amount_usdc": 150},
                  timeout=10)
    assert buy.status_code == 200, buy.text
    pid = buy.json()["position"]["position_id"]
    r = s.post(f"{API}/client/positions/{pid}/redeem", timeout=10)
    assert r.status_code == 400, r.text
    assert "matur" in r.text.lower()


# --- finpact (KYB pending) blocked ---
def test_finpact_kyb_pending_cannot_buy():
    s = _finpact_session()
    r = s.post(f"{API}/client/positions",
               json={"product_id": "liquid_v1", "amount_usdc": 100},
               timeout=10)
    assert r.status_code == 403, r.text


# --- accrual idempotency ---
def test_accrual_is_idempotent_per_day():
    sys.path.insert(0, "/app/backend")
    from dotenv import load_dotenv  # type: ignore
    load_dotenv("/app/backend/.env")
    from jobs.accrual import run_accrual_once
    from db import col, POSITIONS

    # Make sure we have at least one active position
    s = _client_session()
    _create_and_settle_onramp(s, 100_000)

    async def _doit():
        first  = await run_accrual_once()
        # Snapshot accrued_interest before second run
        active = await col(POSITIONS).find(
            {"is_deleted": False, "status": "active"},
            {"_id": 0, "position_id": 1, "accrued_interest": 1,
              "last_accrued_date": 1}).to_list(50)
        before = {p["position_id"]: p.get("accrued_interest", 0.0)
                   for p in active}
        second = await run_accrual_once()
        after_rows = await col(POSITIONS).find(
            {"position_id": {"$in": list(before.keys())}},
            {"_id": 0, "position_id": 1, "accrued_interest": 1}).to_list(50)
        after = {p["position_id"]: p.get("accrued_interest", 0.0)
                  for p in after_rows}
        return first, second, before, after

    first, second, before, after = asyncio.run(_doit())
    assert "updated" in first and "updated" in second
    # Second run on the same UTC day should be a no-op for already-accrued
    assert second["updated"] == 0, (
        f"expected idempotent second-run, got {second}")
    for pid, val in before.items():
        assert abs(after.get(pid, 0.0) - val) < 1e-9, (
            f"accrued_interest changed on second run for {pid}: "
            f"{val} -> {after.get(pid)}")
