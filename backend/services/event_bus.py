"""In-process event bus — Phase 03 first consumer is notifications.

Design constraints (from PRD):
  * Single-process. No external broker.
  * Idempotent by `event_id` (DB-enforced via unique index on
    `deposit_events.event_id`).
  * Fan-out: one event → N subscribers. A failing handler does NOT
    block other handlers for the same event.
  * Same publish/subscribe surface that future multi-process backends
    (Redis Streams) can implement without changing callers.

This module is intentionally narrow. It is NOT a generic message bus.
The schema of the persisted event is the `deposit.credited v1` contract
documented in PRD.md, but `publish()` itself does no validation — that's
the publisher's job.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from pymongo.errors import DuplicateKeyError

from db import DEPOSIT_EVENTS, col

logger = logging.getLogger("prosper.event_bus")

Handler = Callable[[dict[str, Any]], Awaitable[None]]

_subscribers: dict[str, list[Handler]] = {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def subscribe(event_type: str, handler: Handler) -> None:
    """Register `handler` to receive every event with the given type.

    Handlers are invoked in registration order. Idempotent w.r.t. the
    same callable being registered twice (we dedupe).
    """
    bucket = _subscribers.setdefault(event_type, [])
    if handler not in bucket:
        bucket.append(handler)
        logger.info("event_bus: subscribed %s to %s",
                       getattr(handler, "__qualname__",
                                  getattr(handler, "__name__", repr(handler))),
                       event_type)


def reset_subscribers_for_tests() -> None:
    """Drop ALL subscribers. Tests only. Production callers should never
    call this — it is a sharp edge by design."""
    _subscribers.clear()


async def publish(event: dict[str, Any]) -> dict[str, Any]:
    """Persist + fan-out a single event.

    Returns a dict describing what happened so callers/tests can assert:
      * `{"action": "published", "event_id": ..., "handlers_run": N}`
      * `{"action": "duplicate_skipped", "event_id": ...}` if a prior
        publish with the same `event_id` already happened.

    The persist step uses `deposit_events.event_id` unique index as the
    idempotency guard. We persist BEFORE invoking handlers so that
    re-publishes never duplicate side-effects.
    """
    if "event_type" not in event:
        raise ValueError("event missing required field: event_type")

    # Stamp event_id if absent; the publisher may set it for end-to-end
    # idempotency (e.g. derived from deposit_id), but if not, we generate
    # a fresh one per publish call.
    event.setdefault("event_id", "evt_" + secrets.token_hex(8))
    event.setdefault("published_at", _iso_now())

    try:
        await col(DEPOSIT_EVENTS).insert_one(dict(event))  # copy
    except DuplicateKeyError:
        logger.info("event_bus: duplicate publish blocked event_id=%s",
                       event["event_id"])
        return {"action": "duplicate_skipped",
                 "event_id": event["event_id"]}

    handlers = list(_subscribers.get(event["event_type"], []))
    ran = 0
    for h in handlers:
        try:
            await h(dict(event))   # defensive copy — handlers can't mutate
            ran += 1
        except Exception:  # noqa: BLE001
            logger.exception("event_bus: handler %s raised on event_id=%s",
                                getattr(h, "__qualname__",
                                          getattr(h, "__name__", repr(h))),
                                event["event_id"])
            # Continue — one failing handler must not block the others.
    return {"action": "published",
             "event_id": event["event_id"],
             "handlers_run": ran,
             "handlers_total": len(handlers)}
