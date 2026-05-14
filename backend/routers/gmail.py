"""GET /api/gmail              → recent unread Gmail messages
GET /api/gmail/auth            → returns the Google authorization URL
GET /api/gmail/auth/callback   → exchanges ?code= for an access+refresh token

The bootstrap flow only needs to be run once per environment. After the
refresh token lands in GMAIL_TOKEN_PATH the connector refreshes access
tokens on demand and the /api/gmail endpoint just works.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .. import connectors
from ..connectors import gmail as gmail_connector
from ..connectors import store as connector_store

router = APIRouter()


def _config() -> dict[str, Any]:
    c = connectors.get_connector("gmail")
    if not c:
        raise HTTPException(500, detail="gmail connector not registered")
    return c.resolve(connector_store.get_config("gmail"))


def _redirect_uri(request: Request) -> str:
    """Resolve the OAuth redirect URI.

    Priority: GMAIL_REDIRECT_URI env var > the live request URL with
    /callback appended. The override is needed when the dashboard is
    fronted by Cloudflare/nginx and the request URL the app sees doesn't
    match the URL Google calls back to.
    """
    override = os.environ.get("GMAIL_REDIRECT_URI", "").strip()
    if override:
        return override
    base = str(request.url_for("gmail_auth_callback"))
    return base


@router.get("/gmail")
async def get_gmail():
    return await connectors.collect_widget("gmail")


@router.get("/gmail/auth")
async def gmail_auth_start(request: Request):
    cfg = _config()
    creds_path = Path(cfg.get("credentials_path") or "")
    if not creds_path.exists():
        raise HTTPException(
            400,
            detail=(
                f"OAuth client credentials not found at {creds_path}. "
                "Download an OAuth 2.0 Client ID JSON from Google Cloud Console "
                "and set GMAIL_CREDENTIALS_PATH (or configure it via /api/sources)."
            ),
        )
    try:
        creds = gmail_connector._load_credentials(creds_path)
    except Exception as e:
        raise HTTPException(400, detail=f"credentials unreadable: {e}") from e

    state = secrets.token_urlsafe(24)
    redirect_uri = _redirect_uri(request)
    url = gmail_connector.build_authorization_url(creds, redirect_uri=redirect_uri, state=state)
    return {
        "authorization_url": url,
        "redirect_uri": redirect_uri,
        "state": state,
        "next": (
            "Visit authorization_url, grant access, and Google will redirect to "
            "redirect_uri with ?code=... — that hits /api/gmail/auth/callback "
            "and writes the token file."
        ),
    }


@router.get("/gmail/auth/callback", name="gmail_auth_callback")
async def gmail_auth_callback(request: Request, code: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(400, detail=f"OAuth error from Google: {error}")
    if not code:
        raise HTTPException(400, detail="missing ?code parameter")

    cfg = _config()
    creds_path = Path(cfg.get("credentials_path") or "")
    token_path = Path(cfg.get("token_path") or "")
    timeout = float(cfg.get("timeout") or 6.0)

    if not creds_path.exists():
        raise HTTPException(400, detail=f"credentials file not found: {creds_path}")
    try:
        creds = gmail_connector._load_credentials(creds_path)
    except Exception as e:
        raise HTTPException(400, detail=f"credentials unreadable: {e}") from e

    redirect_uri = _redirect_uri(request)
    try:
        token = await gmail_connector.exchange_code_for_token(
            creds, code=code, redirect_uri=redirect_uri, timeout=timeout
        )
    except Exception as e:
        raise HTTPException(400, detail=str(e)) from e

    try:
        gmail_connector._save_token(token_path, token)
    except OSError as e:
        raise HTTPException(500, detail=f"could not write token to {token_path}: {e}") from e

    return {
        "ok": True,
        "token_path": str(token_path),
        "expires_at": token.get("expires_at"),
        "next": "Hit /api/gmail to see recent messages.",
    }
