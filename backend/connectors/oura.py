"""Oura Ring connector — direct API or file-backed summary fallback."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from .base import ConfigField, Connector

OURA_API = "https://api.ouraring.com/v2/usercollection"


async def _api(client: httpx.AsyncClient, token: str, path: str, params: dict) -> dict:
    r = await client.get(
        f"{OURA_API}{path}",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    return r.json()


def _latest(rows: list[dict], key_for_day: str = "day") -> dict | None:
    if not rows:
        return None
    return sorted(rows, key=lambda r: r.get(key_for_day, ""))[-1]


class OuraConnector(Connector):
    id = "oura"
    name = "Oura Ring"
    description = "Sleep, readiness, HRV, resting HR, and activity. API token or file summary."
    icon = "○"
    category = "personal"
    widget_ids = ("health_wellness",)
    config_schema = (
        ConfigField(
            name="token",
            label="Personal access token",
            type="password",
            help="Generate at cloud.ouraring.com/personal-access-tokens. Optional if a summary file is provided.",
            env_fallback="OURA_TOKEN",
        ),
        ConfigField(
            name="summary_path",
            label="Summary file (fallback)",
            type="path",
            help="Path to a daily-summary.json file rsync'd from another machine.",
            placeholder="/data/health-data/daily-summary.json",
            default="/data/health-data/daily-summary.json",
            env_fallback="OURA_SUMMARY",
        ),
        ConfigField(
            name="timeout",
            label="HTTP timeout (seconds)",
            type="number",
            default="4.0",
            env_fallback="OURA_TIMEOUT",
        ),
    )

    def is_configured(self, stored: dict[str, Any] | None) -> bool:
        # Configured if *either* a token OR a readable summary file is present.
        resolved = self.resolve(stored)
        if str(resolved.get("token") or "").strip():
            return True
        p = resolved.get("summary_path") or ""
        return bool(p) and Path(p).exists()

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        token = (config.get("token") or "").strip()
        timeout = _to_float(config.get("timeout"), 4.0)
        if token:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    r = await client.get(
                        f"{OURA_API}/personal_info",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                if r.status_code == 200:
                    return {"ok": True, "detail": "Oura API authenticated"}
                return {"ok": False, "detail": f"Oura API HTTP {r.status_code}"}
            except Exception as e:
                return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
        p = Path(config.get("summary_path") or "")
        if p.exists():
            return {"ok": True, "detail": f"summary file present ({p})"}
        return {"ok": False, "detail": "no token and no summary file"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        token = (config.get("token") or "").strip()
        timeout = _to_float(config.get("timeout"), 4.0)

        if token:
            data = await self._from_api(token, timeout)
            if data and data.get("available"):
                data["collected_at"] = now
                return {"health_wellness": data}

        data = self._from_file(Path(config.get("summary_path") or ""))
        if data:
            data["collected_at"] = now
            return {"health_wellness": data}

        return {
            "health_wellness": {
                "available": False,
                "reason": "No Oura token set and no daily-summary.json on disk.",
                "collected_at": now,
            }
        }

    async def _from_api(self, token: str, timeout: float) -> dict[str, Any] | None:
        end = date.today()
        start = end - timedelta(days=7)
        params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                sleep = await _api(client, token, "/daily_sleep", params)
                periods = await _api(client, token, "/sleep", params)
                readiness = await _api(client, token, "/daily_readiness", params)
                activity = await _api(client, token, "/daily_activity", params)
        except Exception as e:
            return {"error": f"Oura API: {e}"}

        s = _latest(sleep.get("data", []))
        p = _latest(periods.get("data", []))
        r = _latest(readiness.get("data", []))
        a = _latest(activity.get("data", []))

        return {
            "available": True,
            "source": "oura-api",
            "date": (s or {}).get("day") or (a or {}).get("day"),
            "sleep_score": (s or {}).get("score"),
            "sleep_hours": round(((p or {}).get("total_sleep_duration") or 0) / 3600, 1) or None,
            "readiness_score": (r or {}).get("score"),
            "hrv": (p or {}).get("average_hrv"),
            "resting_hr": (p or {}).get("average_heart_rate"),
            "activity_calories": (a or {}).get("active_calories"),
            "steps": (a or {}).get("steps"),
        }

    def _from_file(self, path: Path) -> dict[str, Any] | None:
        if not path or not path.exists():
            return None
        try:
            rows = json.loads(path.read_text())
        except Exception as e:
            return {"available": False, "error": f"could not parse {path}: {e}"}
        if not isinstance(rows, list) or not rows:
            return {"available": False, "error": "summary file is empty"}
        latest = sorted(rows, key=lambda r: r.get("date", ""))[-1]
        return {
            "available": True,
            "source": f"file:{path.name}",
            "date": latest.get("date"),
            "sleep_score": latest.get("sleep_score"),
            "sleep_hours": latest.get("sleep_duration_hours"),
            "readiness_score": latest.get("readiness_score"),
            "hrv": latest.get("avg_hrv"),
            "resting_hr": latest.get("avg_hr_sleep"),
            "activity_calories": latest.get("active_calories"),
            "steps": latest.get("steps"),
        }


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


connector = OuraConnector()
