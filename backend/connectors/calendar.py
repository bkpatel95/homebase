"""Calendar connector — file-backed today.json populated by an external syncer."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .base import ConfigField, Connector


def _is_today(dt_str: str) -> bool:
    try:
        d = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).date()
    except (ValueError, AttributeError):
        return False
    return d == date.today()


class CalendarConnector(Connector):
    id = "calendar"
    name = "Google Calendar"
    description = "Today's events from a JSON feed kept up-to-date by a cron on another machine."
    icon = "▢"
    category = "personal"
    widget_ids = ("calendar",)
    config_schema = (
        ConfigField(
            name="events_path",
            label="Events JSON path",
            type="path",
            required=True,
            help='File written by your calendar syncer. Expected shape: {"events": [...]}',
            placeholder="/data/calendar/today.json",
            default="/data/calendar/today.json",
            env_fallback="CALENDAR_EVENTS",
        ),
    )

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        p = Path(config.get("events_path") or "")
        if not p.exists():
            return {"ok": False, "detail": f"feed not found: {p}"}
        try:
            json.loads(p.read_text())
        except Exception as e:
            return {"ok": False, "detail": f"unreadable: {e}"}
        return {"ok": True, "detail": f"feed present ({p})"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        path = Path(config.get("events_path") or "")
        if not path.exists():
            return {
                "calendar": {
                    "available": False,
                    "reason": f"No calendar feed at {path}.",
                    "events": [],
                    "count": 0,
                    "collected_at": now,
                }
            }
        try:
            raw = json.loads(path.read_text())
        except Exception as e:
            return {
                "calendar": {
                    "available": False,
                    "error": f"parse failed: {e}",
                    "events": [],
                    "count": 0,
                    "collected_at": now,
                }
            }

        events_in = raw.get("events", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        today_events = [e for e in events_in if _is_today(e.get("start", ""))]
        today_events.sort(key=lambda e: e.get("start", ""))

        return {
            "calendar": {
                "available": bool(today_events),
                "events": today_events[:8],
                "count": len(today_events),
                "fetched_at": raw.get("fetched_at") if isinstance(raw, dict) else None,
                "collected_at": now,
            }
        }


connector = CalendarConnector()
