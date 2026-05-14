"""GET /api/health — liveness probe + per-connector staleness.

Two callers care about this endpoint:

  - Podman healthcheck (and any uptime monitor): treats the route as a
    binary "is the process alive" signal. It only inspects the status code,
    so we always return 200 and always include {"status": "ok"} at the top
    level for backward compatibility.

  - Frontend "Data sources" surface: wants a single roll-up of how recently
    each connector synced, what the last sync result was, and how stale the
    cached payload is. That data already lives in the connector store
    (set by `record_sync` after every `collect()` call) — this route just
    shapes it for the UI.

The endpoint bypasses the Cloudflare Access guard via the prefix check in
`cloudflare_access_guard` (any path ending in `/health` is allowed
through). Only timestamps and status flags are exposed here — no config
values or secrets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from .. import connectors

router = APIRouter()


def _age_seconds(iso_ts: str | None, *, now: datetime) -> int | None:
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    delta = (now - ts).total_seconds()
    if delta < 0:
        return 0
    return int(delta)


@router.get("/health")
async def health():
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for snapshot in connectors.describe_all():
        last_sync = snapshot.get("last_sync")
        out.append(
            {
                "id": snapshot["id"],
                "name": snapshot["name"],
                "category": snapshot["category"],
                "status": snapshot["status"],
                "configured": snapshot["configured"],
                "last_sync": last_sync,
                "last_status": snapshot.get("last_status"),
                "last_error": snapshot.get("last_error"),
                "age_seconds": _age_seconds(last_sync, now=now),
            }
        )
    return {
        "status": "ok",
        "checked_at": now.isoformat(),
        "connectors": out,
    }
