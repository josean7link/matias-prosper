"""P0-3 — Staking reconciler against the Prosper CMS protocol.

Pulls `GET /api/v1/cms/staking` (the partner-scoped on-chain staking list),
filters to the wallets we provisioned for our orgs, and idempotently
upserts the local `positions` collection by the on-chain primary key
`(wallet, memo, hash)`.

What the contract returns today (verified live, Feb-09 2026):

  ✅ Already populated:
     - id (CMS row id, integer)
     - hashStaking / hashDeposito
     - memoStaking (10-digit Unix timestamp)
     - wallet (Stellar address)
     - principalAmount, start, maturityPrincipal
     - scheduleInterest: ["end"] | ["month"] | …
     - porcentajeAnual (rate %)
     - payoutAssetPrincipal / payoutAssetInterest / tokenInteres (ARSa | USDC)
     - claimedInterest, principalRedeemed, contractoId
     - createdAt, updatedAt, deletedAt

  ❌ Returned as NULL today:
     - interesesAcumulados   (real-time accrued interest)
     - proximaFechaMonto     (next payout date + amount)
     - interesCada24Horas    (daily accrual)
     - proyectado            (projected interest)

So we keep `jobs/accrual.py` running as the source of truth for accrued
interest. The poller flips `position.contract_provides_interest = True`
on a row IFF `interesesAcumulados is not None` — at that point the local
accrual job skips it and the contract becomes the source of truth.

Idempotency: positions are keyed on `(wallet, memo, hash)`. Re-running
this job N times produces the same DB state.

Orphans: stakings found on-chain that don't match any known org wallet
raise an `alerts` row with severity=info so the operator can investigate
(typically an org provisioned outside the platform or a wallet rotated
without telling us).

Toggle via `PROSPER_STAKING_SYNC_ENABLED=true|false` (default: enabled
when PROSPER_MODE != "mock"; disabled otherwise — there are no real
stakings to read in mock mode).
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from db import ALERTS, ORGANIZATIONS, POSITIONS, STAKING_SYNC_RUNS, USERS, col
from integrations.prosper import ProsperError, get_adapter as prosper_adapter

logger = logging.getLogger("prosper.staking_sync")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def is_enabled() -> bool:
    raw = os.environ.get("PROSPER_STAKING_SYNC_ENABLED")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    # Default ON when we have a real adapter target.
    return (os.environ.get("PROSPER_MODE") or "mock").lower() != "mock"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Wallet → org index. Built once per run; small N (one per org × modality).
# ---------------------------------------------------------------------------
async def _wallet_index() -> dict[str, dict]:
    """Return {address.lower(): {org_id, modality, prosper_user_id, client_email}}."""
    index: dict[str, dict] = {}
    cursor = col(ORGANIZATIONS).find(
        {"$or": [{"prosper_wallets": {"$exists": True, "$ne": []}},
                  {"stellar_address": {"$exists": True, "$ne": None}}]},
        {"_id": 0, "org_id": 1, "prosper_wallets": 1, "stellar_address": 1,
         "prosper_cashin_modality": 1, "prosper_user_id": 1,
         "primary_email": 1, "contact_email": 1})
    orgs: list[dict] = []
    org_ids: list[str] = []
    async for org in cursor:
        orgs.append(org)
        org_ids.append(org["org_id"])

    # Pre-fetch client users to map org_id -> client_email
    org_user_emails: dict[str, str] = {}
    if org_ids:
        u_cursor = col(USERS).find(
            {"org_id": {"$in": org_ids}, "is_deleted": {"$ne": True}},
            {"_id": 0, "org_id": 1, "email": 1, "role": 1})
        async for u in u_cursor:
            u_mail = str(u.get("email") or "").strip().lower()
            if u_mail:
                oid = u["org_id"]
                if oid not in org_user_emails or u.get("role") == "client_admin":
                    org_user_emails[oid] = u_mail

    for org in orgs:
        oid = org["org_id"]
        client_email = (org.get("primary_email")
                        or org.get("contact_email")
                        or org_user_emails.get(oid))
        for w in (org.get("prosper_wallets") or []):
            addr = (w.get("address") or "").strip().lower()
            if addr:
                w_email = w.get("email") or client_email
                index[addr] = {"org_id":   oid,
                                "modality": w.get("modality"),
                                "prosper_user_id": w.get("prosper_user_id"),
                                "client_email": w_email}
        # Legacy singular fallback — only registered if not already mapped.
        legacy = (org.get("stellar_address") or "").strip().lower()
        if legacy and legacy not in index:
            index[legacy] = {"org_id":   oid,
                              "modality": org.get("prosper_cashin_modality")
                                            or "end",
                              "prosper_user_id": org.get("prosper_user_id"),
                              "client_email": client_email}
    return index


# ---------------------------------------------------------------------------
# Per-record sync
# ---------------------------------------------------------------------------
def _classify_status(raw: dict) -> str:
    """Map the staking record onto our `positions.status` vocabulary."""
    if raw.get("deletedAt"):
        return "redeemed"
    principal_redeemed = _to_float(raw.get("principalRedeemed"))
    principal_amount   = _to_float(raw.get("principalAmount"))
    if principal_amount and principal_redeemed >= principal_amount:
        return "redeemed"
    maturity = raw.get("maturityPrincipal")
    if maturity:
        try:
            m = datetime.fromisoformat(str(maturity).replace("Z", "+00:00"))
            if m <= datetime.now(timezone.utc):
                return "matured"
        except ValueError:
            pass
    return "active"


def _modality_from_schedule(schedule: Any, fallback: str) -> str:
    if isinstance(schedule, list) and schedule:
        first = str(schedule[0]).strip().lower()
        if first in ("end", "month"):
            return first
    if isinstance(schedule, str):
        first = schedule.strip().lower()
        if first in ("end", "month"):
            return first
    return fallback or "end"


def _asset_from_token(token: Any) -> str:
    if not token:
        return "usdc"
    t = str(token).strip().lower()
    if t.startswith("arsa"):
        return "arsa"
    return "usdc"


async def _upsert_position(*, raw: dict, wallet_meta: dict) -> dict:
    """Idempotent upsert of a staking record into `positions`.

    Primary key is `(wallet, memo, hash)`. The same partner can have many
    stakings against a single wallet, each identified by its on-chain memo.

    Reclaim path (P0 Feb-2026):
      Before creating a brand-new position when no `(wallet, memo, hash)`
      match exists, we look for a `pending_onchain` placeholder created by
      `POST /v1/client/invest/onchain` that matches `(wallet, asset,
      modality, principal_native)` within a recent window. See
      `_try_reclaim_pending_onchain` for the exact matching rules.
    """
    wallet = (raw.get("wallet") or "").strip()
    memo   = str(raw.get("memoStaking") or "").strip()
    hsh    = (raw.get("hashStaking") or "").strip()
    if not (wallet and memo and hsh):
        return {"action": "skipped", "reason": "missing_pk"}

    asset       = _asset_from_token(raw.get("tokenInteres")
                                       or raw.get("payoutAssetPrincipal"))
    asset_unit  = "ARSa" if asset == "arsa" else "USDC"
    modality    = _modality_from_schedule(raw.get("scheduleInterest"),
                                            fallback=wallet_meta.get("modality"))
    rate        = _to_float(raw.get("porcentajeAnual"))
    principal   = _to_float(raw.get("principalAmount"))
    claimed     = _to_float(raw.get("claimedInterest"))
    redeemed    = _to_float(raw.get("principalRedeemed"))
    accrued_contract = raw.get("interesesAcumulados")
    status      = _classify_status(raw)
    contract_provides_interest = accrued_contract is not None

    # Look up an existing local position by (wallet, memo, hash) — that's
    # the on-chain primary key. Soft-deleted positions are NOT touched.
    existing = await col(POSITIONS).find_one(
        {"wallet": wallet, "memo": memo, "hash": hsh,
         "is_deleted": {"$ne": True}}, {"_id": 0})

    set_doc: dict[str, Any] = {
        "wallet":          wallet,
        "memo":            memo,
        "hash":            hsh,
        "asset":           asset,
        "modality":        modality,
        "rate":            rate,
        "principal_native":   principal,
        "principal_unit":     asset_unit,
        "principal_redeemed": redeemed,
        "claimed_interest":   claimed,
        "currency":           asset_unit,        # legacy mirror
        "principal_usd":      principal,          # legacy mirror
        "apr_bps":            int(round(rate * 100)),
        "status":             status,
        "contract_provides_interest": contract_provides_interest,
        "contract_payload_at": _iso_now(),
        "updated_at":         _iso_now(),
    }
    if accrued_contract is not None:
        set_doc["accrued_interest"] = _to_float(accrued_contract)
    # Contract fields that are nice to surface upstream.
    if raw.get("start"):
        set_doc["start"] = raw["start"]
    if raw.get("maturityPrincipal"):
        set_doc["maturity"] = raw["maturityPrincipal"]
    if raw.get("contractoId"):
        set_doc["contract_id"] = raw["contractoId"]
    resolved_client_email = wallet_meta.get("client_email") or raw.get("email")
    if resolved_client_email:
        set_doc["client_email"] = resolved_client_email
        set_doc["contract_email"] = resolved_client_email
    elif raw.get("email"):
        set_doc["contract_email"] = raw["email"]
        set_doc["client_email"] = raw["email"]
    if raw.get("hashDeposito") and raw["hashDeposito"] != "N/A":
        set_doc["deposit_hash"] = raw["hashDeposito"]
    if raw.get("proyectado") is not None:
        set_doc["projected_interest"] = _to_float(raw.get("proyectado"))
    if raw.get("interesCada24Horas") is not None:
        set_doc["daily_interest"] = _to_float(raw.get("interesCada24Horas"))
    if raw.get("proximaFechaMonto") is not None:
        set_doc["next_payout"] = raw["proximaFechaMonto"]

    if existing:
        await col(POSITIONS).update_one(
            {"position_id": existing["position_id"]}, {"$set": set_doc})
        await _maybe_reconcile_deposit(
            asset=asset, position_id=existing["position_id"], raw=raw,
            wallet=wallet, principal=principal)
        return {"action": "updated",
                 "position_id": existing["position_id"],
                 "status": status}

    # ---- Reclaim path: try to attach this on-chain staking to a pending
    #      placeholder that the client created via /v1/client/invest/onchain.
    reclaim = await _try_reclaim_pending_onchain(
        wallet=wallet, org_id=wallet_meta["org_id"], asset=asset,
        modality=modality, principal=principal, set_doc=set_doc, raw=raw)
    if reclaim is not None:
        if reclaim.get("action") == "reclaimed" and reclaim.get("position_id"):
            await _maybe_reconcile_deposit(
                asset=asset, position_id=reclaim["position_id"], raw=raw,
                wallet=wallet, principal=principal)
        return reclaim

    # New on-chain staking — create local position attributed to the org
    # whose wallet matches. If we don't have an end_customer_id mapping
    # yet, leave that empty (the operator can attribute later via the
    # admin monitor).
    set_doc.update({
        "position_id":      "pos_" + secrets.token_hex(6),
        "org_id":           wallet_meta["org_id"],
        "user_id":          None,                   # not yet attributed
        "product_id":       f"{asset}_{modality}",
        "prosper_tx_id":    f"cms_{raw.get('id', '?')}",
        "accrued_interest": _to_float(accrued_contract),
        "created_at":       _iso_now(),
        "is_deleted":       False,
    })
    await col(POSITIONS).insert_one(set_doc)
    await _maybe_reconcile_deposit(
        asset=asset, position_id=set_doc["position_id"], raw=raw,
        wallet=wallet, principal=principal)
    return {"action": "created",
             "position_id": set_doc["position_id"],
             "status": status}


async def _maybe_reconcile_deposit(*, asset: str, position_id: str,
                                        raw: dict, wallet: str,
                                        principal: float) -> None:
    """Tie a freshly-upserted USDC staking to the matching
    `ramp_movements{status:pending_detected}` row produced by the
    Deposit Engine watcher.

    Soft-fail: the engine is optional and may be OFF. Never raise from
    here — staking_sync correctness is independent.
    """
    if asset != "usdc":
        return
    try:
        from services.deposit_engine import reconcile_usdc_deposit
        await reconcile_usdc_deposit(
            deposit_hash=(raw.get("hashDeposito") or None),
            memo=(str(raw.get("memoStaking")) if raw.get("memoStaking")
                       else None),
            principal=principal,
            wallet=wallet,
            position_id=position_id,
            staking_raw=raw)
    except Exception:  # noqa: BLE001
        logger.exception(
            "staking_sync: reconcile hook failed for position=%s "
            "(non-blocking)", position_id)


# ---------------------------------------------------------------------------
# Pending-onchain reclaim logic (P0 Feb-2026)
# ---------------------------------------------------------------------------
# Matching rules (per user spec):
#   1. Exact amount match first; if no exact, 0.1% tolerance fallback
#   2. If 2+ candidates match the same on-chain deposit → DO NOT auto-claim;
#      leave the deposit unattributed and raise an operational alert
#   3. Reclaim window: 60 minutes (created_at >= now-60min). Older pending
#      placeholders are NOT eligible — they get marked `expired` by a
#      separate sweep before each sync run.
RECLAIM_WINDOW_MINUTES = 60
AMOUNT_TOLERANCE       = 0.001   # 0.1%


async def _expire_stale_pendings() -> int:
    """Mark pending_onchain placeholders older than the reclaim window as
    `expired_pending_onchain` so they NEVER reclaim a future deposit by
    accident. Returns how many rows were flipped.
    """
    cutoff = (datetime.now(timezone.utc)
                - timedelta(minutes=RECLAIM_WINDOW_MINUTES)).isoformat()
    result = await col(POSITIONS).update_many(
        {"status":     "pending_onchain",
         "is_deleted": False,
         "created_at": {"$lt": cutoff}},
        {"$set": {"status":     "expired_pending_onchain",
                    "expired_at": _iso_now(),
                    "updated_at": _iso_now()}})
    if result.modified_count:
        logger.info("staking_sync: expired %d stale pending_onchain "
                      "placeholder(s) older than %d min",
                      result.modified_count, RECLAIM_WINDOW_MINUTES)
    return result.modified_count


async def _try_reclaim_pending_onchain(*, wallet: str, org_id: str,
                                          asset: str, modality: str,
                                          principal: float, set_doc: dict,
                                          raw: dict) -> dict | None:
    """Try to bind a fresh on-chain staking record to a pending_onchain
    placeholder. Returns:
      * `{"action": "reclaimed", ...}` on success
      * `{"action": "ambiguous_skipped", ...}` if 2+ candidates match (then
         we raise an alert and let `_upsert_position` create a fresh row
         anyway so the deposit is not lost)
      * `None` if no candidate found (caller falls through to create-new)
    """
    cutoff = (datetime.now(timezone.utc)
                - timedelta(minutes=RECLAIM_WINDOW_MINUTES)).isoformat()
    base_filter = {
        "status":     "pending_onchain",
        "is_deleted": False,
        "wallet":     wallet,
        "org_id":     org_id,
        "asset":      asset,
        "modality":   modality,
        "created_at": {"$gte": cutoff},
    }

    # 1. Exact-amount match first
    exact = await col(POSITIONS).find(
        {**base_filter, "principal_native": principal},
        {"_id": 0}).sort("created_at", 1).to_list(10)

    candidates = exact
    matched_kind = "exact"

    # 2. Fallback to tolerance only if no exact matches
    if not candidates:
        lo = principal * (1 - AMOUNT_TOLERANCE)
        hi = principal * (1 + AMOUNT_TOLERANCE)
        candidates = await col(POSITIONS).find(
            {**base_filter,
              "principal_native": {"$gte": lo, "$lte": hi}},
            {"_id": 0}).sort("created_at", 1).to_list(10)
        matched_kind = "tolerance"

    if not candidates:
        return None

    # 3. Ambiguity guard: refuse to auto-claim when multiple candidates
    #    match — raise an alert so an operator decides manually.
    if len(candidates) > 1:
        await _alert_ambiguous_reclaim(
            wallet=wallet, org_id=org_id, asset=asset, modality=modality,
            principal=principal,
            candidate_ids=[c["position_id"] for c in candidates],
            raw=raw, matched_kind=matched_kind)
        return {"action": "ambiguous_skipped",
                 "candidates": [c["position_id"] for c in candidates]}

    target = candidates[0]
    update_set = {**set_doc,
                   "status":            "active",
                   "claimed_by_sync_at": _iso_now(),
                   "reclaim_match":     matched_kind}
    await col(POSITIONS).update_one(
        {"position_id": target["position_id"]}, {"$set": update_set})
    logger.info("staking_sync: reclaimed pending_onchain placeholder "
                  "position=%s for org=%s wallet=%s amount=%.4f (%s match)",
                  target["position_id"], org_id, wallet[:10],
                  principal, matched_kind)
    return {"action": "reclaimed",
             "position_id": target["position_id"],
             "status": "active",
             "matched_kind": matched_kind}


async def _alert_ambiguous_reclaim(*, wallet: str, org_id: str, asset: str,
                                       modality: str, principal: float,
                                       candidate_ids: list[str], raw: dict,
                                       matched_kind: str) -> None:
    """Raise an operational alert so an operator resolves the ambiguity."""
    await col(ALERTS).insert_one({
        "alert_id":    "al_reclaim_" + secrets.token_hex(5),
        "type":        "operational",
        "severity":    "warning",
        "title":       "Reclaim ambiguo · staking sin atribución automática",
        "description": (
            f"Llegó un depósito ARSa on-chain de {principal:.4f} a {wallet[:10]}… "
            f"(asset={asset}, modality={modality}) que matchea {len(candidate_ids)} "
            f"placeholders pending_onchain del mismo org. Para no atribuir mal, "
            f"el poller dejó el depósito sin reclamar. Resolvé manualmente."),
        "org_id":      org_id,
        "status":      "open",
        "context": {
            "wallet":            wallet,
            "asset":             asset,
            "modality":          modality,
            "principal":         principal,
            "matched_kind":      matched_kind,
            "candidate_position_ids": candidate_ids,
            "staking_record_id": raw.get("id"),
            "staking_memo":      raw.get("memoStaking"),
            "staking_hash":      raw.get("hashStaking"),
        },
        "created_at":  _iso_now(),
        "updated_at":  _iso_now(),
        "is_deleted":  False,
    })


# ---------------------------------------------------------------------------
# External staking tracking
# ---------------------------------------------------------------------------
# Stakings observed on-chain that do not match any of our provisioned wallets
# are stored as positions with `external=True, org_id=None`. They show up in
# the admin monitor under "Externos / históricos" (gray pill) so they're
# distinguishable at a glance from our own stakings — without polluting the
# alerts/incidents view.
async def _upsert_external(*, raw: dict) -> dict:
    wallet = (raw.get("wallet") or "").strip()
    memo   = str(raw.get("memoStaking") or "").strip()
    hsh    = (raw.get("hashStaking") or "").strip()
    if not (wallet and memo and hsh):
        return {"action": "skipped", "reason": "missing_pk"}

    asset       = _asset_from_token(raw.get("tokenInteres")
                                       or raw.get("payoutAssetPrincipal"))
    asset_unit  = "ARSa" if asset == "arsa" else "USDC"
    modality    = _modality_from_schedule(raw.get("scheduleInterest"),
                                            fallback="end")
    rate        = _to_float(raw.get("porcentajeAnual"))
    principal   = _to_float(raw.get("principalAmount"))
    claimed     = _to_float(raw.get("claimedInterest"))
    redeemed    = _to_float(raw.get("principalRedeemed"))
    status      = _classify_status(raw)

    set_doc: dict[str, Any] = {
        "wallet":          wallet,
        "memo":            memo,
        "hash":            hsh,
        "asset":           asset,
        "modality":        modality,
        "rate":            rate,
        "principal_native":   principal,
        "principal_unit":     asset_unit,
        "principal_redeemed": redeemed,
        "claimed_interest":   claimed,
        "currency":           asset_unit,
        "principal_usd":      principal,
        "apr_bps":            int(round(rate * 100)),
        "status":             status,
        "external":           True,
        "contract_provides_interest":
            raw.get("interesesAcumulados") is not None,
        "contract_payload_at": _iso_now(),
        "updated_at":         _iso_now(),
    }
    if raw.get("start"):
        set_doc["start"] = raw["start"]
    if raw.get("maturityPrincipal"):
        set_doc["maturity"] = raw["maturityPrincipal"]
    if raw.get("contractoId"):
        set_doc["contract_id"] = raw["contractoId"]
    if raw.get("email"):
        set_doc["contract_email"] = raw["email"]

    existing = await col(POSITIONS).find_one(
        {"wallet": wallet, "memo": memo, "hash": hsh,
         "is_deleted": {"$ne": True}}, {"_id": 0, "position_id": 1})
    if existing:
        await col(POSITIONS).update_one(
            {"position_id": existing["position_id"]}, {"$set": set_doc})
        return {"action": "updated", "external": True,
                 "position_id": existing["position_id"]}
    set_doc.update({
        "position_id":      "pos_ext_" + secrets.token_hex(5),
        "org_id":           None,
        "user_id":          None,
        "product_id":       f"{asset}_{modality}",
        "prosper_tx_id":    f"cms_external_{raw.get('id', '?')}",
        "accrued_interest": _to_float(raw.get("interesesAcumulados")),
        "created_at":       _iso_now(),
        "is_deleted":       False,
    })
    await col(POSITIONS).insert_one(set_doc)
    return {"action": "created", "external": True,
             "position_id": set_doc["position_id"]}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
async def run_sync_once() -> dict[str, Any]:
    """Pull /cms/staking, reconcile to local positions. Returns metrics."""
    if not is_enabled():
        return {"ok": False, "skipped": True, "reason": "disabled"}

    started = datetime.now(timezone.utc)
    # Expire stale pending_onchain placeholders BEFORE pulling new stakings
    # so they can't accidentally reclaim an unrelated incoming deposit.
    try:
        expired_count = await _expire_stale_pendings()
    except Exception as e:  # noqa: BLE001
        logger.warning("staking_sync: expire sweep failed: %s", e)
        expired_count = 0
    try:
        rows = await prosper_adapter().get_staking_records()
    except ProsperError as e:
        logger.warning("staking_sync: adapter failed: %s", e)
        return {"ok": False, "error": str(e)}

    index   = await _wallet_index()
    created = 0
    updated = 0
    skipped = 0
    reclaimed = 0
    ambiguous = 0
    external_created = 0
    external_updated = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        addr = (r.get("wallet") or r.get("owner") or "").strip().lower()
        meta = index.get(addr)
        if not meta:
            try:
                ext = await _upsert_external(raw=r)
            except Exception as e:  # noqa: BLE001
                logger.exception("staking_sync: external upsert failed "
                                  "for wallet=%s memo=%s: %s",
                                  addr, r.get("memoStaking"), e)
                continue
            if ext["action"] == "created":
                external_created += 1
            elif ext["action"] == "updated":
                external_updated += 1
            continue
        try:
            res = await _upsert_position(raw=r, wallet_meta=meta)
        except Exception as e:  # noqa: BLE001
            logger.exception("staking_sync: upsert failed for "
                              "wallet=%s memo=%s: %s",
                              addr, r.get("memoStaking"), e)
            continue
        if res["action"] == "created":
            created += 1
        elif res["action"] == "updated":
            updated += 1
        elif res["action"] == "reclaimed":
            reclaimed += 1
        elif res["action"] == "ambiguous_skipped":
            ambiguous += 1
            # Ambiguity → fall through to create-new so the staking is not lost
            try:
                forced = await _create_new_after_ambiguous(
                    raw=r, wallet_meta=meta)
                if forced:
                    created += 1
            except Exception as e:  # noqa: BLE001
                logger.exception("staking_sync: forced-create after ambiguous "
                                  "failed: %s", e)
        else:
            skipped += 1

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    summary = {"ok": True,
                "processed":        len(rows),
                "created":          created,
                "updated":          updated,
                "skipped":          skipped,
                "reclaimed":        reclaimed,
                "ambiguous":        ambiguous,
                "expired_pendings": expired_count,
                "external_total":   external_created + external_updated,
                "external_created": external_created,
                "external_updated": external_updated,
                "elapsed_seconds":  elapsed,
                "started_at":       started.isoformat(),
                "finished_at":      datetime.now(timezone.utc).isoformat()}
    logger.info("staking_sync: processed=%d created=%d updated=%d "
                  "reclaimed=%d ambiguous=%d expired=%d skipped=%d "
                  "external=%d (%.2fs)",
                  len(rows), created, updated, reclaimed, ambiguous,
                  expired_count, skipped,
                  external_created + external_updated, elapsed)
    await _persist_run(summary)
    return summary


async def _create_new_after_ambiguous(*, raw: dict, wallet_meta: dict) -> bool:
    """Force-create a new position when an ambiguity prevented reclaim.

    Reuses the standard build path so the row still surfaces under the
    correct org × modality with the on-chain primary key — the operator
    will manually merge/cancel placeholders via the admin alerts queue.
    """
    wallet = (raw.get("wallet") or "").strip()
    memo   = str(raw.get("memoStaking") or "").strip()
    hsh    = (raw.get("hashStaking") or "").strip()
    if not (wallet and memo and hsh):
        return False
    asset       = _asset_from_token(raw.get("tokenInteres")
                                       or raw.get("payoutAssetPrincipal"))
    asset_unit  = "ARSa" if asset == "arsa" else "USDC"
    modality    = _modality_from_schedule(raw.get("scheduleInterest"),
                                            fallback=wallet_meta.get("modality"))
    rate        = _to_float(raw.get("porcentajeAnual"))
    principal   = _to_float(raw.get("principalAmount"))
    claimed     = _to_float(raw.get("claimedInterest"))
    redeemed    = _to_float(raw.get("principalRedeemed"))
    accrued_contract = raw.get("interesesAcumulados")
    status      = _classify_status(raw)
    doc: dict[str, Any] = {
        "position_id":      "pos_amb_" + secrets.token_hex(5),
        "org_id":           wallet_meta["org_id"],
        "user_id":          None,
        "product_id":       f"{asset}_{modality}",
        "wallet":           wallet, "memo": memo, "hash": hsh,
        "asset":            asset, "modality": modality, "rate": rate,
        "principal_native": principal, "principal_unit": asset_unit,
        "principal_redeemed": redeemed, "claimed_interest": claimed,
        "currency":            asset_unit, "principal_usd": principal,
        "apr_bps":             int(round(rate * 100)),
        "status":              status,
        "needs_manual_attribution": True,
        "contract_provides_interest": accrued_contract is not None,
        "accrued_interest":    _to_float(accrued_contract),
        "prosper_tx_id":       f"cms_amb_{raw.get('id', '?')}",
        "created_at":          _iso_now(),
        "updated_at":          _iso_now(),
        "contract_payload_at": _iso_now(),
        "is_deleted":          False,
    }
    if raw.get("start"):
        doc["start"]    = raw["start"]
    if raw.get("maturityPrincipal"):
        doc["maturity"] = raw["maturityPrincipal"]
    if raw.get("contractoId"):
        doc["contract_id"]    = raw["contractoId"]
    resolved_client_email = wallet_meta.get("client_email") or raw.get("email")
    if resolved_client_email:
        doc["client_email"]   = resolved_client_email
        doc["contract_email"] = resolved_client_email
    elif raw.get("email"):
        doc["contract_email"] = raw["email"]
        doc["client_email"]   = raw["email"]
    await col(POSITIONS).insert_one(doc)
    return True


async def _persist_run(summary: dict) -> None:
    """Persist this run's summary so the admin widget can display it.

    We keep a singleton row (`_id`-style key `latest`) plus an append-only
    history (capped to the last 50 runs) so the operator can see trends.
    """
    await col(STAKING_SYNC_RUNS).update_one(
        {"key": "latest"},
        {"$set": {**summary, "key": "latest"}},
        upsert=True)
    await col(STAKING_SYNC_RUNS).insert_one(
        {"key": "history", **summary})
    # Trim history to last 50.
    history_ids = await col(STAKING_SYNC_RUNS).find(
        {"key": "history"},
        {"_id": 1}).sort("started_at", -1).to_list(1000)
    if len(history_ids) > 50:
        stale = [h["_id"] for h in history_ids[50:]]
        await col(STAKING_SYNC_RUNS).delete_many({"_id": {"$in": stale}})


async def get_last_run() -> dict | None:
    return await col(STAKING_SYNC_RUNS).find_one(
        {"key": "latest"}, {"_id": 0, "key": 0})
