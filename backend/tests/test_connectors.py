"""Connectors — make sure each one handles its sad paths cleanly.

The connectors are the most failure-prone surface in the app: they all talk
to external services that can be down, return junk, or return 401. The
production app has to keep rendering an edition even if every connector
fails, so this suite exercises the error paths explicitly.

External HTTP is mocked with respx so the tests are hermetic and fast.
"""

from __future__ import annotations

import json
import time

import httpx
import respx

from backend.connectors.calendar import CALENDAR_API, CalendarConnector
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


def _wire_google_oauth(monkeypatch, tmp_path, *, with_tokens: bool = True):
    """Point google_oauth at a tmp token file and set client creds in env."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://homebase.test/api/auth/google/callback")
    token_path = tmp_path / "google_token.json"
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(token_path))
    if with_tokens:
        token_path.write_text(
            json.dumps(
                {
                    "refresh_token": "refresh-xyz",
                    "access_token": "access-abc",
                    "expires_at": time.time() + 3600,
                }
            )
        )
    return token_path


async def test_calendar_unavailable_when_oauth_not_configured(monkeypatch, tmp_path):
    """No client creds → connector renders unavailable, not an exception."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(tmp_path / "google_token.json"))
    out = await CalendarConnector().collect({})
    cal = out["calendar"]
    assert cal["available"] is False
    assert "not configured" in cal["reason"].lower()
    assert cal["events"] == []
    assert cal["count"] == 0


async def test_calendar_unavailable_when_not_connected(monkeypatch, tmp_path):
    """OAuth client set but no refresh token persisted → unavailable with a
    pointer to the start endpoint."""
    _wire_google_oauth(monkeypatch, tmp_path, with_tokens=False)
    out = await CalendarConnector().collect({})
    cal = out["calendar"]
    assert cal["available"] is False
    assert "/api/auth/google/start" in cal["reason"]


@respx.mock
async def test_calendar_collect_normalizes_google_events(monkeypatch, tmp_path):
    """Connector turns the Google Calendar v3 event shape into the frontend
    contract: title (from summary), start (ISO), all_day, meeting_link."""
    _wire_google_oauth(monkeypatch, tmp_path)
    respx.get(f"{CALENDAR_API}/calendars/primary/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "evt-1",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-05-14T10:00:00-04:00"},
                        "location": "Zoom",
                        "hangoutLink": "https://meet.google.com/abc",
                    },
                    {
                        "id": "evt-2",
                        "summary": "Lunch",
                        "start": {"date": "2026-05-14"},
                    },
                    {
                        "id": "evt-3",
                        "status": "cancelled",
                        "summary": "Cancelled thing",
                        "start": {"dateTime": "2026-05-14T15:00:00-04:00"},
                    },
                ]
            },
        )
    )
    out = await CalendarConnector().collect({})
    cal = out["calendar"]
    assert cal["available"] is True
    assert cal["count"] == 2  # cancelled event skipped
    titles = [e["title"] for e in cal["events"]]
    assert titles == ["Standup", "Lunch"]
    assert cal["events"][0]["meeting_link"] == "https://meet.google.com/abc"
    assert cal["events"][1]["all_day"] is True


@respx.mock
async def test_calendar_collect_api_error_returned_in_payload(monkeypatch, tmp_path):
    """A 5xx from Google must surface as available=False with the HTTP code,
    not raise — the rest of the edition still has to render."""
    _wire_google_oauth(monkeypatch, tmp_path)
    respx.get(f"{CALENDAR_API}/calendars/primary/events").mock(return_value=httpx.Response(503))
    out = await CalendarConnector().collect({})
    cal = out["calendar"]
    assert cal["available"] is False
    assert "503" in cal["error"]


@respx.mock
async def test_calendar_collect_refreshes_expired_access_token(monkeypatch, tmp_path):
    """Access token within the skew window → connector calls the refresh
    endpoint and uses the new token."""
    token_path = _wire_google_oauth(monkeypatch, tmp_path, with_tokens=False)
    token_path.write_text(
        json.dumps(
            {
                "refresh_token": "refresh-xyz",
                "access_token": "stale",
                "expires_at": time.time() - 10,  # expired
            }
        )
    )
    refresh_route = respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "fresh-token", "expires_in": 3600})
    )
    respx.get(f"{CALENDAR_API}/calendars/primary/events").mock(return_value=httpx.Response(200, json={"items": []}))
    await CalendarConnector().collect({})
    assert refresh_route.called
    # New token landed on disk for next call.
    saved = json.loads(token_path.read_text())
    assert saved["access_token"] == "fresh-token"
    assert saved["refresh_token"] == "refresh-xyz"  # preserved across refresh


async def test_calendar_test_connection_says_not_connected(monkeypatch, tmp_path):
    _wire_google_oauth(monkeypatch, tmp_path, with_tokens=False)
    result = await CalendarConnector().test_connection({})
    assert result["ok"] is False
    assert "/api/auth/google/start" in result["detail"]


@respx.mock
async def test_calendar_test_connection_ok_when_api_reachable(monkeypatch, tmp_path):
    _wire_google_oauth(monkeypatch, tmp_path)
    respx.get(f"{CALENDAR_API}/users/me/calendarList").mock(return_value=httpx.Response(200, json={"items": []}))
    result = await CalendarConnector().test_connection({})
    assert result["ok"] is True


def test_calendar_is_configured_reflects_token_presence(monkeypatch, tmp_path):
    """`is_configured` keys off OAuth state, not a config field — that's how
    the Sources panel shows 'disconnected' until you finish the consent flow."""
    _wire_google_oauth(monkeypatch, tmp_path, with_tokens=False)
    assert CalendarConnector().is_configured({}) is False
    _wire_google_oauth(monkeypatch, tmp_path, with_tokens=True)
    assert CalendarConnector().is_configured({}) is True


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
