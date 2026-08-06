"""Phase 6 — Outbound emails inspector (preview HTML for mock mode)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from auth import CurrentUser
from db import col, OUTBOUND_EMAILS
from ._deps import require_admin

router = APIRouter(prefix="/admin/clients", tags=["admin-clients-emails"])


@router.get("/{org_id}/emails")
async def list_emails(org_id: str, limit: int = Query(50, ge=1, le=200),
                       _: CurrentUser = Depends(require_admin)):
    rows = await col(OUTBOUND_EMAILS).find(
        {"org_id": org_id, "is_deleted": False},
        {"_id": 0, "html": 0}     # html excluded from list view
    ).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}


@router.get("/{org_id}/emails/{email_id}/preview", response_class=HTMLResponse)
async def preview_email(org_id: str, email_id: str,
                         _: CurrentUser = Depends(require_admin)):
    doc = await col(OUTBOUND_EMAILS).find_one(
        {"email_id": email_id, "org_id": org_id, "is_deleted": False})
    if not doc:
        raise HTTPException(404, "Not found")
    return HTMLResponse(doc.get("html") or "<p>No HTML</p>")
