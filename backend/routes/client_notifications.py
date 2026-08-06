"""Client-scoped notifications API.

All endpoints are gated by `get_current_user` and scope by `user.user_id`.
No admin override path exists here — admin observability happens via
`outbound_emails` and `notifications` collections directly in the admin
UI (separate work).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import CurrentUser, get_current_user
from services.notifications import (list_for_user, mark_all_read,
                                          mark_read, unread_count)

router = APIRouter(prefix="/client/me/notifications",
                    tags=["client-notifications"])


@router.get("")
async def list_notifications(
    cursor: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 30,
    user: CurrentUser = Depends(get_current_user),
):
    limit = max(1, min(int(limit or 30), 100))
    return await list_for_user(user_id=user.user_id, limit=limit,
                                  cursor=cursor, unread_only=unread_only)


@router.get("/unread-count")
async def get_unread_count(user: CurrentUser = Depends(get_current_user)):
    count = await unread_count(user_id=user.user_id)
    return {"count": count}


@router.post("/{notification_id}/read")
async def mark_one_read(notification_id: str,
                          user: CurrentUser = Depends(get_current_user)):
    """Flips one notification to read.

    Scope guard: returns 404 if the row exists but belongs to a different
    user. NEVER reveals whether the row exists for someone else.
    """
    ok = await mark_read(user_id=user.user_id,
                            notification_id=notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification_not_found")
    return {"ok": True}


@router.post("/read-all")
async def post_mark_all_read(
    user: CurrentUser = Depends(get_current_user)):
    n = await mark_all_read(user_id=user.user_id)
    return {"ok": True, "marked": n}
