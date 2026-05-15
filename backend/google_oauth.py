"""Google OAuth — single-user refresh-token flow for the Calendar connector.

Token shape on disk (chmod 600, mounted volume):

    {
      "refresh_token": "1//0g...",
      "access_token":  "ya29....",
      "expires_at":    1734567890.0    # unix seconds, UTC
    }

Env vars consumed:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI — OAuth client
  GOOGLE_TOKEN_PATH                                           — defaults to /data/google_token.json

`get_access_token()` is the only entry point connectors need: it returns a
fresh token, refreshing transparently when the current one is within 60s of
expiring. Returns None when OAuth isn't configured or no refresh token has
been persisted yet — callers should treat that as "not connected" and render
unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("homebase.google_oauth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

# Refresh slightly before expiry so a request that takes a few hundred ms
# doesn't race the boundary and get a 401.
EXPIRY_SKEW_SECONDS = 60


def _token_path() -> Path:
    return Path(os.environ.get("GOOGLE_TOKEN_PATH", "/data/google_token.json"))


def _client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def _redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_REDIRECT_URI",
        "https://homebase.lebcp.com/api/auth/google/callback",
    ).strip()


def oauth_configured() -> bool:
    """True iff the OAuth *client* is configured. Says nothing about whether
    a refresh token has been obtained yet."""
    return bool(_client_id() and _client_secret() and _redirect_uri())


def load_tokens() -> dict[str, Any] | None:
    p = _token_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception as e:
        log.warning("google token file unreadable (%s): %s", p, e)
        return None


def save_tokens(tokens: dict[str, Any]) -> None:
    """Write the token file atomically with chmod 600.

    Keeps any existing refresh_token if Google didn't return one this time
    (Google only returns refresh_token on the *first* consent — subsequent
    refreshes return just access_token + expires_in).
    """
    p = _token_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    existing = load_tokens() or {}
    merged = {**existing, **{k: v for k, v in tokens.items() if v is not None}}

    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def clear_tokens() -> None:
    p = _token_path()
    if p.exists():
        p.unlink()


def is_connected() -> bool:
    """True iff OAuth is configured AND a refresh token has been persisted."""
    if not oauth_configured():
        return False
    tokens = load_tokens()
    return bool(tokens and tokens.get("refresh_token"))


def build_auth_url(state: str) -> str:
    """Build the consent-screen URL. `access_type=offline` + `prompt=consent`
    force Google to return a refresh_token even if the user has previously
    granted the same scope."""
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{httpx.QueryParams(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    """Trade an authorization code for tokens and persist them."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        raise RuntimeError(f"token exchange failed: HTTP {r.status_code} {r.text[:200]}")
    payload = r.json()
    expires_at = time.time() + float(payload.get("expires_in", 3600))
    tokens = {
        "refresh_token": payload.get("refresh_token"),
        "access_token": payload.get("access_token"),
        "expires_at": expires_at,
    }
    save_tokens(tokens)
    return tokens


async def _refresh(refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "grant_type": "refresh_token",
            },
        )
    if r.status_code != 200:
        raise RuntimeError(f"token refresh failed: HTTP {r.status_code} {r.text[:200]}")
    payload = r.json()
    expires_at = time.time() + float(payload.get("expires_in", 3600))
    tokens = {
        "access_token": payload.get("access_token"),
        "expires_at": expires_at,
    }
    save_tokens(tokens)
    return tokens


async def get_access_token() -> str | None:
    """Return a valid access token, refreshing if needed. None if not connected."""
    if not oauth_configured():
        return None
    tokens = load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        return None

    access = tokens.get("access_token")
    expires_at = float(tokens.get("expires_at") or 0)
    if access and expires_at - time.time() > EXPIRY_SKEW_SECONDS:
        return access

    refreshed = await _refresh(tokens["refresh_token"])
    return refreshed.get("access_token")
