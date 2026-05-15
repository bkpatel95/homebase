"""Google Calendar connector — direct API via the OAuth refresh-token flow.

Tokens are stored and refreshed by `backend.google_oauth`. The user wires
this up once by visiting /api/auth/google/start; after that the connector
just calls the v3 Calendar API to fetch today's events.

The connector reports `available=False` (not an exception) whenever the
OAuth client isn't configured or the user hasn't completed the consent
flow yet — the calendar widget then renders unavailable instead of
crashing the edition.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .. import google_oauth
from .base import Connector

log = logging.getLogger("homebase.connectors.calendar")

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
MAX_EVENTS = 8


def _local_tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TZ", "America/New_York"))


def _today_window() -> tuple[str, str]:
    """RFC3339 timestamps for [local-midnight, next-local-midnight)."""
    tz = _local_tz()
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _normalize_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Turn a Google Calendar event into the shape the frontend expects."""
    start = ev.get("start") or {}
    # `dateTime` for timed events, `date` (YYYY-MM-DD) for all-day events.
    start_iso = start.get("dateTime") or start.get("date") or ""
    all_day = "date" in start and "dateTime" not in start

    meeting_link = ev.get("hangoutLink")
    if not meeting_link:
        # Fall back to any video entry point in conferenceData.
        cdata = ev.get("conferenceData") or {}
        for ep in cdata.get("entryPoints") or []:
            if ep.get("entryPointType") == "video" and ep.get("uri"):
                meeting_link = ep["uri"]
                break

    return {
        "id": ev.get("id"),
        "title": ev.get("summary") or "Untitled",
        "start": start_iso,
        "all_day": all_day,
        "location": ev.get("location") or "",
        "meeting_link": meeting_link or "",
    }


class CalendarConnector(Connector):
    id = "calendar"
    name = "Google Calendar"
    description = "Today's events fetched live from Google Calendar via OAuth."
    icon = "▢"
    category = "personal"
    widget_ids = ("calendar",)
    config_schema = ()

    def is_configured(self, stored: dict[str, Any] | None) -> bool:
        return google_oauth.is_connected()

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        if not google_oauth.oauth_configured():
            return {"ok": False, "detail": "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set"}
        if not google_oauth.is_connected():
            return {"ok": False, "detail": "not connected — visit /api/auth/google/start"}
        try:
            token = await google_oauth.get_access_token()
        except Exception as e:
            return {"ok": False, "detail": f"token refresh failed: {e}"}
        if not token:
            return {"ok": False, "detail": "no access token after refresh"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    f"{CALENDAR_API}/users/me/calendarList",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"maxResults": 1},
                )
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
        if r.status_code != 200:
            return {"ok": False, "detail": f"Calendar API HTTP {r.status_code}"}
        return {"ok": True, "detail": "Calendar API reachable"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()

        if not google_oauth.oauth_configured():
            return {
                "calendar": {
                    "available": False,
                    "reason": "Google OAuth not configured.",
                    "events": [],
                    "count": 0,
                    "collected_at": now,
                }
            }
        if not google_oauth.is_connected():
            return {
                "calendar": {
                    "available": False,
                    "reason": "Not connected — visit /api/auth/google/start.",
                    "events": [],
                    "count": 0,
                    "collected_at": now,
                }
            }

        try:
            token = await google_oauth.get_access_token()
        except Exception as e:
            return {
                "calendar": {
                    "available": False,
                    "error": f"token refresh failed: {e}",
                    "events": [],
                    "count": 0,
                    "collected_at": now,
                }
            }
        if not token:
            return {
                "calendar": {
                    "available": False,
                    "reason": "Could not obtain access token.",
                    "events": [],
                    "count": 0,
                    "collected_at": now,
                }
            }

        time_min, time_max = _today_window()
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    f"{CALENDAR_API}/calendars/primary/events",
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "timeMin": time_min,
                        "timeMax": time_max,
                        "singleEvents": "true",
                        "orderBy": "startTime",
                        "maxResults": 50,
                    },
                )
        except Exception as e:
            return {
                "calendar": {
                    "available": False,
                    "error": f"{type(e).__name__}: {e}",
                    "events": [],
                    "count": 0,
                    "collected_at": now,
                }
            }
        if r.status_code != 200:
            return {
                "calendar": {
                    "available": False,
                    "error": f"Calendar API HTTP {r.status_code}",
                    "events": [],
                    "count": 0,
                    "collected_at": now,
                }
            }

        raw = (r.json() or {}).get("items") or []
        # Skip cancelled instances (singleEvents=true still surfaces them sometimes).
        events = [_normalize_event(ev) for ev in raw if ev.get("status") != "cancelled"]
        return {
            "calendar": {
                "available": bool(events),
                "events": events[:MAX_EVENTS],
                "count": len(events),
                "fetched_at": now,
                "collected_at": now,
            }
        }


connector = CalendarConnector()
