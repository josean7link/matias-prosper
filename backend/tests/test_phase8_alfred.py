"""Phase 8 — Alfred onramp/offramp + webhook tests (mock mode)."""
from __future__ import annotations
import hashlib
import hmac
import json
import os

import pytest
import requests

BASE = os.environ.get("PROSPER_API_BASE", "http://localhost:8001/api")
API  = f"{BASE}/v1"
SECRET = os.environ.get("ALFRED_WEBHOOK_SECRET", "mock_secret_change_me")


def _client_session() -> requests.Session:
    """Login as approved client (Alemany) and return a session with cookie."""
    s = requests.Session()
    r = s.get(f"{API}/auth/dev-login",
              params={"email": "client.admin@alemany.capital", "next": "/"},
              allow_redirects=False, timeout=10)
    assert r.status_code in (302, 303), f"dev-login {r.status_code}"
    return s


def _pending_session() -> requests.Session:
    """Login as a client whose org is NOT approved (Finpact)."""
    s = requests.Session()
    s.get(f"{API}/auth/dev-login",
          params={"email": "client.admin@finpact.io", "next": "/"},
          allow_redirects=False, timeout=10)
    return s


def _sign(payload: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Quote + onramp flow
# ---------------------------------------------------------------------------
def test_onramp_quote_and_create_with_mock():
    s = _client_session()
    q = s.post(f"{API}/client/onramp/quote",
               json={"source_currency": "ARS", "source_amount": 100_000},
               timeout=10).json()
    assert q["quote_id"].startswith("qt_mock_")
    assert q["target_currency"] == "USDC"
    assert q["mode"] == "mock"
    assert 90 < q["target_amount"] < 100   # ARS 100k → ~96.6 USDC

    r = s.post(f"{API}/client/onramp/orders",
               json={"quote_id": q["quote_id"],
                     "source_currency": "ARS", "source_amount": 100_000,
                     "payment_method": "transfer"},
               timeout=10)
    assert r.status_code == 200, r.text
    order = r.json()["order"]
    assert order["status"] == "pending"
    assert order["alfred_id"].startswith("alf_on_")
    assert order["mode"] == "mock"
    assert order["expected_usdc"] > 90


def test_onramp_blocked_when_kyb_not_approved():
    s = _pending_session()
    r = s.post(f"{API}/client/onramp/quote",
               json={"source_currency": "ARS", "source_amount": 1000}, timeout=10)
    assert r.status_code == 403
    assert "KYB" in r.text


def test_onramp_caps_validation():
    """Alemany has subscribe_daily_cap_usd ≈ 1M. Try to onramp 10M USDC-equivalent."""
    s = _client_session()
    # 10B ARS ≈ 10M USDC (well above any cap)
    huge = 10_000_000_000
    q = s.post(f"{API}/client/onramp/quote",
               json={"source_currency": "ARS", "source_amount": huge},
               timeout=10).json()
    r = s.post(f"{API}/client/onramp/orders",
               json={"quote_id": q["quote_id"],
                     "source_currency": "ARS",
                     "source_amount": huge,
                     "payment_method": "transfer"}, timeout=10)
    assert r.status_code == 400, r.text
    assert "cap" in r.text.lower()


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------
def test_webhook_rejects_invalid_signature():
    payload = json.dumps({"event_id": "evt_bad", "type": "order.confirmed",
                          "order_id": "alf_x"}).encode()
    r = requests.post(f"{API}/webhooks/alfred", data=payload,
                      headers={"Content-Type": "application/json",
                               "X-Alfred-Signature": "deadbeef"},
                      timeout=10)
    assert r.status_code == 401
    assert "HMAC" in r.text or "signature" in r.text.lower()


def test_webhook_accepts_valid_signature_and_is_idempotent():
    import uuid
    event_id = f"evt_test_idem_{uuid.uuid4().hex[:12]}"
    payload = json.dumps({
        "event_id": event_id,
        "type":     "order.confirmed",
        "order_id": "alf_test_nonexistent",
        "settled_amount": 100,
    }).encode()
    sig = _sign(payload)
    r1 = requests.post(f"{API}/webhooks/alfred", data=payload,
                        headers={"Content-Type": "application/json",
                                 "X-Alfred-Signature": sig}, timeout=10)
    assert r1.status_code == 200, r1.text
    assert r1.json()["event_id"] == event_id

    # Replay — must be idempotent
    r2 = requests.post(f"{API}/webhooks/alfred", data=payload,
                        headers={"Content-Type": "application/json",
                                 "X-Alfred-Signature": sig}, timeout=10)
    assert r2.status_code == 200
    assert r2.json().get("idempotent") is True


# ---------------------------------------------------------------------------
# Offramp
# ---------------------------------------------------------------------------
def test_offramp_quote():
    s = _client_session()
    q = s.post(f"{API}/client/offramp/quote",
               json={"usdc_amount": 100, "target_currency": "ARS"},
               timeout=10).json()
    assert q["mode"] == "mock"
    assert q["target_currency"] == "ARS"
    assert q["target_amount"] > 100_000   # 100 USDC -> > 100k ARS


def test_offramp_rejects_mismatched_holder():
    s = _client_session()
    q = s.post(f"{API}/client/offramp/quote",
               json={"usdc_amount": 50, "target_currency": "ARS"},
               timeout=10).json()
    r = s.post(f"{API}/client/offramp/orders", json={
        "quote_id": q["quote_id"],
        "usdc_amount": 50,
        "target_currency": "ARS",
        "source": "balance",
        "bank_account": {
            "holder_name":  "Otra Persona SA",   # NOT Alemany Capital
            "country":      "AR",
            "cbu_or_iban":  "1234567890123456789012",
            "bank_name":    "Test Bank",
        },
    }, timeout=10)
    assert r.status_code == 400, r.text
    assert "titular" in r.text.lower() or "holder" in r.text.lower() or \
           "razón social" in r.text.lower()


def test_offramp_create_succeeds_with_matching_holder():
    s = _client_session()
    q = s.post(f"{API}/client/offramp/quote",
               json={"usdc_amount": 50, "target_currency": "ARS"},
               timeout=10).json()
    r = s.post(f"{API}/client/offramp/orders", json={
        "quote_id": q["quote_id"],
        "usdc_amount": 50,
        "target_currency": "ARS",
        "source": "balance",
        "bank_account": {
            "holder_name":  "Alemany Capital",
            "country":      "AR",
            "cbu_or_iban":  "1234567890123456789012",
            "bank_name":    "Test Bank",
        },
    }, timeout=10)
    assert r.status_code == 200, r.text
    order = r.json()["order"]
    assert order["alfred_id"].startswith("alf_off_")
    assert order["status"] == "pending"
    assert any(s["key"] == "alfred_sent" and s["done"] for s in order["timeline"])


# ---------------------------------------------------------------------------
# Mock-settle + GET-order auto-refresh + transactions history
# ---------------------------------------------------------------------------
def test_mock_settle_and_get_order_auto_refresh_and_history():
    s = _client_session()
    q = s.post(f"{API}/client/onramp/quote",
               json={"source_currency": "ARS", "source_amount": 50_000},
               timeout=10).json()
    r = s.post(f"{API}/client/onramp/orders",
               json={"quote_id": q["quote_id"],
                     "source_currency": "ARS", "source_amount": 50_000,
                     "payment_method": "transfer"}, timeout=10)
    order = r.json()["order"]
    onramp_id, alfred_id = order["onramp_id"], order["alfred_id"]
    assert order["checkout_url"], "checkout_url should be filled"

    # Force settle via mock endpoint
    ms = requests.post(f"{API}/alfred/mock-settle/{alfred_id}", timeout=10)
    assert ms.status_code == 200, ms.text
    assert ms.json()["status"] == "confirmed"

    # GET order should now show confirmed + auto-refresh status (also exercises adapter)
    g = s.get(f"{API}/client/onramp/orders/{onramp_id}", timeout=10)
    assert g.status_code == 200
    got = g.json()["order"]
    assert got["status"] == "confirmed"

    # History should include this onramp tx
    h = s.get(f"{API}/client/transactions/history",
              params={"tx_type": "onramp", "status": "confirmed"}, timeout=10)
    assert h.status_code == 200
    items = h.json()["items"]
    assert any(it.get("metadata", {}).get("onramp_id") == onramp_id for it in items)


def test_history_requires_auth():
    r = requests.get(f"{API}/client/transactions/history", timeout=10)
    assert r.status_code in (401, 403)
