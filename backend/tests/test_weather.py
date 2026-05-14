"""Weather connector — Open-Meteo happy path + failure mode.

The connector is the only thing in the codebase that talks to Open-Meteo,
so this suite exists to pin three things:
  1. The Open-Meteo response shape we depend on is parsed correctly.
  2. Failures don't raise — they round-trip into `available: False`.
  3. The ticker pulls weather data when the connector is present and skips
     it when the payload is missing or empty.
"""

from __future__ import annotations

import httpx
import respx

from backend.connectors.weather import OPEN_METEO_URL, WeatherConnector
from backend.routers.edition import _ticker_item


def _sample_open_meteo() -> dict:
    return {
        "current": {
            "time": "2026-05-13T15:00",
            "temperature_2m": 62.3,
            "apparent_temperature": 60.0,
            "weather_code": 2,
            "wind_speed_10m": 4.2,
            "relative_humidity_2m": 28,
        },
        "hourly": {
            "time": ["2026-05-13T00:00", "2026-05-13T12:00", "2026-05-14T00:00"],
            "temperature_2m": [40.0, 55.0, 38.0],
            "weather_code": [0, 2, 3],
            "precipitation_probability": [0, 5, 10],
        },
        "daily": {
            "time": ["2026-05-13", "2026-05-14", "2026-05-15", "2026-05-16"],
            "temperature_2m_max": [65.0, 70.0, 68.0, 72.0],
            "temperature_2m_min": [38.0, 40.0, 42.0, 44.0],
            "weather_code": [2, 1, 3, 61],
            "precipitation_sum": [0.0, 0.0, 0.1, 0.3],
        },
    }


@respx.mock
async def test_weather_collect_happy_path(monkeypatch):
    """Open-Meteo returns its usual shape → connector emits a populated payload."""
    # Pin "today" so the hourly filter has stable input.
    import backend.connectors.weather as weather_mod

    class _FakeDate:
        @staticmethod
        def today():
            from datetime import date

            return date(2026, 5, 13)

    monkeypatch.setattr(weather_mod, "date", _FakeDate)

    respx.get(OPEN_METEO_URL).mock(return_value=httpx.Response(200, json=_sample_open_meteo()))
    out = await WeatherConnector().collect(
        {
            "latitude": "40.6461",
            "longitude": "-111.498",
            "label": "Park City, UT",
            "units": "fahrenheit",
            "timeout": 2.0,
        }
    )
    w = out["weather"]
    assert w["available"] is True
    assert w["label"] == "Park City, UT"
    assert w["temp_unit"] == "°F"
    assert w["current"]["temp"] == 62.3
    assert w["current"]["condition"] == "Partly cloudy"
    # Only today's hours kept, in input order.
    assert [h["time"] for h in w["hourly_today"]] == ["2026-05-13T00:00", "2026-05-13T12:00"]
    # 3-day forecast capped, dropping the extra day.
    assert len(w["forecast"]) == 3
    assert w["forecast"][0]["high"] == 65.0
    assert w["forecast"][0]["low"] == 38.0
    assert "collected_at" in w


@respx.mock
async def test_weather_collect_http_error_returns_unavailable():
    respx.get(OPEN_METEO_URL).mock(return_value=httpx.Response(500))
    out = await WeatherConnector().collect({"label": "Anywhere", "timeout": 2.0})
    w = out["weather"]
    assert w["available"] is False
    assert "collected_at" in w
    assert "HTTPStatusError" in w["error"] or "Server" in w["error"] or "500" in w["error"]


@respx.mock
async def test_weather_test_connection_200(monkeypatch):
    respx.get(OPEN_METEO_URL).mock(return_value=httpx.Response(200, json=_sample_open_meteo()))
    result = await WeatherConnector().test_connection({"timeout": 2.0})
    assert result["ok"] is True
    assert "current=" in result["detail"]


@respx.mock
async def test_weather_test_connection_network_error():
    respx.get(OPEN_METEO_URL).mock(side_effect=httpx.ConnectError("nope"))
    result = await WeatherConnector().test_connection({"timeout": 2.0})
    assert result["ok"] is False
    assert "ConnectError" in result["detail"]


def test_ticker_weather_item_renders_when_available():
    item = _ticker_item(
        "weather",
        {
            "weather": {
                "available": True,
                "label": "Park City",
                "temp_unit": "°F",
                "current": {"temp": 61.7, "condition": "Mostly clear"},
            }
        },
    )
    assert item["label"] == "Park City"
    assert item["value"] == "62°F"
    assert item["suffix"] == "Mostly clear"


def test_ticker_weather_item_returns_none_when_unavailable():
    assert _ticker_item("weather", {"weather": {"available": False}}) is None
    assert _ticker_item("weather", {}) is None
