#!/usr/bin/env bash
# Build + (re)start the daily-bhavi-test container at homebase-test.lebcp.com.
#
# Usage:
#   ./deploy-test.sh                          # default: sprint-1/test-combined
#   ./deploy-test.sh <branch-or-ref>          # any pushed branch, tag, or SHA
#
# Sources from the sibling checkout at ~/homebase-test/ (auto-cloned on first
# run). That clone is independent of ~/homebase/ so we can preview unmerged
# branches without tripping the dirty-tree guard in deploy.sh.
#
# Reads secrets from ./.env.test (chmod 600, gitignored). If .env.test is
# missing, falls back to copying ./.env so the first run works out of the box.
#
# Exit codes:
#   0  deploy succeeded and /api/health responds on host port 8096
#   1  git checkout failure, build failure, missing test clone, or unhealthy
set -euo pipefail
cd "$(dirname "$0")"

BRANCH="${1:-sprint-1/test-combined}"

TEST_REPO="${HOME}/homebase-test"
PROD_REPO="$(cd "$(git rev-parse --show-toplevel)" && pwd)"
REMOTE_URL="$(cd "${PROD_REPO}" && git config --get remote.origin.url)"

if [ ! -d "${TEST_REPO}/.git" ]; then
  echo "==> Cloning ${REMOTE_URL} -> ${TEST_REPO}"
  git clone "${REMOTE_URL}" "${TEST_REPO}"
fi

echo "==> Syncing ${TEST_REPO} to origin/${BRANCH}"
(
  cd "${TEST_REPO}"
  if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: working tree at ${TEST_REPO} has local changes. Refusing." >&2
    git status --short >&2
    exit 1
  fi
  git fetch origin "${BRANCH}"
  git checkout "${BRANCH}"
  git reset --hard "origin/${BRANCH}"
)

if [ ! -f .env.test ]; then
  if [ -f .env ]; then
    echo "==> .env.test missing -- seeding from ./.env"
    cp .env .env.test
    chmod 600 .env.test
  else
    echo "ERROR: neither .env.test nor .env exists in $(pwd)." >&2
    exit 1
  fi
fi

sudo mkdir -p /srv/containers/homebase-test/data

GIT_SHA="$(cd "${TEST_REPO}" && git rev-parse --short HEAD)"
GIT_FULL_SHA="$(cd "${TEST_REPO}" && git rev-parse HEAD)"
BUILD_VERSION="${GIT_SHA}-$(date -u +%Y%m%d%H%M%S)-test"
export BUILD_VERSION

echo "==> Deploying ${BRANCH} (${GIT_FULL_SHA}) to daily-bhavi-test"
echo "    BUILD_VERSION=${BUILD_VERSION}"

echo "==> Building daily-bhavi-test"
sudo --preserve-env=BUILD_VERSION \
  podman-compose -f docker-compose.test.yml build daily-bhavi-test

echo "==> Recreating daily-bhavi-test"
sudo --preserve-env=BUILD_VERSION \
  podman-compose -f docker-compose.test.yml up -d --force-recreate daily-bhavi-test

echo "==> Waiting for health (up to 180s)"
healthy=false
for i in $(seq 1 18); do
  status=$(sudo podman inspect --format '{{.State.Health.Status}}' daily-bhavi-test 2>/dev/null || echo "missing")
  if [ "$status" = "healthy" ]; then
    echo "    healthy after ${i}0s"
    healthy=true
    break
  fi
  sleep 10
done

sudo podman ps --filter name=daily-bhavi-test --format "{{.Names}}  {{.Status}}"

if [ "$healthy" != "true" ]; then
  echo "ERROR: daily-bhavi-test did not become healthy after 180s" >&2
  echo "---- last 50 log lines ----" >&2
  sudo podman logs --tail 50 daily-bhavi-test >&2 || true
  exit 1
fi

if ! curl -sf http://localhost:8096/api/health > /dev/null; then
  echo "ERROR: http://localhost:8096/api/health did not respond after deploy" >&2
  exit 1
fi

echo "==> Test deploy OK"
echo "    branch:        ${BRANCH}"
echo "    commit:        ${GIT_FULL_SHA}"
echo "    build version: ${BUILD_VERSION}"
echo "    url:           https://homebase-test.lebcp.com"
echo "    verify:        curl -s http://localhost:8096/build-info.json"
