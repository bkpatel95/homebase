"""Google OAuth — token store, refresh, and the /api/auth/google routes.

External HTTP is mocked with respx so tests stay hermetic. Every test
points GOOGLE_OAUTH_TOKENS_PATH at a tmp file so refresh-token writes
don't bleed across tests or pollute /data.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient


@pytest.fixture
def google_env(monkeypatch, tmp_path):
    """Configure a fake Google OAuth client + isolated token file."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://test/api/auth/google/callback")
    tokens = tmp_path / "google_oauth.json"
    monkeypatch.setenv("GOOGLE_OAUTH_TOKENS_PATH", str(tokens))
    # The module reads TOKENS_PATH at import time — point it at the tmp file.
    from backend import google_oauth

    monkeypatch.setattr(google_oauth, "TOKENS_PATH", tokens)
    return tokens


@pytest.fixture
def google_client(google_env, monkeypatch):
    """TestClient pointed at the app with auth disabled and OAuth env set."""
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    import backend.app as app_module

    monkeypatch.setattr(app_module, "REQUIRE_AUTH", False)
    return TestClient(app_module.app)


# ─── module-level helpers ───────────────────────────────────────────────────


def test_build_auth_url_requires_client_id(monkeypatch, tmp_path):
    """Without GOOGLE_CLIENT_ID we should refuse rather than build a URL
    that Google would reject with a confusing error."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    from backend import google_oauth

    monkeypatch.setattr(google_oauth, "TOKENS_PATH", tmp_path / "tokens.json")
    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth.build_auth_url("state-abc")


def test_build_auth_url_includes_required_params(google_env):
    """Refresh tokens require access_type=offline + prompt=consent. Both
    must be in the URL or repeat consents drop the refresh_token."""
    from backend import google_oauth

    url = google_oauth.build_auth_url("state-abc")
    assert "client_id=test-client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=state-abc" in url
    # Both readonly scopes must be present so one consent covers Gmail and
    # Calendar.
    assert "gmail.readonly" in url
    assert "calendar.readonly" in url


@respx.mock
async def test_exchange_code_persists_tokens_and_email(google_env):
    """A happy-path code exchange writes both tokens to disk and tags them
    with the user's email from the userinfo endpoint."""
    from backend import google_oauth

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
                "scope": " ".join(google_oauth.SCOPES),
                "token_type": "Bearer",
            },
        )
    )
    respx.get("https://openidconnect.googleapis.com/v1/userinfo").mock(
        return_value=httpx.Response(200, json={"email": "bhavi@example.com"})
    )

    info = await google_oauth.exchange_code("the-code")
    assert info["connected"] is True
    assert info["email"] == "bhavi@example.com"

    on_disk = json.loads(Path(google_oauth.TOKENS_PATH).read_text())
    assert on_disk["access_token"] == "access-1"
    assert on_disk["refresh_token"] == "refresh-1"
    assert on_disk["email"] == "bhavi@example.com"


@respx.mock
async def test_exchange_code_without_refresh_token_raises(google_env):
    """If Google withholds the refresh_token (typical when a prior consent
    still exists), we must surface a useful error rather than silently
    persisting a stub."""
    from backend import google_oauth

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "access-1", "expires_in": 3600, "token_type": "Bearer"},
        )
    )
    with pytest.raises(google_oauth.GoogleOAuthError, match="refresh_token"):
        await google_oauth.exchange_code("the-code")


@respx.mock
async def test_get_access_token_refreshes_when_expired(google_env):
    """Cached access token within REFRESH_LEEWAY of expiry → call /token
    and replace it. The refresh_token stays the same when Google doesn't
    rotate it."""
    from backend import google_oauth

    google_oauth.TOKENS_PATH.write_text(
        json.dumps(
            {
                "access_token": "old-access",
                "refresh_token": "refresh-1",
                "expires_at": 1.0,  # ancient — definitely expired
                "scope": " ".join(google_oauth.SCOPES),
                "email": "bhavi@example.com",
                "obtained_at": 1.0,
            }
        )
    )

    route = respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600})
    )
    token = await google_oauth.get_access_token()
    assert token == "new-access"
    assert route.called
    on_disk = json.loads(google_oauth.TOKENS_PATH.read_text())
    assert on_disk["access_token"] == "new-access"
    assert on_disk["refresh_token"] == "refresh-1"  # preserved


@respx.mock
async def test_get_access_token_invalid_grant_surfaces_useful_message(google_env):
    """invalid_grant means the refresh_token was revoked (or expired by
    inactivity). The error must mention re-auth so the operator knows what
    to do."""
    from backend import google_oauth

    google_oauth.TOKENS_PATH.write_text(
        json.dumps(
            {
                "access_token": "old",
                "refresh_token": "revoked",
                "expires_at": 1.0,
                "email": "bhavi@example.com",
            }
        )
    )
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(google_oauth.GoogleOAuthError, match="invalid_grant"):
        await google_oauth.get_access_token()


async def test_get_access_token_when_not_connected_raises(google_env):
    """No refresh token on disk → callers must see a clear error rather
    than an opaque KeyError."""
    from backend import google_oauth

    assert google_oauth.is_connected() is False
    with pytest.raises(google_oauth.GoogleOAuthError, match="not connected"):
        await google_oauth.get_access_token()


# ─── routes ─────────────────────────────────────────────────────────────────


def test_login_redirects_to_google(google_client):
    """/api/auth/google/login → 302 to accounts.google.com with the OAuth
    params. TestClient follow_redirects defaults to off for 302s."""
    r = google_client.get("/api/auth/google/login", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in location
    assert "prompt=consent" in location


def test_login_503_when_oauth_not_configured(monkeypatch):
    """No GOOGLE_CLIENT_ID → /login returns 503 with a hint, never a 5xx
    stacktrace."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    import backend.app as app_module

    monkeypatch.setattr(app_module, "REQUIRE_AUTH", False)
    client = TestClient(app_module.app)
    r = client.get("/api/auth/google/login", follow_redirects=False)
    assert r.status_code == 503
    assert "GOOGLE_CLIENT_ID" in r.json()["detail"]


def test_callback_rejects_invalid_state(google_client):
    """Anyone hitting /callback with a state we never minted must get a
    400 — this is the CSRF check, so it has to be strict."""
    r = google_client.get(
        "/api/auth/google/callback",
        params={"code": "abc", "state": "never-minted"},
        follow_redirects=False,
    )
    assert r.status_code == 400


@respx.mock
def test_callback_happy_path_stores_tokens_and_redirects(google_client):
    """Mint a state via /login, then complete the exchange. Tokens land on
    disk and the response 302s the user back to the dashboard."""
    from backend import google_oauth

    # Step 1: mint a real state via the login route.
    login = google_client.get("/api/auth/google/login", follow_redirects=False)
    location = login.headers["location"]
    state = _extract_state(location)

    # Step 2: mock the token + userinfo endpoints.
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
                "scope": " ".join(google_oauth.SCOPES),
                "token_type": "Bearer",
            },
        )
    )
    respx.get("https://openidconnect.googleapis.com/v1/userinfo").mock(
        return_value=httpx.Response(200, json={"email": "bhavi@example.com"})
    )

    r = google_client.get(
        "/api/auth/google/callback",
        params={"code": "auth-code-1", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "google=connected" in r.headers["location"]
    # State is single-use — replaying must now fail.
    r2 = google_client.get(
        "/api/auth/google/callback",
        params={"code": "auth-code-1", "state": state},
        follow_redirects=False,
    )
    assert r2.status_code == 400


def test_status_reports_disconnected_when_no_tokens(google_client):
    """The UI polls /status to decide whether to show a 'Connect Google'
    button. When nothing is on disk it must return connected=False."""
    r = google_client.get("/api/auth/google/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["connected"] is False


@respx.mock
def test_disconnect_revokes_and_clears(google_client):
    """DELETE /api/auth/google calls Google's revoke endpoint AND wipes
    the local token file even if the revoke call fails."""
    from backend import google_oauth

    google_oauth.TOKENS_PATH.write_text(
        json.dumps(
            {
                "access_token": "a",
                "refresh_token": "r",
                "expires_at": 1.0,
                "email": "bhavi@example.com",
            }
        )
    )
    revoke_route = respx.post("https://oauth2.googleapis.com/revoke").mock(return_value=httpx.Response(200))
    r = google_client.delete("/api/auth/google")
    assert r.status_code == 200
    assert r.json()["removed"] is True
    assert revoke_route.called
    assert not google_oauth.TOKENS_PATH.exists()


# ─── helpers ────────────────────────────────────────────────────────────────


def _extract_state(google_auth_url: str) -> str:
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(google_auth_url).query)
    return qs["state"][0]
