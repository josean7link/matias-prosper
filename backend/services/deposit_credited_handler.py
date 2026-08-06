"""Subscriber for `deposit.credited` v1.

Resolves recipients (per the contract documented in PRD.md) and creates
one in-app notification + (conditional) one email per recipient.

Idempotency: per-recipient via `notifications.{idempotency_key, user_id}`
unique index. Same event re-published → all recipients still see
exactly one row each. Different recipients of the same event → one row
per user (this is THE key correctness invariant).

Channels:
  * in-app: ALWAYS created for deposit_credited (overrides
    `inapp_transactions=false`).
  * email: only if `users.notifications.email_account_activity=true` AND
    `users.email` is set.

Soft-fail per recipient and per channel. One failing user's notification
must not block the next user's.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from db import ORGANIZATIONS, USERS, col
from integrations.email_sender import send_email
from services.notifications import (create_notification,
                                          update_channels)
from services.notifications_emails import (
    inapp_copy_deposit_credited, t_deposit_credited_arsa,
    t_deposit_credited_usdc)

logger = logging.getLogger("prosper.deposit_credited_handler")


def _portal_url() -> str:
    return (os.environ.get("PUBLIC_BASE_URL")
              or "https://app.prosper.foundation").rstrip("/") + "/client"


# ---------------------------------------------------------------------------
# Recipient resolution
# ---------------------------------------------------------------------------
async def resolve_recipients(*, org_id: str,
                                  user_id_hint: str | None
                                  ) -> list[dict[str, Any]]:
    """Returns list of user docs (dict, not Pydantic). Logic per PRD:
       personal org → unique user; business org → all client_admin users.
       `user_id_hint`, if set, overrides everything (single recipient)."""
    if user_id_hint:
        u = await col(USERS).find_one(
            {"user_id": user_id_hint, "is_deleted": {"$ne": True}},
            {"_id": 0})
        return [u] if u else []

    org = await col(ORGANIZATIONS).find_one(
        {"org_id": org_id, "is_deleted": {"$ne": True}},
        {"_id": 0, "org_id": 1, "type": 1, "owner_user_id": 1})
    if not org:
        return []

    if (org.get("type") or "").lower() == "personal":
        # Personal orgs are 1-user. We just take whichever user belongs
        # to the org (most orgs of this type were seeded with exactly
        # one). If owner_user_id is set, prefer it.
        if org.get("owner_user_id"):
            u = await col(USERS).find_one(
                {"user_id": org["owner_user_id"],
                  "is_deleted": {"$ne": True}}, {"_id": 0})
            return [u] if u else []
        users = await col(USERS).find(
            {"org_id": org_id, "is_deleted": {"$ne": True}},
            {"_id": 0}).limit(2).to_list(2)
        return users[:1]   # take exactly 1 even if seed somehow added more

    # business / fintech / unknown → all client_admin
    users = await col(USERS).find(
        {"org_id": org_id,
          "role":   "client_admin",
          "is_deleted": {"$ne": True}},
        {"_id": 0}).to_list(50)
    return users


# ---------------------------------------------------------------------------
# Channel helpers
# ---------------------------------------------------------------------------
def _idempotency_key(event: dict) -> str:
    return (f"notif:deposit_credited:{event.get('asset','?')}"
              f":{event.get('deposit_id','?')}")


def _ntf_type(event: dict) -> str:
    return f"deposit_credited_{event.get('asset')}"


async def _send_email_for(*, user: dict, event: dict
                              ) -> tuple[str, dict[str, Any]]:
    """Returns (channel_status, email_record_or_meta_dict).
    channel_status ∈ {sent, preview_only, failed,
                       skipped_toggle_off, skipped_no_email}."""
    email = (user.get("email") or "").strip()
    if not email:
        return "skipped_no_email", {}
    prefs = user.get("notifications") or {}
    if prefs.get("email_account_activity") is False:
        return "skipped_toggle_off", {}

    lang = (user.get("preferences", {}).get("language") or "es").lower()
    if lang not in ("es", "en"):
        lang = "es"
    asset = event.get("asset")
    occurred_at = event.get("occurred_at") or event.get("detected_at") or ""
    # The contract sends ISO timestamps; show a friendly slice (YYYY-MM-DD HH:MM UTC)
    pretty_date = occurred_at.replace("T", " ").split(".")[0].split("+")[0]
    if pretty_date and not pretty_date.endswith("UTC"):
        pretty_date = pretty_date + " UTC"

    if asset == "arsa":
        subject, html = t_deposit_credited_arsa(
            lang=lang, amount=event.get("amount", "0"),
            ref=event.get("ref"), date_iso=pretty_date,
            portal_url=_portal_url())
    elif asset == "usdc":
        subject, html = t_deposit_credited_usdc(
            lang=lang, amount=event.get("amount", "0"),
            ref=event.get("ref"), date_iso=pretty_date,
            portal_url=_portal_url())
    else:
        return "failed", {"error": f"unknown_asset:{asset}"}

    record = await send_email(
        to=email, subject=subject, html=html,
        template=f"deposit-credited-{asset}",
        context={"asset": asset, "amount": event.get("amount"),
                  "deposit_id": event.get("deposit_id"),
                  "event_id": event.get("event_id")},
        org_id=event.get("org_id"), user_id=user.get("user_id"))
    return record.get("status", "failed"), record


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------
async def on_event(event: dict[str, Any]) -> None:
    """Subscriber entry point. Called by `event_bus.publish` for every
    `deposit.credited` event. Errors per recipient are logged but do not
    propagate (the bus would already swallow them, but defense-in-depth
    keeps the loop running for the remaining recipients).
    """
    asset = event.get("asset")
    if asset not in ("arsa", "usdc"):
        logger.warning("deposit_credited: ignoring unknown asset=%r "
                          "event_id=%s", asset, event.get("event_id"))
        return

    org_id = event.get("org_id") or ""
    if not org_id:
        logger.warning("deposit_credited: event without org_id "
                          "event_id=%s", event.get("event_id"))
        return

    recipients = await resolve_recipients(
        org_id=org_id, user_id_hint=event.get("user_id"))
    if not recipients:
        logger.warning("deposit_credited: no recipients for org=%s "
                          "(event_id=%s) — persisting orphan in_app",
                          org_id, event.get("event_id"))
        # Persist as orphan with user_id=null so admin tools can see it.
        await create_notification(
            user_id="",  # empty string = no recipient (sparse-friendly)
            org_id=org_id, ntf_type=_ntf_type(event),
            title="Deposit credited (no recipient)",
            body=f"Asset={asset} deposit_id={event.get('deposit_id')}",
            data={"asset": asset, "amount": event.get("amount"),
                   "deposit_id": event.get("deposit_id"),
                   "event_id": event.get("event_id"),
                   "ref": event.get("ref"),
                   "orphan": True},
            idempotency_key=_idempotency_key(event) + ":orphan",
            channels={"inapp": "delivered",
                       "email": "skipped_no_email"})
        return

    idem = _idempotency_key(event)
    for user in recipients:
        try:
            await _process_one(user=user, event=event, idem_key=idem)
        except Exception:  # noqa: BLE001
            logger.exception(
                "deposit_credited: recipient pipeline failed user=%s "
                "event_id=%s — continuing", user.get("user_id"),
                event.get("event_id"))


async def _process_one(*, user: dict, event: dict, idem_key: str) -> None:
    lang = (user.get("preferences", {}).get("language") or "es").lower()
    if lang not in ("es", "en"):
        lang = "es"
    title, body = inapp_copy_deposit_credited(
        lang=lang, asset=event["asset"], amount=event.get("amount", "0"))

    # 1. Create the in-app row (idempotent per recipient). Email channel
    #    placeholder until we resolve it.
    res = await create_notification(
        user_id=user["user_id"], org_id=event["org_id"],
        ntf_type=_ntf_type(event),
        title=title, body=body,
        data={"asset":      event["asset"],
              "amount":     event.get("amount"),
              "currency":   event.get("currency"),
              "deposit_id": event.get("deposit_id"),
              "tx_hash":    event.get("tx_hash"),
              "ref":        event.get("ref"),
              "occurred_at": event.get("occurred_at"),
              "event_id":   event.get("event_id"),
              "source":     event.get("source")},
        idempotency_key=idem_key,
        channels={"inapp": "delivered", "email": "pending"})

    if res["action"] == "duplicate":
        # We've already processed this (user, event). Don't re-send email.
        logger.info("deposit_credited: duplicate skipped user=%s "
                       "event_id=%s", user["user_id"],
                       event.get("event_id"))
        return

    # 2. Email channel (conditional). Failures land in channels.email
    #    so audit is preserved; the in-app row stays intact.
    try:
        email_status, _record = await _send_email_for(user=user, event=event)
    except Exception:  # noqa: BLE001
        logger.exception("deposit_credited: email pipeline failed "
                            "user=%s event_id=%s",
                            user.get("user_id"), event.get("event_id"))
        email_status = "failed"

    await update_channels(
        notification_id=res["notification_id"],
        channels_patch={"email": email_status})
