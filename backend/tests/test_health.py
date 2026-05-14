"""GET /api/health — liveness probe used by podman healthchecks."""

from __future__ import annotations


def test_health_returns_200(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_bypasses_auth(auth_client):
    """Healthchecks run without Cloudflare Access headers — must not 403."""
    r = auth_client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


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
