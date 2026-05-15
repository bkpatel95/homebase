"""Shared Google OAuth token store + helpers.

One Google identity (the operator's Gmail account) backs every Google
connector. Rather than each connector running its own OAuth flow, this
module owns the credentials and exposes:

  - `is_configured()` — are GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET set?
  - `is_connected()` — is there a refresh token on disk?
  - `build_auth_url(state)` / `exchange_code(code)` — OAuth 2.0 web flow
  - `get_access_token()` — returns a fresh access token, refreshing if
    the cached one is within `REFRESH_LEEWAY` of expiry
  - `revoke()` — clear local tokens and call Google's revoke endpoint

Token storage is a single JSON file (GOOGLE_OAUTH_TOKENS_PATH, default
/data/google_oauth.json). Writes are atomic and process-locked. The file
is chmod 600 on first write — it holds a refresh token good for offline
Gmail + Calendar reads.

Scope choices are kept narrow (`*.readonly`) because the dashboard never
mutates Gmail or Calendar data. If a connector ever needs write access,
add it here and re-run the auth flow.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger("homebase.google_oauth")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Shared, narrow read-only scopes. `openid` + `email` are added so we can
# record *which* Google account is connected — useful when one operator has
# several.
SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
)

# Refresh a token if it's within this many seconds of expiry. Google access
# tokens last 3600s; 120s leeway is enough to outrun clock skew without
# refreshing on every request.
REFRESH_LEEWAY = 120

TOKENS_PATH = Path(os.environ.get("GOOGLE_OAUTH_TOKENS_PATH", "/data/google_oauth.json"))

_lock = threading.Lock()


class GoogleOAuthError(RuntimeError):
    """Raised when the OAuth flow or token refresh fails in a way the
    caller needs to surface (bad code, revoked refresh token, etc.)."""


def client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_REDIRECT_URI",
        "https://homebase.lebcp.com/api/auth/google/callback",
    ).strip()


def is_configured() -> bool:
    """True when the Google Cloud OAuth client is set up in env."""
    return bool(client_id() and client_secret())


# ─── token file IO ──────────────────────────────────────────────────────────


def _load() -> dict[str, Any]:
    if not TOKENS_PATH.exists():
        return {}
    try:
        with TOKENS_PATH.open() as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log.warning("could not read %s: %s", TOKENS_PATH, e)
        return {}


def _save(state: dict[str, Any]) -> None:
    TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKENS_PATH.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    # chmod 600 *before* rename so the live file is never world-readable.
    os.chmod(tmp, 0o600)
    tmp.replace(TOKENS_PATH)


def _now() -> float:
    return time.time()


# ─── public read API ────────────────────────────────────────────────────────


def is_connected() -> bool:
    """True when we hold a refresh token (and therefore can mint access
    tokens offline). Access-token expiry is irrelevant here."""
    with _lock:
        return bool(_load().get("refresh_token"))


def connection_info() -> dict[str, Any]:
    """Snapshot for /api/auth/google/status — no secrets."""
    with _lock:
        data = _load()
    if not data.get("refresh_token"):
        return {
            "configured": is_configured(),
            "connected": False,
            "redirect_uri": redirect_uri(),
        }
    expires_at = data.get("expires_at")
    return {
        "configured": is_configured(),
        "connected": True,
        "email": data.get("email"),
        "scope": data.get("scope"),
        "obtained_at": data.get("obtained_at"),
        "expires_at": expires_at,
        "access_token_valid": bool(expires_at and expires_at > _now() + REFRESH_LEEWAY),
        "redirect_uri": redirect_uri(),
    }


# ─── auth-code flow ─────────────────────────────────────────────────────────


def build_auth_url(state: str) -> str:
    """Build the URL the user's browser visits to grant access.

    `access_type=offline` + `prompt=consent` together guarantee Google
    returns a refresh token even if the user has consented before — without
    this the second auth attempt only returns an access token and we lose
    the ability to refresh in the background.
    """
    if not is_configured():
        raise GoogleOAuthError("Google OAuth client not configured (GOOGLE_CLIENT_ID/SECRET unset)")
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    """Trade an auth code for an access + refresh token pair and persist
    them. Returns the public `connection_info()` snapshot on success.
    """
    if not is_configured():
        raise GoogleOAuthError("Google OAuth client not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id(),
                "client_secret": client_secret(),
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        raise GoogleOAuthError(f"token exchange failed: HTTP {r.status_code} {r.text[:200]}")
    payload = r.json()

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        # Almost always means the user previously consented and Google
        # silently dropped the refresh_token. The fix is to revoke prior
        # access at https://myaccount.google.com/permissions and retry.
        raise GoogleOAuthError(
            "Google did not return a refresh_token. Revoke prior access at "
            "https://myaccount.google.com/permissions and try again."
        )

    access_token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    scope = payload.get("scope", " ".join(SCOPES))

    email = await _fetch_email(access_token)

    record = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": _now() + expires_in,
        "scope": scope,
        "email": email,
        "obtained_at": _now(),
    }
    with _lock:
        _save(record)
    log.info("google oauth: stored credentials for %s", email or "<unknown>")
    return connection_info()


async def _fetch_email(access_token: str) -> str | None:
    """Best-effort: ask Google who this access token belongs to. A failure
    here is non-fatal — we still store the tokens, just without a label."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if r.status_code == 200:
            return r.json().get("email")
    except Exception as e:
        log.warning("could not fetch userinfo: %s", e)
    return None


# ─── access-token mint ──────────────────────────────────────────────────────


async def get_access_token() -> str:
    """Return a non-expired access token, refreshing from the stored
    refresh_token if needed. Raises GoogleOAuthError if we aren't connected
    or the refresh fails (typically: user revoked access)."""
    with _lock:
        data = _load()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise GoogleOAuthError("not connected — visit /api/auth/google/login")

    access_token = data.get("access_token")
    expires_at = data.get("expires_at", 0)
    if access_token and expires_at > _now() + REFRESH_LEEWAY:
        return access_token

    return await _refresh(refresh_token)


async def _refresh(refresh_token: str) -> str:
    """Trade a refresh token for a new access token and update the store."""
    if not is_configured():
        raise GoogleOAuthError("Google OAuth client not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id(),
                "client_secret": client_secret(),
                "grant_type": "refresh_token",
            },
        )
    if r.status_code != 200:
        # 400 invalid_grant means the refresh token was revoked or has
        # expired (180-day inactivity). Surface a useful message so the
        # caller can prompt re-auth.
        detail = r.text[:200]
        if r.status_code == 400 and "invalid_grant" in detail:
            raise GoogleOAuthError("refresh token rejected (invalid_grant) — re-authenticate at /api/auth/google/login")
        raise GoogleOAuthError(f"token refresh failed: HTTP {r.status_code} {detail}")
    payload = r.json()

    access_token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))

    with _lock:
        data = _load()
        data["access_token"] = access_token
        data["expires_at"] = _now() + expires_in
        # Google rotates refresh tokens on a slow cadence; if it sends a new
        # one in the response, store it. Otherwise keep the existing one.
        if payload.get("refresh_token"):
            data["refresh_token"] = payload["refresh_token"]
        _save(data)
    return access_token


# ─── revoke ─────────────────────────────────────────────────────────────────


async def revoke() -> bool:
    """Tell Google to invalidate the refresh token, then clear local
    storage. Returns True if a token existed to revoke."""
    with _lock:
        data = _load()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(GOOGLE_REVOKE_URL, data={"token": refresh_token})
    except Exception as e:
        # Even if Google's revoke endpoint is unreachable, drop the local
        # copy — the user asked to disconnect.
        log.warning("google revoke endpoint failed (clearing locally anyway): %s", e)

    with _lock:
        if TOKENS_PATH.exists():
            TOKENS_PATH.unlink()
    return True
