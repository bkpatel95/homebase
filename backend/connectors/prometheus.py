"""Prometheus connector — feeds both `infrastructure` and `system_metrics`.

One connector covers both widgets because they share a Prometheus endpoint
and a single test/configure surface.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

import httpx

from .base import ConfigField, Connector


async def _query(client: httpx.AsyncClient, base: str, expr: str) -> list[dict[str, Any]]:
    r = await client.get(f"{base}/api/v1/query", params={"query": expr})
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"prom query failed: {data}")
    return data["data"]["result"]


def _scalar(result: list[dict[str, Any]]) -> float | None:
    if not result:
        return None
    try:
        return float(result[0]["value"][1])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


class PrometheusConnector(Connector):
    id = "prometheus"
    name = "Prometheus"
    description = "Container roll-call (podman-exporter) and host vitals (node-exporter)."
    icon = "P"
    category = "infra"
    widget_ids = ("infrastructure", "system_metrics")
    config_schema = (
        ConfigField(
            name="url",
            label="Prometheus URL",
            type="url",
            required=True,
            help="Base URL of the Prometheus query API.",
            placeholder="http://prometheus:9090",
            default="http://host.containers.internal:9090",
            env_fallback="PROMETHEUS_URL",
        ),
        ConfigField(
            name="timeout",
            label="HTTP timeout (seconds)",
            type="number",
            default="4.0",
            env_fallback="PROMETHEUS_TIMEOUT",
        ),
    )

    def _timeout(self, config: dict[str, Any]) -> float:
        try:
            return float(config.get("timeout") or 4.0)
        except (TypeError, ValueError):
            return 4.0

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        url = (config.get("url") or "").rstrip("/")
        if not url:
            return {"ok": False, "detail": "Prometheus URL not configured"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout(config)) as client:
                r = await client.get(f"{url}/-/ready")
            if r.status_code >= 400:
                return {"ok": False, "detail": f"HTTP {r.status_code} from {url}/-/ready"}
            return {"ok": True, "detail": f"ready ({url})"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        url = (config.get("url") or "").rstrip("/")
        timeout = self._timeout(config)
        infra = await self._infra(url, timeout)
        sysm = await self._system(url, timeout)
        return {"infrastructure": infra, "system_metrics": sysm}

    async def _infra(self, url: str, timeout: float) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        if not url:
            return {
                "error": "prometheus url not set",
                "containers": [],
                "containers_up": 0,
                "containers_total": 0,
                "containers_down": 0,
                "collected_at": now,
            }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                info = await _query(client, url, "podman_container_info")
                states = await _query(client, url, "podman_container_state")
                health = await _query(client, url, "podman_container_health")
        except Exception as e:
            return {
                "error": f"prometheus unreachable: {e}",
                "containers": [],
                "containers_up": 0,
                "containers_total": 0,
                "containers_down": 0,
                "collected_at": now,
            }

        state_name = {
            0: "unknown",
            1: "created",
            2: "running",
            3: "stopped",
            4: "exited",
            5: "paused",
            6: "removing",
            7: "error",
        }
        health_name = {0: "none", 1: "healthy", 2: "unhealthy", 3: "starting"}

        id_to_name: dict[str, str] = {}
        for r in info:
            cid = r["metric"].get("id")
            nm = r["metric"].get("name")
            if cid and nm:
                id_to_name[cid] = nm

        state_by_id: dict[str, int] = {}
        for r in states:
            cid = r["metric"].get("id")
            with contextlib.suppress(ValueError, TypeError):
                state_by_id[cid] = int(float(r["value"][1]))

        health_by_id: dict[str, int] = {}
        for r in health:
            cid = r["metric"].get("id")
            with contextlib.suppress(ValueError, TypeError):
                health_by_id[cid] = int(float(r["value"][1]))

        containers: list[dict[str, Any]] = []
        for cid, name in id_to_name.items():
            code = state_by_id.get(cid, 0)
            containers.append(
                {
                    "name": name,
                    "state": state_name.get(code, "unknown"),
                    "health": health_name.get(health_by_id.get(cid, 0), "none"),
                    "restarts": 0,
                }
            )
        containers.sort(key=lambda c: (c["state"] != "running", c["name"]))

        up = sum(1 for c in containers if c["state"] == "running")
        total = len(containers)
        down_names = [c["name"] for c in containers if c["state"] != "running"]

        return {
            "containers": containers,
            "containers_up": up,
            "containers_total": total,
            "containers_down": total - up,
            "down_names": down_names,
            "collected_at": now,
        }

    async def _system(self, url: str, timeout: float) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        if not url:
            return {"error": "prometheus url not set", "collected_at": now}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                cpu = _scalar(
                    await _query(
                        client,
                        url,
                        '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[2m])) * 100)',
                    )
                )
                mem = _scalar(
                    await _query(
                        client,
                        url,
                        "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100",
                    )
                )
                disk = _scalar(
                    await _query(
                        client,
                        url,
                        '(1 - (node_filesystem_avail_bytes{mountpoint="/"} '
                        '/ node_filesystem_size_bytes{mountpoint="/"})) * 100',
                    )
                )
                load1 = _scalar(await _query(client, url, "node_load1"))
                uptime = _scalar(await _query(client, url, "time() - node_boot_time_seconds"))
        except Exception as e:
            return {"error": f"prometheus unreachable: {e}", "collected_at": now}

        return {
            "cpu_pct": cpu,
            "mem_pct": mem,
            "disk_pct": disk,
            "load1": load1,
            "uptime_seconds": uptime,
            "collected_at": now,
        }


connector = PrometheusConnector()
