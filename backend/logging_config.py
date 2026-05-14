"""Logging configuration.

Two formats:
  - "json"  → one JSON object per line, suitable for log aggregators
  - "text"  → human-readable, used for local dev

Choose via LOG_FORMAT env var. Default: json when ENV=production, text otherwise.

Structured fields can be attached by passing `extra={"fields": {...}}` to any
log call; the JSON formatter merges them into the top-level object.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, default=str)


def _resolve_format() -> str:
    fmt = os.environ.get("LOG_FORMAT", "").strip().lower()
    if fmt in ("json", "text"):
        return fmt
    env = os.environ.get("ENV", "production").strip().lower()
    return "json" if env in ("production", "prod") else "text"


_configured = False


def configure_logging() -> None:
    """Idempotent — uvicorn imports the app module multiple times in --reload."""
    global _configured
    if _configured:
        return
    _configured = True

    fmt = _resolve_format()
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s — %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Uvicorn's access log duplicates our request middleware — silence it.
    logging.getLogger("uvicorn.access").handlers = [handler]
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").handlers = [handler]
