"""Plex + Overseerr connector — feeds the `media` widget.

The two services are bundled into one connector because the widget rendering
combines them into a single "Media" section. Either can be left blank.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import ConfigField, Connector


class PlexConnector(Connector):
    id = "plex"
    name = "Plex & Overseerr"
    description = "Recently-added items from Plex and pending Overseerr requests."
    icon = "▶"
    category = "media"
    widget_ids = ("media",)
    config_schema = (
        ConfigField(
            name="plex_url", label="Plex URL", type="url",
            placeholder="http://host.containers.internal:32400",
            default="http://host.containers.internal:32400",
            env_fallback="PLEX_URL",
        ),
        ConfigField(
            name="plex_token", label="Plex X-Plex-Token", type="password",
            help="Find this under 'Account → Authorized Devices → Show Token' in Plex.",
            env_fallback="PLEX_TOKEN",
        ),
        ConfigField(
            name="overseerr_url", label="Overseerr URL", type="url",
            placeholder="http://host.containers.internal:5055",
            default="http://host.containers.internal:5055",
            env_fallback="OVERSEERR_URL",
        ),
        ConfigField(
            name="overseerr_key", label="Overseerr API key", type="password",
            help="Optional. Generated under Settings → General.",
            env_fallback="OVERSEERR_API_KEY",
        ),
        ConfigField(
            name="timeout", label="HTTP timeout (seconds)", type="number",
            default="4.0", env_fallback="MEDIA_TIMEOUT",
        ),
    )

    def is_configured(self, stored: dict[str, Any] | None) -> bool:
        resolved = self.resolve(stored)
        # At least one of the two integrations must be wired up.
        return bool(str(resolved.get("plex_token") or "").strip()
                    or str(resolved.get("overseerr_key") or "").strip())

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        plex_url = (config.get("plex_url") or "").rstrip("/")
        plex_token = (config.get("plex_token") or "").strip()
        ovr_url = (config.get("overseerr_url") or "").rstrip("/")
        ovr_key = (config.get("overseerr_key") or "").strip()
        timeout = _to_float(config.get("timeout"), 4.0)

        details: list[str] = []
        ok_any = False
        async with httpx.AsyncClient(timeout=timeout) as client:
            if plex_token:
                try:
                    r = await client.get(f"{plex_url}/identity",
                                         params={"X-Plex-Token": plex_token})
                    if r.status_code == 200:
                        details.append("Plex ok")
                        ok_any = True
                    else:
                        details.append(f"Plex HTTP {r.status_code}")
                except Exception as e:
                    details.append(f"Plex error: {e}")
            if ovr_key:
                try:
                    r = await client.get(f"{ovr_url}/api/v1/status",
                                         headers={"X-Api-Key": ovr_key})
                    if r.status_code == 200:
                        details.append("Overseerr ok")
                        ok_any = True
                    else:
                        details.append(f"Overseerr HTTP {r.status_code}")
                except Exception as e:
                    details.append(f"Overseerr error: {e}")
        if not details:
            return {"ok": False, "detail": "neither Plex nor Overseerr is configured"}
        return {"ok": ok_any, "detail": "; ".join(details)}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        plex_url = (config.get("plex_url") or "").rstrip("/")
        plex_token = (config.get("plex_token") or "").strip()
        ovr_url = (config.get("overseerr_url") or "").rstrip("/")
        ovr_key = (config.get("overseerr_key") or "").strip()
        timeout = _to_float(config.get("timeout"), 4.0)

        recent: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            if plex_token:
                try:
                    recent = await self._plex_recent(client, plex_url, plex_token)
                except Exception as e:
                    errors.append(f"plex: {e}")
            if ovr_key:
                try:
                    pending = await self._overseerr_pending(client, ovr_url, ovr_key)
                except Exception as e:
                    errors.append(f"overseerr: {e}")

        return {"media": {
            "available": bool(recent or pending),
            "recently_added": recent,
            "pending_requests": pending,
            "errors": errors or None,
            "collected_at": now,
        }}

    async def _plex_recent(self, client: httpx.AsyncClient, url: str, token: str) -> list[dict[str, Any]]:
        r = await client.get(
            f"{url}/library/recentlyAdded",
            params={"X-Plex-Token": token, "X-Plex-Container-Size": "10"},
            headers={"Accept": "application/xml"},
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        out: list[dict[str, Any]] = []
        for item in list(root)[:10]:
            kind = item.tag
            title = item.get("title") or item.get("grandparentTitle") or "Untitled"
            if kind == "Video" and item.get("grandparentTitle"):
                title = f"{item.get('grandparentTitle')} — {item.get('title')}"
            added = item.get("addedAt")
            added_iso = None
            if added:
                try:
                    added_iso = datetime.fromtimestamp(int(added), tz=timezone.utc).isoformat()
                except (ValueError, TypeError):
                    pass
            out.append({
                "title": title,
                "type": item.get("type") or kind.lower(),
                "year": item.get("year"),
                "library": item.get("librarySectionTitle"),
                "added_at": added_iso,
            })
        return out

    async def _overseerr_pending(self, client: httpx.AsyncClient, url: str, key: str) -> list[dict[str, Any]]:
        r = await client.get(
            f"{url}/api/v1/request",
            params={"take": 6, "filter": "pending", "sort": "added"},
            headers={"X-Api-Key": key},
        )
        r.raise_for_status()
        data = r.json()
        out: list[dict[str, Any]] = []
        for req in data.get("results", [])[:6]:
            media = req.get("media", {}) or {}
            out.append({
                "id": req.get("id"),
                "type": media.get("mediaType"),
                "title": media.get("title") or media.get("name") or f"#{media.get('tmdbId')}",
                "requested_by": (req.get("requestedBy") or {}).get("displayName"),
                "status": req.get("status"),
                "created": req.get("createdAt"),
            })
        return out


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


connector = PlexConnector()
