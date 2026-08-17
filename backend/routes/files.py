"""Signed-URL endpoint for GridFS-backed files (Fase 0.5).

Serves the file identified by a token generated via
`services/storage/…::signed_url`. Tokens are multi-use by default
(viewers: pdf.js range requests, reloads) or single-use when minted
with `single_use=True` (links sent by email). Validation + usage
bookkeeping happen atomically; the raw `storage_key` is never accepted
from the client.

Requires an authenticated session. The token itself is unguessable
(32 url-safe bytes), but layering session auth in front keeps the
endpoint out of reach of anyone without a Prosper cookie.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from auth import CurrentUser, get_current_user
from services.storage import get_storage
from services.storage.gridfs_backend import consume_access_token

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{token}")
async def get_signed_file(token: str,
                            _user: CurrentUser = Depends(get_current_user)):
    if not token or len(token) < 20:
        raise HTTPException(400, "invalid token")
    storage_key = await consume_access_token(token)
    if storage_key is None:
        # Same response for not-found / expired / already-used so the
        # caller cannot enumerate states.
        raise HTTPException(404, "token not found or expired")
    content, meta = await get_storage().get(storage_key)
    content_type = str(meta.get("content_type") or "application/octet-stream")
    filename = str(meta.get("filename") or "file")
    return Response(
        content=content, media_type=content_type,
        headers={"Content-Disposition":
                    f'inline; filename="{filename}"',
                  "Cache-Control": "private, no-store"})
