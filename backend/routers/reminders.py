"""GET /api/reminders — incomplete Apple Reminders, sorted by due date.

Thin wrapper around the reminders connector. The connector handles both
the on-host osascript path and the file fallback used when the dashboard
runs inside a container, so this route stays small.
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import connectors

router = APIRouter()


@router.get("/reminders")
async def get_reminders():
    return await connectors.collect_widget("reminders")
