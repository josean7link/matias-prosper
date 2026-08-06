"""Phase 16.x — Public proxy for Andes → us webhooks.

Andes can only reach us through the public ingress (which routes `/api/*` to
FastAPI on port 8001). The gateway lives on `localhost:8090` and is not
externally exposed.

This endpoint forwards the raw body + signature headers UNTOUCHED to the
gateway's `/webhooks/andes`, where ES256 verification happens. The gateway
then forwards the verified payload to `/internal/ramp/webhook` for dispatch.

Net architecture for incoming webhooks:

    Andes ──HTTPS──▶ ingress ──▶ FastAPI /api/v1/ramp/webhooks/andes  (this file)
                                          │ raw body + headers
                                          ▼
                                  gateway /webhooks/andes  (ES256 verify)
                                          │ verified
                                          ▼
                              FastAPI /internal/ramp/webhook  (dispatch)
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Request, Response

logger = logging.getLogger("prosper.ramp.public_webhook")

router = APIRouter(tags=["ramp-public-webhook"])

_PROXY_HEADERS = {
    "x-webhook-timestamp",
    "x-webhook-signature",
    "x-webhook-delivery-id",
    "content-type",
}


def _gateway_url() -> str:
    return (os.environ.get("ANDES_GATEWAY_URL")
              or "http://localhost:8090").rstrip("/")


@router.post("/ramp/webhooks/andes")
async def proxy_andes_webhook(request: Request):
    """Public Andes webhook receiver. Forwards raw body + signing headers
    to the internal gateway. NEVER trusts the payload here — verification
    happens inside the gateway. Returns the gateway's status code verbatim
    so Andes' built-in retry policy works correctly."""
    raw = await request.body()
    headers = {k: v for k, v in request.headers.items()
                if k.lower() in _PROXY_HEADERS}
    if "content-type" not in headers:
        headers["content-type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=15.0) as cx:
            r = await cx.post(f"{_gateway_url()}/webhooks/andes",
                                 content=raw, headers=headers)
    except httpx.HTTPError as e:
        logger.exception("gateway unreachable for webhook proxy: %s", e)
        return Response(content=b'{"error":"gateway unreachable"}',
                          status_code=502,
                          media_type="application/json")
    return Response(content=r.content, status_code=r.status_code,
                      media_type=r.headers.get("content-type",
                                                "application/json"))
