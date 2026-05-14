"""GET /api/health — liveness probe + per-connector staleness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_health_returns_200_and_status_ok(client):
    """Backward compat: external healthchecks rely on the top-level `status`
    field staying truthy. The body is now richer but `status: ok` is fixed."""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "connectors" in body
    assert "checked_at" in body


def test_health_lists_every_registered_connector(client):
    r = client.get("/api/health")
    body = r.json()
    ids = {c["id"] for c in body["connectors"]}
    # Every connector that auto-registers should show up. The exact set
    # changes as connectors are added — pin a stable subset.
    for known in ("oura", "calendar", "markets", "weather", "reminders", "gmail"):
        assert known in ids, f"missing connector {known} from /api/health"


def test_health_includes_age_seconds_when_last_sync_present(client, sources_path, monkeypatch):
    """When the store has a last_sync timestamp, /api/health reports an
    integer age_seconds derived from it."""
    from backend.connectors import store

    monkeypatch.setattr(store, "SOURCES_PATH", sources_path)
    five_min_ago = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    sources_path.write_text('{"oura": {"last_sync": "' + five_min_ago + '", "last_status": "ok"}}')

    r = client.get("/api/health")
    oura = next(c for c in r.json()["connectors"] if c["id"] == "oura")
    assert oura["last_sync"] == five_min_ago
    assert oura["last_status"] == "ok"
    # Allow a couple seconds of drift for the request itself.
    assert 290 <= oura["age_seconds"] <= 320


def test_health_bypasses_auth(auth_client):
    """Healthchecks run without Cloudflare Access headers — must not 403."""
    r = auth_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unauth_request_blocked(auth_client):
    r = auth_client.get("/api/whoami")
    assert r.status_code == 403
    assert r.json()["error"] == "unauthorized"


def test_auth_passes_with_known_email(auth_client):
    r = auth_client.get(
        "/api/whoami",
        headers={"cf-access-authenticated-user-email": "allowed@example.com"},
    )
    assert r.status_code == 200
    assert r.json() == {"email": "allowed@example.com"}


def test_auth_rejects_unknown_email(auth_client):
    r = auth_client.get(
        "/api/whoami",
        headers={"cf-access-authenticated-user-email": "stranger@example.com"},
    )
    assert r.status_code == 403
