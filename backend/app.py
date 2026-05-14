"""The Daily Bhavi — FastAPI backend.

Mounted by nginx at /api/*. Routes:
  GET   /api/edition                       — compiled widget payload + effective layout + ticker
  GET   /api/layout                        — current layout overrides
  PUT   /api/layout                        — replace layout overrides (broadcasts to clients)
  POST  /api/layout/reset                  — clear all overrides
  GET   /api/sources                       — list connectors + status
  GET   /api/sources/{id}                  — single connector snapshot
  POST  /api/sources/{id}/configure        — save the connector's config
  POST  /api/sources/{id}/test             — run test_connection()
  DEL   /api/sources/{id}                  — clear stored config
  POST  /api/chat                          — SSE stream of a Claude response (tool use, model routing)
  GET   /api/chat/{sid}                    — fetch session transcript (visible text only)
  DEL   /api/chat/{sid}                    — clear a session
  WS    /api/ws                            — broadcast channel for edition_dirty notifications
  GET   /api/whoami                        — echoes the Cloudflare Access user
  GET   /api/health                        — liveness probe
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import validate_env
from .routers import chat, edition, layout, sources, ws

# Fail fast at import time if required env vars are missing. Uvicorn surfaces
# the RuntimeError and refuses to bind the port — easier to debug than a
# late 503 from /api/chat. Optional integrations log a warning instead.
validate_env()

ALLOWED_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EMAILS", "bhavipatel141@gmail.com").split(",")
    if e.strip()
}
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "true").lower() in ("1", "true", "yes")

app = FastAPI(title="The Daily Bhavi", version="0.3.0")


@app.middleware("http")
async def cloudflare_access_guard(request: Request, call_next):
    # /api/health bypasses auth so podman healthchecks work.
    if request.url.path.endswith("/health"):
        return await call_next(request)

    if not REQUIRE_AUTH:
        return await call_next(request)

    email = request.headers.get("cf-access-authenticated-user-email", "").strip().lower()
    if not email or email not in ALLOWED_EMAILS:
        return JSONResponse(
            {"error": "unauthorized", "detail": "missing or unknown Cloudflare Access identity"},
            status_code=403,
        )
    request.state.user_email = email
    return await call_next(request)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/whoami")
async def whoami(request: Request):
    return {"email": getattr(request.state, "user_email", None)}


app.include_router(edition.router, prefix="/api")
app.include_router(layout.router,  prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(chat.router,    prefix="/api")
app.include_router(ws.router,      prefix="/api")
