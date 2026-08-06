"""Notifications — Phase 03 storage + scope-guarded read/write helpers.

The schema (one row per recipient × idempotency_key):

    {
      notification_id: "ntf_<hex>",
      idempotency_key: "notif:deposit_credited:usdc:<tx_hash>",
      user_id:    "usr_<id>",       # NOT null in client-visible rows
      org_id:     "org_<id>",
      type:       "deposit_credited_arsa" | "deposit_credited_usdc" | ...,
      title:      "<localized>",
      body:       "<localized>",
      data:       { amount, currency, ref, asset, deposit_id, ... },
      channels:   { inapp: "delivered", email: "sent"|"skipped_*"|"failed"|"preview_only" },
      read:       false,
      created_at: "<ISO-8601>",
      read_at:    null,
    }

Uniqueness is DB-enforced by `{idempotency_key, user_id}` so the same
event redelivered → same row (no dup). Different recipients of the same
event → distinct rows (one per user).

All read/mutate endpoints in `routes/client_notifications.py` MUST go
through this module so the user_id scope guard is never bypassed.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pymongo.errors import DuplicateKeyError

from db import NOTIFICATIONS, col

logger = logging.getLogger("prosper.notifications")

NotificationType = Literal[
    "deposit_credited_arsa",
    "deposit_credited_usdc",
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_notification(*, user_id: str, org_id: str,
                                   ntf_type: NotificationType,
                                   title: str, body: str,
                                   data: dict[str, Any],
                                   idempotency_key: str,
                                   channels: Optional[dict] = None,
                                   ) -> dict[str, Any]:
    """Idempotent insert. Returns `{action: "inserted"|"duplicate", ...}`.

    Duplicate-by-unique-index means the same `(idempotency_key, user_id)`
    combination was already inserted. Caller should NOT re-trigger
    side-effects (e.g. don't re-send the email).
    """
    doc = {
        "notification_id": "ntf_" + secrets.token_hex(7),
        "idempotency_key": idempotency_key,
        "user_id":         user_id,
        "org_id":          org_id,
        "type":            ntf_type,
        "title":           title,
        "body":            body,
        "data":            data,
        "channels":        channels or {"inapp": "delivered"},
        "read":            False,
        "created_at":      _iso_now(),
        "read_at":         None,
    }
    try:
        await col(NOTIFICATIONS).insert_one(dict(doc))
        return {"action":  "inserted",
                 "notification_id": doc["notification_id"]}
    except DuplicateKeyError:
        existing = await col(NOTIFICATIONS).find_one(
            {"idempotency_key": idempotency_key, "user_id": user_id},
            {"_id": 0, "notification_id": 1})
        return {"action":  "duplicate",
                 "notification_id": (existing or {}).get("notification_id")}


async def update_channels(*, notification_id: str,
                                channels_patch: dict[str, str]) -> None:
    """Patch the `channels` sub-doc — used by the deposit handler after
    a Resend attempt resolves to sent/failed/preview_only/skipped_*."""
    sets = {f"channels.{k}": v for k, v in channels_patch.items()}
    sets["channels_updated_at"] = _iso_now()
    await col(NOTIFICATIONS).update_one(
        {"notification_id": notification_id},
        {"$set": sets})


# ---------------------------------------------------------------------------
# User-facing read helpers (called from client_notifications routes).
# Every helper scopes by `user_id` — there is no escape hatch.
# ---------------------------------------------------------------------------
async def list_for_user(*, user_id: str, limit: int = 30,
                              cursor: Optional[str] = None,
                              unread_only: bool = False
                              ) -> dict[str, Any]:
    q: dict[str, Any] = {"user_id": user_id}
    if unread_only:
        q["read"] = False
    if cursor:
        q["created_at"] = {"$lt": cursor}
    cur = col(NOTIFICATIONS).find(
        q, {"_id": 0}).sort("created_at", -1).limit(limit + 1)
    items = await cur.to_list(limit + 1)
    has_more = len(items) > limit
    items = items[:limit]
    next_cursor = items[-1]["created_at"] if (items and has_more) else None
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


async def unread_count(*, user_id: str) -> int:
    return await col(NOTIFICATIONS).count_documents(
        {"user_id": user_id, "read": False})


async def mark_read(*, user_id: str, notification_id: str) -> bool:
    """Returns True on a successful state flip (not-read → read).

    Scope guard: when `notification_id` exists but belongs to another
    user, NOTHING is updated AND the caller MUST treat as 404.
    """
    result = await col(NOTIFICATIONS).update_one(
        {"notification_id": notification_id,
         "user_id":         user_id},     # ← scope guard
        {"$set": {"read": True, "read_at": _iso_now()}})
    return result.matched_count > 0


async def mark_all_read(*, user_id: str) -> int:
    result = await col(NOTIFICATIONS).update_many(
        {"user_id": user_id, "read": False},
        {"$set": {"read": True, "read_at": _iso_now()}})
    return result.modified_count
