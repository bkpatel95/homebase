"""Google OAuth endpoints — /api/auth/google/{start,callback,status,disconnect}.

The flow:
  1. user hits /start              → 302 to Google with a CSRF state
  2. Google bounces back to /callback?code=...&state=...
  3. backend exchanges code for a refresh+access token, persists, redirects home
  4. /status reports {configured, connected}
  5. /disconnect wipes the persisted token

Tests use respx to mock the Google token endpoint and monkeypatch env so each
test has its own client creds and a tmp-path token file.
"""

from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import respx

from backend import google_oauth


def _wire_oauth(monkeypatch, tmp_path, *, with_tokens: bool = False) -> str:
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
    return str(token_path)


def test_status_unconfigured(client, monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(tmp_path / "google_token.json"))
    r = client.get("/api/auth/google/status")
    assert r.status_code == 200
    assert r.json() == {"configured": False, "connected": False}


def test_status_configured_but_not_connected(client, monkeypatch, tmp_path):
    _wire_oauth(monkeypatch, tmp_path, with_tokens=False)
    r = client.get("/api/auth/google/status")
    assert r.json() == {"configured": True, "connected": False}


def test_status_connected(client, monkeypatch, tmp_path):
    _wire_oauth(monkeypatch, tmp_path, with_tokens=True)
    r = client.get("/api/auth/google/status")
    assert r.json() == {"configured": True, "connected": True}


def test_start_requires_oauth_configured(client, monkeypatch, tmp_path):
    """Trying to start the flow with no client creds is a 503, not a confusing
    redirect-to-Google-with-empty-client_id."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(tmp_path / "google_token.json"))
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert r.status_code == 503
    assert "GOOGLE_CLIENT_ID" in r.json()["detail"]


def test_start_redirects_to_google_with_expected_params(client, monkeypatch, tmp_path):
    _wire_oauth(monkeypatch, tmp_path)
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert r.status_code == 302
    parsed = urlparse(r.headers["location"])
    assert parsed.netloc == "accounts.google.com"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["test-client-id"]
    assert qs["redirect_uri"] == ["https://homebase.test/api/auth/google/callback"]
    assert qs["response_type"] == ["code"]
    assert qs["scope"] == ["https://www.googleapis.com/auth/calendar.readonly"]
    assert qs["access_type"] == ["offline"]
    # prompt=consent guarantees Google returns a refresh_token even on re-auth.
    assert qs["prompt"] == ["consent"]
    assert qs["state"]  # non-empty


@respx.mock
def test_callback_exchanges_code_and_persists_tokens(client, monkeypatch, tmp_path):
    token_path = _wire_oauth(monkeypatch, tmp_path)
    # Drive the state through /start so the callback's CSRF check passes.
    r = client.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "refresh_token": "rt-from-google",
                "access_token": "at-from-google",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )
    r = client.get(
        f"/api/auth/google/callback?code=auth-code-xyz&state={state}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/?google=connected"

    from pathlib import Path

    saved = json.loads(Path(token_path).read_text())
    assert saved["refresh_token"] == "rt-from-google"
    assert saved["access_token"] == "at-from-google"
    assert saved["expires_at"] > time.time()


def test_callback_rejects_unknown_state(client, monkeypatch, tmp_path):
    """Unknown state → 400, not a token exchange attempt. Defends against
    someone landing on /callback with a forged state."""
    _wire_oauth(monkeypatch, tmp_path)
    r = client.get(
        "/api/auth/google/callback?code=anything&state=not-a-real-state",
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "state" in r.json()["detail"].lower()


def test_callback_surfaces_google_error_param(client, monkeypatch, tmp_path):
    """If the user denies consent, Google bounces back with ?error=access_denied
    instead of a code. We surface it as a 400 with the reason."""
    _wire_oauth(monkeypatch, tmp_path)
    r = client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
    assert r.status_code == 400
    assert "access_denied" in r.json()["detail"]


def test_disconnect_removes_token_file(client, monkeypatch, tmp_path):
    token_path = _wire_oauth(monkeypatch, tmp_path, with_tokens=True)
    assert google_oauth.is_connected() is True
    r = client.post("/api/auth/google/disconnect")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    import os

    assert not os.path.exists(token_path)
    assert google_oauth.is_connected() is False
