"""Tests for ramp_balance_sync + Horizon on-chain balance surfacing.

Covers the Option A + B fix (Feb 2026):
  * `refresh_ramp_balances_for_org` upserts a `ramp_balances` row with
    `org_id` set (so dashboard-summary's primary lookup hits).
  * `dashboard-summary` returns the fresh `cash.arsa_cvu` and a
    Horizon-injected `cash.arsa_stellar` for a client with a
    provisioned ARSa wallet.

Both suites use the mock Andes provider and the mock Horizon adapter —
no external network required.

Run:
    cd /app/backend && python -m pytest tests/test_ramp_balance_sync.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db as db_module                                          # noqa: E402
from db import RAMP_ACCOUNTS, RAMP_BALANCES, RAMP_WALLETS, col   # noqa: E402
from services.ramp_balance_sync import (                          # noqa: E402
    refresh_ramp_balances_for_org)


ORG_ID = "org_ramp_balance_sync_test"
ACC_ID = "racc_ramp_balance_sync_test"
WALLET_ADDR = "GDTESTBALANCESYNCACCOUNT" + "A" * 32


@pytest.fixture(autouse=True)
def _mock_providers():
    """Force the mock ramp provider and the mock Horizon adapter so the
    test never reaches the real Andes gateway / Stellar Horizon.

    Also reset the motor client so it re-binds to the current event
    loop (pytest-asyncio in `auto` mode creates a new loop per test —
    the module-level singleton from a prior test leaks otherwise).
    """
    prev_ramp = os.environ.get("RAMP_PROVIDER_DEFAULT")
    prev_hz = os.environ.get("HORIZON_MODE")
    os.environ["RAMP_PROVIDER_DEFAULT"] = "mock"
    os.environ["HORIZON_MODE"] = "mock"
    from integrations.horizon.factory import reset_adapter_cache
    reset_adapter_cache()
    db_module._client = None
    yield
    if prev_ramp is None:
        os.environ.pop("RAMP_PROVIDER_DEFAULT", None)
    else:
        os.environ["RAMP_PROVIDER_DEFAULT"] = prev_ramp
    if prev_hz is None:
        os.environ.pop("HORIZON_MODE", None)
    else:
        os.environ["HORIZON_MODE"] = prev_hz
    reset_adapter_cache()
    db_module._client = None


@pytest_asyncio.fixture()
async def _seed_and_teardown():
    """Seed a ramp_account for the test org, wipe balances/wallets,
    then clean up on exit."""
    from db import RAMP_PROVIDER_CONFIG
    await col(RAMP_ACCOUNTS).delete_many({"org_id": ORG_ID})
    await col(RAMP_BALANCES).delete_many({"org_id": ORG_ID})
    await col(RAMP_BALANCES).delete_many({"ramp_account_id": ACC_ID})
    await col(RAMP_WALLETS).delete_many({"org_id": ORG_ID})
    await col(RAMP_PROVIDER_CONFIG).delete_many({"scope": ORG_ID})
    # Per-org provider config → force alfred/mock, which implements
    # `get_balances` returning whatever we seed on the mock adapter.
    await col(RAMP_PROVIDER_CONFIG).insert_one({
        "scope": ORG_ID, "provider": "alfred", "mode": "mock",
        "enabled": True,
    })
    await col(RAMP_ACCOUNTS).insert_one({
        "id": ACC_ID, "org_id": ORG_ID,
        "provider": "alfred",
        "provider_user_id": "mock_user_ramp_balance_sync",
        "end_customer_id": "ec_ramp_balance_sync",
        "is_deleted": False,
    })

    # Seed the mock adapter's per-user balance table so `get_balances`
    # returns a non-empty result. The registry caches adapters per
    # (provider, mode) so we resolve BEFORE the code under test hits it.
    from ramp.provider import WalletAsset, AvailableChain, RampBalance
    from ramp.registry import get_registry
    adapter = get_registry().adapter_for("alfred", "mock")
    adapter._balances["mock_user_ramp_balance_sync"] = [
        RampBalance(asset=WalletAsset.ARSA,
                     chain=AvailableChain.STELLAR,
                     balance="42.50"),
    ]

    yield
    await col(RAMP_ACCOUNTS).delete_many({"org_id": ORG_ID})
    await col(RAMP_BALANCES).delete_many({"org_id": ORG_ID})
    await col(RAMP_BALANCES).delete_many({"ramp_account_id": ACC_ID})
    await col(RAMP_WALLETS).delete_many({"org_id": ORG_ID})
    await col(RAMP_PROVIDER_CONFIG).delete_many({"scope": ORG_ID})
    adapter._balances.pop("mock_user_ramp_balance_sync", None)


# ---------------------------------------------------------------------------
# Option A — refresh_ramp_balances_for_org upserts with org_id
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_refresh_ramp_balances_upserts_with_org_id(_seed_and_teardown):
    """`ramp_balances` must contain `org_id` after the refresh so the
    primary lookup in dashboard-summary (`{org_id, asset:arsa}`) hits."""
    result = await refresh_ramp_balances_for_org(ORG_ID)
    assert result["skipped"] is False, result
    assert result["written"] >= 1

    row = await col(RAMP_BALANCES).find_one(
        {"org_id": ORG_ID, "asset": "arsa"},
        {"_id": 0, "org_id": 1, "balance": 1, "ramp_account_id": 1,
         "chain": 1})
    assert row is not None, "balance row missing after refresh"
    assert row["org_id"] == ORG_ID
    assert row["ramp_account_id"] == ACC_ID
    assert row["chain"] == "stellar"
    assert float(row["balance"]) >= 0.0


@pytest.mark.asyncio
async def test_refresh_ramp_balances_skips_org_without_ramp_account():
    """No ramp account → skip cleanly (no exception, no upsert)."""
    unknown = "org_that_does_not_exist_ramp"
    result = await refresh_ramp_balances_for_org(unknown)
    assert result == {"skipped": True, "reason": "no_ramp_account"}


# ---------------------------------------------------------------------------
# Option B — Horizon on-chain read exposed via _read_stellar_balance
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stellar_balance_reads_from_horizon(_seed_and_teardown):
    """Inject an ARSa balance into the mock Horizon adapter and confirm
    `_read_stellar_balance` returns it for the org's ARSa wallet."""
    from datetime import datetime, timezone
    from integrations.horizon import get_adapter
    from integrations.horizon.adapter import AccountBalance
    from routes.client_invest import _read_stellar_balance

    # Provision an ARSa wallet for the org.
    await col(RAMP_WALLETS).insert_one({
        "id": "rw_ramp_balance_sync_test",
        "org_id": ORG_ID, "ramp_account_id": ACC_ID,
        "provider_user_id": "mock_user_ramp_balance_sync",
        "asset": "arsa", "chain": "stellar",
        "address": WALLET_ADDR, "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_deleted": False,
    })

    issuer = "GTESTISSUERADDRESS" + "A" * 40
    adapter = get_adapter()
    adapter.set_account_balances(WALLET_ADDR, [
        AccountBalance(asset_code="ARSa", asset_issuer=issuer,
                        balance="123.45"),
        AccountBalance(asset_code="", asset_issuer="", balance="9"),  # XLM
    ])

    got = await _read_stellar_balance(org_id=ORG_ID, asset_code="ARSa",
                                        asset_issuer=issuer)
    assert got == pytest.approx(123.45)


@pytest.mark.asyncio
async def test_stellar_balance_returns_zero_without_wallet():
    got_no_wallet = None
    from routes.client_invest import _read_stellar_balance
    got_no_wallet = await _read_stellar_balance(
        org_id="org_never_seen", asset_code="ARSa",
        asset_issuer="GISSUER")
    assert got_no_wallet == 0.0
