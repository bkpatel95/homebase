"""Layout persistence + the canonical "effective layout" computation.

The newspaper has three columns and a ticker. The default order depends on
edition mood (morning / midday / evening). The chat bar can override that
default — those overrides are persisted to /data/layout.json. The
`effective_layout()` function merges defaults + overrides into a single
column plan the frontend renders without ambiguity.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LAYOUT_PATH = Path(os.environ.get("LAYOUT_PATH", "/data/layout.json"))
N_COLUMNS = 3

ALL_WIDGETS = [
    "health_wellness",
    "calendar",
    "weather",
    "reminders",
    "gmail",
    "markets",
    "media",
    "nutrition",
    "infrastructure",
    "system_metrics",
    "prod_health",
    "quick_links",
]

DEFAULT_TICKER_ITEMS = ["prod", "sleep", "weather", "markets", "meetings", "cpu"]

# Time-of-day priority. The first widget in each list becomes column-0 top,
# the next column-1 top, etc. — interleaved so columns balance out.
MOOD_PRIORITY = {
    "morning": [
        "health_wellness",
        "weather",
        "calendar",
        "reminders",
        "gmail",
        "nutrition",
        "markets",
        "media",
        "system_metrics",
        "infrastructure",
        "prod_health",
        "quick_links",
    ],
    "midday": [
        "markets",
        "calendar",
        "reminders",
        "weather",
        "gmail",
        "health_wellness",
        "media",
        "nutrition",
        "system_metrics",
        "infrastructure",
        "prod_health",
        "quick_links",
    ],
    "evening": [
        "reminders",
        "gmail",
        "weather",
        "health_wellness",
        "nutrition",
        "media",
        "markets",
        "calendar",
        "system_metrics",
        "infrastructure",
        "prod_health",
        "quick_links",
    ],
}

DEFAULT_STATE: dict[str, Any] = {
    "version": 2,
    "priority": None,  # list[str] | None — None = use mood default
    "hidden": [],  # list[str] — widgets explicitly hidden
    "ticker_items": None,  # list[str] | None — None = use default
    "updated_at": None,
    "updated_by": None,
}

_lock = threading.Lock()


def _load_raw() -> dict[str, Any]:
    if not LAYOUT_PATH.exists():
        return dict(DEFAULT_STATE)
    try:
        with LAYOUT_PATH.open() as f:
            data = json.load(f)
        # Merge missing keys with defaults so older saves don't blow up.
        merged = dict(DEFAULT_STATE)
        merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULT_STATE)


def _save_raw(state: dict[str, Any]) -> None:
    LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LAYOUT_PATH.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(LAYOUT_PATH)


def get_state() -> dict[str, Any]:
    with _lock:
        return _load_raw()


def save_state(state: dict[str, Any], *, source: str = "api") -> dict[str, Any]:
    state = dict(state)
    state["updated_at"] = datetime.now(UTC).isoformat()
    state["updated_by"] = source
    with _lock:
        _save_raw(state)
    return state


def _three_columns(order: list[str]) -> list[list[str]]:
    """Distribute the ordered list across N_COLUMNS columns, interleaving.

    Index 0 → column 0, index 1 → column 1, index 2 → column 2, index 3 →
    column 0 (second row), … so the highest-priority items live above the
    fold across all three columns.
    """
    cols: list[list[str]] = [[] for _ in range(N_COLUMNS)]
    for i, w in enumerate(order):
        cols[i % N_COLUMNS].append(w)
    return cols


def effective_layout(mood: str, available: dict[str, bool]) -> dict[str, Any]:
    """Combine stored overrides + mood default + per-widget availability into
    the columns/ticker the frontend renders.

    `available[widget_id]` is whether the widget reported `available: true`
    this edition. Widgets that aren't available are dropped from the layout
    automatically — the chat bar can still "show" them later by clearing
    the hide override; if the data source comes back, they'll reappear.
    """
    state = get_state()
    base = MOOD_PRIORITY.get(mood) or MOOD_PRIORITY["midday"]

    if state.get("priority"):
        # User-pinned order. Keep user's list, then append any widgets they
        # didn't mention (in mood-default order) so new sections still appear.
        seen = set(state["priority"])
        order = [w for w in state["priority"] if w in ALL_WIDGETS]
        order += [w for w in base if w not in seen and w in ALL_WIDGETS]
    else:
        order = list(base)

    hidden = set(state.get("hidden") or [])
    visible = [w for w in order if w not in hidden and available.get(w, True)]

    ticker_items = state.get("ticker_items") or DEFAULT_TICKER_ITEMS

    return {
        "columns": _three_columns(visible),
        "priority": order,
        "visible": visible,
        "hidden": sorted(hidden),
        "ticker_items": ticker_items,
        "overrides_active": bool(state.get("priority") or state.get("hidden") or state.get("ticker_items")),
        "updated_at": state.get("updated_at"),
        "updated_by": state.get("updated_by"),
    }
