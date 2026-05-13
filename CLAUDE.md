# Claude context — homebase

The Daily Bhavi PWA at `homebase.lebcp.com`. FastAPI + Vite/React in a
single Podman container (`daily-bhavi`) on the Minisforum prod box.

Split out of `podman-server` on 2026-05-13 — older history lives in that
repo if you need to dig further back than this repo's initial commit.

## How code lands in prod

1. Branch + commit on the Mac.
2. Open PR for visibility, then `gh pr merge <N> --merge --delete-branch`
   immediately (PR workflow is not gating — see auto-memory
   `feedback_pr_workflow.md`).
3. `ssh bp@100.91.251.82 'cd ~/homebase/deploy && ./deploy.sh'`.

Prod only runs `origin/main`. There is no out-of-band deploy path. Do not
`ssh` to prod and edit files under `~/homebase/` — the dirty-tree guard in
`deploy.sh` will refuse to deploy on the next run.

## Where things live

| Thing | Path |
|---|---|
| Repo on the Mac | `~/Documents/homebase/` (or wherever you cloned it) |
| Repo on prod | `~/homebase/` on `bp@100.91.251.82` |
| App source | `backend/` (FastAPI) and `frontend/` (Vite/React) |
| Dockerfile | repo root |
| Compose + deploy script | `deploy/` |
| Prod `.env` (gitignored, chmod 600) | `~/homebase/deploy/.env` |
| Container data volume | `/srv/containers/homebase/` on prod |
| Service worker | `frontend/public/sw.js` |
| Host port | `8095` (cloudflared maps homebase.lebcp.com → :8095) |
| Image tag | `localhost/homebase:local` |

## Build-version / service-worker mechanism

`deploy.sh` computes `BUILD_VERSION=<short-sha>-<utc-timestamp>` and passes
it through `podman-compose build --build-arg BUILD_VERSION=...`. The
Dockerfile `sed`s the placeholder `__BUILD_VERSION__` in
`frontend/public/sw.js` and writes `/build-info.json`.

The SW cache name is `daily-bhavi-shell-<BUILD_VERSION>`. On `activate`,
old caches are deleted, so every deploy wipes the prior shell on first
load.

Never hardcode a version string in `sw.js`. If the placeholder isn't
getting substituted, fix the Dockerfile `sed` step — don't bump the string.

## Cross-repo dependencies

The container reaches Prometheus on `monitoring-net`, a Podman network
created by the `podman-server` monitoring compose stack. If you spin this
service up on a box that doesn't run the podman-server stack,
`monitoring-net` must exist first (either reuse the name as an external
network or create a stand-in).

Cloudflared on prod also lives in `podman-server` — adding/changing the
ingress hostname for `homebase.lebcp.com` is done in
`prod/cloudflared/config.yml` there, not here.

## Adding a widget / connector

See `skills/add-widget/SKILL.md` — Claude Code will auto-load it when you
ask to add a new data source, widget, or section. It walks through the
backend connector class, layout store, frontend component, WidgetGrid wire-up,
and the chat-bar/ticker plumbing.

## Things not to do

- Don't manually bump the `daily-bhavi-shell-vN` string in `sw.js`. The
  placeholder mechanism handles this on every deploy.
- Don't `sudo ./deploy.sh`. Run it as `bp` — the script `sudo`s internally
  for `podman` commands. Outer `sudo` strips the git credential helper
  that `git fetch` needs.
- Don't push to `main` directly. Branch + PR + merge, always.
- Don't deploy other services from `deploy/deploy.sh`. It only touches
  `daily-bhavi`.
