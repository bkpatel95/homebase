#!/usr/bin/env bash
# Build + (re)start daily-bhavi. Secrets come from ./.env via env_file in
# docker-compose.yml, so they are NOT echoed in podman-compose output.
#
# Sources the homebase code from main on GitHub. Every deploy syncs to main
# first, so prod always runs what is merged in GitHub.
#
# Exit codes:
#   0  deploy succeeded and /api/health responds
#   1  dirty working tree, git sync failure, build failure, or unhealthy after timeout
set -euo pipefail
cd "$(dirname "$0")"

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "==> Checking working tree is clean"
(
  cd "$REPO_ROOT"
  if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: working tree at $REPO_ROOT has local changes. Refusing to deploy." >&2
    git status --short >&2
    exit 1
  fi
)

echo "==> Syncing repo to origin/main"
(
  cd "$REPO_ROOT"
  git fetch origin main
  git checkout main
  git pull --ff-only origin main
)

GIT_SHA="$(cd "$REPO_ROOT" && git rev-parse --short HEAD)"
GIT_FULL_SHA="$(cd "$REPO_ROOT" && git rev-parse HEAD)"
BUILD_VERSION="${GIT_SHA}-$(date -u +%Y%m%d%H%M%S)"
export BUILD_VERSION

echo "==> Deploying ${GIT_FULL_SHA}"
echo "    BUILD_VERSION=${BUILD_VERSION}"

echo "==> Building daily-bhavi"
sudo --preserve-env=BUILD_VERSION podman-compose build daily-bhavi

echo "==> Recreating daily-bhavi"
sudo --preserve-env=BUILD_VERSION podman-compose up -d --force-recreate daily-bhavi

echo "==> Waiting for health (up to 180s)"
healthy=false
for i in $(seq 1 18); do
  status=$(sudo podman inspect --format '{{.State.Health.Status}}' daily-bhavi 2>/dev/null || echo "missing")
  if [ "$status" = "healthy" ]; then
    echo "    healthy after ${i}0s"
    healthy=true
    break
  fi
  sleep 10
done

sudo podman ps --filter name=daily-bhavi --format "{{.Names}}  {{.Status}}"

if [ "$healthy" != "true" ]; then
  echo "ERROR: daily-bhavi did not become healthy after 180s" >&2
  echo "---- last 50 log lines ----" >&2
  sudo podman logs --tail 50 daily-bhavi >&2 || true
  exit 1
fi

# Sanity-check the host port too — the in-container healthcheck doesn't prove
# nginx is reachable from the host.
if ! curl -sf http://localhost:8095/api/health > /dev/null; then
  echo "ERROR: http://localhost:8095/api/health did not respond after deploy" >&2
  exit 1
fi

echo "==> Deploy OK"
echo "    commit:        ${GIT_FULL_SHA}"
echo "    build version: ${BUILD_VERSION}"
echo "    verify:        curl -s http://localhost:8095/build-info.json"
