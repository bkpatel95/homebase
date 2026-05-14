"""Connector registry — auto-discovers every module in this package that
exports a `connector` attribute and gives the rest of the app a single API
to talk to them.

Drop a new file in `backend/connectors/<your_id>.py` that does:

    from .base import Connector, ConfigField
    class MyConnector(Connector):
        id = "my_thing"
        name = "My Thing"
        ...
    connector = MyConnector()

…and it will show up in /api/sources, the Sources panel, and (if its
`widget_ids` are referenced in the frontend) the edition payload, with no
edits anywhere else.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from . import store
from .base import ConfigField, Connector

log = logging.getLogger("homebase.connectors")

_REGISTRY: dict[str, Connector] = {}


def _discover() -> None:
    """Import every sibling module and register anything that looks like a
    Connector. Failures in one module shouldn't break the rest of the app —
    we log and move on.
    """
    package = __name__
    for mod_info in pkgutil.iter_modules(__path__):
        if mod_info.name.startswith("_") or mod_info.name in ("base", "store"):
            continue
        try:
            mod = importlib.import_module(f"{package}.{mod_info.name}")
        except Exception as e:
            log.warning("connector module %s failed to import: %s", mod_info.name, e)
            continue
        instance = getattr(mod, "connector", None)
        if not isinstance(instance, Connector):
            continue
        if not instance.id:
            log.warning("connector in %s has no id, skipping", mod_info.name)
            continue
        if instance.id in _REGISTRY:
            log.warning("duplicate connector id %s (from %s) — keeping first", instance.id, mod_info.name)
            continue
        _REGISTRY[instance.id] = instance
        log.info("registered connector: %s (widgets=%s)", instance.id, ",".join(instance.widget_ids))


_discover()


# ─── public API ─────────────────────────────────────────────────────────────


def all_connectors() -> list[Connector]:
    return sorted(_REGISTRY.values(), key=lambda c: (c.category, c.name.lower()))


def get_connector(connector_id: str) -> Connector | None:
    return _REGISTRY.get(connector_id)


def _status_for(c: Connector, record: dict[str, Any]) -> str:
    """Compute a UI-facing status string.

    - "error":        last test/sync failed and we have an explicit error
    - "connected":    configured (stored or env-fallback) and no recent failure
    - "disconnected": missing required fields
    """
    stored = record.get("config") or {}
    if not c.is_configured(stored):
        return "disconnected"
    if record.get("last_status") == "error":
        return "error"
    return "connected"


def describe_all() -> list[dict[str, Any]]:
    """Snapshot used by GET /api/sources."""
    records = store.all_records()
    out: list[dict[str, Any]] = []
    for c in all_connectors():
        rec = records.get(c.id, {}) or {}
        stored = rec.get("config") or {}
        resolved = c.resolve(stored)
        # Mask secrets in the snapshot — the UI only needs to know presence.
        config_values: dict[str, dict[str, Any]] = {}
        for f in c.config_schema:
            stored_v = stored.get(f.name) or ""
            env_v = ""
            if f.env_fallback:
                import os

                env_v = os.environ.get(f.env_fallback, "") or ""
            present = bool(str(resolved.get(f.name) or "").strip())
            config_values[f.name] = {
                "set": bool(str(stored_v).strip()),
                "from_env": bool(env_v and not str(stored_v).strip()),
                "present": present,
                # Echo a redacted preview for non-secret fields only.
                "preview": (stored_v if f.type != "password" else "") if stored_v else "",
            }
        out.append(
            {
                **c.describe(),
                "status": _status_for(c, rec),
                "configured": c.is_configured(stored),
                "missing_required": c.missing_required(resolved),
                "last_sync": rec.get("last_sync"),
                "last_status": rec.get("last_status"),
                "last_error": rec.get("last_error"),
                "last_tested_at": rec.get("last_tested_at"),
                "configured_at": rec.get("configured_at"),
                "values": config_values,
            }
        )
    return out


async def collect_widget(widget_id: str) -> dict[str, Any]:
    """Run any connector that claims to feed `widget_id` and return that
    portion of its result. The first connector wins if two claim the same id.
    """
    for c in _REGISTRY.values():
        if widget_id in c.widget_ids:
            payload = await _safe_collect(c)
            return payload.get(widget_id, {})
    return {"error": f"no connector for widget '{widget_id}'"}


async def collect_all() -> dict[str, dict[str, Any]]:
    """Run every connector concurrently and merge their widget payloads."""
    import asyncio

    coros = {c.id: _safe_collect(c) for c in _REGISTRY.values()}
    results = await asyncio.gather(*coros.values(), return_exceptions=False)
    merged: dict[str, dict[str, Any]] = {}
    for payload in results:
        for wid, p in payload.items():
            # First connector to claim a widget id wins; later ones are no-ops.
            merged.setdefault(wid, p)
    return merged


async def _safe_collect(c: Connector) -> dict[str, dict[str, Any]]:
    """Wrap collect() so a single connector raising doesn't sink the edition."""
    config = c.resolve(store.get_config(c.id))
    try:
        result = await c.collect(config)
        # Record success only when the connector produced *something*; a connector
        # that returns `{widget: {available: False, reason: "no token"}}` isn't
        # really an error, but we still want a last_sync timestamp.
        store.record_sync(c.id, ok=True)
        return result or {}
    except Exception as e:
        store.record_sync(c.id, ok=False, error=f"{type(e).__name__}: {e}")
        log.exception("connector %s collect failed", c.id)
        # Surface the error on every widget the connector claims so the UI
        # doesn't silently render blanks.
        return {wid: {"error": f"{type(e).__name__}: {e}", "available": False} for wid in c.widget_ids}


async def test_connector(connector_id: str) -> dict[str, Any]:
    c = _REGISTRY.get(connector_id)
    if not c:
        return {"ok": False, "detail": f"unknown connector '{connector_id}'"}
    config = c.resolve(store.get_config(connector_id))
    try:
        result = await c.test_connection(config)
    except Exception as e:
        result = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    store.record_test(connector_id, result)
    return result


__all__ = [
    "Connector",
    "ConfigField",
    "store",
    "all_connectors",
    "get_connector",
    "describe_all",
    "collect_widget",
    "collect_all",
    "test_connector",
]
