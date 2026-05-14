"""Shared pytest fixtures.

The backend reads a few module-level globals from environment variables on
import (ALLOWED_EMAILS, REQUIRE_AUTH, SOURCES_PATH, ANTHROPIC_API_KEY). We
neutralize those before importing app modules so the tests run hermetically
regardless of the developer's shell.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Point the connector store at a throwaway file before any backend import.
# Individual tests get their own isolated path via the `sources_path` fixture,
# but the import-time read in backend.connectors.store needs something safe.
_DEFAULT_TMP_SOURCES = Path("/tmp/homebase-tests-default-sources.json")
os.environ.setdefault("SOURCES_PATH", str(_DEFAULT_TMP_SOURCES))
os.environ.setdefault("REQUIRE_AUTH", "false")
os.environ.setdefault("ALLOWED_EMAILS", "test@example.com")

# Make the repo root importable so `from backend.app import app` works
# regardless of where pytest was invoked from.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def sources_path(tmp_path, monkeypatch):
    """Point backend.connectors.store at an isolated JSON file for one test."""
    p = tmp_path / "sources.json"
    monkeypatch.setattr("backend.connectors.store.SOURCES_PATH", p)
    return p


@pytest.fixture
def client():
    """FastAPI TestClient with auth disabled."""
    from fastapi.testclient import TestClient

    from backend.app import app

    return TestClient(app)


@pytest.fixture
def auth_client(monkeypatch):
    """FastAPI TestClient with REQUIRE_AUTH=True and an authenticated identity."""
    import backend.app as app_module

    monkeypatch.setattr(app_module, "REQUIRE_AUTH", True)
    monkeypatch.setattr(app_module, "ALLOWED_EMAILS", {"allowed@example.com"})

    from fastapi.testclient import TestClient

    return TestClient(app_module.app)
