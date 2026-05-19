"""Quick links connector — a configurable list of *.lebcp.com shortcuts.

Storage is just JSON inside sources.json: a textarea of one link per line as
'Name | https://url | optional blurb'.
"""

from __future__ import annotations

from typing import Any

from .base import ConfigField, Connector

DEFAULT_LINKS_BLOB = (
    "Grafana | https://grafana.lebcp.com | Dashboards & drilldowns\n"
    "Airflow | https://airflow.lebcp.com | Data pipelines\n"
    "Superset | https://superset.lebcp.com | Analytics & charts\n"
    "Plex | https://plex.lebcp.com | Media library\n"
    "Requests | https://requests.lebcp.com | Overseerr request portal"
)


def _parse_links(blob: str | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in (blob or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        out.append(
            {
                "name": parts[0],
                "href": parts[1],
                "blurb": parts[2] if len(parts) > 2 else "",
            }
        )
    return out


class QuickLinksConnector(Connector):
    id = "quick_links"
    name = "Quick Links"
    description = "User-editable shortcuts to your *.lebcp.com services."
    icon = "→"
    category = "infra"
    widget_ids = ("quick_links",)
    config_schema = (
        ConfigField(
            name="links",
            label="Links",
            type="textarea",
            help="One per line: Name | https://url | optional blurb",
            placeholder=DEFAULT_LINKS_BLOB,
            default=DEFAULT_LINKS_BLOB,
        ),
    )

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        links = _parse_links(config.get("links"))
        if not links:
            return {"ok": False, "detail": "no links defined"}
        return {"ok": True, "detail": f"{len(links)} link(s) parsed"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"quick_links": {"links": _parse_links(config.get("links"))}}


connector = QuickLinksConnector()
