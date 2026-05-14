"""Apple Reminders connector — file-fallback path is exercised here.

The osascript path only works on a macOS host with TCC consent; we don't
spin it up in CI. The file fallback is the path the prod container takes,
so it gets the bulk of the coverage. The osascript output parser is
exercised directly without touching the subprocess.
"""

from __future__ import annotations

import json

from backend.connectors.reminders import RemindersConnector, _parse_osascript_output


async def test_reminders_collect_from_file(tmp_path):
    feed = {
        "reminders": [
            {"title": "Mow lawn", "due_date": "2026-05-14T18:00:00", "list_name": "Home", "priority": 5},
            {"title": "Send invoice", "due_date": "2026-05-12T09:00:00", "list_name": "Work", "priority": 1},
            {"title": "No due date", "due_date": None, "list_name": "Misc", "priority": 0, "notes": ""},
        ],
        "fetched_at": "2026-05-13T10:00:00Z",
    }
    path = tmp_path / "today.json"
    path.write_text(json.dumps(feed))
    out = await RemindersConnector().collect({"mode": "file", "reminders_path": str(path), "timeout": 2.0, "limit": 10})
    r = out["reminders"]
    assert r["available"] is True
    assert r["count"] == 3
    # Earliest due-date first; undated reminders trail.
    assert [item["title"] for item in r["reminders"]] == ["Send invoice", "Mow lawn", "No due date"]
    assert r["source"] == f"file:{path.name}"
    assert r["fetched_at"] == "2026-05-13T10:00:00Z"
    assert "collected_at" in r


async def test_reminders_collect_missing_file_returns_unavailable(tmp_path):
    path = tmp_path / "no-such-file.json"
    out = await RemindersConnector().collect({"mode": "file", "reminders_path": str(path), "timeout": 2.0, "limit": 10})
    r = out["reminders"]
    assert r["available"] is False
    assert "no-such-file.json" in r["reason"] or "file not found" in r["reason"]
    assert r["reminders"] == []
    assert "collected_at" in r


async def test_reminders_collect_unreadable_file_returns_unavailable(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not-json{")
    out = await RemindersConnector().collect({"mode": "file", "reminders_path": str(path), "timeout": 2.0, "limit": 10})
    r = out["reminders"]
    assert r["available"] is False
    assert "could not parse" in r["reason"]


def test_reminders_parse_osascript_output():
    raw = (
        "Mow lawn\t2026-05-14T18:00:00\tHome\t5\tdon't forget edging\n"
        "Send invoice\t2026-05-12T09:00:00\tWork\t1\t\n"
        "Standalone\t\tMisc\t0\t\n"
    )
    parsed = _parse_osascript_output(raw)
    assert len(parsed) == 3
    assert parsed[0]["title"] == "Mow lawn"
    assert parsed[0]["due_date"] == "2026-05-14T18:00:00"
    assert parsed[0]["priority"] == 5
    assert parsed[0]["notes"] == "don't forget edging"
    assert parsed[2]["due_date"] is None


async def test_reminders_test_connection_file_missing(tmp_path):
    result = await RemindersConnector().test_connection(
        {"mode": "file", "reminders_path": str(tmp_path / "missing.json"), "timeout": 1.0}
    )
    assert result["ok"] is False
    assert "file not found" in result["detail"]


async def test_reminders_test_connection_file_present(tmp_path):
    path = tmp_path / "today.json"
    path.write_text(json.dumps({"reminders": []}))
    result = await RemindersConnector().test_connection({"mode": "file", "reminders_path": str(path), "timeout": 1.0})
    assert result["ok"] is True
    assert "file present" in result["detail"]
