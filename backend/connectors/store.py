"""Persistent connector config + status store.

One JSON file at /data/sources.json (configurable via SOURCES_PATH) holds:
  {
    "<connector_id>": {
      "config":         {field: value, ...},
      "configured_at":  ISO-8601,
      "last_sync":      ISO-8601 | null,
      "last_status":    "ok" | "error" | null,
      "last_error":     str | null,
      "last_detail":    str | null
    }
  }

Writes are atomic (tmp + rename) and guarded by a process-wide lock.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCES_PATH = Path(os.environ.get("SOURCES_PATH", "/data/sources.json"))

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_raw() -> dict[str, dict[str, Any]]:
    if not SOURCES_PATH.exists():
        return {}
    try:
        with SOURCES_PATH.open() as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw(state: dict[str, Any]) -> None:
    SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SOURCES_PATH.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp.replace(SOURCES_PATH)


def all_records() -> dict[str, dict[str, Any]]:
    with _lock:
        return _load_raw()


def get(connector_id: str) -> dict[str, Any]:
    return all_records().get(connector_id, {})


def get_config(connector_id: str) -> dict[str, Any]:
    """Just the config dict for a connector, or {} if unset."""
    return (get(connector_id).get("config") or {}).copy()


def save_config(connector_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """Replace the config block for `connector_id`. Returns the updated record."""
    with _lock:
        state = _load_raw()
        rec = dict(state.get(connector_id) or {})
        # Strip empty strings so they don't shadow env_fallbacks later.
        clean = {k: v for k, v in (config or {}).items() if v not in (None, "")}
        rec["config"] = clean
        rec["configured_at"] = _now()
        state[connector_id] = rec
        _save_raw(state)
        return rec


def record_test(connector_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Persist the latest test_connection result."""
    with _lock:
        state = _load_raw()
        rec = dict(state.get(connector_id) or {})
        rec["last_status"] = "ok" if result.get("ok") else "error"
        rec["last_error"] = None if result.get("ok") else result.get("detail")
        rec["last_detail"] = result.get("detail")
        rec["last_tested_at"] = _now()
        state[connector_id] = rec
        _save_raw(state)
        return rec


def record_sync(connector_id: str, *, ok: bool, error: str | None = None) -> None:
    """Update last_sync and last_status after a collect() run."""
    with _lock:
        state = _load_raw()
        rec = dict(state.get(connector_id) or {})
        rec["last_sync"] = _now()
        rec["last_status"] = "ok" if ok else "error"
        if ok:
            rec["last_error"] = None
        else:
            rec["last_error"] = error
        state[connector_id] = rec
        _save_raw(state)


def delete(connector_id: str) -> bool:
    """Remove a connector's config + status. Returns True if a record existed."""
    with _lock:
        state = _load_raw()
        if connector_id not in state:
            return False
        del state[connector_id]
        _save_raw(state)
        return True
