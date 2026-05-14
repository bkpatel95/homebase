"""Tool definitions + executors for The Daily Bhavi's chat bar.

Four tools mirror the things the editor's desk lets the user do without
opening a settings page:
  - update_layout   → reorder / hide / show sections
  - query_data      → read structured data via a connector
  - update_ticker   → change what the ticker bar shows
  - manage_sources  → list, test, or remove connector configurations

Each handler returns a `{ok, summary, ...}` dict that gets fed back to Claude
as the tool_result so it can write a natural-language reply.
"""

from __future__ import annotations

from typing import Any

from .. import connectors, layout_store, ws_manager

# ─── Tool schemas (Anthropic tool-use shape) ────────────────────────────────


def _query_data_sources() -> list[str]:
    """Build the enum for query_data from the registry. Includes every widget
    a connector claims to feed.
    """
    out: set[str] = set()
    for c in connectors.all_connectors():
        for w in c.widget_ids:
            out.add(w)
    return sorted(out)


TOOLS: list[dict[str, Any]] = [
    {
        "name": "update_layout",
        "description": (
            "Reorder, show, or hide newspaper sections. Use this when the user asks to "
            "move a widget, hide one, bring one back, or reset to default. The dashboard "
            "has three columns; position 0 is the top of column 1, position 1 is the top "
            "of column 2, position 2 is the top of column 3, position 3 is the second "
            "row of column 1, and so on. Layout changes broadcast to all connected "
            "browsers immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["move", "hide", "show", "reset"],
                    "description": "What to do.",
                },
                "widget": {
                    "type": "string",
                    "enum": layout_store.ALL_WIDGETS,
                    "description": "Which widget to act on. Required for move/hide/show.",
                },
                "position": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "0-based slot in the priority order. Required for 'move'.",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "query_data",
        "description": (
            "Fetch fresh data from a registered connector to answer the user's question. "
            "Use this when they ask 'how was my X', 'what's happening with Y'. "
            "The response is structured JSON; summarize it in 1-3 sentences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": _query_data_sources() or ["health_wellness"],
                    "description": "Widget id to query (e.g. health_wellness, markets, infrastructure).",
                },
                "detail": {
                    "type": "string",
                    "description": "Optional natural-language hint about what aspect to focus on.",
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "update_ticker",
        "description": (
            "Change which items appear in the ticker bar under the masthead. Items are "
            "picked from a fixed set. Pass the list in display order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["prod", "sleep", "cpu", "markets", "meetings"]},
                    "minItems": 1,
                    "maxItems": 6,
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "manage_sources",
        "description": (
            "Inspect, test, or remove a data connector. Use this when the user asks "
            "'what sources do I have', 'is X connected', 'test the Oura connection', "
            "or 'disconnect my Plex'. To *add or change* credentials, direct the user "
            "to the Sources panel (gear icon in the masthead) — secret values should "
            "not be entered into chat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "test", "remove"],
                    "description": "list = describe all, test = run connectivity check, remove = clear stored config.",
                },
                "connector_id": {
                    "type": "string",
                    "description": "Required for test/remove. Use one of the ids from `list`.",
                },
            },
            "required": ["action"],
        },
    },
]


# ─── Executors ───────────────────────────────────────────────────────────────


async def _execute_update_layout(args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action")
    widget = args.get("widget")
    state = layout_store.get_state()

    if action == "reset":
        new_state = dict(layout_store.DEFAULT_STATE)
        layout_store.save_state(new_state, source="chat:update_layout")
        await ws_manager.broadcast({"type": "edition_dirty", "reason": "layout_reset"})
        return {
            "ok": True,
            "summary": "Layout reset to defaults — the newspaper now follows the time-of-day arrangement.",
        }

    if not widget:
        return {"ok": False, "error": "widget is required for move/hide/show"}
    if widget not in layout_store.ALL_WIDGETS:
        return {"ok": False, "error": f"unknown widget '{widget}'"}

    hidden = set(state.get("hidden") or [])
    priority = list(state.get("priority") or layout_store.MOOD_PRIORITY["midday"])
    if widget not in priority:
        priority.append(widget)

    if action == "hide":
        hidden.add(widget)
        state["hidden"] = sorted(hidden)
        layout_store.save_state(state, source="chat:update_layout")
        await ws_manager.broadcast({"type": "edition_dirty", "reason": "hide", "widget": widget})
        return {"ok": True, "summary": f"Hidden the {pretty(widget)} section."}

    if action == "show":
        hidden.discard(widget)
        state["hidden"] = sorted(hidden)
        layout_store.save_state(state, source="chat:update_layout")
        await ws_manager.broadcast({"type": "edition_dirty", "reason": "show", "widget": widget})
        return {"ok": True, "summary": f"Showing the {pretty(widget)} section again."}

    if action == "move":
        position = args.get("position")
        if position is None or position < 0:
            return {"ok": False, "error": "position is required and must be >= 0 for move"}
        priority = [w for w in priority if w != widget]
        position = min(position, len(priority))
        priority.insert(position, widget)
        hidden.discard(widget)
        state["priority"] = priority
        state["hidden"] = sorted(hidden)
        layout_store.save_state(state, source="chat:update_layout")
        await ws_manager.broadcast({"type": "edition_dirty", "reason": "move", "widget": widget, "position": position})
        return {"ok": True, "summary": f"Moved {pretty(widget)} to position {position}.", "new_order": priority}

    return {"ok": False, "error": f"unknown action '{action}'"}


async def _execute_query_data(args: dict[str, Any]) -> dict[str, Any]:
    # Back-compat aliases: earlier the enum was {health, markets, infra, ...}.
    aliases = {
        "health": "health_wellness",
        "infra": "infrastructure",
        "system": "system_metrics",
    }
    source = aliases.get(args.get("source"), args.get("source"))
    detail = (args.get("detail") or "").strip()

    if not source:
        return {"ok": False, "error": "source is required"}

    data = await connectors.collect_widget(source)

    # Compact some sources so the model doesn't drink from a firehose.
    if source == "infrastructure":
        data = {
            "containers_up": data.get("containers_up"),
            "containers_total": data.get("containers_total"),
            "containers_down": data.get("containers_down"),
            "down_names": data.get("down_names"),
            "containers": data.get("containers", [])[:25],
        }
    if source == "markets":
        data = {
            "tickers": [
                {k: t.get(k) for k in ("label", "symbol", "price", "prev_close", "pct_change") if t.get(k) is not None}
                for t in data.get("tickers", [])
            ]
        }

    return {"ok": True, "data": data, "detail_hint": detail}


async def _execute_update_ticker(args: dict[str, Any]) -> dict[str, Any]:
    items = args.get("items") or []
    if not items:
        return {"ok": False, "error": "items cannot be empty"}
    state = layout_store.get_state()
    state["ticker_items"] = list(items)
    layout_store.save_state(state, source="chat:update_ticker")
    await ws_manager.broadcast({"type": "edition_dirty", "reason": "ticker", "items": items})
    return {"ok": True, "summary": f"Ticker now shows: {', '.join(items)}."}


async def _execute_manage_sources(args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action")
    cid = args.get("connector_id")

    if action == "list":
        snapshot = connectors.describe_all()
        # Trim secrets/schema before handing back to Claude.
        rows = [
            {
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "status": s["status"],
                "configured": s["configured"],
                "widgets": s["widget_ids"],
                "missing_required": s["missing_required"],
                "last_sync": s["last_sync"],
                "last_error": s["last_error"],
            }
            for s in snapshot
        ]
        return {"ok": True, "summary": f"{len(rows)} connectors registered.", "sources": rows}

    if not cid:
        return {"ok": False, "error": "connector_id is required for test/remove"}
    if not connectors.get_connector(cid):
        return {"ok": False, "error": f"unknown connector '{cid}'"}

    if action == "test":
        result = await connectors.test_connector(cid)
        return {
            "ok": bool(result.get("ok")),
            "summary": f"{cid}: {'ok' if result.get('ok') else 'failed'} — {result.get('detail', '')}",
            "test_result": result,
        }

    if action == "remove":
        removed = connectors.store.delete(cid)
        if removed:
            await ws_manager.broadcast({"type": "edition_dirty", "reason": "sources", "connector_id": cid})
        return {
            "ok": True,
            "summary": (f"Cleared stored config for {cid}." if removed else f"{cid} had no stored config to remove."),
        }

    return {"ok": False, "error": f"unknown action '{action}'"}


_EXECUTORS = {
    "update_layout": _execute_update_layout,
    "query_data": _execute_query_data,
    "update_ticker": _execute_update_ticker,
    "manage_sources": _execute_manage_sources,
}


async def execute(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = _EXECUTORS.get(tool_name)
    if not fn:
        return {"ok": False, "error": f"unknown tool '{tool_name}'"}
    try:
        return await fn(args)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def pretty(widget_id: str) -> str:
    return {
        "health_wellness": "Health & Wellness",
        "calendar": "Calendar",
        "markets": "Markets",
        "media": "Media",
        "nutrition": "Nutrition",
        "infrastructure": "Infrastructure",
        "system_metrics": "System Metrics",
        "prod_health": "Prod Health",
        "quick_links": "Quick Links",
    }.get(widget_id, widget_id.replace("_", " ").title())
