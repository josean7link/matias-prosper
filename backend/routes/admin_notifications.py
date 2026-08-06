"""Admin — synthetic deposit-credited test event.

Endpoint `POST /api/v1/admin/notifications/test` lets ops verify in
PROD that the end-to-end notifications pipeline (event bus →
deposit_credited_handler → in-app + Resend) is wired correctly, WITHOUT
waiting for a real deposit to flow through.

Crucially, this uses the SAME `event_bus.publish` path the real
publishers use — no mock fork. If Resend is misconfigured, this will
fail in exactly the way a real deposit would fail.

The synthetic event is marked with `metadata.synthetic=true` and
`source="admin_test"` so it cannot be confused with real deposit
events in audit logs. The corresponding row in `notifications.data`
also carries `synthetic=true`.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import CurrentUser, requires_role
from db import USERS, col
from services.event_bus import publish

logger = logging.getLogger("prosper.routes.admin_notifications")
router = APIRouter(prefix="/admin/notifications",
                    tags=["admin · notifications"])

Asset = Literal["arsa", "usdc"]


class TestNotificationReq(BaseModel):
    target_user_id: str = Field(..., min_length=4)
    asset:          Asset = "arsa"
    amount:         str   = "100"
    # Optional override so QA can spot synthetic events in dashboards.
    note:           Optional[str] = None


@router.post("/test")
async def test_deposit_notification(
    body: TestNotificationReq,
    actor: CurrentUser = Depends(requires_role("super_admin",
                                                    "ops_admin")),
):
    """Fire a synthetic `deposit.credited` to a specific user. The user
    MUST exist and belong to a known org — we won't conjure an event
    pointing to a phantom org. The event traverses the same handler that
    real deposits do, so the in-app + Resend + retry path is exercised.
    """
    user = await col(USERS).find_one(
        {"user_id": body.target_user_id,
          "is_deleted": {"$ne": True}},
        {"_id": 0, "user_id": 1, "org_id": 1, "email": 1})
    if not user:
        raise HTTPException(status_code=404,
                              detail="target_user_not_found")
    if not user.get("org_id"):
        raise HTTPException(status_code=409,
                              detail="target_user_without_org")

    synthetic_id = "synth_" + secrets.token_hex(8)
    now = datetime.now(timezone.utc).isoformat()
    currency = "ARSa" if body.asset == "arsa" else "USDC"

    event = {
        "event_type":  "deposit.credited",
        "version":     1,
        "event_id":    f"evt_synth_{synthetic_id}",
        "asset":       body.asset,
        "deposit_id":  synthetic_id,
        "tx_hash":     None,
        "org_id":      user["org_id"],
        # `user_id` set so the handler skips org-scan resolution and
        # only the target receives the notification.
        "user_id":     body.target_user_id,
        "amount":      body.amount,
        "currency":    currency,
        "ref":         f"ADMIN-TEST · {body.note}" if body.note
                          else "ADMIN-TEST",
        "occurred_at": now,
        "detected_at": now,
        "source":      "admin_test",
        "metadata": {
            "synthetic":  True,
            "fired_by":   actor.user_id,
            "note":       body.note,
        },
    }
    result = await publish(event)
    logger.info("admin_notifications.test fired: actor=%s target=%s "
                  "asset=%s amount=%s result=%s",
                  actor.user_id, body.target_user_id, body.asset,
                  body.amount, result.get("action"))
    return {"ok":           True,
             "event":        event,
             "publish_result": result}
