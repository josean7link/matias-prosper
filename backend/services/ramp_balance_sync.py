"""Shared helper: refresh `ramp_balances` for an org from the ramp provider.

Historically only `GET /ramp/accounts/{end_customer_id}/balances` upserted
into `ramp_balances`. That meant if the client never opened that page but
made a CVU deposit, `ramp_balances` stayed empty and the dashboard showed
0 ARSa — even though the funds were in the org's ramp account.

This module centralises the "pull balances from provider + upsert local
cache" step so it can be triggered from any read path that needs fresh
numbers (movements sync, dashboard summary, admin panels).

The function is:
  * Best-effort: never raises to the caller. Providers fail intermittently
    (rate limits, upstream 502s); the UI already falls back to whatever
    is cached.
  * Idempotent: the collection has a unique index on
    (ramp_account_id, asset, chain) — repeated calls are safe.
  * Provider-agnostic: uses `ramp.registry.get_registry().resolve(org_id)`
    so future providers (Alfred, mock) work without changes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from db import RAMP_ACCOUNTS, RAMP_BALANCES, col
from ramp.provider import NotSupportedByProvider
from ramp.registry import get_registry

logger = logging.getLogger("prosper.ramp.balance_sync")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _asset_code(asset: Any) -> str:
    return (asset.value if hasattr(asset, "value") else str(asset)).lower()


def _chain_code(chain: Any) -> str:
    return (chain.value if hasattr(chain, "value") else str(chain)).lower()


async def refresh_ramp_balances_for_org(org_id: str) -> dict[str, Any]:
    """Fetch the org's ramp account balances from the provider and upsert
    them into `ramp_balances`. Returns a small summary for observability.

    No-op (returns `{skipped: True, ...}`) when the org has no ramp
    account or no `provider_user_id` yet — that's the normal state for
    orgs that haven't finished onboarding.
    """
    acc = await col(RAMP_ACCOUNTS).find_one(
        {"org_id": org_id, "is_deleted": {"$ne": True}},
        {"_id": 0, "id": 1, "provider": 1, "provider_user_id": 1})
    if not acc or not acc.get("provider_user_id"):
        return {"skipped": True, "reason": "no_ramp_account"}

    try:
        provider = await get_registry().resolve(org_id=org_id)
        balances = await provider.get_balances(
            andes_user_id=acc["provider_user_id"])
    except NotSupportedByProvider as e:
        logger.info("refresh_ramp_balances skipped org=%s: %s", org_id, e)
        return {"skipped": True, "reason": "not_supported"}
    except Exception as e:                                    # noqa: BLE001
        logger.warning("refresh_ramp_balances failed org=%s: %s", org_id, e)
        return {"skipped": True, "reason": "provider_error",
                 "error": str(e)[:200]}

    now = _iso_now()
    written = 0
    for b in balances or []:
        asset = _asset_code(b.asset)
        chain = _chain_code(b.chain)
        await col(RAMP_BALANCES).update_one(
            {"ramp_account_id": acc["id"], "asset": asset, "chain": chain},
            {"$set": {
                "org_id":          org_id,
                "ramp_account_id": acc["id"],
                "asset":           asset,
                "chain":           chain,
                "balance":         str(b.balance),
                "as_of":           now,
            }},
            upsert=True)
        written += 1

    return {"skipped": False, "ramp_account_id": acc["id"],
             "written": written, "as_of": now}
