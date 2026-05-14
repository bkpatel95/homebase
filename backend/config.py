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
    ("GMAIL_CREDENTIALS_PATH", "Gmail connector will render unavailable until /api/gmail/auth is run"),
]


def _is_dev_mode() -> bool:
    # Only ENV=production is treated as strict. Everything else (development,
    # dev, test, unset) is dev-permissive: missing REQUIRED vars log a
    # warning instead of crashing app startup. Prod's deploy/compose.yml
    # pins ENV=production, so prod behavior is unchanged.
    env = (os.environ.get("ENV") or os.environ.get("HOMEBASE_ENV") or "").strip().lower()
    return env != "production"


def validate_env() -> None:
    missing = [(name, desc, hint) for name, desc, hint in REQUIRED if not os.environ.get(name, "").strip()]

    if missing:
        lines = ["", "homebase: required environment variables are missing:"]
        for name, desc, hint in missing:
            lines.append(f"  - {name}: {desc}")
            lines.append(f"    where to get it: {hint}")
        lines.append("")
        lines.append("Set them in .env (see .env.example) and restart.")
        message = "\n".join(lines)

        if _is_dev_mode():
            log.warning("%s\n(dev mode: continuing — affected features will return 503)", message)
        else:
            raise RuntimeError(message)

    for name, consequence in OPTIONAL_INTEGRATIONS:
        if not os.environ.get(name, "").strip():
            log.warning("%s not set — %s", name, consequence)
