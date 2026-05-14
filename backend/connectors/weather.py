"""Weather connector — Open-Meteo current + 3-day forecast.

Open-Meteo is free, requires no API key, and tolerates the kind of light
traffic the dashboard produces (one request per edition compile). Default
coordinates point at Park City, UT; both lat/lon and the rendered place
label are overridable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from .base import ConfigField, Connector

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

DEFAULT_LAT = "40.6461"
DEFAULT_LON = "-111.498"
DEFAULT_LABEL = "Park City, UT"

# https://open-meteo.com/en/docs/ — small subset of WMO codes that show up
# in mountain-west weather; everything else falls through to the raw code.
_WMO_TEXT = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Heavy showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm w/ hail",
    99: "Thunderstorm w/ heavy hail",
}


def _condition(code: Any) -> str:
    try:
        return _WMO_TEXT.get(int(code), f"WMO {code}")
    except (TypeError, ValueError):
        return "Unknown"


def _today_hourly(hourly: dict[str, Any]) -> list[dict[str, Any]]:
    """Slice the hourly response down to today's hours, in local order."""
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    precip = hourly.get("precipitation_probability") or []
    today = date.today().isoformat()
    out: list[dict[str, Any]] = []
    for i, t in enumerate(times):
        if not isinstance(t, str) or not t.startswith(today):
            continue
        out.append(
            {
                "time": t,
                "temp": temps[i] if i < len(temps) else None,
                "condition": _condition(codes[i]) if i < len(codes) else None,
                "precip_prob": precip[i] if i < len(precip) else None,
            }
        )
    return out


def _daily_forecast(daily: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    days = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []
    precip = daily.get("precipitation_sum") or []
    out: list[dict[str, Any]] = []
    for i, d in enumerate(days[:limit]):
        out.append(
            {
                "date": d,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "condition": _condition(codes[i]) if i < len(codes) else None,
                "precip_total": precip[i] if i < len(precip) else None,
            }
        )
    return out


class WeatherConnector(Connector):
    id = "weather"
    name = "Weather"
    description = "Current conditions + 3-day forecast from Open-Meteo. No API key required."
    icon = "☼"
    category = "data"
    widget_ids = ("weather",)
    config_schema = (
        ConfigField(
            name="latitude",
            label="Latitude",
            type="number",
            required=True,
            help="Decimal degrees. Default points at Park City, UT.",
            default=DEFAULT_LAT,
            env_fallback="WEATHER_LAT",
        ),
        ConfigField(
            name="longitude",
            label="Longitude",
            type="number",
            required=True,
            help="Decimal degrees. Negative for the western hemisphere.",
            default=DEFAULT_LON,
            env_fallback="WEATHER_LON",
        ),
        ConfigField(
            name="label",
            label="Place label",
            help="Human-readable location shown on the widget.",
            default=DEFAULT_LABEL,
            env_fallback="WEATHER_LABEL",
        ),
        ConfigField(
            name="units",
            label="Temperature units",
            help="'fahrenheit' or 'celsius'. Wind/precip units track accordingly.",
            default="fahrenheit",
            env_fallback="WEATHER_UNITS",
        ),
        ConfigField(
            name="timeout",
            label="HTTP timeout (seconds)",
            type="number",
            default="4.0",
            env_fallback="WEATHER_TIMEOUT",
        ),
    )

    def _params(self, config: dict[str, Any]) -> dict[str, Any]:
        units = (config.get("units") or "fahrenheit").strip().lower()
        if units not in ("fahrenheit", "celsius"):
            units = "fahrenheit"
        return {
            "latitude": config.get("latitude") or DEFAULT_LAT,
            "longitude": config.get("longitude") or DEFAULT_LON,
            "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m,apparent_temperature",
            "hourly": "temperature_2m,weather_code,precipitation_probability",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_sum",
            "temperature_unit": units,
            "wind_speed_unit": "mph" if units == "fahrenheit" else "kmh",
            "precipitation_unit": "inch" if units == "fahrenheit" else "mm",
            "timezone": "auto",
            "forecast_days": 4,
        }

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        timeout = _to_float(config.get("timeout"), 4.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(OPEN_METEO_URL, params=self._params(config))
            if r.status_code != 200:
                return {"ok": False, "detail": f"Open-Meteo HTTP {r.status_code}"}
            j = r.json()
            if not isinstance(j, dict) or "current" not in j:
                return {"ok": False, "detail": "Open-Meteo response missing 'current'"}
            return {"ok": True, "detail": f"reachable; current={j['current'].get('temperature_2m')}"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        timeout = _to_float(config.get("timeout"), 4.0)
        label = (config.get("label") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
        units = (config.get("units") or "fahrenheit").strip().lower()
        if units not in ("fahrenheit", "celsius"):
            units = "fahrenheit"
        temp_unit_symbol = "°F" if units == "fahrenheit" else "°C"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(OPEN_METEO_URL, params=self._params(config))
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            return {
                "weather": {
                    "available": False,
                    "error": f"{type(e).__name__}: {e}",
                    "label": label,
                    "collected_at": now,
                }
            }

        current = data.get("current") or {}
        hourly_today = _today_hourly(data.get("hourly") or {})
        forecast = _daily_forecast(data.get("daily") or {}, limit=3)

        return {
            "weather": {
                "available": True,
                "label": label,
                "units": units,
                "temp_unit": temp_unit_symbol,
                "current": {
                    "temp": current.get("temperature_2m"),
                    "apparent_temp": current.get("apparent_temperature"),
                    "condition": _condition(current.get("weather_code")),
                    "humidity": current.get("relative_humidity_2m"),
                    "wind": current.get("wind_speed_10m"),
                    "observed_at": current.get("time"),
                },
                "hourly_today": hourly_today,
                "forecast": forecast,
                "collected_at": now,
            }
        }


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


connector = WeatherConnector()
