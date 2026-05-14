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

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .logging_config import configure_logging
from .routers import chat, edition, layout, sources, ws

configure_logging()
log = logging.getLogger("homebase.app")
req_log = logging.getLogger("homebase.request")

# Optional Sentry. The app works fine without it — the SDK is only imported
# and initialized when SENTRY_DSN is set.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get("ENV", "production"),
        release=os.environ.get("BUILD_VERSION") or None,
        traces_sample_rate=0.1,
    )
    log.info(
        "sentry initialized",
        extra={
            "fields": {
                "env": os.environ.get("ENV", "production"),
                "release": os.environ.get("BUILD_VERSION") or None,
            }
        },
    )

ALLOWED_EMAILS = {
    e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "bhavipatel141@gmail.com").split(",") if e.strip()
}
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "true").lower() in ("1", "true", "yes")

app = FastAPI(title="The Daily Bhavi", version="0.3.0")


# Middlewares stack in reverse-registration order: the auth guard is
# registered first so it runs *inside* the request logger, which means every
# request — including 403s from the guard — is logged with its final status.
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


@app.middleware("http")
async def request_logger(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    req_log.info(
        "%s %s %d %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        extra={
            "fields": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 1),
            }
        },
    )
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/whoami")
async def whoami(request: Request):
    return {"email": getattr(request.state, "user_email", None)}


app.include_router(edition.router, prefix="/api")
app.include_router(layout.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(ws.router, prefix="/api")
