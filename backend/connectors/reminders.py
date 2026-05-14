"""Apple Reminders connector.

Reminders only exposes itself via macOS-native APIs: Apple Events
(`osascript`), EventKit, or AppleScript over IPC. The dashboard usually
runs inside a Podman container on the Mac mini — the container can't see
the host's Reminders DB directly. So this connector supports two paths:

  1. **osascript mode** (preferred when running on the host directly):
     shell out to `osascript -e` with an AppleScript that walks every list
     and returns incomplete reminders as a JSON-ish CSV stream. Requires
     the user to have granted the running process access to Reminders in
     System Settings → Privacy & Security → Reminders.

  2. **File mode** (containerised deployments): point `reminders_path` at
     a JSON file the host writes via a cron/launchd job. Same pattern the
     calendar connector uses. Expected shape:

         {
           "reminders": [
             {"title": "...", "due_date": "ISO-8601" | null,
              "list_name": "...", "priority": 0-9, "notes": "..."}
           ],
           "fetched_at": "ISO-8601"
         }

If neither path produces data the connector returns `available: false`
with a clear reason — never raises — so the rest of the edition keeps
rendering.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import ConfigField, Connector

# AppleScript that prints one reminder per line as a tab-separated record:
#   <title>\t<due_date_iso_or_empty>\t<list_name>\t<priority>\t<notes>
# Tabs/newlines in titles or notes are stripped before output. Empty due
# dates and notes round-trip cleanly as empty strings between tabs.
_OSASCRIPT_SOURCE = r"""
on iso8601(d)
    if d is missing value then return ""
    set y to year of d as integer
    set m to (month of d as integer)
    set dd to day of d as integer
    set hh to hours of d as integer
    set mm to minutes of d as integer
    set ss to seconds of d as integer
    set pad to {"0","00","000"}
    set ymd to (text -4 thru -1 of ("0000" & y)) & "-" & ¬
        (text -2 thru -1 of ("00" & m)) & "-" & ¬
        (text -2 thru -1 of ("00" & dd))
    set hms to (text -2 thru -1 of ("00" & hh)) & ":" & ¬
        (text -2 thru -1 of ("00" & mm)) & ":" & ¬
        (text -2 thru -1 of ("00" & ss))
    return ymd & "T" & hms
end iso8601

on clean(t)
    if t is missing value then return ""
    set s to t as text
    set AppleScript's text item delimiters to tab
    set parts to text items of s
    set AppleScript's text item delimiters to " "
    set s to parts as text
    set AppleScript's text item delimiters to linefeed
    set parts to text items of s
    set AppleScript's text item delimiters to " "
    set s to parts as text
    set AppleScript's text item delimiters to return
    set parts to text items of s
    set AppleScript's text item delimiters to " "
    set s to parts as text
    set AppleScript's text item delimiters to ""
    return s
end clean

tell application "Reminders"
    set output to ""
    set theLists to every list
    repeat with aList in theLists
        set listName to name of aList
        set theReminders to (reminders of aList whose completed is false)
        repeat with r in theReminders
            set t to my clean(name of r)
            set d to ""
            try
                if (due date of r) is not missing value then
                    set d to my iso8601(due date of r)
                end if
            end try
            set p to 0
            try
                set p to priority of r
            end try
            set nbody to ""
            try
                set nbody to my clean(body of r)
            end try
            set output to output & t & tab & d & tab & listName & tab & (p as text) & tab & nbody & linefeed
        end repeat
    end repeat
    return output
end tell
"""


def _parse_osascript_output(raw: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        # Tolerate trailing fields being absent.
        while len(parts) < 5:
            parts.append("")
        title, due, list_name, prio, notes = parts[:5]
        try:
            priority = int(prio or "0")
        except (TypeError, ValueError):
            priority = 0
        out.append(
            {
                "title": title.strip(),
                "due_date": due.strip() or None,
                "list_name": list_name.strip(),
                "priority": priority,
                "notes": notes.strip(),
            }
        )
    return out


def _sort_key(r: dict[str, Any]) -> tuple[int, str, str]:
    # Reminders without a due date sort after dated ones; ties break on title.
    due = r.get("due_date") or ""
    return (0 if due else 1, due, (r.get("title") or "").lower())


async def _run_osascript(script: str, timeout: float) -> tuple[bool, str]:
    """Run an AppleScript via osascript. Returns (ok, stdout-or-stderr)."""
    if shutil.which("osascript") is None:
        return False, "osascript not on PATH"
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(input=script.encode("utf-8")), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return False, f"osascript timed out after {timeout}s"
    except FileNotFoundError:
        return False, "osascript not found"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    if proc.returncode != 0:
        msg = (stderr or b"").decode("utf-8", errors="replace").strip()
        # macOS reports TCC denials with code -1743 in the stderr.
        if "-1743" in msg or "not authorized" in msg.lower():
            return False, "Reminders access not granted (System Settings → Privacy → Reminders)"
        return False, msg or f"osascript exited {proc.returncode}"
    return True, (stdout or b"").decode("utf-8", errors="replace")


class RemindersConnector(Connector):
    id = "reminders"
    name = "Apple Reminders"
    description = "Incomplete reminders from every list, sorted by due date."
    icon = "✓"
    category = "personal"
    widget_ids = ("reminders",)
    config_schema = (
        ConfigField(
            name="mode",
            label="Source",
            help="'auto' tries osascript first, then the file. 'osascript' or 'file' forces one path.",
            default="auto",
            env_fallback="REMINDERS_MODE",
        ),
        ConfigField(
            name="reminders_path",
            label="Reminders JSON path",
            type="path",
            help="File written by a host-side sync job. Required when running inside a container.",
            placeholder="/data/reminders/today.json",
            default="/data/reminders/today.json",
            env_fallback="REMINDERS_PATH",
        ),
        ConfigField(
            name="timeout",
            label="osascript timeout (seconds)",
            type="number",
            default="6.0",
            env_fallback="REMINDERS_TIMEOUT",
        ),
        ConfigField(
            name="limit",
            label="Max reminders returned",
            type="number",
            default="50",
            env_fallback="REMINDERS_LIMIT",
        ),
    )

    def is_configured(self, stored: dict[str, Any] | None) -> bool:
        # Either source counts as configured. We can't probe TCC here, but if
        # osascript is on PATH the user can at least *try*; the file path has
        # a default so it always passes the simple "is set" check.
        resolved = self.resolve(stored)
        mode = (resolved.get("mode") or "auto").strip().lower()
        if mode in ("auto", "osascript") and shutil.which("osascript") is not None:
            return True
        return bool(str(resolved.get("reminders_path") or "").strip())

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        mode = (config.get("mode") or "auto").strip().lower()
        timeout = _to_float(config.get("timeout"), 6.0)
        path = Path(config.get("reminders_path") or "")

        if mode in ("auto", "osascript") and shutil.which("osascript"):
            ok, detail = await _run_osascript('tell application "Reminders" to return name of first list', timeout)
            if ok:
                return {"ok": True, "detail": f"osascript reachable; first list: {detail.strip()[:60]}"}
            if mode == "osascript":
                return {"ok": False, "detail": detail}
            # auto mode falls through to file
        if path.exists():
            try:
                json.loads(path.read_text())
            except Exception as e:
                return {"ok": False, "detail": f"file present but unreadable: {e}"}
            return {"ok": True, "detail": f"file present ({path})"}

        if mode == "file":
            return {"ok": False, "detail": f"file not found: {path}"}
        return {"ok": False, "detail": "osascript unavailable and no fallback file present"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        mode = (config.get("mode") or "auto").strip().lower()
        timeout = _to_float(config.get("timeout"), 6.0)
        path = Path(config.get("reminders_path") or "")
        limit = int(_to_float(config.get("limit"), 50.0))

        reminders: list[dict[str, Any]] | None = None
        source: str | None = None
        reason: str | None = None
        fetched_at: str | None = None

        if mode in ("auto", "osascript") and shutil.which("osascript"):
            ok, body = await _run_osascript(_OSASCRIPT_SOURCE, timeout)
            if ok:
                reminders = _parse_osascript_output(body)
                source = "osascript"
            elif mode == "osascript":
                reason = body
        if reminders is None and (mode in ("auto", "file")):
            if path.exists():
                try:
                    raw = json.loads(path.read_text())
                except Exception as e:
                    reason = f"could not parse {path}: {e}"
                else:
                    if isinstance(raw, dict):
                        items = raw.get("reminders") or []
                        fetched_at = raw.get("fetched_at")
                    elif isinstance(raw, list):
                        items = raw
                    else:
                        items = []
                    reminders = []
                    for r in items:
                        if not isinstance(r, dict):
                            continue
                        reminders.append(
                            {
                                "title": str(r.get("title") or "").strip(),
                                "due_date": r.get("due_date") or None,
                                "list_name": str(r.get("list_name") or "").strip(),
                                "priority": int(r.get("priority") or 0),
                                "notes": str(r.get("notes") or "").strip(),
                            }
                        )
                    source = f"file:{path.name}"
            elif reason is None:
                reason = f"file not found: {path}"

        if reminders is None:
            return {
                "reminders": {
                    "available": False,
                    "reason": reason or "no source available",
                    "reminders": [],
                    "count": 0,
                    "collected_at": now,
                }
            }

        reminders.sort(key=_sort_key)
        trimmed = reminders[:limit]
        return {
            "reminders": {
                "available": bool(trimmed),
                "source": source,
                "reminders": trimmed,
                "count": len(reminders),
                "fetched_at": fetched_at,
                "collected_at": now,
            }
        }


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


connector = RemindersConnector()
