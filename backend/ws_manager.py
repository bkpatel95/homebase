"""Module-level WebSocket connection registry.

Anywhere in the app can `await broadcast({...})` and every connected client
will receive the message. Used to push `edition_dirty` notifications when the
chat bar mutates layout state, so the newspaper re-renders without a refresh.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("homebase.ws")

_lock = asyncio.Lock()
_connections: set[WebSocket] = set()


async def register(ws: WebSocket) -> None:
    async with _lock:
        _connections.add(ws)


async def unregister(ws: WebSocket) -> None:
    async with _lock:
        _connections.discard(ws)


async def broadcast(message: dict[str, Any]) -> int:
    """Send `message` (JSON-encoded) to every connected client.

    Returns the number of clients reached. Silently drops dead sockets — the
    next attempt to use them will surface the error and remove them.
    """
    async with _lock:
        targets = list(_connections)

    sent = 0
    for ws in targets:
        try:
            await ws.send_json(message)
            sent += 1
        except Exception as e:
            log.debug("dropping ws: %s", e)
            await unregister(ws)
    return sent


def connection_count() -> int:
    return len(_connections)
