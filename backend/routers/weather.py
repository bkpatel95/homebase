"""GET /api/weather — current conditions + short forecast.

Thin wrapper around the weather connector. Returns the widget payload
verbatim so the same shape powers both the dashboard widget and any
external caller (e.g. the ticker on the marquee). The connector handles
errors and emits a `collected_at` stamp the client can use to detect
stale data.
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import connectors

router = APIRouter()


@router.get("/weather")
async def get_weather():
    return await connectors.collect_widget("weather")
