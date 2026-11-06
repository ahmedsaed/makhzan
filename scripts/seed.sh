#!/usr/bin/env bash
# Initial data load / full manual refresh: scrape every enabled source, regroup
# products, rebuild the search index. Run once after the first deploy (and any
# time you want an immediate refresh instead of waiting for the daily cron).
#
#   ./scripts/seed.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Running full ingestion + reindex (this scrapes all suppliers; takes a few minutes)"
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm ingestion python -m worker.seed
