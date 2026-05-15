"""Google OAuth — connect/disconnect endpoints for the Calendar connector.

Routes (mounted under /api):
  GET /auth/google/start    — redirect to Google's consent screen
  GET /auth/google/callback — exchange authorization code for tokens
  GET /auth/google/status   — { configured, connected }
  POST /auth/google/disconnect — wipe the persisted refresh token

The whole thing sits behind Cloudflare Access (same middleware as the rest
of /api), so only `bhavipatel141@gmail.com` can hit these endpoints in prod.
The CSRF state cache is in-process and resets on restart — fine for a
single-user app behind Access; the only consequence is that an in-flight
auth code is invalidated by a container restart and the user clicks Connect
again.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from .. import google_oauth

log = logging.getLogger("homebase.auth")

router = APIRouter(prefix="/auth/google", tags=["auth"])

# state -> timestamp. Bounded by the number of clicks-without-callback; we
# don't trim aggressively because the set will never grow beyond a handful
# in practice for a single-user app.
_PENDING_STATES: set[str] = set()


@router.get("/start")
async def start():
    if not google_oauth.oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Google OAuth not configured — set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI",
        )
    state = secrets.token_urlsafe(32)
    _PENDING_STATES.add(state)
    url = google_oauth.build_auth_url(state)
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    if error:
        log.warning("google oauth callback returned error: %s", error)
        raise HTTPException(status_code=400, detail=f"Google returned error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")
    if state not in _PENDING_STATES:
        raise HTTPException(status_code=400, detail="unknown state — restart the flow at /api/auth/google/start")
    _PENDING_STATES.discard(state)

    try:
        await google_oauth.exchange_code(code)
    except Exception as e:
        log.exception("google oauth token exchange failed")
        raise HTTPException(status_code=502, detail=f"token exchange failed: {e}") from e

    log.info("google oauth connected")
    # Bounce the user back to the dashboard. Frontend can show a toast if it
    # notices ?google=connected in the URL.
    return RedirectResponse("/?google=connected", status_code=302)


@router.get("/status")
async def status():
    return {
        "configured": google_oauth.oauth_configured(),
        "connected": google_oauth.is_connected(),
    }


@router.post("/disconnect")
async def disconnect():
    google_oauth.clear_tokens()
    log.info("google oauth disconnected (token file removed)")
    return {"ok": True}
