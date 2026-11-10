#!/usr/bin/env bash
# Replace the production database with a backup, bring it to the current schema
# and rebuild the search index from it.
#
#   ./scripts/restore-db.sh [--yes] [--no-safety-backup] FILE    # or: ./makhzan restore ...
#
# FILE is a backup-db.sh dump (custom format, *.dump) or an older plain-SQL one
# (*.sql.gz, or *.sql); the format is read from the file, not its name.
#
#   --yes                skip the prompt (type the database name) for scripted use
#   --no-safety-backup   do not dump the current database first
#
# What it does, in order. Nothing is changed until the file has been read through:
#   1. checks the file (pg_restore --list / gzip -t) and asks for confirmation;
#   2. backs up the current database to backups/makhzan-<ts>-pre-restore.dump;
#   3. stops api and ingestion, the services that use the database (web only
#      talks to api; db, search and redis stay up);
#   4. loads FILE into a scratch database, stopping at the first error. The live
#      database is untouched until this succeeds, then dropped and replaced by it;
#   5. runs the deploy's `migrate` service (alembic upgrade head, sources sync,
#      index settings), so an older backup comes up to the current schema;
#   6. rebuilds products and the search index (python -m worker.reindex);
#   7. starts again the services it stopped, and prints what was restored.
#
# The crawl resumes from where the backup was: source_cursors come back with the
# rest, so a sweep in progress then continues from the backup's page, and pages
# swept since are swept again. That is consistent (cursors and listings are from
# the same moment), unlike loading a server dump into a dev database
# (db-load.sh), which resets them.
#
# COMPOSE_FILE / ENV_FILE point it at another stack (default: production).
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
  sed -n '5,13p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

YES=0
SAFETY=1
FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --no-safety-backup) SAFETY=0 ;;
    -h | --help) usage ;;
    -*) echo "unknown option: $1" >&2; usage 1 ;;
    *)
      [ -z "$FILE" ] || { echo "only one file, please" >&2; usage 1; }
      FILE="$1"
      ;;
  esac
  shift
done
[ -n "$FILE" ] || usage 1
if [ ! -s "$FILE" ]; then
  echo "No such backup, or it is empty: $FILE" >&2
  exit 1
fi

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
case "$ENV_FILE" in /* | ./* | ../*) ;; *) ENV_FILE="./$ENV_FILE" ;; esac
export COMPOSE_FILE ENV_FILE # backup-db.sh and the compose file's env_file: follow them
COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
DB="$POSTGRES_DB"
SCRATCH="${DB}_restoring"

# Services that use the database. web reads only through api, so it stays up.
WRITERS=(api ingestion)

psql_admin() { "${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -qtA; }
psql_db() { "${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d "$DB" -v ON_ERROR_STOP=1 -qtA; }

# --- 1. Read the file through before anything changes -------------------------
case "$(head -c 5 "$FILE" | od -An -tx1 | tr -d ' \n')" in
  5047444d50) FORMAT=custom ;; # "PGDMP"
  1f8b*) FORMAT=gzip ;;
  *) FORMAT=sql ;;
esac

echo "==> Starting db + search"
"${COMPOSE[@]}" up -d db search >/dev/null
for i in $(seq 1 60); do
  "${COMPOSE[@]}" exec -T db pg_isready -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1 && break
  [ "$i" = 60 ] && { echo "Postgres did not become ready in 2 minutes." >&2; exit 1; }
  sleep 2
done

echo "==> Checking $FILE ($FORMAT)"
case "$FORMAT" in
  custom)
    # The whole archive, not just --list: that reads only the table of contents
    # at its head and passes a file cut off halfway.
    if ! "${COMPOSE[@]}" exec -T db pg_restore -f /dev/null < "$FILE" ||
      ! toc="$("${COMPOSE[@]}" exec -T db pg_restore --list < "$FILE")"; then
      echo "pg_restore cannot read $FILE; nothing was changed." >&2
      exit 1
    fi
    grep -q 'TABLE DATA public alembic_version' <<<"$toc" || {
      echo "$FILE has no alembic_version data; not a makhzan backup? Nothing was changed." >&2
      exit 1
    }
    ;;
  gzip)
    gzip -t "$FILE" || { echo "$FILE is not a readable gzip; nothing was changed." >&2; exit 1; }
    ;;
  sql)
    head -c 4096 "$FILE" | grep -q 'PostgreSQL database dump' || {
      echo "$FILE is neither a pg_dump custom archive nor a plain-SQL dump; nothing was changed." >&2
      exit 1
    }
    ;;
esac

if [ "$YES" != 1 ]; then
  if [ ! -t 0 ]; then
    echo "Refusing to restore without confirmation: no terminal to ask on. Pass --yes." >&2
    exit 1
  fi
  echo
  echo "    This REPLACES the database '$DB' with $FILE."
  echo "    api and ingestion stop until it is done."
  printf "    Type the database name (%s) to continue: " "$DB"
  read -r reply
  if [ "$reply" != "$DB" ]; then
    echo "Aborted; nothing was changed." >&2
    exit 1
  fi
fi

# --- 2. Safety backup -----------------------------------------------------------
SAFETY_FILE=""
if [ "$SAFETY" = 1 ]; then
  SAFETY_FILE="backups/makhzan-$(date +%Y%m%d-%H%M%S)-pre-restore.dump"
  echo "==> Backing up the current database to $SAFETY_FILE"
  # No pruning: it could evict the very backup being restored.
  BACKUP_PRUNE=0 ./scripts/backup-db.sh "$SAFETY_FILE" || {
    echo "The safety backup failed; nothing was changed. (--no-safety-backup skips it.)" >&2
    exit 1
  }
fi

# --- 3. Stop what uses the database -----------------------------------------------
mapfile -t RUNNING < <("${COMPOSE[@]}" ps --status running --services)
STOPPED=()
for s in "${WRITERS[@]}"; do
  for r in "${RUNNING[@]}"; do [ "$s" = "$r" ] && STOPPED+=("$s"); done
done

# From here on a failure must say what state it left. Until the swap the live
# database is untouched, so the services go back up; after it, they stay down,
# because the database they would serve is not finished.
PHASE=prepare
on_exit() {
  local code=$?
  [ "$code" = 0 ] && return
  echo >&2
  case "$PHASE" in
    prepare | load)
      "${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d postgres -qc \
        "DROP DATABASE IF EXISTS \"$SCRATCH\" WITH (FORCE)" >/dev/null 2>&1 || true
      echo "RESTORE FAILED while loading $FILE (exit $code)." >&2
      echo "The live database '$DB' was NOT changed." >&2
      if [ "${#STOPPED[@]}" -gt 0 ]; then
        echo "Starting again: ${STOPPED[*]}" >&2
        "${COMPOSE[@]}" start "${STOPPED[@]}" >&2 || echo "  could not; run: ${COMPOSE[*]} start ${STOPPED[*]}" >&2
      fi
      ;;
    *)
      echo "RESTORE FAILED after the database was replaced, during: $PHASE (exit $code)." >&2
      echo "The database '$DB' now holds $FILE but is not finished." >&2
      echo "These services are STOPPED and were left so: ${STOPPED[*]:-(none were running)}" >&2
      [ -n "$SAFETY_FILE" ] && echo "The previous database is in $SAFETY_FILE." >&2
      echo "Fix the cause, then finish by hand:" >&2
      echo "  ${COMPOSE[*]} run --rm migrate" >&2
      echo "  ${COMPOSE[*]} run --rm --no-deps ingestion python -m worker.reindex" >&2
      echo "  ${COMPOSE[*]} up -d" >&2
      if [ -n "$SAFETY_FILE" ]; then
        echo "or go back to the previous database, then start the stack:" >&2
        echo "  ./scripts/restore-db.sh --yes --no-safety-backup $SAFETY_FILE" >&2
        echo "  ${COMPOSE[*]} up -d" >&2
      fi
      ;;
  esac
}
trap on_exit EXIT

if [ "${#STOPPED[@]}" -gt 0 ]; then
  echo "==> Stopping ${STOPPED[*]}"
  "${COMPOSE[@]}" stop "${STOPPED[@]}"
fi

# --- 4. Load into a scratch database, then swap ------------------------------------
PHASE=load
echo "==> Loading into a scratch database '$SCRATCH'"
psql_admin <<SQL
SET client_min_messages = warning;
DROP DATABASE IF EXISTS "$SCRATCH" WITH (FORCE);
CREATE DATABASE "$SCRATCH";
SQL
case "$FORMAT" in
  custom)
    # --no-owner/--no-acl: a seed dump may come from a machine with other roles.
    "${COMPOSE[@]}" exec -T db pg_restore -U "$POSTGRES_USER" -d "$SCRATCH" \
      --exit-on-error --no-owner --no-acl < "$FILE"
    ;;
  gzip | sql)
    # Plain dumps from pg_dump >= 16.10 open with \restrict, which only psql >=
    # 16.10 understands; the db container's psql matches the server that made it.
    { if [ "$FORMAT" = gzip ]; then gunzip -c "$FILE"; else cat "$FILE"; fi; } |
      "${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d "$SCRATCH" \
        -v ON_ERROR_STOP=1 -q -o /dev/null
    ;;
esac

PHASE="replacing '$DB' with the scratch database"
echo "==> Replacing '$DB'"
psql_admin <<SQL
DROP DATABASE IF EXISTS "$DB" WITH (FORCE);
ALTER DATABASE "$SCRATCH" RENAME TO "$DB";
SQL

# --- 5. Migrations, the same one-shot the deploy runs ---------------------------------
PHASE="migrations (the migrate service)"
echo "==> Migrating to the current schema"
"${COMPOSE[@]}" run --rm migrate

# --- 6. Products + search index --------------------------------------------------------
PHASE="the search index rebuild"
echo "==> Rebuilding products and the search index"
"${COMPOSE[@]}" run --rm --no-deps ingestion python -m worker.reindex

# --- 7. Back up ------------------------------------------------------------------------
PHASE="restarting ${STOPPED[*]:-nothing}"
if [ "${#STOPPED[@]}" -gt 0 ]; then
  echo "==> Starting ${STOPPED[*]}"
  "${COMPOSE[@]}" start "${STOPPED[@]}"
fi
PHASE=finished

echo
echo "==> Restored $FILE into '$DB'"
psql_db <<'SQL' | sed 's/^/    /'
SELECT 'alembic version:  ' || string_agg(version_num, ', ') FROM alembic_version;
SELECT 'listed products:  ' || count(*) FROM products WHERE merged_into IS NULL AND delisted_at IS NULL;
SELECT 'listings:         ' || count(*) FROM listings;
SELECT 'newest run:       ' || coalesce(max(started_at)::text, 'none') FROM ingestion_runs;
SQL
[ -n "$SAFETY_FILE" ] && echo "    previous database: $SAFETY_FILE"
echo "    The crawl resumes from the backup's cursors; pages swept since are swept again."
if [ "${#STOPPED[@]}" -eq 0 ]; then
  echo "    api and ingestion were not running, so they were not started: ./scripts/deploy.sh"
fi
