"""GET /api/edition — compiles the current edition from every registered connector.

The registry's `collect_all()` runs every connector concurrently and merges
their widget payloads. New connectors appear in the edition automatically.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from .. import connectors, layout_store

router = APIRouter()

LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "America/New_York"))

# The first four widgets always render — they have static fallbacks or always
# have *something* to report. The trailing three (weather/reminders/gmail) are
# self-fetching widgets: they pull from /api/weather, /api/reminders, /api/gmail
# directly and decide their own visibility (collapsing to nothing when the
# upstream endpoint isn't wired yet). The layout still needs to reserve a slot
# for them so the WidgetGrid can mount the components.
ALWAYS_AVAILABLE = {
    "infrastructure",
    "system_metrics",
    "prod_health",
    "quick_links",
    "weather",
    "reminders",
    "gmail",
}


def _edition_mood(now: datetime) -> str:
    h = now.astimezone(LOCAL_TZ).hour
    if h < 11:
        return "morning"
    if h < 17:
        return "midday"
    return "evening"


def _is_available(widget_id: str, payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return widget_id in ALWAYS_AVAILABLE
    if widget_id in ALWAYS_AVAILABLE:
        return True
    return bool(payload.get("available"))


def _build_ticker(widgets: dict, items: list[str]) -> list[dict]:
    out: list[dict] = []
    for key in items:
        item = _ticker_item(key, widgets)
        if item:
            out.append(item)
    return out


def _ticker_item(key: str, widgets: dict) -> dict | None:
    if key == "prod":
        infra = widgets.get("infrastructure") or {}
        up = infra.get("containers_up")
        total = infra.get("containers_total")
        if not total:
            return None
        return {
            "label": "Prod",
            "value": f"{up}/{total}",
            "suffix": "up",
            "status": "bad" if (infra.get("containers_down") or 0) else "ok",
        }
    if key == "sleep":
        hw = widgets.get("health_wellness") or {}
        if not hw.get("available") or hw.get("sleep_score") is None:
            return None
        score = hw["sleep_score"]
        return {
            "label": "Sleep",
            "value": str(score),
            "suffix": "score",
            "status": "ok" if score >= 80 else "warn" if score >= 65 else "bad",
        }
    if key == "markets":
        m = widgets.get("markets") or {}
        sp = next((t for t in m.get("tickers", []) if t.get("id") == "sp500"), None)
        if not sp or sp.get("pct_change") is None:
            return None
        pct = sp["pct_change"]
        sign = "+" if pct >= 0 else ""
        return {
            "label": "S&P",
            "value": f"{sign}{pct:.2f}%",
            "suffix": "today",
            "status": "ok" if pct >= 0 else "bad",
        }
    if key == "meetings":
        cal = widgets.get("calendar") or {}
        n = cal.get("count", 0)
        return {
            "label": "Meetings",
            "value": str(n),
            "suffix": "today",
            "status": "warn" if n >= 5 else "ok" if n else "idle",
        }
    if key == "cpu":
        sys_m = widgets.get("system_metrics") or {}
        cpu = sys_m.get("cpu_pct")
        if cpu is None:
            return None
        return {
            "label": "CPU",
            "value": f"{cpu:.0f}%",
            "suffix": "",
            "status": "bad" if cpu > 85 else "warn" if cpu > 60 else "ok",
        }
    if key == "weather":
        w = widgets.get("weather") or {}
        current = w.get("current") or {}
        temp = current.get("temp")
        if not w.get("available") or temp is None:
            return None
        unit = w.get("temp_unit") or "°"
        return {
            "label": w.get("label") or "Weather",
            "value": f"{round(float(temp))}{unit}",
            "suffix": current.get("condition") or "",
            "status": "ok",
        }
    return None


@router.get("/edition")
async def get_edition():
    widgets = await connectors.collect_all()

    # Ensure every known widget id is present in the payload — even if no
    # connector claims it — so the frontend's COMPONENT_FOR lookup still
    # works and missing connectors don't crash anything downstream.
    for wid in layout_store.ALL_WIDGETS:
        widgets.setdefault(wid, {})

    now = datetime.now(UTC)
    mood = _edition_mood(now)

    available = {k: _is_available(k, v) for k, v in widgets.items()}
    layout = layout_store.effective_layout(mood, available)
    ticker = _build_ticker(widgets, layout["ticker_items"])

    return {
        "compiled_at": now.isoformat(),
        "edition": now.astimezone(LOCAL_TZ).strftime("%Y-%m-%d"),
        "mood": mood,
        "layout": layout,
        "ticker": ticker,
        "widgets": widgets,
    }
