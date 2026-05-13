#!/bin/bash
set -e

# Forward signals so podman can stop us cleanly.
shutdown() {
  nginx -s quit 2>/dev/null || true
  kill -TERM "$UVICORN_PID" 2>/dev/null || true
  wait
  exit 0
}
trap shutdown TERM INT

# Start nginx in the foreground reactor, daemonless.
nginx -g 'daemon off;' &
NGINX_PID=$!

# Run uvicorn in the foreground — if it dies, the container dies.
uvicorn backend.app:app \
  --host 127.0.0.1 --port 8096 \
  --proxy-headers --forwarded-allow-ips='*' &
UVICORN_PID=$!

# Wait for either to exit (bash supports -n)
wait -n "$NGINX_PID" "$UVICORN_PID"
EXIT=$?
shutdown
exit $EXIT
