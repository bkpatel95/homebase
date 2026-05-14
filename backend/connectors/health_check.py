"""Prod health audit connector — reads the latest prod-health.json on disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import ConfigField, Connector


class HealthCheckConnector(Connector):
    id = "prod_health"
    name = "Prod Health Audit"
    description = "Reads the rolling prod-health.json audit and surfaces flagged issues."
    icon = "✓"
    category = "infra"
    widget_ids = ("prod_health",)
    config_schema = (
        ConfigField(
            name="path",
            label="Health JSON path",
            type="path",
            required=True,
            help="Filesystem path inside the container where the health audit is mounted.",
            placeholder="/data/health-data/prod-health.json",
            default="/data/health-data/prod-health.json",
            env_fallback="PROD_HEALTH_JSON",
        ),
    )

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        p = Path(config.get("path") or "")
        if not p:
            return {"ok": False, "detail": "no path configured"}
        if not p.exists():
            return {"ok": False, "detail": f"not found: {p}"}
        try:
            with p.open() as f:
                json.load(f)
        except Exception as e:
            return {"ok": False, "detail": f"unreadable JSON: {e}"}
        return {"ok": True, "detail": f"present and parseable ({p})"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        path = Path(config.get("path") or "")
        if not path.exists():
            return {"prod_health": {"error": f"{path} not found", "issues": []}}
        try:
            with path.open() as f:
                raw = json.load(f)
        except Exception as e:
            return {"prod_health": {"error": f"could not parse health file: {e}", "issues": []}}

        issues: list[str] = []
        checks = raw.get("checks", {})
        containers = checks.get("containers", {})
        for nm in containers.get("missing", []) or []:
            issues.append(f"Container missing: {nm}")
        for nm in containers.get("not_running", []) or []:
            issues.append(f"Container not running: {nm}")
        for nm in containers.get("high_restart", []) or []:
            issues.append(f"High restart count: {nm}")

        for category, payload in checks.items():
            if category == "containers" or not isinstance(payload, dict):
                continue
            for k, v in payload.items():
                if isinstance(v, list) and v and k in ("errors", "warnings", "issues"):
                    for entry in v:
                        issues.append(f"{category}: {entry}")

        total = containers.get("total")
        expected = containers.get("expected_total")
        summary = None
        if total is not None and expected is not None:
            summary = f"{total} containers running (expected {expected})."

        return {
            "prod_health": {
                "timestamp": raw.get("timestamp"),
                "issues": issues,
                "summary": summary,
                "source": str(path),
            }
        }


connector = HealthCheckConnector()
