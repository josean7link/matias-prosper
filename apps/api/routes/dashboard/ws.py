"""WebSocket — pushes ops-queue updates instead of 30s polling.

Authentication: parses the `prosper_session` cookie like the rest of the API.
Behaviour: sends the queue snapshot once on connect, then re-checks every
`POLL_SECONDS` seconds. Only pushes when at least one count changed (so an
idle dashboard doesn't get spammed).
"""
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth import parse_jwt
from roles import Role

from ._deps import DASH_ROLES
from .ops_queue import build_ops_queue

router = APIRouter()

POLL_SECONDS = 10


def _signature(snap: dict) -> tuple:
    """Tuple of all the counts — used to detect changes."""
    return (
        snap.get("approvals", {}).get("count", 0),
        snap.get("kyb", {}).get("count", 0),
        snap.get("alerts", {}).get("count", 0),
        snap.get("webhook_failing", {}).get("count", 0),
        snap.get("reconciliation", {}).get("count", 0),
    )


@router.websocket("/ws/ops-queue")
async def ws_ops_queue(ws: WebSocket):
    # ── Auth via prosper_session cookie ───────────────────────────────────
    token = ws.cookies.get("prosper_session")
    if not token:
        await ws.close(code=4401)
        return
    try:
        payload = parse_jwt(token)
    except Exception:
        await ws.close(code=4401)
        return
    try:
        role = Role(payload.get("role"))
    except ValueError:
        await ws.close(code=4403)
        return
    if role not in DASH_ROLES:
        await ws.close(code=4403)
        return

    await ws.accept()

    last_sig: tuple | None = None
    try:
        while True:
            snap = await build_ops_queue()
            sig = _signature(snap)
            if sig != last_sig:
                await ws.send_text(json.dumps(snap))
                last_sig = sig
            # Allow client pings to extend liveness without server work
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=POLL_SECONDS)
                if msg == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass
