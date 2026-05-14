"""App startup — exercise the env-validation contract and the auth-middleware
config that's read at import time.

`backend.config.validate_env()` runs at module import (see
`backend/app.py`). It requires ANTHROPIC_API_KEY (RuntimeError if absent)
and warns about missing OURA_TOKEN / PLEX_TOKEN / OVERSEERR_API_KEY without
blocking startup. These tests pin that contract.
"""

from __future__ import annotations

import importlib
import os

import pytest
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


def test_validate_env_refuses_without_anthropic_key(monkeypatch):
    """validate_env() raises a RuntimeError that names the missing var so
    operators see a clear error on a fresh deploy instead of a late 503.
    The backend.app module calls validate_env() at import — we invoke it
    directly here to avoid leaving the module in a half-imported state."""
    from backend.config import validate_env

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        validate_env()


def test_app_boots_without_optional_connector_env(monkeypatch):
    """No connector creds (but ANTHROPIC_API_KEY present): app imports and
    /api/sources responds. Optional integrations only log warnings."""
    for k in ("OURA_TOKEN", "PLEX_TOKEN", "OVERSEERR_API_KEY", "PROMETHEUS_URL"):
        monkeypatch.delenv(k, raising=False)
    app_module = _reload_app(
        monkeypatch,
        ANTHROPIC_API_KEY="sk-test-placeholder",
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


def test_app_has_expected_routes():
    """Smoke check — the routes the frontend depends on are all mounted."""
    # Use the already-loaded module (no reload — keep conftest's env settings).
    os.environ.setdefault("REQUIRE_AUTH", "false")
    from backend.app import app

    paths = {r.path for r in app.routes}
    for required in (
        "/api/health",
        "/api/whoami",
        "/api/edition",
        "/api/layout",
        "/api/sources",
        "/api/chat",
        "/api/weather",
        "/api/reminders",
        "/api/gmail",
        "/api/gmail/auth",
        "/api/gmail/auth/callback",
    ):
        assert required in paths, f"missing route {required}"
