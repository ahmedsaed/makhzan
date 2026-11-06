#!/usr/bin/env bash
# Dump the production Postgres database to ./backups/ (gzipped, timestamped).
# Cron-friendly:  0 2 * * *  ~/Documents/Projects/makhzan/scripts/backup-db.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Load POSTGRES_USER / POSTGRES_DB (and everything else) from .env.prod.
set -a; . ./.env.prod; set +a

mkdir -p backups
ts="$(date +%Y%m%d-%H%M%S)"
out="backups/makhzan-${ts}.sql.gz"

docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$out"

echo "==> Wrote $out"

# Keep the 14 most recent backups.
ls -1t backups/makhzan-*.sql.gz | tail -n +15 | xargs -r rm --
