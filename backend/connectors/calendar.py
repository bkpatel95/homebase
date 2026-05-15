"""Calendar connector — Google Calendar API when connected, file-backed
today.json otherwise.

The connector tries the Google API first (shared OAuth credentials in
backend.google_oauth) when:
  - the operator has completed /api/auth/google/login, AND
  - `source` is not pinned to "file" in the connector config.

If the API path errors out or the operator has never connected Google,
the connector falls back to reading today's events from a JSON file
populated by an external syncer.

This means existing file-backed deployments keep rendering — flipping to
the Google API is a no-config-change upgrade once OAuth is completed.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from .. import google_oauth
from .base import ConfigField, Connector

log = logging.getLogger("homebase.connectors.calendar")

CALENDAR_API = "https://www.googleapis.com/calendar/v3"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_today(dt_str: str) -> bool:
    try:
        d = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return False
    return d == date.today()


class CalendarConnector(Connector):
    id = "calendar"
    name = "Google Calendar"
    description = "Today's events from the Google Calendar API or a file feed fallback."
    icon = "▢"
    category = "personal"
    widget_ids = ("calendar",)
    config_schema = (
        ConfigField(
            name="source",
            label="Source preference",
            type="string",
            help="'auto' (Google API if connected, else file), 'google', or 'file'.",
            default="auto",
            env_fallback="CALENDAR_SOURCE",
        ),
        ConfigField(
            name="calendar_id",
            label="Google Calendar ID",
            type="string",
            help="'primary' or a specific calendar address. Only used when source != 'file'.",
            default="primary",
            env_fallback="CALENDAR_ID",
        ),
        ConfigField(
            name="events_path",
            label="Events JSON path (file fallback)",
            type="path",
            help='Written by your calendar syncer. Expected shape: {"events": [...]}',
            placeholder="/data/calendar/today.json",
            default="/data/calendar/today.json",
            env_fallback="CALENDAR_EVENTS",
        ),
        ConfigField(
            name="timeout",
            label="Google API timeout (seconds)",
            type="number",
            default="5.0",
            env_fallback="CALENDAR_TIMEOUT",
        ),
    )

    def is_configured(self, stored: dict[str, Any] | None) -> bool:
        """The connector is configured when *either* the file fallback path
        is set or Google is connected — both paths are valid."""
        resolved = self.resolve(stored)
        if (resolved.get("events_path") or "").strip():
            return True
        return google_oauth.is_configured() and google_oauth.is_connected()

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        source = (config.get("source") or "auto").lower()
        # When Google is the preferred source (auto+connected, or explicit "google")
        # we test the API. Otherwise we fall through to the file probe so the
        # legacy deployments still get a meaningful status.
        use_google = source == "google" or (
            source == "auto" and google_oauth.is_configured() and google_oauth.is_connected()
        )
        if use_google:
            return await self._test_google(config)
        return _test_file(config)

    async def _test_google(self, config: dict[str, Any]) -> dict[str, Any]:
        if not google_oauth.is_configured():
            return {"ok": False, "detail": "Google OAuth not configured on the server."}
        if not google_oauth.is_connected():
            return {"ok": False, "detail": "Google account not connected — visit /api/auth/google/login"}
        try:
            token = await google_oauth.get_access_token()
        except google_oauth.GoogleOAuthError as e:
            return {"ok": False, "detail": str(e)}

        calendar_id = (config.get("calendar_id") or "primary").strip() or "primary"
        timeout = _to_float(config.get("timeout"), 5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(
                    f"{CALENDAR_API}/calendars/{calendar_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if r.status_code == 200:
                return {"ok": True, "detail": f"Google Calendar '{r.json().get('summary', calendar_id)}' reachable"}
            return {"ok": False, "detail": f"Calendar API HTTP {r.status_code}: {r.text[:160]}"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        source = (config.get("source") or "auto").lower()
        use_google = source == "google" or (
            source == "auto" and google_oauth.is_configured() and google_oauth.is_connected()
        )

        if use_google:
            payload = await self._collect_google(config)
            if payload is not None:
                return {"calendar": payload}
            # Auto mode: API failed → fall through to file. Explicit "google"
            # mode surfaces the error instead of silently falling back.
            if source == "google":
                return {
                    "calendar": {
                        "available": False,
                        "events": [],
                        "count": 0,
                        "collected_at": _now(),
                        "error": "Google Calendar API call failed (see logs)",
                    }
                }
            log.info("calendar: Google API path failed, falling back to file feed")

        return {"calendar": _collect_file(config)}

    async def _collect_google(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """Return today's events from Google Calendar, or None on failure
        so the caller can decide whether to fall back."""
        try:
            token = await google_oauth.get_access_token()
        except google_oauth.GoogleOAuthError as e:
            log.warning("calendar: cannot get access token: %s", e)
            return None

        calendar_id = (config.get("calendar_id") or "primary").strip() or "primary"
        timeout = _to_float(config.get("timeout"), 5.0)

        # Today, in UTC. Google accepts RFC3339; using midnight-to-midnight
        # in the server's local TZ would be more correct for "today", but
        # the existing file-backed path also keys off date.today() so we
        # stay consistent here.
        start = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        params = {
            "timeMin": start.isoformat().replace("+00:00", "Z"),
            "timeMax": end.isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "20",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(
                    f"{CALENDAR_API}/calendars/{calendar_id}/events",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
            r.raise_for_status()
        except Exception as e:
            log.warning("calendar: Google API call failed: %s", e)
            return None

        items = r.json().get("items", [])
        events = [_normalize_google_event(e) for e in items]
        events = [e for e in events if e]
        events.sort(key=lambda e: e.get("start", ""))

        return {
            "available": bool(events),
            "events": events[:8],
            "count": len(events),
            "source": "google-api",
            "collected_at": _now(),
        }


def _normalize_google_event(item: dict[str, Any]) -> dict[str, Any] | None:
    """Reshape a Google event resource into the same envelope the file feed
    uses, so downstream widgets don't have to know which source ran."""
    start_obj = item.get("start") or {}
    end_obj = item.get("end") or {}
    start = start_obj.get("dateTime") or start_obj.get("date")
    end = end_obj.get("dateTime") or end_obj.get("date")
    if not start:
        return None
    return {
        "id": item.get("id"),
        "title": item.get("summary") or "(no title)",
        "start": start,
        "end": end,
        "location": item.get("location"),
        "all_day": "date" in start_obj and "dateTime" not in start_obj,
        "html_link": item.get("htmlLink"),
    }


def _test_file(config: dict[str, Any]) -> dict[str, Any]:
    p = Path(config.get("events_path") or "")
    if not p.exists():
        return {"ok": False, "detail": f"feed not found: {p}"}
    try:
        json.loads(p.read_text())
    except Exception as e:
        return {"ok": False, "detail": f"unreadable: {e}"}
    return {"ok": True, "detail": f"feed present ({p})"}


def _collect_file(config: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    path = Path(config.get("events_path") or "")
    if not path.exists():
        return {
            "available": False,
            "reason": f"No calendar feed at {path}.",
            "events": [],
            "count": 0,
            "collected_at": now,
        }
    try:
        raw = json.loads(path.read_text())
    except Exception as e:
        return {
            "available": False,
            "error": f"parse failed: {e}",
            "events": [],
            "count": 0,
            "collected_at": now,
        }

    events_in = raw.get("events", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    today_events = [e for e in events_in if _is_today(e.get("start", ""))]
    today_events.sort(key=lambda e: e.get("start", ""))

    return {
        "available": bool(today_events),
        "events": today_events[:8],
        "count": len(today_events),
        "source": "file",
        "fetched_at": raw.get("fetched_at") if isinstance(raw, dict) else None,
        "collected_at": now,
    }


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


connector = CalendarConnector()
