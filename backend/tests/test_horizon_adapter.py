"""PR1 — Unit tests for the Horizon adapter (Mock + Factory).

Real adapter is NOT exercised here (it requires network egress to
Horizon, which is blocked from preview/CI). The Real adapter is covered
indirectly via type-checking + smoke health endpoint in PR2.

Run:
    cd /app/backend && python -m pytest tests/test_horizon_adapter.py -v
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# Make backend importable when pytest is invoked from /app/backend
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.horizon import (  # noqa: E402
    HorizonError, Payment, get_adapter, reset_adapter_cache,
)
from integrations.horizon.mock import MockHorizonAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture-loading
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_adapter_between_tests():
    """The factory caches the adapter — tests can mutate the mock's
    in-memory stream so we wipe the cache before and after each test."""
    os.environ.pop("HORIZON_MOCK_FIXTURE", None)
    os.environ["HORIZON_MODE"] = "mock"
    reset_adapter_cache()
    yield
    reset_adapter_cache()


@pytest.mark.asyncio
async def test_mock_loads_default_fixture():
    a = get_adapter()
    assert a.mode == "mock"
    health = await a.health_check()
    assert health["ok"] is True
    # The default fixture has 7 records; failed ones are NOT filtered at
    # load time (real Horizon filters via `include_failed=false` — that
    # is the watcher's job, not the adapter's).
    assert health["payments_loaded"] == 7


@pytest.mark.asyncio
async def test_factory_returns_singleton():
    a = get_adapter()
    b = get_adapter()
    assert a is b


@pytest.mark.asyncio
async def test_factory_reset_makes_new_instance():
    a = get_adapter()
    reset_adapter_cache()
    b = get_adapter()
    assert a is not b


@pytest.mark.asyncio
async def test_fetch_from_beginning():
    a = get_adapter()
    page = await a.fetch_payments(cursor="", limit=200)
    assert len(page.payments) == 7
    # Cursor advances to the last item's paging_token
    assert page.next_cursor == page.payments[-1].paging_token
    # Ordered ascending
    tokens = [p.paging_token for p in page.payments]
    assert tokens == sorted(tokens)


@pytest.mark.asyncio
async def test_fetch_with_cursor_is_strict_greater_than():
    a = get_adapter()
    # Take the first item only, then page from its cursor.
    first_page = await a.fetch_payments(cursor="", limit=1)
    assert len(first_page.payments) == 1
    first_token = first_page.payments[0].paging_token
    second_page = await a.fetch_payments(cursor=first_token, limit=200)
    # 7 total - 1 already consumed = 6 remaining
    assert len(second_page.payments) == 6
    # First item of second page is strictly after the cursor
    assert second_page.payments[0].paging_token > first_token


@pytest.mark.asyncio
async def test_fetch_empty_page_keeps_cursor():
    a = get_adapter()
    # Use a cursor higher than any fixture entry
    page = await a.fetch_payments(cursor="9999999999999999999", limit=200)
    assert page.payments == []
    assert page.next_cursor == "9999999999999999999"


@pytest.mark.asyncio
async def test_limit_clamps_to_200():
    a = get_adapter()
    page = await a.fetch_payments(cursor="", limit=10000)
    assert len(page.payments) <= 200


@pytest.mark.asyncio
async def test_payment_normalization_fields():
    a = get_adapter()
    page = await a.fetch_payments(cursor="", limit=1)
    p = page.payments[0]
    assert isinstance(p, Payment)
    assert p.tx_hash and len(p.tx_hash) == 64
    assert p.to.startswith("G") and len(p.to) == 56
    assert p.asset_code == "USDC"
    assert p.asset_issuer.startswith("G")
    assert p.amount == "100.0000000"
    assert p.memo == "1739100000"
    assert p.memo_type == "text"
    assert p.successful is True


@pytest.mark.asyncio
async def test_native_xlm_payment_normalizes_with_empty_asset_code():
    a = get_adapter()
    page = await a.fetch_payments(cursor="", limit=200)
    xlm = [p for p in page.payments if p.amount == "10.0000000"
              and p.asset_code == ""]
    assert len(xlm) == 1
    assert xlm[0].asset_issuer == ""


@pytest.mark.asyncio
async def test_path_payment_strict_receive_accepted():
    a = get_adapter()
    page = await a.fetch_payments(cursor="", limit=200)
    path = [p for p in page.payments
              if p.raw.get("type") == "path_payment_strict_receive"]
    assert len(path) == 1
    assert path[0].amount == "75.0000000"


@pytest.mark.asyncio
async def test_inject_payment_appears_in_next_fetch():
    a = get_adapter()
    assert isinstance(a, MockHorizonAdapter)
    initial = await a.fetch_payments(cursor="", limit=200)
    a.inject_payment({
        "id": "1729200000000000999",
        "paging_token": "1729200000000000999",
        "type": "payment",
        "transaction_hash": ("9" * 64),
        "transaction_successful": True,
        "from": "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN",
        "to": "GDHQFTLNKHSRECW7FTOBXDDAZU2JTJGEB3WVWRMBV6ROSGCCGG4DRLDF",
        "asset_code": "USDC",
        "asset_issuer": "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN",
        "asset_type": "credit_alphanum4",
        "amount": "1.0000000",
        "created_at": "2026-02-09T11:00:00Z",
        "memo": "test-inject",
        "memo_type": "text",
    })
    later = await a.fetch_payments(cursor=initial.next_cursor, limit=200)
    assert len(later.payments) == 1
    assert later.payments[0].tx_hash == "9" * 64
    assert later.payments[0].memo == "test-inject"


@pytest.mark.asyncio
async def test_unsupported_op_type_raises_at_normalization():
    from integrations.horizon.mock import _normalize
    with pytest.raises(HorizonError):
        _normalize({"type": "account_merge",
                       "paging_token": "1", "transaction_hash": "x" * 64,
                       "to": "G" + "A" * 55})


@pytest.mark.asyncio
async def test_missing_required_fields_raises():
    from integrations.horizon.mock import _normalize
    with pytest.raises(HorizonError):
        _normalize({"type": "payment",
                       "paging_token": "1",
                       "transaction_hash": "",   # missing
                       "to": "G" + "A" * 55,
                       "amount": "1",
                       "asset_code": "USDC",
                       "asset_issuer": "G" + "B" * 55})


@pytest.mark.asyncio
async def test_missing_fixture_file_starts_empty(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    os.environ["HORIZON_MOCK_FIXTURE"] = str(missing)
    reset_adapter_cache()
    a = get_adapter()
    h = await a.health_check()
    assert h["payments_loaded"] == 0
    page = await a.fetch_payments(cursor="", limit=10)
    assert page.payments == []
    assert page.next_cursor == ""


@pytest.mark.asyncio
async def test_malformed_fixture_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    os.environ["HORIZON_MOCK_FIXTURE"] = str(bad)
    reset_adapter_cache()
    with pytest.raises(HorizonError):
        get_adapter()


@pytest.mark.asyncio
async def test_custom_fixture_via_env(tmp_path):
    fixture = tmp_path / "custom.json"
    fixture.write_text(json.dumps([{
        "id": "100",
        "paging_token": "100",
        "type": "payment",
        "transaction_hash": "a" * 64,
        "transaction_successful": True,
        "from": "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN",
        "to": "GDHQFTLNKHSRECW7FTOBXDDAZU2JTJGEB3WVWRMBV6ROSGCCGG4DRLDF",
        "asset_code": "USDC",
        "asset_issuer": "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN",
        "asset_type": "credit_alphanum4",
        "amount": "1.0000000",
        "created_at": "2026-02-09T11:00:00Z",
    }]))
    os.environ["HORIZON_MOCK_FIXTURE"] = str(fixture)
    reset_adapter_cache()
    a = get_adapter()
    h = await a.health_check()
    assert h["payments_loaded"] == 1
    assert h["fixture"] == str(fixture)


@pytest.mark.asyncio
async def test_factory_picks_real_mode():
    os.environ["HORIZON_MODE"] = "real"
    os.environ["STELLAR_HORIZON_URL"] = "https://horizon.stellar.org"
    reset_adapter_cache()
    a = get_adapter()
    assert a.mode == "real"
    # We don't actually call Horizon — just type-assert. Network egress
    # is not available in preview/CI.
    from integrations.horizon.real import RealHorizonAdapter
    assert isinstance(a, RealHorizonAdapter)


@pytest.mark.asyncio
async def test_real_adapter_rejects_bad_base_url():
    os.environ["HORIZON_MODE"] = "real"
    os.environ["STELLAR_HORIZON_URL"] = "not-a-url"
    reset_adapter_cache()
    with pytest.raises(HorizonError):
        get_adapter()
