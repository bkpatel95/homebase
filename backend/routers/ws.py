"""WebSocket endpoint — pushes `edition_dirty` events when the chat bar or
API mutates layout.

Auth: same Cloudflare Access header the rest of the API enforces. Cloudflared
forwards the `Cf-Access-Authenticated-User-Email` header on WS handshakes too,
so we read it from the upgrade request and 1008 (Policy Violation) if it's
missing or not on the allowlist.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import ws_manager

log = logging.getLogger("homebase.ws")

router = APIRouter()

ALLOWED_EMAILS = {
    e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "bhavipatel141@gmail.com").split(",") if e.strip()
}
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "true").lower() in ("1", "true", "yes")


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    if REQUIRE_AUTH:
        email = websocket.headers.get("cf-access-authenticated-user-email", "").strip().lower()
        if not email or email not in ALLOWED_EMAILS:
            await websocket.close(code=1008, reason="unauthorized")
            return

    await websocket.accept()
    await ws_manager.register(websocket)
    await websocket.send_json({"type": "hello", "msg": "connected"})

    try:
        while True:
            # We don't expect client→server messages yet, but keep the
            # connection alive by awaiting (and consuming any ping payloads).
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug("ws error: %s", e)
    finally:
        await ws_manager.unregister(websocket)
