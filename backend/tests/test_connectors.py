"""Connectors — make sure each one handles its sad paths cleanly.

The connectors are the most failure-prone surface in the app: they all talk
to external services that can be down, return junk, or return 401. The
production app has to keep rendering an edition even if every connector
fails, so this suite exercises the error paths explicitly.

External HTTP is mocked with respx so the tests are hermetic and fast.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
import respx

from backend.connectors.calendar import CalendarConnector
from backend.connectors.gmail import GMAIL_API, GmailConnector
from backend.connectors.oura import OURA_API, OuraConnector
from backend.connectors.plex import PlexConnector

# ─── Oura ────────────────────────────────────────────────────────────────────


@respx.mock
async def test_oura_test_connection_401_returns_auth_error():
    """A 401 from Oura must surface as ok=False with an explicit HTTP code."""
    respx.get(f"{OURA_API}/personal_info").mock(return_value=httpx.Response(401))
    result = await OuraConnector().test_connection({"token": "bad-token", "timeout": 2.0})
    assert result["ok"] is False
    assert "401" in result["detail"]


@respx.mock
async def test_oura_test_connection_200_returns_ok():
    respx.get(f"{OURA_API}/personal_info").mock(return_value=httpx.Response(200, json={"id": "x"}))
    result = await OuraConnector().test_connection({"token": "good-token", "timeout": 2.0})
    assert result["ok"] is True


@respx.mock
async def test_oura_test_connection_network_error_does_not_raise():
    """Connection errors must round-trip into a tidy dict, not bubble up."""
    respx.get(f"{OURA_API}/personal_info").mock(side_effect=httpx.ConnectError("boom"))
    result = await OuraConnector().test_connection({"token": "x", "timeout": 2.0})
    assert result["ok"] is False
    assert "ConnectError" in result["detail"]


async def test_oura_test_connection_no_token_no_file():
    """No token and no fallback file: still must return a dict, not crash."""
    result = await OuraConnector().test_connection({"token": "", "summary_path": "/nope/missing.json"})
    assert result == {"ok": False, "detail": "no token and no summary file"}


async def test_oura_test_connection_with_summary_file(tmp_path):
    summary = tmp_path / "summary.json"
    summary.write_text("[]")
    result = await OuraConnector().test_connection({"token": "", "summary_path": str(summary)})
    assert result["ok"] is True


async def test_oura_collect_no_token_no_file_returns_unavailable():
    out = await OuraConnector().collect({"token": "", "summary_path": "/nope/missing.json"})
    assert out["health_wellness"]["available"] is False
    assert "collected_at" in out["health_wellness"]


async def test_oura_collect_from_summary_file(tmp_path):
    """File fallback path: the connector reads the latest dated row."""
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            [
                {"date": "2025-01-01", "sleep_score": 70, "steps": 1000},
                {"date": "2025-01-03", "sleep_score": 85, "steps": 9000},
                {"date": "2025-01-02", "sleep_score": 75, "steps": 4000},
            ]
        )
    )
    out = await OuraConnector().collect({"token": "", "summary_path": str(summary)})
    hw = out["health_wellness"]
    assert hw["available"] is True
    assert hw["sleep_score"] == 85  # latest date wins
    assert hw["steps"] == 9000


# ─── Calendar ────────────────────────────────────────────────────────────────


async def test_calendar_missing_file_returns_empty_schedule(tmp_path):
    """Calendar feed not on disk yet → connector returns an unavailable payload,
    not an exception. The widget should still render."""
    path = tmp_path / "does-not-exist.json"
    out = await CalendarConnector().collect({"events_path": str(path)})
    cal = out["calendar"]
    assert cal["available"] is False
    assert cal["events"] == []
    assert cal["count"] == 0


async def test_calendar_unreadable_file_returns_error_payload(tmp_path):
    path = tmp_path / "today.json"
    path.write_text("not-json {{")
    out = await CalendarConnector().collect({"events_path": str(path)})
    cal = out["calendar"]
    assert cal["available"] is False
    assert "parse failed" in cal["error"]


async def test_calendar_filters_to_todays_events(tmp_path):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    feed = {
        "events": [
            {"summary": "Yesterday", "start": (today - timedelta(days=1)).isoformat() + "T09:00:00Z"},
            {"summary": "Today A", "start": today.isoformat() + "T15:00:00Z"},
            {"summary": "Today B", "start": today.isoformat() + "T10:00:00Z"},
            {"summary": "Tomorrow", "start": tomorrow.isoformat() + "T09:00:00Z"},
        ]
    }
    path = tmp_path / "today.json"
    path.write_text(json.dumps(feed))
    out = await CalendarConnector().collect({"events_path": str(path)})
    cal = out["calendar"]
    assert cal["count"] == 2
    # Events come out sorted by start time.
    assert [e["summary"] for e in cal["events"]] == ["Today B", "Today A"]


async def test_calendar_test_connection_missing_file(tmp_path):
    result = await CalendarConnector().test_connection({"events_path": str(tmp_path / "nope.json")})
    assert result["ok"] is False
    assert "feed not found" in result["detail"]


async def test_calendar_test_connection_valid_json(tmp_path):
    path = tmp_path / "today.json"
    path.write_text(json.dumps({"events": []}))
    result = await CalendarConnector().test_connection({"events_path": str(path)})
    assert result["ok"] is True


# ─── Plex + Overseerr ────────────────────────────────────────────────────────


@respx.mock
async def test_plex_test_auth_error_distinct_from_network_error():
    """401 from Plex must surface as 'Plex HTTP 401' — different message
    than a connection error so we can tell them apart in the UI."""
    respx.get("http://plex.test/identity").mock(return_value=httpx.Response(401))
    cfg = {
        "plex_url": "http://plex.test",
        "plex_token": "bad",
        "overseerr_url": "",
        "overseerr_key": "",
        "timeout": 2.0,
    }
    result = await PlexConnector().test_connection(cfg)
    assert result["ok"] is False
    assert "Plex HTTP 401" in result["detail"]


@respx.mock
async def test_plex_test_network_error_message_distinct():
    respx.get("http://plex.test/identity").mock(side_effect=httpx.ConnectError("nope"))
    cfg = {
        "plex_url": "http://plex.test",
        "plex_token": "good",
        "overseerr_url": "",
        "overseerr_key": "",
        "timeout": 2.0,
    }
    result = await PlexConnector().test_connection(cfg)
    assert result["ok"] is False
    assert "Plex error" in result["detail"]
    assert "HTTP" not in result["detail"]


@respx.mock
async def test_plex_test_one_ok_one_fails_returns_ok_true():
    """If Plex works but Overseerr fails, we still consider the connector ok."""
    respx.get("http://plex.test/identity").mock(return_value=httpx.Response(200))
    respx.get("http://ovr.test/api/v1/status").mock(return_value=httpx.Response(500))
    cfg = {
        "plex_url": "http://plex.test",
        "plex_token": "good",
        "overseerr_url": "http://ovr.test",
        "overseerr_key": "key",
        "timeout": 2.0,
    }
    result = await PlexConnector().test_connection(cfg)
    assert result["ok"] is True
    assert "Plex ok" in result["detail"]
    assert "Overseerr HTTP 500" in result["detail"]


async def test_plex_test_no_creds_returns_clear_message():
    cfg = {"plex_url": "", "plex_token": "", "overseerr_url": "", "overseerr_key": "", "timeout": 2.0}
    result = await PlexConnector().test_connection(cfg)
    assert result == {"ok": False, "detail": "neither Plex nor Overseerr is configured"}


@respx.mock
async def test_plex_collect_records_errors_but_returns_payload():
    """A failing Plex call must not sink the connector — the payload still
    comes back, and the error is attached for the UI."""
    respx.get("http://plex.test/library/recentlyAdded").mock(side_effect=httpx.ConnectError("x"))
    cfg = {
        "plex_url": "http://plex.test",
        "plex_token": "good",
        "overseerr_url": "",
        "overseerr_key": "",
        "timeout": 2.0,
    }
    out = await PlexConnector().collect(cfg)
    media = out["media"]
    assert media["available"] is False
    assert media["errors"] is not None
    assert any("plex" in e for e in media["errors"])


@respx.mock
async def test_plex_collect_overseerr_pending_parses_request_list():
    overseerr_payload = {
        "results": [
            {
                "id": 1,
                "status": 1,
                "createdAt": "2025-05-01T00:00:00Z",
                "media": {"mediaType": "movie", "title": "Foo", "tmdbId": 42},
                "requestedBy": {"displayName": "alice"},
            }
        ]
    }
    respx.get("http://ovr.test/api/v1/request").mock(return_value=httpx.Response(200, json=overseerr_payload))
    cfg = {
        "plex_url": "",
        "plex_token": "",
        "overseerr_url": "http://ovr.test",
        "overseerr_key": "key",
        "timeout": 2.0,
    }
    out = await PlexConnector().collect(cfg)
    pending = out["media"]["pending_requests"]
    assert len(pending) == 1
    assert pending[0]["title"] == "Foo"
    assert pending[0]["requested_by"] == "alice"


# ─── registry-level safety net ───────────────────────────────────────────────


async def test_connector_registry_isolates_failures(monkeypatch, sources_path):
    """A single connector raising must NOT take down the rest of collect_all()."""
    from backend import connectors as registry

    async def boom(self, config):
        raise RuntimeError("simulated outage")

    monkeypatch.setattr(OuraConnector, "collect", boom)

    out = await registry.collect_all()
    # Every other connector still produced something; oura's payload has an
    # `error` field but no exception escaped.
    assert isinstance(out, dict)
    hw = out.get("health_wellness")
    assert hw is not None
    assert hw.get("available") is False
    assert "RuntimeError" in (hw.get("error") or "")


def test_calendar_is_configured_when_path_field_has_value(monkeypatch):
    """`is_configured` reflects whether the required field has a value, not
    whether the file exists on disk. Existence is checked when collect()
    actually runs."""
    monkeypatch.delenv("CALENDAR_EVENTS", raising=False)
    # Default is set on the field, so even {} resolves to "configured".
    assert CalendarConnector().is_configured({}) is True
    assert CalendarConnector().is_configured({"events_path": "/anywhere"}) is True


# ─── Calendar via Google API ─────────────────────────────────────────────────


@respx.mock
async def test_calendar_google_path_normalises_events(monkeypatch, tmp_path):
    """When `source=google` and the OAuth token store has live creds, the
    connector calls the Calendar API and reshapes each event into the same
    envelope the file feed uses (start/title/etc.)."""
    from backend import google_oauth

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    tokens = tmp_path / "google_oauth.json"
    monkeypatch.setattr(google_oauth, "TOKENS_PATH", tokens)
    tokens.write_text(
        json.dumps(
            {
                "access_token": "live-access",
                "refresh_token": "r",
                "expires_at": 9_999_999_999,  # very far in the future
                "email": "bhavi@example.com",
            }
        )
    )

    today = date.today().isoformat()
    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "evt-1",
                        "summary": "Standup",
                        "start": {"dateTime": f"{today}T15:00:00Z"},
                        "end": {"dateTime": f"{today}T15:30:00Z"},
                        "htmlLink": "https://cal/evt-1",
                    },
                    {
                        "id": "evt-2",
                        "summary": "Lunch",
                        "start": {"dateTime": f"{today}T12:00:00Z"},
                        "end": {"dateTime": f"{today}T13:00:00Z"},
                    },
                ]
            },
        )
    )

    out = await CalendarConnector().collect({"source": "google", "calendar_id": "primary"})
    cal = out["calendar"]
    assert cal["available"] is True
    assert cal["count"] == 2
    assert cal["source"] == "google-api"
    # Order by start: Lunch at 12 before Standup at 15.
    assert [e["title"] for e in cal["events"]] == ["Lunch", "Standup"]


@respx.mock
async def test_calendar_explicit_google_source_does_not_fall_back(monkeypatch, tmp_path):
    """`source=google` means "use the API or report the error" — silently
    rendering a stale file would mask a real outage."""
    from backend import google_oauth

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    tokens = tmp_path / "google_oauth.json"
    monkeypatch.setattr(google_oauth, "TOKENS_PATH", tokens)
    tokens.write_text(json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 9_999_999_999}))

    respx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events").mock(
        side_effect=httpx.ConnectError("boom")
    )

    feed = tmp_path / "today.json"
    feed.write_text(json.dumps({"events": []}))  # file would have worked
    out = await CalendarConnector().collect({"source": "google", "calendar_id": "primary", "events_path": str(feed)})
    cal = out["calendar"]
    assert cal["available"] is False
    assert "error" in cal


# ─── Gmail ───────────────────────────────────────────────────────────────────


async def test_gmail_unavailable_when_oauth_not_configured(monkeypatch):
    """No GOOGLE_CLIENT_ID → connector returns a tidy unavailable payload
    pointing the operator at the OAuth flow."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    out = await GmailConnector().collect({})
    g = out["gmail"]
    assert g["available"] is False
    assert "OAuth" in g["reason"]


async def test_gmail_unavailable_when_not_connected(monkeypatch, tmp_path):
    """OAuth client configured but no refresh token on disk → reason
    string points the operator at /api/auth/google/login."""
    from backend import google_oauth

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(google_oauth, "TOKENS_PATH", tmp_path / "missing.json")
    out = await GmailConnector().collect({})
    g = out["gmail"]
    assert g["available"] is False
    assert "/api/auth/google/login" in g["reason"]


@respx.mock
async def test_gmail_collect_returns_unread_total_and_previews(monkeypatch, tmp_path):
    """End-to-end: stored tokens → label fetch → metadata fan-out → final
    payload. The payload shape is what the widget binds to."""
    from backend import google_oauth

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    tokens = tmp_path / "google_oauth.json"
    monkeypatch.setattr(google_oauth, "TOKENS_PATH", tokens)
    tokens.write_text(
        json.dumps(
            {
                "access_token": "a",
                "refresh_token": "r",
                "expires_at": 9_999_999_999,
                "email": "bhavi@example.com",
            }
        )
    )

    respx.get(f"{GMAIL_API}/labels/INBOX").mock(return_value=httpx.Response(200, json={"threadsUnread": 3}))
    respx.get(f"{GMAIL_API}/messages").mock(
        return_value=httpx.Response(
            200,
            json={"messages": [{"id": "m1"}, {"id": "m2"}]},
        )
    )
    respx.get(f"{GMAIL_API}/messages/m1").mock(
        return_value=httpx.Response(
            200,
            json={
                "snippet": "hello there",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Alice <a@example.com>"},
                        {"name": "Subject", "value": "Coffee?"},
                        {"name": "Date", "value": "Wed, 14 May 2026 10:00:00 -0400"},
                    ]
                },
            },
        )
    )
    respx.get(f"{GMAIL_API}/messages/m2").mock(
        return_value=httpx.Response(
            200,
            json={
                "snippet": "the report",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Bob"},
                        {"name": "Subject", "value": "Q2"},
                    ]
                },
            },
        )
    )

    out = await GmailConnector().collect({})
    g = out["gmail"]
    assert g["available"] is True
    assert g["unread_total"] == 3
    assert len(g["unread_preview"]) == 2
    assert g["unread_preview"][0]["subject"] == "Coffee?"
    assert g["email"] == "bhavi@example.com"


async def test_gmail_is_configured_requires_oauth_and_connection(monkeypatch, tmp_path):
    """The Sources panel uses is_configured() to decide the status pill.
    Both halves of the OAuth setup must be in place for it to flip green."""
    from backend import google_oauth

    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert GmailConnector().is_configured({}) is False

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(google_oauth, "TOKENS_PATH", tmp_path / "missing.json")
    assert GmailConnector().is_configured({}) is False

    tokens = tmp_path / "google_oauth.json"
    monkeypatch.setattr(google_oauth, "TOKENS_PATH", tokens)
    tokens.write_text(json.dumps({"refresh_token": "r"}))
    assert GmailConnector().is_configured({}) is True
