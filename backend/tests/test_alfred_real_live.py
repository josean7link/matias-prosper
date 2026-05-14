"""Live integration test against Alfred Pay Penny sandbox.

Skipped automatically when `ALFRED_MODE != sandbox/production` or when the
required env vars are missing. Marked `live` so CI can opt-out via
`pytest -m 'not live'`.
"""
from __future__ import annotations
import os
import asyncio

import pytest

pytestmark = pytest.mark.live


def _alfred_ready() -> bool:
    return (
        os.environ.get("ALFRED_MODE") in {"sandbox", "production"}
        and bool(os.environ.get("ALFRED_API_KEY"))
        and bool(os.environ.get("ALFRED_API_SECRET"))
    )


@pytest.mark.skipif(not _alfred_ready(),
                     reason="Alfred sandbox creds not configured")
def test_alfred_real_adapter_quote_live():
    from integrations.alfred.factory import reset_cache, get_adapter
    reset_cache()
    adapter = get_adapter()
    assert type(adapter).__name__ == "RealAlfredAdapter", \
        f"Expected RealAlfredAdapter, got {type(adapter).__name__}"

    quote = asyncio.run(adapter.get_quote(
        direction="onramp",
        source_currency="ARS",
        source_amount=35_000,
        target_currency="USDC",
    ))
    assert quote.quote_id, "Quote did not return a quoteId"
    assert quote.target_amount > 0, "Quote target amount must be positive"
    assert quote.rate > 0, "Quote rate must be positive"
    assert quote.mode == "sandbox"
    # Sanity: 35,000 ARS at a real rate ≥ 500 should yield ≥ 5 USDC
    assert quote.target_amount > 5


@pytest.mark.skipif(not _alfred_ready(),
                     reason="Alfred sandbox creds not configured")
def test_alfred_health_check_live():
    from integrations.alfred.factory import reset_cache, get_adapter
    reset_cache()
    adapter = get_adapter()
    res = asyncio.run(adapter.health_check())
    assert res["ok"] is True, f"Alfred health failed: {res}"
    assert res["mode"] == "sandbox"
