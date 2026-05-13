"""Connector framework — base class, config schema, status helpers.

A connector is a self-contained module that knows how to:
  - declare what config it needs (tokens, urls, paths) via a schema
  - test that it can reach its data source
  - produce a payload for one or more widget IDs

Dropping a new file in `backend/connectors/` is enough to make it appear in
the Sources panel — the registry auto-discovers modules that expose a
module-level `connector` instance.

Config values flow from three layers, in priority order:
  1. The persisted /data/sources.json file (set via the API/UI)
  2. The environment variable named in the field's `env_fallback`
  3. The field's `default`

This means existing env-based deployments keep working, but the user can now
override any value at runtime through the Sources panel.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# Field types the frontend understands. Anything else falls back to "string".
FIELD_TYPES = ("string", "password", "url", "path", "number", "textarea")


@dataclass(frozen=True)
class ConfigField:
    name: str                          # key in the stored config dict
    label: str                         # human label in the UI
    type: str = "string"
    required: bool = False
    help: str = ""
    placeholder: str = ""
    default: str | None = None
    env_fallback: str | None = None    # env var to read if no stored value


class Connector:
    """Subclass and set the class attrs; instantiate at module scope as
    `connector = MyConnector()` so the registry can pick it up.
    """

    id: str = ""                       # stable identifier (file-system-safe)
    name: str = ""                     # display name
    description: str = ""              # one-line blurb shown on the card
    icon: str = "●"                    # emoji or single character
    category: str = "data"             # "infra" | "data" | "personal" | "media"
    widget_ids: tuple[str, ...] = ()   # widgets this connector populates
    config_schema: tuple[ConfigField, ...] = ()

    # ─── helpers ──────────────────────────────────────────────────────────

    def resolve(self, stored: dict[str, Any] | None) -> dict[str, Any]:
        """Layer stored values over env-var fallbacks and defaults."""
        stored = stored or {}
        out: dict[str, Any] = {}
        for f in self.config_schema:
            v = stored.get(f.name)
            if v in (None, "") and f.env_fallback:
                v = os.environ.get(f.env_fallback, "")
            if v in (None, "") and f.default is not None:
                v = f.default
            out[f.name] = v
        return out

    def missing_required(self, resolved: dict[str, Any]) -> list[str]:
        return [
            f.name for f in self.config_schema
            if f.required and not str(resolved.get(f.name) or "").strip()
        ]

    def is_configured(self, stored: dict[str, Any] | None) -> bool:
        """True when all required fields have a value somewhere in the chain."""
        if not self.config_schema:
            return True
        return not self.missing_required(self.resolve(stored))

    # ─── overridable surface ──────────────────────────────────────────────

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        """Return `{ok: bool, detail: str}`. Default: configured == ok."""
        missing = self.missing_required(config)
        if missing:
            return {"ok": False, "detail": f"missing required fields: {', '.join(missing)}"}
        return {"ok": True, "detail": "configured"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        """Return `{ widget_id: payload }` for every id in self.widget_ids.

        For a single-widget connector you can `return {self.widget_ids[0]: payload}`
        — the registry merges these dicts before edition assembly.
        """
        return {}

    # ─── serialization for the API ────────────────────────────────────────

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "category": self.category,
            "widget_ids": list(self.widget_ids),
            "config_schema": [
                {
                    "name": f.name,
                    "label": f.label,
                    "type": f.type if f.type in FIELD_TYPES else "string",
                    "required": f.required,
                    "help": f.help,
                    "placeholder": f.placeholder,
                    "default": f.default,
                    "env_fallback": f.env_fallback,
                }
                for f in self.config_schema
            ],
        }


# Sentinel callable that connectors can use for "no config needed" testers.
async def always_ok(_config: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "detail": "no configuration required"}
