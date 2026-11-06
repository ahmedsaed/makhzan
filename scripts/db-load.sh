#!/usr/bin/env bash
# Load a production dump into the LOCAL development database.
#
#   ./scripts/db-load.sh                      # newest dump in seed/
#   ./scripts/db-load.sh seed/some.dump       # a specific one
#   CONFIRM=yes ./scripts/db-load.sh          # skip the prompt
#   SKIP_REINDEX=1 ./scripts/db-load.sh       # leave products/search alone
#
# This DROPS your local makhzan database and rebuilds it from the dump. It only
# ever touches localhost — there is no path from here to the server.
set -euo pipefail
cd "$(dirname "$0")/.."

DUMP="${1:-}"
if [ -z "$DUMP" ]; then
  # Follow the symlink db-pull leaves, else the newest dump on disk.
  if [ -e seed/makhzan-prod-latest.dump ]; then
    DUMP="seed/makhzan-prod-latest.dump"
  else
    DUMP="$(ls -1t seed/*.dump 2>/dev/null | head -1 || true)"
  fi
fi
[ -n "$DUMP" ] && [ -f "$DUMP" ] || {
  echo "No dump found. Run 'make db-pull' first, or pass a path." >&2
  exit 1
}

DB_NAME="${POSTGRES_DB:-makhzan}"
DB_USER="${POSTGRES_USER:-makhzan}"
CONTAINER="${DB_CONTAINER:-makhzan-db-1}"

echo "==> Loading $DUMP into the local '$DB_NAME' database"
if [ "${CONFIRM:-}" != "yes" ]; then
  printf "    This DROPS your local database. Continue? [y/N] "
  read -r reply
  case "$reply" in [yY]*) ;; *) echo "Aborted."; exit 1 ;; esac
fi

docker compose up -d db >/dev/null
echo "==> Waiting for Postgres"
for _ in $(seq 1 60); do
  docker exec "$CONTAINER" pg_isready -U "$DB_USER" >/dev/null 2>&1 && break
  sleep 1
done

# Drop and recreate rather than pg_restore --clean: a dump taken from a newer
# schema leaves objects behind that --clean does not know about, and a
# half-migrated database is a confusing thing to debug.
echo "==> Recreating the database"
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL >/dev/null
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "${DB_NAME}";
CREATE DATABASE "${DB_NAME}";
SQL

echo "==> Restoring"
# --no-owner/--no-acl: the dump's roles do not exist locally and do not matter.
docker exec -i "$CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" \
  --no-owner --no-acl --single-transaction < "$DUMP"

echo "==> Applying migrations"
DB_URL="postgresql+asyncpg://${DB_USER}:${POSTGRES_PASSWORD:-makhzan}@localhost:5432/${DB_NAME}"
(cd packages/schemas && DATABASE_URL="$DB_URL" poetry run alembic upgrade head)

# A dump from before the sources table existed restores with it empty, and the
# worker builds its adapters from the table — so sync the local file in.
echo "==> Syncing the sources table from sources.toml"
(cd apps/ingestion && DATABASE_URL="$DB_URL" poetry run python -m worker.sources.sync)

# The reason this script exists rather than a one-liner in the README.
#
# A dump carries whatever cursor state the server had mid-cycle: which partitions
# were already swept, and when the cycle began. Archiving is cycle-gated and keys
# off `cycle_started_at`, so a restored mid-cycle state makes the first local
# sweep believe the untouched partitions were checked and never seen — and it
# retires them. A dump taken mid-session would have archived roughly 16,600 live
# listings of the largest supplier this way.
#
# Resetting here means the next local sweep starts a clean cycle. It costs
# nothing: cursors are progress, not data.
echo "==> Resetting sweep cursors (a restored mid-cycle state archives live stock)"
# Counted in SQL, not by piping to wc: psql -tA emits a trailing newline even
# for an empty result, so line-counting reports one row when there are none.
cursors=$(docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
  "WITH cleared AS (DELETE FROM source_cursors RETURNING 1) SELECT count(*) FROM cleared;")
echo "    cleared ${cursors} cursor row(s)"

if [ "${SKIP_REINDEX:-}" = "1" ]; then
  echo "==> Skipping reindex (SKIP_REINDEX=1). Run 'make reindex' before using the UI."
else
  echo "==> Rebuilding products and the search index"
  # Only db was started above; the index lives in Meilisearch.
  docker compose up -d search >/dev/null
  make reindex
fi

echo
echo "Done. 'make status' shows what you now have."
