#!/usr/bin/env bash
# Seed a fresh deployment from an exported database dump (see seed/README.md),
# then rebuild the search index from it — no scraping. Run this ONCE on the
# first deploy, before ./scripts/deploy.sh.
#
#   ./scripts/restore-seed.sh [path/to/dump]   # default: seed/makhzan-seed.dump
set -euo pipefail
cd "$(dirname "$0")/.."

DUMP="${1:-seed/makhzan-seed.dump}"
if [ ! -f "$DUMP" ]; then
  echo "Seed dump not found: $DUMP" >&2
  echo "Create one on the source machine with:" >&2
  echo "  docker compose exec -T db pg_dump -U <user> -Fc <db> > seed/makhzan-seed.dump" >&2
  exit 1
fi

# Load POSTGRES_USER / POSTGRES_DB from .env.prod.
set -a; . ./.env.prod; set +a
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

echo "==> Starting db + search"
"${COMPOSE[@]}" up -d db search

echo "==> Waiting for Postgres"
until "${COMPOSE[@]}" exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
  sleep 2
done

echo "==> Restoring $DUMP (drops & recreates existing objects)"
# The dump carries schema@head + data + alembic_version, so a later
# 'alembic upgrade head' (deploy.sh) is a no-op.
"${COMPOSE[@]}" exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --clean --if-exists --no-owner < "$DUMP"

echo "==> Rebuilding search index from restored data"
"${COMPOSE[@]}" run --rm --no-deps ingestion python -m worker.reindex

echo "==> Seed complete. Start the app with: ./scripts/deploy.sh"
