---
name: add-widget
description: Scaffold a new connector + widget pair for The Daily Bhavi newspaper dashboard. Use when the user asks to add a new data source, widget, section, or panel to homebase / the dashboard / the newspaper. Walks through the edits needed to wire a widget end-to-end (backend connector class, layout store, frontend component, WidgetGrid, optional chat-bar/ticker plumbing) and the PR + deploy.sh flow.
---

# add-widget — wire a new section into The Daily Bhavi

There is **one** data path in this app: a connector populates a payload, the edition router merges every connector's payload into the widgets dict, and a React component renders it. Adding a widget means writing a connector class, registering its widget id in the layout store, and wiring up the frontend component.

> **Naming convention.** Pick a `<widget_id>` (snake_case, e.g. `weather`, `news_brief`, `package_tracker`). The matching React component is PascalCase (`Weather`, `NewsBrief`, `PackageTracker`). The connector's `id` is usually the source name (e.g. `openweather`) and can differ from the widget id when one source feeds multiple widgets (the `prometheus` connector feeds both `infrastructure` and `system_metrics`).

## The actual architecture

The data path is connector → edition → widget. There is no parallel system.

- **Connectors are class-based.** Each file under `backend/connectors/` defines a subclass of `Connector` (from `connectors/base.py`) and instantiates it at module scope as `connector = MyConnector()`.
- **Connectors auto-register.** `connectors/__init__.py` walks the package at import time, picks up anything with a module-level `connector` attribute, and adds it to the registry. No edits to `edition.py` are needed to wire a connector in — drop the file, restart, and it appears in the edition payload and in `/api/sources`.
- **A connector can feed multiple widgets** by declaring `widget_ids = ("a", "b")` and returning `{"a": {...}, "b": {...}}` from `collect()`. First connector to claim a widget id wins.
- **Config flows through a three-layer schema.** Stored config (`/data/sources.json`, set via the Sources panel) → env-var fallback → field default. Define the schema with `ConfigField` so the UI can render the form and `is_configured()` can decide whether to render the connector's widgets.
- **The Sources panel** (gear in the masthead) lists every connector, shows its `status`, and lets the user fill in the config form, run `test_connection()`, or clear stored config.
- **Visibility** is driven by the `available: true` flag in the widget payload + the layout-store priority list + chat-bar overrides.
- **Deploy** is PR-to-main + `~/homebase/deploy/deploy.sh` on the prod host (the script fetches origin/main and rebuilds with a unique `BUILD_VERSION`).

## Step 1 — Write the connector

Create `backend/connectors/<connector_id>.py`. The shape every connector must satisfy:

- Subclass `Connector` from `.base`. Set `id`, `name`, `description`, `icon`, `category`, `widget_ids`, and `config_schema` as class attributes.
- Implement `async def collect(self, config) -> dict`. It must return `{widget_id: payload, ...}` for every id in `self.widget_ids`. Each payload should have at least `available: bool`. A `collected_at` ISO-8601 UTC string is conventional but not required.
- Implement `async def test_connection(self, config) -> dict` returning `{ok: bool, detail: str}`. The base class' default works for connectors whose only requirement is "all required fields are set", but if you can do a real upstream ping (e.g. one HTTP call), do.
- **Never raise from `collect()`.** The registry wraps every connector in `_safe_collect`, so a raise won't crash `/api/edition` — but it will mark `last_status: "error"` for the source and surface `{available: False, error: ...}` on every widget the connector claims. Returning `{available: False, reason: "..."}` for expected unconfigured/empty states is cleaner than raising.
- **HTTP timeouts are mandatory.** Default httpx timeouts are mostly fine if you set 4–6s; expose a `timeout` `ConfigField` with an `env_fallback` so it can be tuned without a deploy (see `markets.py`, `oura.py`).
- **Env-driven defaults still work.** Set `env_fallback="<NAME>"` on each `ConfigField` and existing env-based deployments keep going. The user can later override any value through the Sources panel.

Template — `backend/connectors/<connector_id>.py`:

```python
"""<One-line summary>.

<One paragraph: what this fetches, from where, and what the fallback is if the
upstream source is unavailable. Always returns a payload — the `available` flag
tells the frontend whether to render or collapse.>
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .base import ConfigField, Connector


class <Name>Connector(Connector):
    id = "<connector_id>"
    name = "<Display Name>"
    description = "<One-line blurb shown on the Sources card.>"
    icon = "●"               # emoji or single character
    category = "data"        # "infra" | "data" | "personal" | "media"
    widget_ids = ("<widget_id>",)
    config_schema = (
        ConfigField(
            name="token", label="API token", type="password",
            required=True,
            help="Generate at <wherever>.",
            env_fallback="<WIDGET_ID>_TOKEN",
        ),
        ConfigField(
            name="timeout", label="HTTP timeout (seconds)", type="number",
            default="5.0", env_fallback="<WIDGET_ID>_TIMEOUT",
        ),
    )

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        token = (config.get("token") or "").strip()
        if not token:
            return {"ok": False, "detail": "no token configured"}
        timeout = _to_float(config.get("timeout"), 5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(
                    "https://api.example.com/v1/ping",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if r.status_code == 200:
                return {"ok": True, "detail": "API authenticated"}
            return {"ok": False, "detail": f"API HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        token = (config.get("token") or "").strip()
        timeout = _to_float(config.get("timeout"), 5.0)

        if not token:
            return {"<widget_id>": {
                "available": False,
                "reason": "No token set — configure in the Sources panel.",
                "collected_at": now,
            }}

        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                "https://api.example.com/v1/<endpoint>",
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            payload = r.json()

        # Map upstream JSON → flat fields the frontend expects.
        return {"<widget_id>": {
            "available": True,
            "source": "<connector_id>-api",
            # ... widget-specific fields ...
            "collected_at": now,
        }}


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


connector = <Name>Connector()      # ← registry picks this up at import time
```

**File-backed variant.** Several real connectors (`oura.py`, `calendar.py`, `nutrition.py`) read from a JSON/markdown directory under `/data/` instead of (or as a fallback for) an API. The volume is mounted from `/srv/containers/homebase/...` on prod. Use this pattern when the data comes from a Mac-side syncer or the user dropping files. Declare a `path` `ConfigField` of `type="path"` and override `is_configured()` if "file exists" is the configured signal (see `oura.py` for the both-token-or-file pattern).

If you add a new mount path, update `deploy/docker-compose.yml` `volumes:` and create the host dir under `/srv/containers/homebase/<dir>/`.

## Step 2 — Register the widget id in the layout store

Edit `backend/layout_store.py`:

1. Append `<widget_id>` to the `ALL_WIDGETS` list. This list is the source of truth for which widget ids are valid — chat-bar tool schemas, layout validation, and the `update_layout` enum all key off it.
2. Add `<widget_id>` to each of the three `MOOD_PRIORITY` lists (`morning`, `midday`, `evening`) at whatever position makes sense for that time of day. Higher up = appears earlier in the broadsheet. If you skip a mood the widget will be invisible during that part of the day until the user pins it via the chat bar.

The nine widgets distribute 3-3-3 across the three columns by `_three_columns()` (it interleaves: position 0 → col 0 top, 1 → col 1 top, 2 → col 2 top, 3 → col 0 row 2, …). To put a new widget at the top of column 2 in the morning, drop it at index 1 in `MOOD_PRIORITY["morning"]`.

> **You do not edit `edition.py`.** The registry auto-discovers your connector and `collect_all()` includes it in the payload. The edition router only needs `ALWAYS_AVAILABLE` updated if your widget should render even when its connector reports `available: false` (e.g. it has a static fallback like `quick_links`). Otherwise leave it out — the layout collapses unavailable widgets automatically.

## Step 3 — Build the widget component

Create `frontend/src/components/widgets/<Name>.jsx`. Every widget:

- Default-exports a function component named `<Name>` taking a single `{ data }` prop. `data` is whatever the connector returned for `widget_ids[i]`.
- Returns `null` (or a `<Skeleton />`) when `!data?.available` — the layout collapses gracefully because `WidgetGrid` renders whatever the component returns.
- Wraps everything in a top-level `<section>` (the broadsheet column gives it the gap spacing).
- Uses the newspaper CSS primitives, not arbitrary Tailwind. The vocabulary:
  - `section-eyebrow` — small uppercase kicker (e.g. "Markets & Finance")
  - `headline` — Playfair Display, used for the section title and any inline headlines
  - `rule-after` — adds a thick horizontal rule under the header block
  - `rule-thin` / `rule-thick` — border colors for separators
  - `body-serif` — Georgia paragraph copy
  - `byline` — small italic footer line ("Filed from …")
  - `meta-sans` — small uppercase tracked metadata
  - `data-num` — tabular numeric display
  - `bg-paperdark` — the warmer cream tint used for inset cards
  - `dropcap` — first-letter drop cap (use sparingly, mostly the lead story)

Colors are CSS variables in `frontend/src/newspaper.css`: `--paper`, `--paper-dark`, `--ink`, `--ink-soft`, `--rule`, `--rule-thick`, `--accent` (oxblood `#8a2a1f`). Don't introduce new accent colors unless the widget genuinely needs one.

Template — `frontend/src/components/widgets/<Name>.jsx`:

```jsx
import React from 'react';

export default function <Name>({ data }) {
  if (!data?.available) return null;

  return (
    <section>
      <header className="rule-after mb-3">
        <div className="section-eyebrow"><Section eyebrow, e.g. "The Forecast"></div>
        <h3 className="headline text-[1.35rem] mt-1"><Section title, e.g. "Today's Weather"></h3>
      </header>

      {/* Body: cards, lists, metric grids — see HealthWellness.jsx for a
          MetricBox grid; Calendar.jsx for a colored-rail list; Markets.jsx
          for a tabular row layout; QuickLinks.jsx for a divider list. */}

      <p className="byline mt-3">
        Filed from <source> · {data.source || 'cached'}
      </p>
    </section>
  );
}
```

For multi-state widgets (loading skeleton + expanded/collapsed states) crib from `InfraHealth.jsx`. For grid-of-metrics widgets crib from `HealthWellness.jsx`'s `MetricBox`.

## Step 4 — Register the component in WidgetGrid

Edit `frontend/src/components/WidgetGrid.jsx`:

1. Add the import alongside the others at the top: `import <Name> from './widgets/<Name>.jsx';`
2. Add an entry to the `COMPONENT_FOR` map. The **key must match** the `<widget_id>` used in the connector's `widget_ids` and in `layout_store.ALL_WIDGETS`:
   ```js
   <widget_id>: (w) => <<Name> data={w.<widget_id>} />,
   ```

That's it for the basic widget. The component will now render in the position dictated by `layout_store.MOOD_PRIORITY` whenever the connector reports `available: true`.

## Step 5 (optional) — Make the widget queryable from the chat bar

The chat-bar's `query_data` tool's `source` enum is **auto-built from the registry** in `backend/chat/tools.py::_query_data_sources()` — it includes every widget id any connector claims. As long as your connector declares the widget id in `widget_ids`, the chat bar can already query it via `connectors.collect_widget(widget_id)`. No code edits needed.

If the widget needs special compaction before being handed back to Claude (e.g. trimming a long container list — see how `infrastructure` and `markets` are sliced in `_execute_query_data`), add an `if source == "<widget_id>": data = {...}` branch there.

Add a `pretty()` mapping entry at the bottom of `tools.py` so layout-change confirmations read nicely (e.g. `"news_brief": "News Brief"`).

The `update_layout` tool's `widget` enum is sourced directly from `layout_store.ALL_WIDGETS`, so step 2 already makes the widget addressable for `move`/`hide`/`show` — no separate edit needed.

## Step 6 (optional) — Ticker support

If you want the widget to appear in the ticker bar under the masthead, edit `backend/routers/edition.py`:

1. Add a `key` for it (e.g. `"weather"`) and an `elif key == "weather": ...` branch in `_ticker_item()`. Return `{label, value, suffix, status}` where `status` is `ok | warn | bad | idle`.
2. Add the key to `DEFAULT_TICKER_ITEMS` in `backend/layout_store.py` if it should be on by default. If not, the user can still surface it via the chat bar.
3. Add the key to the `enum` in the `update_ticker` tool in `backend/chat/tools.py` so the chat bar knows it's valid.

## Step 7 — Test locally before deploying

Backend smoke test (from the repo root):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
# Set whatever env vars the connector needs (or leave them and configure via the Sources panel):
export <WIDGET_ID>_TOKEN=...
uvicorn backend.app:app --host 127.0.0.1 --port 8095 --reload
```

Then in another shell:

```bash
# Confirm the connector registered:
curl -s http://127.0.0.1:8095/api/sources | jq '.sources[] | {id, status, widgets: .widget_ids}'

# Run a connectivity check against the upstream:
curl -s -XPOST http://127.0.0.1:8095/api/sources/<connector_id>/test | jq

# Confirm the widget id appears in the compiled edition and is available:
curl -s http://127.0.0.1:8095/api/edition | jq '.widgets | keys'
curl -s http://127.0.0.1:8095/api/edition | jq '.widgets.<widget_id>'
curl -s http://127.0.0.1:8095/api/edition | jq '.layout.visible'   # should include <widget_id>
```

Frontend dev (from `frontend/` in the repo root):

```bash
npm install
VITE_API_BASE=http://127.0.0.1:8095 npm run dev
```

Open the printed URL and confirm:
- The widget renders in its assigned column at the assigned mood.
- It collapses (renders nothing, layout reflows) when the connector reports `available: false` — clear the stored config via the Sources panel or yank the upstream to confirm.
- The Sources panel (gear icon) lists the new connector with the right status and config form.
- The chat bar can "hide \<widget>" / "show \<widget>" / "move \<widget> to position 0" out of the box, and "how's my \<widget>" works via `query_data`.

For the **container build** (closer to prod):

```bash
cd deploy
podman-compose up --build -d
podman logs -f daily-bhavi
curl -s http://localhost:8095/api/edition | jq '.widgets.<widget_id>'
```

## Step 8 — Deploy to prod

Prod is the Minisforum at Tailscale IP `100.91.251.82` (user `bp`). The repo lives at `~/homebase/` on the server. The container is built from the repo root via `~/homebase/deploy/docker-compose.yml`.

**1. Branch, PR, merge to main.** Prod's `deploy.sh` only ever deploys `origin/main`:

```bash
git checkout -b claude/<short-description>
# … your edits …
git commit -am "…"
git push -u origin HEAD
gh pr create --title "…" --body "…"
gh pr merge <N> --merge --delete-branch
```

**2. Run deploy.sh on prod** (as `bp` — the script `sudo`s internally for podman; outer `sudo` would strip the git credential helper that `git fetch` needs):

```bash
ssh bp@100.91.251.82 'cd ~/homebase/deploy && ./deploy.sh'
```

`deploy.sh` fetches origin/main, builds with a unique `BUILD_VERSION`, recreates the container, polls health for 180s, and verifies `/api/health` on the host port.

**3. Verify on prod:**

```bash
ssh bp@100.91.251.82 'sudo podman ps --filter name=daily-bhavi'
ssh bp@100.91.251.82 'sudo podman logs --tail 50 daily-bhavi'
ssh bp@100.91.251.82 'curl -s http://localhost:8095/build-info.json'   # must match the deployed SHA
# Hit the live URL once Cloudflare picks up the new container:
curl -s https://homebase.lebcp.com/api/health     # 403 unless you have a CF Access session; logs are the better signal
```

Then visit `https://homebase.lebcp.com` and confirm the new section is on the page (and the new connector card is on the Sources panel).

## Common pitfalls

- **Widget never appears.** 95% of the time you forgot one of: adding it to `WidgetGrid.COMPONENT_FOR`, adding it to `MOOD_PRIORITY` for the current time of day, or returning `available: true`. Curl `/api/edition` and check both `widgets.<id>.available` and `layout.visible`.
- **Connector imports but doesn't show up in `/api/sources`.** Either you forgot the module-level `connector = <Name>Connector()`, or you set `id = ""`, or two connectors are claiming the same `id` (the registry keeps the first and logs a warning). Check `daily-bhavi` logs for `registered connector:` lines and duplicate-id warnings.
- **Edition shows `{available: False, error: "..."}` for every widget the connector claims.** The connector raised. The registry catches it and stamps the error onto each widget — check the source's `last_error` in `/api/sources` and the container logs for the traceback.
- **Stale layout pinned.** `layout_store` persists `priority` and `hidden` overrides to `/data/layout.json`. If you renamed a widget id mid-development, old pinned state may reference a dead id — clear it with `curl -X POST http://localhost:8095/api/layout/reset` (or via the chat bar: "reset layout").
- **Prod build cache stale.** `podman-compose up -d --build --force-recreate` rebuilds the image and recreates the container. If you only ran `up -d` after rsyncing, the old image still runs. Watch the build output for the `COPY backend` line to confirm your changes shipped.
- **Env var added but not surfacing.** If you used an `env_fallback` on a `ConfigField`, the container needs to actually see the var. `deploy/docker-compose.yml` only forwards env vars listed under `environment:`. Add it there (with a `${VAR:-}` default so a missing var doesn't break the compose file), then set the value in `~/homebase/deploy/.env` on prod. The user can also bypass env entirely by entering the value in the Sources panel.

## End-to-end recap

To add a "Weather" widget you would edit, in order:

1. `backend/connectors/openweather.py` — new file, defines `OpenWeatherConnector` with `widget_ids = ("weather",)` and a module-level `connector = OpenWeatherConnector()`.
2. `backend/layout_store.py` — append `"weather"` to `ALL_WIDGETS` + each `MOOD_PRIORITY` list.
3. `frontend/src/components/widgets/Weather.jsx` — new file.
4. `frontend/src/components/WidgetGrid.jsx` — import + add to `COMPONENT_FOR`.
5. (optional) `backend/chat/tools.py` — add to `pretty()`; add an `if source == "weather"` compaction branch in `_execute_query_data` only if the payload is too big.
6. (optional) `backend/routers/edition.py` `_ticker_item()` + `layout_store.DEFAULT_TICKER_ITEMS` + `update_ticker` enum in chat tools.
7. (if it needs config) `deploy/docker-compose.yml` — add env var to `environment:` block (only needed if you set an `env_fallback`).

Then PR → merge to main → `ssh bp@100.91.251.82 'cd ~/homebase/deploy && ./deploy.sh'`. Done.
