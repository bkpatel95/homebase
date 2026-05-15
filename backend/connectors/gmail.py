"""Gmail connector — unread inbox snapshot via the Gmail REST API.

Auth flows through the shared `backend.google_oauth` token store. There
is no per-connector token field: once the operator completes the
/api/auth/google/login flow once, Gmail + Calendar both see the same
credentials.

Payload (shape, not contract):
    {
      "gmail": {
        "available": bool,
        "unread_total": int,           # Gmail's threadsUnread for INBOX
        "unread_preview": [            # up to MAX_PREVIEW recent unread
          {"from": "...", "subject": "...", "snippet": "...", "received_at": "..."}
        ],
        "email": "you@gmail.com",
        "collected_at": ISO-8601,
      }
    }
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from .. import google_oauth
from .base import ConfigField, Connector

log = logging.getLogger("homebase.connectors.gmail")

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_PREVIEW = 5  # how many unread messages to fetch metadata for


def _now() -> str:
    return datetime.now(UTC).isoformat()


class GmailConnector(Connector):
    id = "gmail"
    name = "Gmail"
    description = "Unread inbox count + recent unread message previews via Google OAuth."
    icon = "✉"
    category = "personal"
    widget_ids = ("gmail",)
    # No per-connector secrets — auth lives in the shared OAuth token store.
    # We expose timeout + max_preview so they can be tuned without code edits.
    config_schema = (
        ConfigField(
            name="timeout",
            label="HTTP timeout (seconds)",
            type="number",
            default="5.0",
            env_fallback="GMAIL_TIMEOUT",
        ),
        ConfigField(
            name="max_preview",
            label="Max unread previews",
            type="number",
            default=str(MAX_PREVIEW),
            env_fallback="GMAIL_MAX_PREVIEW",
        ),
        ConfigField(
            name="query",
            label="Gmail search query",
            type="string",
            help="Gmail q= query for the preview list. Default: in:inbox is:unread",
            default="in:inbox is:unread",
            env_fallback="GMAIL_QUERY",
        ),
    )

    def is_configured(self, stored: dict[str, Any] | None) -> bool:
        """Configured when the shared OAuth client is set up *and* the user
        has connected. The per-connector config is all optional."""
        return google_oauth.is_configured() and google_oauth.is_connected()

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        if not google_oauth.is_configured():
            return {
                "ok": False,
                "detail": "Google OAuth not configured on the server. "
                "Set GOOGLE_CLIENT_ID/SECRET — see docs/google-oauth-setup.md.",
            }
        if not google_oauth.is_connected():
            return {"ok": False, "detail": "not connected — visit /api/auth/google/login"}
        try:
            token = await google_oauth.get_access_token()
        except google_oauth.GoogleOAuthError as e:
            return {"ok": False, "detail": str(e)}

        timeout = _to_float(config.get("timeout"), 5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(
                    f"{GMAIL_API}/labels/INBOX",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if r.status_code == 200:
                label = r.json()
                return {
                    "ok": True,
                    "detail": f"INBOX has {label.get('threadsUnread', 0)} unread threads",
                }
            return {"ok": False, "detail": f"Gmail API HTTP {r.status_code}: {r.text[:160]}"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        if not google_oauth.is_configured():
            return {
                "gmail": {
                    "available": False,
                    "reason": "Google OAuth not configured on the server.",
                    "unread_total": 0,
                    "unread_preview": [],
                    "collected_at": now,
                }
            }
        if not google_oauth.is_connected():
            return {
                "gmail": {
                    "available": False,
                    "reason": "Google account not connected. Visit /api/auth/google/login.",
                    "unread_total": 0,
                    "unread_preview": [],
                    "collected_at": now,
                }
            }

        try:
            token = await google_oauth.get_access_token()
        except google_oauth.GoogleOAuthError as e:
            return {
                "gmail": {
                    "available": False,
                    "error": str(e),
                    "unread_total": 0,
                    "unread_preview": [],
                    "collected_at": now,
                }
            }

        timeout = _to_float(config.get("timeout"), 5.0)
        max_preview = max(0, _to_int(config.get("max_preview"), MAX_PREVIEW))
        query = (config.get("query") or "in:inbox is:unread").strip() or "in:inbox is:unread"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                headers = {"Authorization": f"Bearer {token}"}
                label_r = await client.get(f"{GMAIL_API}/labels/INBOX", headers=headers)
                label_r.raise_for_status()
                unread_total = int(label_r.json().get("threadsUnread", 0))

                previews: list[dict[str, Any]] = []
                if max_preview > 0 and unread_total > 0:
                    list_r = await client.get(
                        f"{GMAIL_API}/messages",
                        headers=headers,
                        params={"q": query, "maxResults": max_preview},
                    )
                    list_r.raise_for_status()
                    msg_ids = [m["id"] for m in list_r.json().get("messages", [])]

                    # Fan out the per-message fetches — these tend to be the
                    # slow part of the call. Two or three serial requests over
                    # HTTPS to Google would cost 200-400ms; running them
                    # together stays under the timeout for typical inboxes.
                    import asyncio

                    detail_responses = await asyncio.gather(
                        *(
                            client.get(
                                f"{GMAIL_API}/messages/{mid}",
                                headers=headers,
                                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                            )
                            for mid in msg_ids
                        ),
                        return_exceptions=True,
                    )
                    for resp in detail_responses:
                        if isinstance(resp, Exception):
                            continue
                        if resp.status_code != 200:
                            continue
                        previews.append(_summarize_message(resp.json()))
        except httpx.HTTPStatusError as e:
            return {
                "gmail": {
                    "available": False,
                    "error": f"Gmail HTTP {e.response.status_code}: {e.response.text[:160]}",
                    "unread_total": 0,
                    "unread_preview": [],
                    "collected_at": now,
                }
            }
        except Exception as e:
            return {
                "gmail": {
                    "available": False,
                    "error": f"{type(e).__name__}: {e}",
                    "unread_total": 0,
                    "unread_preview": [],
                    "collected_at": now,
                }
            }

        info = google_oauth.connection_info()
        return {
            "gmail": {
                "available": True,
                "unread_total": unread_total,
                "unread_preview": previews,
                "email": info.get("email"),
                "collected_at": now,
            }
        }


def _summarize_message(msg: dict[str, Any]) -> dict[str, Any]:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {
        "from": headers.get("from", ""),
        "subject": headers.get("subject", "(no subject)"),
        "snippet": msg.get("snippet", ""),
        "received_at": headers.get("date", ""),
    }


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v: Any, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


connector = GmailConnector()
