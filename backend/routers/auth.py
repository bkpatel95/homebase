"""Google OAuth web flow.

  GET    /api/auth/google/login     → 302 to Google's consent screen
  GET    /api/auth/google/callback  → exchanges the code, stores tokens,
                                       302s back to the dashboard
  GET    /api/auth/google/status    → JSON: configured / connected / email
  DELETE /api/auth/google           → revoke + drop local tokens

CSRF: a random `state` token is minted at /login and parked in a tiny
JSON file alongside the OAuth tokens. /callback only accepts states that
appear there and removes them on use. States older than `STATE_TTL`
expire (default 10 min) so a stale file doesn't accumulate.

Auth: these routes sit behind the existing Cloudflare Access middleware,
so only `ALLOWED_EMAILS` can initiate the flow.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from .. import google_oauth

log = logging.getLogger("homebase.auth")

router = APIRouter(prefix="/auth/google", tags=["auth"])

STATE_TTL = 600  # 10 minutes — a person clicking through the consent screen


def _state_path() -> Path:
    """Sit next to the tokens file so the data volume holds both."""
    return google_oauth.TOKENS_PATH.with_name("google_oauth_state.json")


def _load_states() -> dict[str, float]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_states(states: dict[str, float]) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(states))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def _mint_state() -> str:
    """Generate a state token, persist it with a timestamp, prune expired."""
    now = time.time()
    states = {s: ts for s, ts in _load_states().items() if now - ts < STATE_TTL}
    state = secrets.token_urlsafe(32)
    states[state] = now
    _save_states(states)
    return state


def _consume_state(state: str) -> bool:
    """Return True if state was present and unexpired. Always removes it
    (single-use)."""
    now = time.time()
    states = _load_states()
    ts = states.pop(state, None)
    # Prune the rest while we're here.
    states = {s: t for s, t in states.items() if now - t < STATE_TTL}
    _save_states(states)
    return ts is not None and now - ts < STATE_TTL


def _post_auth_redirect() -> str:
    """Where to send the user after they finish the consent screen.
    Defaults to the SPA root; override with GOOGLE_POST_AUTH_REDIRECT for
    tests or alt deployments."""
    return os.environ.get("GOOGLE_POST_AUTH_REDIRECT", "/").strip() or "/"


# ─── routes ─────────────────────────────────────────────────────────────────


@router.get("/login")
async def login():
    """Kick off the OAuth flow — 302 to Google's consent page."""
    if not google_oauth.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Google OAuth client is not configured on the server "
            "(GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET). See docs/google-oauth-setup.md.",
        )
    state = _mint_state()
    url = google_oauth.build_auth_url(state)
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Google sends the user's browser here with `?code=...&state=...`."""
    if error:
        # User declined or Google returned an error directly. Show it
        # plainly — a 400 with the message is enough for one-time setup.
        raise HTTPException(status_code=400, detail=f"Google returned error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")
    if not _consume_state(state):
        raise HTTPException(status_code=400, detail="invalid or expired state")

    try:
        info = await google_oauth.exchange_code(code)
    except google_oauth.GoogleOAuthError as e:
        log.warning("google oauth exchange failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    log.info("google oauth: connected as %s", info.get("email"))
    target = _post_auth_redirect()
    sep = "&" if "?" in target else "?"
    return RedirectResponse(f"{target}{sep}google=connected", status_code=302)


@router.get("/status")
async def status() -> dict[str, Any]:
    """Cheap snapshot for the UI — does NOT mint or refresh a token."""
    return google_oauth.connection_info()


@router.delete("")
async def disconnect():
    """Revoke at Google + drop local tokens."""
    removed = await google_oauth.revoke()
    return {"removed": removed, "status": google_oauth.connection_info()}
