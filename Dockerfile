# syntax=docker/dockerfile:1.6

# ─── Stage 1: build the React SPA ────────────────────────────────────────────
FROM docker.io/library/node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ─── Stage 2: Python runtime with FastAPI + nginx in one container ───────────
FROM docker.io/library/python:3.12-slim AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx curl tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY --from=frontend /build/dist /var/www/daily-bhavi
COPY nginx.conf /etc/nginx/nginx.conf
COPY start.sh /usr/local/bin/start.sh

# Stamp the build version into sw.js so the service-worker cache key changes
# on every deploy. Without this, browsers keep serving the old app shell from
# the previously-named cache. deploy.sh passes a git-sha + timestamp string.
ARG BUILD_VERSION=dev
ENV BUILD_VERSION=${BUILD_VERSION}
RUN sed -i "s/__BUILD_VERSION__/${BUILD_VERSION}/g" /var/www/daily-bhavi/sw.js \
 && echo "{\"version\":\"${BUILD_VERSION}\"}" > /var/www/daily-bhavi/build-info.json

RUN chmod +x /usr/local/bin/start.sh \
 && mkdir -p /data /data/health-data \
 && rm -f /etc/nginx/sites-enabled/default

EXPOSE 8095

ENV PYTHONUNBUFFERED=1 \
    PROMETHEUS_URL=http://host.containers.internal:9090 \
    PROD_HEALTH_JSON=/data/health-data/prod-health.json \
    LAYOUT_PATH=/data/layout.json \
    REQUIRE_AUTH=true

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -sf http://localhost:8095/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/start.sh"]
