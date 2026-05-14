#!/usr/bin/env bash
# Rewrites dev/mock-data/calendar/today.json with today's date so the
# calendar connector (which filters out non-today events) actually shows
# something during local development.
#
# Run from the repo root: ./dev/seed-mock-data.sh  (or `make dev-seed`)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TODAY="$(date +%Y-%m-%d)"
TZ_OFFSET="$(date +%z | sed -E 's/([+-][0-9]{2})([0-9]{2})/\1:\2/')"
NOW_ISO="$(date +%Y-%m-%dT%H:%M:%S)${TZ_OFFSET}"

cat > "${SCRIPT_DIR}/mock-data/calendar/today.json" <<EOF
{
  "fetched_at": "${NOW_ISO}",
  "events": [
    {
      "title": "Standup",
      "start": "${TODAY}T09:30:00${TZ_OFFSET}",
      "end":   "${TODAY}T09:45:00${TZ_OFFSET}",
      "location": "Zoom"
    },
    {
      "title": "Design review — homebase dev env",
      "start": "${TODAY}T11:00:00${TZ_OFFSET}",
      "end":   "${TODAY}T12:00:00${TZ_OFFSET}",
      "location": "Office"
    },
    {
      "title": "1:1 with manager",
      "start": "${TODAY}T15:00:00${TZ_OFFSET}",
      "end":   "${TODAY}T15:30:00${TZ_OFFSET}"
    }
  ]
}
EOF

echo "Wrote dev/mock-data/calendar/today.json with date ${TODAY}"
