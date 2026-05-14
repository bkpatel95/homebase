"""Gmail connector — recent unread messages via the Gmail REST API.

OAuth 2.0 authorization-code flow without `google-auth-oauthlib`:

  - The user downloads an OAuth 2.0 Client ID JSON from Google Cloud
    Console and points `GMAIL_CREDENTIALS_PATH` at it. That file holds
    `client_id`, `client_secret`, `token_uri`, and the list of registered
    `redirect_uris`.

  - The dashboard exposes a one-time bootstrap flow at /api/gmail/auth
    (see backend/routers/gmail.py) that hands the user an authorization
    URL, then exchanges the returned code for an access + refresh token
    pair which gets persisted to `GMAIL_TOKEN_PATH`.

  - From then on, the connector refreshes the access token on demand via
    Google's token endpoint and calls Gmail with httpx. No third-party
    Google libraries needed.

If the token file is missing or the refresh fails the connector returns
`available: false` with a `reason` field rather than raising — the rest
of the edition keeps rendering.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from .base import ConfigField, Connector

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
DEFAULT_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

_token_lock = threading.Lock()


def _load_credentials(path: Path) -> dict[str, Any]:
    """Read a Google Cloud OAuth client JSON. Supports both the
    `installed` and `web` shapes downloaded from the console.
    """
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        if "installed" in raw and isinstance(raw["installed"], dict):
            return raw["installed"]
        if "web" in raw and isinstance(raw["web"], dict):
            return raw["web"]
    return raw if isinstance(raw, dict) else {}


def _load_token(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _save_token(path: Path, token: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(token, indent=2, sort_keys=True))
    with contextlib.suppress(OSError):
        os.chmod(tmp, 0o600)
    tmp.replace(path)


def _token_is_fresh(token: dict[str, Any], *, leeway: int = 60) -> bool:
    exp = token.get("expires_at")
    if not exp:
        return False
    try:
        exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return datetime.now(UTC) + timedelta(seconds=leeway) < exp_dt


async def _refresh(token: dict[str, Any], creds: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    """Exchange the refresh token for a new access token. Returns the
    updated token dict (caller is responsible for persisting it).
    """
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("token file has no refresh_token — re-run /api/gmail/auth")
    payload = {
        "client_id": creds.get("client_id"),
        "client_secret": creds.get("client_secret"),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    token_uri = creds.get("token_uri") or GOOGLE_TOKEN_URL
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(token_uri, data=payload)
    if r.status_code != 200:
        raise RuntimeError(f"refresh failed: HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    new_token = dict(token)
    new_token["access_token"] = body["access_token"]
    expires_in = int(body.get("expires_in") or 3600)
    new_token["expires_at"] = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
    if "scope" in body:
        new_token["scope"] = body["scope"]
    if "id_token" in body:
        new_token["id_token"] = body["id_token"]
    return new_token


async def get_access_token(creds_path: Path, token_path: Path, *, timeout: float) -> str:
    """Return a fresh access token, refreshing + persisting as needed."""
    token = _load_token(token_path)
    if not token:
        raise RuntimeError(f"no token file at {token_path} — run /api/gmail/auth")
    if _token_is_fresh(token):
        return token["access_token"]
    creds = _load_credentials(creds_path)
    new_token = await _refresh(token, creds, timeout=timeout)
    with _token_lock:
        _save_token(token_path, new_token)
    return new_token["access_token"]


def _header_value(headers: list[dict[str, Any]], name: str) -> str:
    target = name.lower()
    for h in headers or []:
        if (h.get("name") or "").lower() == target:
            return h.get("value") or ""
    return ""


def _parse_internal_date(ms: Any) -> str | None:
    try:
        ts = int(ms) / 1000
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def _build_query(*, hours: int, label_ids: list[str], extra_query: str) -> str:
    bits: list[str] = []
    if hours > 0:
        bits.append(f"newer_than:{int(hours)}h")
    if "INBOX" in label_ids:
        bits.append("in:inbox")
    if "UNREAD" in label_ids:
        bits.append("is:unread")
    if extra_query.strip():
        bits.append(extra_query.strip())
    return " ".join(bits) if bits else "is:unread"


class GmailConnector(Connector):
    id = "gmail"
    name = "Gmail"
    description = "Recent unread Gmail messages via the Gmail REST API (OAuth 2.0)."
    icon = "✉"
    category = "personal"
    widget_ids = ("gmail",)
    config_schema = (
        ConfigField(
            name="credentials_path",
            label="OAuth client JSON path",
            type="path",
            required=True,
            help="Downloaded from Google Cloud Console → APIs & Services → Credentials.",
            placeholder="/data/gmail/credentials.json",
            default="/data/gmail/credentials.json",
            env_fallback="GMAIL_CREDENTIALS_PATH",
        ),
        ConfigField(
            name="token_path",
            label="Token file path",
            type="path",
            required=True,
            help="Where the access/refresh tokens are persisted after /api/gmail/auth.",
            placeholder="/data/gmail/token.json",
            default="/data/gmail/token.json",
            env_fallback="GMAIL_TOKEN_PATH",
        ),
        ConfigField(
            name="labels",
            label="Label filter",
            help="Comma-separated label IDs (e.g. INBOX,UNREAD,IMPORTANT). Default: UNREAD.",
            default="UNREAD",
            env_fallback="GMAIL_LABELS",
        ),
        ConfigField(
            name="query",
            label="Extra Gmail query",
            help="Optional 'q' clause appended to the search (Gmail search syntax).",
            placeholder="from:notifications@github.com",
            env_fallback="GMAIL_QUERY",
        ),
        ConfigField(
            name="hours",
            label="Look-back window (hours)",
            type="number",
            default="24",
            env_fallback="GMAIL_HOURS",
        ),
        ConfigField(
            name="max_results",
            label="Max messages returned",
            type="number",
            default="20",
            env_fallback="GMAIL_MAX_RESULTS",
        ),
        ConfigField(
            name="timeout",
            label="HTTP timeout (seconds)",
            type="number",
            default="6.0",
            env_fallback="GMAIL_TIMEOUT",
        ),
    )

    def is_configured(self, stored: dict[str, Any] | None) -> bool:
        resolved = self.resolve(stored)
        creds = Path(resolved.get("credentials_path") or "")
        token = Path(resolved.get("token_path") or "")
        # Configured = both paths set AND both files present. The token file
        # is only created by the /api/gmail/auth flow, so a missing token
        # surfaces as "needs setup" rather than "no creds".
        if not creds or not str(creds).strip() or not token or not str(token).strip():
            return False
        return creds.exists() and token.exists()

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        creds_path = Path(config.get("credentials_path") or "")
        token_path = Path(config.get("token_path") or "")
        timeout = _to_float(config.get("timeout"), 6.0)

        if not creds_path.exists():
            return {"ok": False, "detail": f"credentials file not found: {creds_path}"}
        try:
            _load_credentials(creds_path)
        except Exception as e:
            return {"ok": False, "detail": f"credentials unreadable: {e}"}
        if not token_path.exists():
            return {"ok": False, "detail": f"no token at {token_path} — run /api/gmail/auth"}
        try:
            access = await get_access_token(creds_path, token_path, timeout=timeout)
        except Exception as e:
            return {"ok": False, "detail": f"refresh failed: {e}"}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(
                    f"{GMAIL_API_BASE}/profile",
                    headers={"Authorization": f"Bearer {access}"},
                )
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
        if r.status_code != 200:
            return {"ok": False, "detail": f"Gmail HTTP {r.status_code}: {r.text[:200]}"}
        prof = r.json() or {}
        return {"ok": True, "detail": f"authenticated as {prof.get('emailAddress', '?')}"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        creds_path = Path(config.get("credentials_path") or "")
        token_path = Path(config.get("token_path") or "")
        timeout = _to_float(config.get("timeout"), 6.0)
        hours = int(_to_float(config.get("hours"), 24.0))
        max_results = int(_to_float(config.get("max_results"), 20.0))
        labels_str = (config.get("labels") or "UNREAD").strip()
        label_ids = [s.strip() for s in labels_str.split(",") if s.strip()]
        extra_query = (config.get("query") or "").strip()

        if not creds_path.exists() or not token_path.exists():
            return {
                "gmail": {
                    "available": False,
                    "reason": "Gmail not yet authorized — visit /api/gmail/auth.",
                    "messages": [],
                    "count": 0,
                    "collected_at": now,
                }
            }

        try:
            access = await get_access_token(creds_path, token_path, timeout=timeout)
        except Exception as e:
            return {
                "gmail": {
                    "available": False,
                    "error": f"token refresh failed: {e}",
                    "messages": [],
                    "count": 0,
                    "collected_at": now,
                }
            }

        headers = {"Authorization": f"Bearer {access}"}
        params: dict[str, Any] = {
            "maxResults": max_results,
            "q": _build_query(hours=hours, label_ids=label_ids, extra_query=extra_query),
        }
        # Filter by label IDs that aren't expressible as a query token. UNREAD
        # is already in the query string; IMPORTANT etc. go here.
        applied_label_filter = [lid for lid in label_ids if lid not in ("UNREAD",)]
        if applied_label_filter:
            params["labelIds"] = applied_label_filter

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(f"{GMAIL_API_BASE}/messages", params=params, headers=headers)
                r.raise_for_status()
                listing = r.json() or {}
                ids = [m["id"] for m in listing.get("messages") or [] if m.get("id")]

                async def _fetch(message_id: str) -> dict[str, Any]:
                    mr = await client.get(
                        f"{GMAIL_API_BASE}/messages/{message_id}",
                        params={
                            "format": "metadata",
                            "metadataHeaders": ["Subject", "From", "Date"],
                        },
                        headers=headers,
                    )
                    mr.raise_for_status()
                    return mr.json()

                msgs = await asyncio.gather(*(_fetch(mid) for mid in ids))
        except Exception as e:
            return {
                "gmail": {
                    "available": False,
                    "error": f"{type(e).__name__}: {e}",
                    "messages": [],
                    "count": 0,
                    "collected_at": now,
                }
            }

        out: list[dict[str, Any]] = []
        for m in msgs:
            payload = m.get("payload") or {}
            hdrs = payload.get("headers") or []
            out.append(
                {
                    "id": m.get("id"),
                    "thread_id": m.get("threadId"),
                    "subject": _header_value(hdrs, "Subject"),
                    "from": _header_value(hdrs, "From"),
                    "date": _header_value(hdrs, "Date"),
                    "internal_date": _parse_internal_date(m.get("internalDate")),
                    "snippet": (m.get("snippet") or "").strip(),
                    "labels": m.get("labelIds") or [],
                }
            )

        return {
            "gmail": {
                "available": True,
                "messages": out,
                "count": len(out),
                "query": params["q"],
                "labels": label_ids,
                "collected_at": now,
            }
        }


# ─── helpers re-exported for the auth router ────────────────────────────────


def build_authorization_url(creds: dict[str, Any], *, redirect_uri: str, state: str | None = None) -> str:
    """Construct a Google OAuth 2.0 authorization URL (offline access)."""
    from urllib.parse import urlencode

    params = {
        "client_id": creds["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DEFAULT_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    if state:
        params["state"] = state
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_token(
    creds: dict[str, Any],
    *,
    code: str,
    redirect_uri: str,
    timeout: float,
) -> dict[str, Any]:
    """Authorization-code → access/refresh token exchange."""
    payload = {
        "code": code,
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    token_uri = creds.get("token_uri") or GOOGLE_TOKEN_URL
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(token_uri, data=payload)
    if r.status_code != 200:
        raise RuntimeError(f"code exchange failed: HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    if "refresh_token" not in body:
        raise RuntimeError("Google did not return a refresh_token — revoke prior consent and retry with prompt=consent")
    expires_in = int(body.get("expires_in") or 3600)
    return {
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "scope": body.get("scope") or DEFAULT_SCOPE,
        "token_type": body.get("token_type") or "Bearer",
        "expires_at": (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat(),
    }


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# Surface a no-op base64 helper if anyone wants to decode message bodies later;
# we don't decode bodies here to keep payloads slim and avoid PII bloat.
def _b64url_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


connector = GmailConnector()
