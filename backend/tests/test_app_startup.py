"""App startup — make sure the app boots without optional env vars and that
the auth middleware reads its config from env at import time correctly.

There are no required env vars to *boot* the app — every connector tolerates
missing config. ANTHROPIC_API_KEY is required to actually send a chat, and
that's surfaced at request time (HTTP 503), not at startup. This test pins
that contract so we don't accidentally start requiring an env var to boot.
"""

from __future__ import annotations

import importlib
import os

from fastapi.testclient import TestClient


def _reload_app(monkeypatch, **env):
    """Re-import backend.app with a specific env. Returns the fresh module."""
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)

    import backend.app as app_module

    return importlib.reload(app_module)


def test_app_boots_without_anthropic_key(monkeypatch):
    """No ANTHROPIC_API_KEY: app still imports and /api/health responds."""
    app_module = _reload_app(
        monkeypatch,
        ANTHROPIC_API_KEY=None,
        REQUIRE_AUTH="false",
        SOURCES_PATH="/tmp/homebase-tests-startup-sources.json",
    )
    client = TestClient(app_module.app)
    r = client.get("/api/health")
    assert r.status_code == 200


def test_app_boots_without_optional_connector_env(monkeypatch):
    """No connector creds: app still imports and /api/sources responds."""
    for k in ("OURA_TOKEN", "PLEX_TOKEN", "OVERSEERR_API_KEY", "PROMETHEUS_URL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    app_module = _reload_app(
        monkeypatch,
        REQUIRE_AUTH="false",
        SOURCES_PATH="/tmp/homebase-tests-startup-sources.json",
    )
    client = TestClient(app_module.app)
    r = client.get("/api/sources")
    assert r.status_code == 200
    data = r.json()
    assert "sources" in data
    # Every registered connector returns a status, even with no env config.
    assert all("status" in s for s in data["sources"])


def test_allowed_emails_parses_comma_separated_list(monkeypatch):
    app_module = _reload_app(
        monkeypatch,
        ALLOWED_EMAILS="A@Example.COM, b@example.com",
        REQUIRE_AUTH="true",
    )
    # Whitespace stripped, lowercased.
    assert {"a@example.com", "b@example.com"} == app_module.ALLOWED_EMAILS
    assert app_module.REQUIRE_AUTH is True


def test_require_auth_recognises_truthy_strings(monkeypatch):
    for val in ("1", "true", "TRUE", "yes"):
        app_module = _reload_app(monkeypatch, REQUIRE_AUTH=val)
        assert app_module.REQUIRE_AUTH is True, f"REQUIRE_AUTH={val!r} should be True"
    for val in ("0", "false", "no", ""):
        app_module = _reload_app(monkeypatch, REQUIRE_AUTH=val)
        assert app_module.REQUIRE_AUTH is False, f"REQUIRE_AUTH={val!r} should be False"


def test_chat_endpoint_returns_503_when_api_key_missing(monkeypatch):
    """The /api/chat endpoint surfaces a clear error rather than 500 when
    ANTHROPIC_API_KEY is missing — important for a fresh prod box."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app_module = _reload_app(monkeypatch, REQUIRE_AUTH="false")
    client = TestClient(app_module.app)
    r = client.post("/api/chat", json={"session_id": "xxxx-test", "message": "hello"})
    assert r.status_code == 503
    body = r.json()
    assert body["error"] == "chat_unavailable"
    assert "ANTHROPIC_API_KEY" in body["detail"]


def test_app_has_expected_routes():
    """Smoke check — the routes the frontend depends on are all mounted."""
    # Use the already-loaded module (no reload — keep conftest's env settings).
    os.environ.setdefault("REQUIRE_AUTH", "false")
    from backend.app import app

    paths = {r.path for r in app.routes}
    for required in ("/api/health", "/api/whoami", "/api/edition", "/api/layout", "/api/sources", "/api/chat"):
        assert required in paths, f"missing route {required}"
