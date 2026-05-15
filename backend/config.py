"""Startup environment validation.

`validate_env()` runs at app import time (see backend/app.py) and:
  - raises RuntimeError if any REQUIRED var is missing — uvicorn aborts
    before binding the port and prints a clear message about what to fix.
  - logs a warning for each OPTIONAL_INTEGRATIONS var that's missing, so
    operators can see at a glance which connectors will render as
    unavailable.

Vars with sensible code-level defaults (PROMETHEUS_URL, LAYOUT_PATH, TZ,
etc.) are deliberately not listed here — they're discoverable via
.env.example and don't merit a startup warning when unset.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("homebase.config")


REQUIRED: list[tuple[str, str, str]] = [
    (
        "ANTHROPIC_API_KEY",
        "Anthropic API key for the chat backend",
        "https://console.anthropic.com/settings/keys",
    ),
]


OPTIONAL_INTEGRATIONS: list[tuple[str, str]] = [
    ("OURA_TOKEN", "Oura connector will fall back to the OURA_SUMMARY file or render unavailable"),
    ("PLEX_TOKEN", "Plex 'recently added' will not appear in the media widget"),
    ("OVERSEERR_API_KEY", "Overseerr 'pending requests' will not appear in the media widget"),
    ("GOOGLE_CLIENT_ID", "Gmail + Google Calendar connectors will be unavailable; /api/auth/google/login returns 503"),
    (
        "GOOGLE_CLIENT_SECRET",
        "Gmail + Google Calendar connectors will be unavailable; /api/auth/google/login returns 503",
    ),
]


def validate_env() -> None:
    missing = [(name, desc, hint) for name, desc, hint in REQUIRED if not os.environ.get(name, "").strip()]

    if missing:
        lines = ["", "homebase: required environment variables are missing:"]
        for name, desc, hint in missing:
            lines.append(f"  - {name}: {desc}")
            lines.append(f"    where to get it: {hint}")
        lines.append("")
        lines.append("Set them in .env (see .env.example) and restart.")
        raise RuntimeError("\n".join(lines))

    for name, consequence in OPTIONAL_INTEGRATIONS:
        if not os.environ.get(name, "").strip():
            log.warning("%s not set — %s", name, consequence)
