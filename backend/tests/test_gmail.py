"""Gmail connector — OAuth refresh + message list/fetch.

Google's OAuth and Gmail endpoints are mocked with respx so the tests are
hermetic. The setup file is a hand-written OAuth client JSON in the
"installed" shape that Google Cloud Console ships.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import respx

from backend.connectors.gmail import (
    GMAIL_API_BASE,
    GOOGLE_TOKEN_URL,
    GmailConnector,
    build_authorization_url,
)


def _write_creds(tmp_path) -> str:
    p = tmp_path / "credentials.json"
    p.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "abc.apps.googleusercontent.com",
                    "client_secret": "shhh",
                    "token_uri": GOOGLE_TOKEN_URL,
                    "redirect_uris": ["http://localhost:8095/api/gmail/auth/callback"],
                }
            }
        )
    )
    return str(p)


def _write_token(tmp_path, *, expired: bool = True) -> str:
    p = tmp_path / "token.json"
    expires_at = datetime.now(UTC) + (timedelta(seconds=-60) if expired else timedelta(hours=1))
    p.write_text(
        json.dumps(
            {
                "access_token": "old-access",
                "refresh_token": "refresh-xyz",
                "expires_at": expires_at.isoformat(),
                "scope": "https://www.googleapis.com/auth/gmail.readonly",
            }
        )
    )
    return str(p)


def _cfg(tmp_path, *, token_expired: bool = True) -> dict:
    return {
        "credentials_path": _write_creds(tmp_path),
        "token_path": _write_token(tmp_path, expired=token_expired),
        "labels": "UNREAD",
        "query": "",
        "hours": 24,
        "max_results": 5,
        "timeout": 2.0,
    }


@respx.mock
async def test_gmail_collect_refreshes_token_and_returns_messages(tmp_path):
    """Token is expired → connector hits the refresh endpoint, then lists +
    fetches messages, then surfaces a tidy payload."""
    respx.post(GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "new-access", "expires_in": 3600, "scope": "x"},
        )
    )
    respx.get(f"{GMAIL_API_BASE}/messages").mock(
        return_value=httpx.Response(
            200,
            json={"messages": [{"id": "m1"}, {"id": "m2"}]},
        )
    )
    respx.get(f"{GMAIL_API_BASE}/messages/m1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "m1",
                "threadId": "t1",
                "snippet": "hi there",
                "labelIds": ["INBOX", "UNREAD"],
                "internalDate": "1715607600000",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Hello"},
                        {"name": "From", "value": "alice@example.com"},
                        {"name": "Date", "value": "Mon, 13 May 2026 12:00:00 +0000"},
                    ]
                },
            },
        )
    )
    respx.get(f"{GMAIL_API_BASE}/messages/m2").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "m2",
                "threadId": "t2",
                "snippet": "second",
                "labelIds": ["INBOX", "UNREAD"],
                "internalDate": "1715607700000",
                "payload": {"headers": [{"name": "Subject", "value": "Two"}]},
            },
        )
    )

    out = await GmailConnector().collect(_cfg(tmp_path))
    g = out["gmail"]
    assert g["available"] is True
    assert g["count"] == 2
    titles = [m["subject"] for m in g["messages"]]
    assert titles == ["Hello", "Two"]
    assert g["messages"][0]["from"] == "alice@example.com"
    assert "newer_than:24h" in g["query"]
    assert "collected_at" in g


@respx.mock
async def test_gmail_collect_refresh_failure_returns_unavailable(tmp_path):
    """A 400 from Google's token endpoint must surface as `available: False`,
    not bubble as a 500 from /api/gmail."""
    respx.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(400, text="invalid_grant"))
    out = await GmailConnector().collect(_cfg(tmp_path))
    g = out["gmail"]
    assert g["available"] is False
    assert "token refresh failed" in g["error"]


async def test_gmail_collect_missing_token_file_returns_setup_hint(tmp_path):
    cfg = _cfg(tmp_path)
    # Remove the token file before the connector runs.
    import os

    os.remove(cfg["token_path"])
    out = await GmailConnector().collect(cfg)
    g = out["gmail"]
    assert g["available"] is False
    assert "/api/gmail/auth" in g["reason"]


@respx.mock
async def test_gmail_skips_refresh_when_token_fresh(tmp_path):
    """Token is still valid → no call to /token; just the listing + fetches."""
    cfg = _cfg(tmp_path, token_expired=False)
    refresh_route = respx.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(500))
    respx.get(f"{GMAIL_API_BASE}/messages").mock(return_value=httpx.Response(200, json={"messages": []}))

    out = await GmailConnector().collect(cfg)
    g = out["gmail"]
    assert g["available"] is True
    assert g["count"] == 0
    assert not refresh_route.called, "fresh token should not trigger a refresh"


@respx.mock
async def test_gmail_test_connection_authenticated(tmp_path):
    cfg = _cfg(tmp_path)
    respx.post(GOOGLE_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
    )
    respx.get(f"{GMAIL_API_BASE}/profile").mock(
        return_value=httpx.Response(200, json={"emailAddress": "user@example.com"})
    )
    result = await GmailConnector().test_connection(cfg)
    assert result["ok"] is True
    assert "user@example.com" in result["detail"]


async def test_build_authorization_url_includes_offline_access():
    url = build_authorization_url(
        {"client_id": "cid"},
        redirect_uri="http://localhost/cb",
        state="zzz",
    )
    assert "client_id=cid" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%2Fcb" in url
    assert "access_type=offline" in url
    assert "state=zzz" in url
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly" in url
