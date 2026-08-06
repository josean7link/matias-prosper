"""Sprint 12.4 / Phase CMS — Onramp E2E real flow helpers.

Centralises:
  - `ensure_org_prosper_wallet(org_id, modality)`: idempotent wallet
    provisioning for an org × modality pair. The CMS protocol assigns ONE
    wallet per (prosperId, modality), so an org operating both `end` and
    `month` gets TWO distinct Stellar wallets — stored as an array on the
    organization doc.
  - `alfred_status_to_internal`: maps Penny webhook status enums to our
    internal {pending, confirmed, completed, failed} buckets.

Both helpers are safe to call when running against mocks — they Just Work
because `prosper_adapter()` returns the mock or the real adapter based on
`PROSPER_MODE`.

P0 migration (Feb 2026):
  • Wallets are no longer a singleton field on the org doc; they live in
    `organizations.prosper_wallets: [{modality, address, provisioned_at, ...}]`.
  • The customer-level memo is NO LONGER generated locally — the Prosper
    smart contract emits the memo (Unix timestamp) when it sees the
    incoming transfer. Reading the memo lives in the staking poller
    (`jobs/staking_sync.py`).
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone

from db import col, ORGANIZATIONS
from integrations.prosper import get_adapter as prosper_adapter

logger = logging.getLogger("prosper.onramp")

# Modalities recognised by the CMS protocol.
VALID_MODALITIES = ("end", "month")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_modality() -> str:
    m = (os.environ.get("PROSPER_DEFAULT_CASHIN") or "end").lower()
    return m if m in VALID_MODALITIES else "end"


def _is_valid_stellar_address(addr: str | None) -> bool:
    """Stellar account addresses start with 'G' and are 56 chars (base32).

    Used to discard legacy placeholders (e.g. 'GA…ALEMANY') from seed/backfill
    paths — passing a non-Stellar address to a deposit UI would be a safety
    hazard (QR + Stellar Expert link would both be bogus).
    """
    if not addr or not isinstance(addr, str):
        return False
    a = addr.strip()
    if len(a) != 56 or not a.startswith("G"):
        return False
    # Stellar uses RFC4648 base32 (A-Z, 2-7). No lowercase, no padding.
    valid = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    return all(c in valid for c in a)


def _find_wallet(wallets: list[dict] | None, modality: str) -> dict | None:
    for w in (wallets or []):
        if (w or {}).get("modality") == modality:
            if not _is_valid_stellar_address((w or {}).get("address")):
                # Invalid placeholder — force re-provisioning.
                continue
            return w
    return None


async def ensure_org_prosper_wallet(org_id: str,
                                      modality: str | None = None) -> dict:
    """Idempotently ensure an org has a Prosper wallet for the given modality.

    Returns a dict
        {prosper_id, modality, stellar_address, prosper_user_id,
         created, wallets}

    `created` is True iff we just provisioned a NEW (modality) wallet.
    `wallets` is the full updated array stored on the org.

    Strategy (CMS protocol):
      1. Read `organizations.prosper_wallets`. If a wallet for the given
         `modality` already exists, return early.
      2. Otherwise call `POST /api/v1/cms/cashin` with the body
         `{prosperId: org_id, cashin: modality}`. The endpoint upserts the
         wallet at the partner side and returns the Stellar `address`.
      3. Append `{modality, address, provisioned_at, ...}` to the org's
         `prosper_wallets` array and persist `prosper_id` (= org_id),
         `prosper_id_source = "org_id_provisional"`.

    NOTE: the customer memo is intentionally NOT generated nor persisted
    here. The CMS smart contract emits the memo (a 10-digit Unix timestamp)
    when it observes the incoming transfer; the poller reads it back from
    `/api/v1/cms/staking[].memoStaking`.
    """
    modality = (modality or _default_modality()).lower()
    if modality not in VALID_MODALITIES:
        raise ValueError(f"Invalid modality {modality!r}; "
                          f"expected one of {VALID_MODALITIES}")

    org = await col(ORGANIZATIONS).find_one({"org_id": org_id},
                                              {"_id": 0,
                                                "org_id": 1,
                                                "prosper_id": 1,
                                                "prosper_wallets": 1,
                                                # Legacy singular fields (pre-P0):
                                                "prosper_user_id": 1,
                                                "stellar_address": 1,
                                                "prosper_cashin_modality": 1})
    if org is None:
        raise ValueError(f"Org {org_id} not found")

    wallets: list[dict] = list(org.get("prosper_wallets") or [])

    # Backfill from the legacy singular field if the array is empty and
    # we have a valid Stellar address on the doc. We skip non-Stellar
    # placeholders (e.g. seed leftovers like 'GA…ALEMANY') so the deposit
    # UI never surfaces a bogus address — those orgs lazy-provision via
    # /cms/cashin instead.
    if not wallets and _is_valid_stellar_address(org.get("stellar_address")):
        legacy = {"modality":        org.get("prosper_cashin_modality")
                                       or _default_modality(),
                   "address":         org.get("stellar_address"),
                   "prosper_user_id": org.get("prosper_user_id"),
                   "provisioned_at":  _iso_now(),
                   "source":          "legacy_backfill"}
        wallets = [legacy]
    elif not wallets and org.get("stellar_address"):
        logger.warning("ensure_org_prosper_wallet: discarding invalid legacy "
                          "stellar_address %r for org=%s (not Stellar format)",
                          org.get("stellar_address"), org_id)

    existing = _find_wallet(wallets, modality)
    if existing and existing.get("address"):
        return {"prosper_id":       org.get("prosper_id") or org_id,
                 "modality":         modality,
                 "stellar_address":  existing["address"],
                 "prosper_user_id":  existing.get("prosper_user_id") or "",
                 "created":          False,
                 "wallets":          wallets}

    # Provisional mapping: prosper_id := org_id. Pending partner confirmation
    # — `prosper_id_source` lets us flip to a partner-assigned id without a
    # schema migration.
    prosper_id = org.get("prosper_id") or org_id

    ptx = f"wallet_{org_id}_{modality}_{secrets.token_hex(4)}"
    try:
        resp = await prosper_adapter().create_user_wallet(
            user_reference_id=prosper_id, prosper_tx_id=ptx,
            modality=modality)
    except Exception as real_err:  # noqa: BLE001
        # In `development` PROSPER_MODE the dev API may reject
        # create_user_wallet (e.g. credentials lack admin scope). We fall
        # back to the local mock adapter so the alta E2E proceeds with a
        # deterministic wallet. This NEVER happens in `production` mode.
        mode = (os.environ.get("PROSPER_MODE") or "mock").lower()
        if mode == "production":
            raise
        from integrations.prosper.mock import MockProsperAdapter
        logger.warning("Prosper REAL create_user_wallet failed (%s); "
                          "falling back to MOCK wallet in mode=%s",
                          real_err, mode)
        resp = await MockProsperAdapter().create_user_wallet(
            user_reference_id=prosper_id, prosper_tx_id=ptx,
            modality=modality)

    raw = getattr(resp, "raw", {}) or {}
    prosper_user_id = (raw.get("user", {}).get("userId")
                        if isinstance(raw.get("user"), dict) else None)
    prosper_user_id = (prosper_user_id
                        or raw.get("userId")
                        or raw.get("prosperUserId")
                        or raw.get("prosperId")
                        or prosper_id)
    stellar_address = (resp.address
                        or raw.get("walletAddress")
                        or raw.get("address")
                        or "")

    wallet_entry = {"modality":        modality,
                     "address":         stellar_address,
                     "prosper_user_id": str(prosper_user_id),
                     "provisioned_at":  _iso_now(),
                     "source":          "cms_cashin"}
    # Replace any stale entry for this modality, otherwise append.
    wallets = [w for w in wallets if w.get("modality") != modality]
    wallets.append(wallet_entry)

    update_set = {"prosper_id":         prosper_id,
                   "prosper_id_source":  "org_id_provisional",
                   "prosper_wallets":    wallets,
                   "updated_at":         _iso_now()}
    update_unset = {"prosper_memo":         "",
                     "prosper_memo_kind":    ""}
    await col(ORGANIZATIONS).update_one(
        {"org_id": org_id},
        {"$set": update_set, "$unset": update_unset})
    logger.info("Provisioned Prosper wallet for org=%s · modality=%s · "
                 "prosperId=%s · user=%s · addr=%s",
                 org_id, modality, prosper_id, prosper_user_id,
                 stellar_address[:12])
    return {"prosper_id":       prosper_id,
             "modality":         modality,
             "stellar_address":  stellar_address,
             "prosper_user_id":  str(prosper_user_id),
             "created":          True,
             "wallets":          wallets}



async def reconcile_org_wallets(org_id: str) -> dict:
    """Source-of-truth reconciliation against /cms/users.

    For every entry in `org.prosper_wallets`, look up the current
    address recorded by the CMS partner for (prosperId, cashin=modality).
    If the live address differs from what we have stored, update the
    array in place (the partner is the authority).

    Does NOT call /cms/cashin and does NOT move funds — read-only against
    /cms/users + Mongo update of the address strings.
    """
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": org_id},
        {"_id": 0, "org_id": 1, "prosper_id": 1, "prosper_wallets": 1})
    if not org:
        return {"ok": False, "reason": "org_not_found"}

    prosper_id = org.get("prosper_id") or org_id
    wallets = list(org.get("prosper_wallets") or [])
    if not wallets:
        return {"ok": True, "org_id": org_id, "changes": [],
                 "note": "no wallets stored"}

    from integrations.prosper.real import RealProsperAdapter

    try:
        adapter = RealProsperAdapter(mode=os.environ.get("PROSPER_MODE",
                                                              "development"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"adapter_init_failed: {e}"}

    changes: list[dict] = []
    new_wallets: list[dict] = []
    for w in wallets:
        modality = (w.get("modality") or "").lower()
        old_addr = w.get("address")
        live = await adapter._find_user_by_prosper_id_and_modality(
            prosper_id, modality)
        live_addr = (live or {}).get("address")
        if live_addr and live_addr != old_addr:
            new_w = {**w,
                      "address":         live_addr,
                      "prosper_user_id": str((live or {}).get("prosperId")
                                                or w.get("prosper_user_id") or ""),
                      "reconciled_at":   _iso_now(),
                      "reconciled_from": old_addr,
                      "source":          "reconciled_from_cms_users"}
            new_wallets.append(new_w)
            changes.append({"modality":      modality,
                              "before":        old_addr,
                              "after":         live_addr,
                              "action":        "address_corrected"})
        else:
            new_wallets.append(w)
            if live_addr:
                changes.append({"modality": modality,
                                  "address":  live_addr,
                                  "action":   "no_change"})
            else:
                changes.append({"modality": modality,
                                  "address":  old_addr,
                                  "action":   "no_cms_row"})

    corrected = sum(1 for c in changes if c["action"] == "address_corrected")
    if corrected:
        await col(ORGANIZATIONS).update_one(
            {"org_id": org_id},
            {"$set": {"prosper_wallets": new_wallets,
                       "updated_at":      _iso_now()}})
        logger.info("Reconciled prosper_wallets for org=%s · corrected=%d",
                     org_id, corrected)

    return {"ok": True, "org_id": org_id, "prosper_id": prosper_id,
             "corrected": corrected, "changes": changes,
             "wallets_after": new_wallets}


async def reconcile_all_org_wallets() -> dict:
    """Run `reconcile_org_wallets` for every org that has prosper_wallets."""
    summary: list[dict] = []
    corrected_total = 0
    cursor = col(ORGANIZATIONS).find(
        {"prosper_wallets": {"$exists": True, "$ne": []}},
        {"_id": 0, "org_id": 1})
    async for o in cursor:
        res = await reconcile_org_wallets(o["org_id"])
        summary.append(res)
        corrected_total += res.get("corrected", 0)
    return {"ok": True, "orgs_scanned": len(summary),
             "corrected_total": corrected_total, "items": summary}


async def get_org_wallet(org_id: str, modality: str) -> dict | None:
    """Read-only — returns the wallet entry for (org_id, modality) or None."""
    modality = (modality or _default_modality()).lower()
    org = await col(ORGANIZATIONS).find_one(
        {"org_id": org_id},
        {"_id": 0, "prosper_wallets": 1, "stellar_address": 1,
          "prosper_cashin_modality": 1, "prosper_user_id": 1})
    if not org:
        return None
    wallets = org.get("prosper_wallets") or []
    found = _find_wallet(wallets, modality)
    if found:
        return found
    # Legacy fallback
    if org.get("stellar_address") and (
            (org.get("prosper_cashin_modality")
              or _default_modality()) == modality):
        return {"modality":        modality,
                 "address":         org.get("stellar_address"),
                 "prosper_user_id": org.get("prosper_user_id"),
                 "source":          "legacy_singular_field"}
    return None


# ---------------------------------------------------------------------------
# Alfred / Penny status mapping
# ---------------------------------------------------------------------------
_STATUS_MAP: dict[str, str] = {
    # Phase 8 mock (backwards compat)
    "order.pending":        "pending",
    "order.confirmed":      "confirmed",
    "order.completed":      "completed",
    "order.failed":         "failed",
    # Penny live — onramp / offramp lifecycle
    "fiat_deposit_received": "pending",
    "trade_completed":        "confirmed",
    "on_chain_initiated":     "confirmed",
    "on_chain_completed":     "completed",
    "failed":                 "failed",
    "expired":                "failed",
    "cancelled":              "failed",
    # KYC events from Penny (handled separately by /webhooks/alfred)
    "kyc_pending":            "kyc_pending",
    "kyc_approved":           "kyc_approved",
    "kyc_rejected":           "kyc_rejected",
    # Refund events
    "refund_initiated":       "refund_initiated",
    "refund_completed":       "refund_completed",
}


def alfred_status_to_internal(event_type: str) -> str | None:
    if not event_type:
        return None
    return _STATUS_MAP.get(event_type.strip().lower())
