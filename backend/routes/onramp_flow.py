"""Sprint 12.4 — Onramp E2E real flow helpers.

Centralises:
  - `ensure_org_prosper_wallet`: idempotent wallet provisioning for an org.
  - `alfred_status_to_internal`: maps Penny webhook status enums to our
    internal {pending, confirmed, completed, failed} buckets.

Both helpers are safe to call when running against mocks — they Just Work
because `prosper_adapter()` returns the mock or the real adapter based on
`PROSPER_MODE`.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from db import col, ORGANIZATIONS
from integrations.prosper import get_adapter as prosper_adapter, ProsperError

logger = logging.getLogger("prosper.onramp")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_org_prosper_wallet(org_id: str) -> dict:
    """Idempotently ensure an organization has a Prosper wallet provisioned.

    Returns a dict ``{prosper_user_id, stellar_address, created}`` — `created`
    is True iff we just provisioned it (and persisted to Mongo).

    Strategy:
        * If the org doc already has `prosper_user_id`, return early.
        * Otherwise call `POST /api/v1/prosper/users/new` with our org_id as
          the `userReferenceId` and a fresh UUID as `prosperTxId`.
        * On success, persist {prosper_user_id, stellar_address} on the org.

    Raises:
        ProsperError if the live adapter rejects the call.
    """
    org = await col(ORGANIZATIONS).find_one({"org_id": org_id},
                                              {"_id": 0,
                                                "org_id": 1,
                                                "prosper_user_id": 1,
                                                "stellar_address": 1})
    # IMPORTANT: orgs without `prosper_user_id` project to `{"org_id": …}`
    # only — never `None`. We check `is None` explicitly so an empty
    # projection doesn't incorrectly raise "not found".
    if org is None:
        raise ValueError(f"Org {org_id} not found")

    if org.get("prosper_user_id"):
        return {"prosper_user_id":  org["prosper_user_id"],
                 "stellar_address":  org.get("stellar_address") or "",
                 "created":          False}

    ptx = f"wallet_{org_id}_{secrets.token_hex(4)}"
    resp = await prosper_adapter().create_user_wallet(
        user_reference_id=org_id, prosper_tx_id=ptx)

    # The Prosper response shape lives in `WalletResp.raw`. We persist:
    # `prosper_user_id`  → the protocol-side identifier (raw.userId / .prosperId).
    # `stellar_address`  → the public XLM address.
    raw = getattr(resp, "raw", {}) or {}
    prosper_user_id = (raw.get("prosperUserId")
                        or raw.get("userId")
                        or raw.get("prosperId")
                        or org_id)  # fallback to our own ref so retries are no-ops
    stellar_address = (resp.address
                        or raw.get("walletAddress")
                        or raw.get("address")
                        or "")

    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": {"prosper_user_id":  prosper_user_id,
                    "stellar_address":  stellar_address,
                    "prosper_provisioned_at": _iso_now(),
                    "updated_at":       _iso_now()}})
    logger.info("Provisioned Prosper wallet for org=%s · prosper_user=%s · addr=%s",
                 org_id, prosper_user_id, stellar_address[:12])
    return {"prosper_user_id":  prosper_user_id,
             "stellar_address":  stellar_address,
             "created":          True}


# ---------------------------------------------------------------------------
# Alfred status mapping — translates Penny webhook enums to our internal
# vocabulary. Sources:
#   1. Phase 8 mock: `order.confirmed`, `order.completed`, `order.failed`,
#      `order.pending`.
#   2. Penny live (`type` field): FIAT_DEPOSIT_RECEIVED, TRADE_COMPLETED,
#      ON_CHAIN_INITIATED, ON_CHAIN_COMPLETED, FAILED, EXPIRED.
# ---------------------------------------------------------------------------
# Buckets used internally:
#   pending    → fiat received, on its way; user shouldn't act yet.
#   confirmed  → funds settled in our control; safe to trigger auto-buy.
#   completed  → fully settled, on-chain too (terminal happy).
#   failed     → terminal error.
_STATUS_MAP: dict[str, str] = {
    # Phase 8 mock (backwards compat)
    "order.pending":        "pending",
    "order.confirmed":      "confirmed",
    "order.completed":      "completed",
    "order.failed":         "failed",
    # Penny live
    "fiat_deposit_received": "pending",
    "trade_completed":        "confirmed",
    "on_chain_initiated":     "confirmed",
    "on_chain_completed":     "completed",
    "failed":                 "failed",
    "expired":                "failed",
    "cancelled":              "failed",
}


def alfred_status_to_internal(event_type: str) -> str | None:
    """Map an Alfred webhook `type` to one of our 4 internal buckets.

    Returns ``None`` when the event isn't actionable (e.g. metadata-only).
    Case-insensitive; gracefully handles unknown enums by returning None
    (the caller logs and skips, never crashes).
    """
    if not event_type:
        return None
    return _STATUS_MAP.get(event_type.strip().lower())
