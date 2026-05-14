"""Live integration test against the Prosper Stellar Protocol sandbox.

Skipped when `PROSPER_MODE` isn't a live mode or creds are missing.
"""
from __future__ import annotations
import os
import asyncio

import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

pytestmark = pytest.mark.live


def _prosper_ready() -> bool:
    return (
        os.environ.get("PROSPER_MODE") in {"development", "production"}
        and bool(os.environ.get("PROSPER_API_USER"))
        and bool(os.environ.get("PROSPER_API_PASS"))
    )


@pytest.mark.skipif(not _prosper_ready(),
                     reason="Prosper sandbox creds not configured")
def test_prosper_login_and_health_live():
    from integrations.prosper.factory import reset_cache, get_adapter
    reset_cache()
    adapter = get_adapter()
    assert type(adapter).__name__ == "RealProsperAdapter"
    res = asyncio.run(adapter.health_check())
    assert res["ok"] is True, f"Prosper health failed: {res}"
    assert "jwt_expires_at" in res
