# homebase

The Daily Bhavi — a personal newspaper PWA at `homebase.lebcp.com`.

A FastAPI backend + Vite/React frontend, served by a single Podman container
(`daily-bhavi`) on the Minisforum prod box. Pulls live data from connectors
(Plex, Overseerr, Oura, calendar, markets, Prometheus, etc.) and renders it
as a three-column newspaper with a chat bar that can edit the layout.

Split out of [`podman-server`](https://github.com/bkpatel95/podman-server)
on 2026-05-13. Older history lives there.

## Layout

```
backend/        FastAPI app — routers, connectors, chat tools
frontend/       Vite/React SPA — components, widgets, hooks
Dockerfile      Multi-stage build: node → python+nginx single image
nginx.conf      Serves /api/* → uvicorn:8096, everything else → /var/www
start.sh        Container entrypoint: nginx + uvicorn under tini
deploy/         docker-compose.yml + deploy.sh used on the Minisforum
skills/         Claude Code skills scoped to this repo (e.g. add-widget)
```

## Develop

Backend (from `backend/`):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --reload --port 8096
```

Frontend (from `frontend/`):

```bash
npm install
npm run dev          # vite at :5173, proxies /api → :8096
```

## Deploy

Auto-deploy is git-driven: prod runs whatever is on `origin/main`.

```bash
ssh bp@100.91.251.82 'cd ~/homebase/deploy && ./deploy.sh'
```

`deploy.sh`:
1. Refuses if the prod working tree is dirty.
2. `git fetch + checkout main + pull --ff-only origin main`.
3. Computes `BUILD_VERSION=<short-sha>-<utc-timestamp>` and exports it.
4. Builds + recreates `daily-bhavi` via `podman-compose`.
5. Polls health for 180s, curls `/api/health`, exits non-zero on failure.

The `BUILD_VERSION` arg flows into the Dockerfile, which stamps it into
`sw.js` so the service worker cache key rotates on every deploy.

## Prod paths

| Thing | Path |
|---|---|
| Repo on prod | `~/homebase/` (Tailscale IP `100.91.251.82`, user `bp`) |
| `.env` (gitignored, chmod 600) | `~/homebase/deploy/.env` |
| Container data volume | `/srv/containers/homebase/` |
| Host port | `8095` (cloudflared maps homebase.lebcp.com → :8095) |
| Image tag | `localhost/homebase:local` |

## Service worker / cache

App-shell cache name: `daily-bhavi-shell-<BUILD_VERSION>`. The activate
handler deletes any cache whose name doesn't match the new one, so every
deploy invalidates the prior shell. Nginx serves `/sw.js` with
`Cache-Control: no-cache`, so browsers always re-fetch it.

If a deploy isn't showing in the browser:

```bash
curl http://localhost:8095/build-info.json     # confirm server has the new SHA
curl http://localhost:8095/sw.js | grep CACHE  # confirm new BUILD_VERSION
```

If the server is right but the client is stale: hard-refresh (Cmd+Shift+R),
or DevTools → Application → Service Workers → Unregister.
