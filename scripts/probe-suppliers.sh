#!/usr/bin/env bash
# Ask each supplier what it thinks of each crawler identity, from wherever this runs.
#
#   ./scripts/probe-suppliers.sh [--source ID] [--no-sign] [--no-db --sites FILE] ...
#
# A thin wrapper. The probe is `python -m worker.probe` (apps/ingestion/worker/probe.py),
# which builds every request with the crawler's own client (`make_client`) for
# each identity: curl is not our client — its TLS fingerprint, its HTTP/2 and its
# header order differ, Cloudflare scores those, and curl with browser headers got
# 429 where the crawler with the same headers did not. See the module docstring.
#
# On the server (a .env.prod beside this script's repo) it runs in the ingestion
# image, with the worker's key, SITE_URL, database and private configuration.
# Elsewhere it runs from apps/ingestion's virtualenv via `make probe`; set
# PROBE_LOCAL=1 to force that on the server.
#
# Run it on the server and on a laptop and compare: the same result in both
# places means the headers or the site; different results mean the egress IP.
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$here/.env.prod" ] && [ -z "${PROBE_LOCAL:-}" ]; then
  exec docker compose -f "$here/docker-compose.prod.yml" --env-file "$here/.env.prod" \
    run --rm --no-deps ingestion python -m worker.probe "$@"
fi
exec make -C "$here" probe ARGS="$*"
