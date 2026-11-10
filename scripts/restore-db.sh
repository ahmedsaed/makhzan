#!/usr/bin/env bash
# Replace the production database with a backup, bring it to the current schema
# and rebuild the search index from it.
#
#   ./scripts/restore-db.sh [--yes] [--no-safety-backup] [--drop-leftover-scratch] FILE
#   ./makhzan restore ...                                  # the same
#
# FILE is a backup-db.sh dump (custom format, *.dump) or an older plain-SQL one
# (*.sql.gz, or *.sql); the format is read from the file, not its name.
#
#   --yes                    skip the prompt (type the database name), for scripts
#   --no-safety-backup       do not dump the current database first
#   --drop-leftover-scratch  a previous attempt left <db>_restoring; drop it
#
# Run it in tmux or screen: it takes minutes, and an SSH drop mid-way leaves the
# operator guessing. Everything it prints also goes to backups/restore-<ts>.log.
#
# What it does, in order. The live database is not touched until step 6:
#   1. reads the file through (pg_restore, or the dump's own trailer for plain
#      SQL) and asks for confirmation;
#   2. backs up the current database to backups/makhzan-<ts>-pre-restore.dump,
#      unless there is nothing there to keep (a fresh server);
#   3. stops api and ingestion, the services that use the database (web only
#      talks to api; db, search and redis stay up);
#   4. loads FILE into a scratch database <db>_restoring, stopping at the first
#      error, and refuses it unless it has one alembic version, products,
#      listings, the core tables' primary keys and foreign keys;
#   5. runs the deploy's `migrate` service against the scratch database
#      (alembic upgrade head, sources sync), so an older backup comes up to the
#      current schema and a broken one fails here;
#   6. drops the live database and renames the scratch one into its place;
#   7. rebuilds the search index from it (python -m worker.reindex). Products
#      come from the backup as they were; the worker regroups them on its next
#      rebuild, as it does after every crawl;
#   8. starts again the services it stopped, and prints what was restored.
#
# The crawl resumes from where the backup was: source_cursors come back with the
# rest, so a sweep in progress then continues from the backup's page, and pages
# swept since are swept again. That is consistent (cursors and listings are from
# the same moment), unlike loading a server dump into a dev database
# (db-load.sh), which resets them.
#
# Takes the operations lock, so no deploy or backup runs meanwhile; pause
# releases (they deploy) while restoring. MAKHZAN_ENV_FILE /
# MAKHZAN_COMPOSE_FILE with COMPOSE_PROJECT_NAME point it at another stack.
set -euo pipefail
export MAKHZAN_CALLER_PWD="${MAKHZAN_CALLER_PWD:-$PWD}"
cd "$(dirname "$0")/.."
. scripts/lib/ops.sh

usage() {
  sed -n '5,14p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# Services that use the database. web reads only through api, so it stays up.
WRITERS=(api ingestion)

psql_on() { # DB: run the SQL on stdin
  "${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -qtA
}

# db_exists NAME: prints yes, no, or unknown (cannot ask Postgres).
db_exists() {
  local n
  n="$(psql_on postgres <<<"SELECT count(*) FROM pg_database WHERE datname = '$1'" 2>/dev/null)" || {
    echo unknown
    return
  }
  case "$n" in 1) echo yes ;; 0) echo no ;; *) echo unknown ;; esac
}

# shellcheck disable=SC2329 # called from on_exit
start_again() {
  [ "${#WERE_UP[@]}" -gt 0 ] || return 0
  echo "Starting again: ${WERE_UP[*]}"
  "${COMPOSE[@]}" start "${WERE_UP[@]}" ||
    echo "  could not; run: $CMD start ${WERE_UP[*]}"
}

# From step 3 on, any exit that is not the finish (an error, Ctrl-C, an SSH
# drop, a kill) cleans up and says what state it left, from what Postgres
# reports rather than from how far the script got. It decides on PHASE, never
# on $?: when bash dies from a signal, $? in the EXIT trap is the last command's
# status, often 0. The signals are turned into exits (in main) and ignored from
# here on, so neither a second Ctrl-C nor a dead terminal cuts the cleanup short.
# shellcheck disable=SC2329 # run by the EXIT trap
on_exit() {
  local code=$? live scratch why
  trap '' INT HUP TERM PIPE
  set +e
  case "$PHASE" in "" | finished) return ;; esac
  case "$code" in
    129) why="hangup: the terminal or SSH session went away" ;;
    130) why="interrupted" ;;
    143) why="terminated" ;;
    *) why="exit $code" ;;
  esac
  echo
  case "$PHASE" in
    prepare | load | validate | migrate)
      echo "RESTORE FAILED during: $PHASE ($why)."
      echo "The live database '$DB' was NOT changed."
      if "${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d postgres -qc \
        "DROP DATABASE IF EXISTS \"$SCRATCH\" WITH (FORCE)" >/dev/null 2>&1; then
        echo "The scratch database '$SCRATCH' was dropped."
      else
        echo "Could not drop the scratch database '$SCRATCH'; once Postgres answers, drop it:"
        echo "  $CMD exec -T db dropdb -U $POSTGRES_USER --if-exists '$SCRATCH'"
      fi
      start_again
      ;;
    swap)
      live="$(db_exists "$DB")"
      scratch="$(db_exists "$SCRATCH")"
      echo "RESTORE FAILED while swapping the databases ($why)."
      echo "Postgres reports: '$DB' exists: $live; '$SCRATCH' exists: $scratch."
      if [ "$live" = yes ] && [ "$scratch" = yes ]; then
        echo "The live database '$DB' was NOT changed. The restored, migrated copy is kept"
        echo "as '$SCRATCH'; drop it, or rerun with --drop-leftover-scratch."
        start_again
      elif [ "$live" = no ] && [ "$scratch" = yes ]; then
        echo "The old database is gone and the restored one is still named '$SCRATCH'."
        echo "api and ingestion are STOPPED. Finish by hand:"
        echo "  $CMD exec -T db psql -U $POSTGRES_USER -d postgres -c 'ALTER DATABASE \"$SCRATCH\" RENAME TO \"$DB\"'"
        echo "  $CMD run --rm --no-deps ingestion python -m worker.reindex"
        echo "  $CMD up -d"
      elif [ "$live" = yes ] && [ "$scratch" = no ]; then
        echo "The swap went through: '$DB' is the restored, migrated database."
        echo "Only the search index is left to rebuild, then start the stack:"
        echo "  $CMD run --rm --no-deps ingestion python -m worker.reindex"
        echo "  $CMD up -d"
      else
        echo "Could not tell what state the databases are in. api and ingestion are STOPPED."
        echo "Look with: $CMD exec -T db psql -U $POSTGRES_USER -d postgres -c '\\l'"
        echo "Once Postgres answers, rerunning this restore says which case it is: with both"
        echo "databases the live one is intact; with only '$SCRATCH' it prints the rename."
      fi
      ;;
    reindex | restart)
      echo "RESTORE FAILED during: $PHASE ($why)."
      echo "'$DB' holds $FILE, migrated; that part is done."
      [ "$PHASE" = reindex ] && echo "The search index was not rebuilt: $CMD run --rm --no-deps ingestion python -m worker.reindex"
      start_again
      ;;
  esac
  [ -n "$SAFETY_FILE" ] && echo "The previous database is in $SAFETY_FILE."
  echo "Log: $LOG"
}

main() {
  YES=0
  SAFETY=1
  DROP_LEFTOVER=0
  FILE=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes) YES=1 ;;
      --no-safety-backup) SAFETY=0 ;;
      --drop-leftover-scratch) DROP_LEFTOVER=1 ;;
      -h | --help) usage ;;
      -*) echo "unknown option: $1" >&2; usage 1 ;;
      *)
        [ -z "$FILE" ] || { echo "only one file, please" >&2; usage 1; }
        FILE="$(ops_abspath "$1")"
        ;;
    esac
    shift
  done
  [ -n "$FILE" ] || usage 1
  if [ ! -s "$FILE" ]; then
    echo "No such backup, or it is empty: $FILE" >&2
    exit 1
  fi
  FILE="$(realpath -- "$FILE")"

  ops_stack
  CMD="${STACK_ENV}${COMPOSE[*]}"
  ops_lock "restore-db.sh $FILE"

  LOG="$PWD/backups/restore-$(date +%Y%m%d-%H%M%S).log"
  # The log keeps going when the terminal goes: tee ignores the signals that
  # end this script, only warns when the terminal is gone, and does not hold
  # the lock (fd 9) once the script has let it go.
  exec > >(
    trap '' INT HUP TERM
    exec tee --output-error=warn -a "$LOG" 9>&-
  ) 2>&1
  PHASE=""
  trap on_exit EXIT
  trap 'exit 130' INT
  trap 'exit 129' HUP
  trap 'exit 143' TERM

  DB="$POSTGRES_DB"
  SCRATCH="${DB}_restoring"
  SAFETY_FILE=""
  WERE_UP=()

  # The migrate service reads DATABASE_URL; pointed at the scratch database it
  # migrates that instead of the live one.
  if [[ "$DATABASE_URL" =~ ^(.*/)"$DB"(\?.*)?$ ]]; then
    SCRATCH_URL="${BASH_REMATCH[1]}${SCRATCH}${BASH_REMATCH[2]}"
  else
    echo "DATABASE_URL in $MAKHZAN_ENV_FILE does not end in /$DB; cannot point migrate at a scratch database." >&2
    exit 1
  fi

  # --- 1. Read the file through before anything changes ----------------------
  local format
  case "$(head -c 5 "$FILE" | od -An -tx1 | tr -d ' \n')" in
    5047444d50) format=custom ;; # "PGDMP"
    1f8b*) format=gzip ;;
    *) format=sql ;;
  esac

  echo "==> Starting db + search (if not running)"
  "${COMPOSE[@]}" up -d --no-recreate db search
  local i
  for i in $(seq 1 60); do
    "${COMPOSE[@]}" exec -T db pg_isready -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1 && break
    [ "$i" = 60 ] && { echo "Postgres did not become ready in 2 minutes." >&2; exit 1; }
    sleep 2
  done

  echo "==> Checking $FILE ($format)"
  case "$format" in
    custom)
      # The whole archive, not just --list: that reads only the table of
      # contents at its head and passes a file cut off halfway.
      local toc
      if ! "${COMPOSE[@]}" exec -T db pg_restore -f /dev/null < "$FILE" ||
        ! toc="$("${COMPOSE[@]}" exec -T db pg_restore --list < "$FILE")"; then
        echo "pg_restore cannot read $FILE; nothing was changed." >&2
        exit 1
      fi
      if ! grep -q 'TABLE DATA public alembic_version' <<<"$toc"; then
        echo "$FILE has no alembic_version data; not a makhzan backup? Nothing was changed." >&2
        exit 1
      fi
      ;;
    gzip | sql)
      # A gzip of nothing (what the old backup-db.sh left when pg_dump failed)
      # passes gzip -t and loads as zero statements; a dump cut on a line
      # boundary loads without its keys and indexes. pg_dump ends every complete
      # dump with this trailer, after the data, constraints and indexes.
      if ! { if [ "$format" = gzip ]; then gunzip -c "$FILE"; else cat "$FILE"; fi; } |
        awk '/^COPY public\.alembic_version /{a=1} /^-- PostgreSQL database dump complete/{c=1}
             END{exit !(a && c)}'; then
        echo "$FILE is not a complete makhzan dump: it needs 'COPY public.alembic_version'" >&2
        echo "and pg_dump's closing 'PostgreSQL database dump complete' line. Nothing was changed." >&2
        exit 1
      fi
      ;;
  esac

  local live_db scratch_db
  live_db="$(db_exists "$DB")"
  scratch_db="$(db_exists "$SCRATCH")"
  if [ "$live_db" = unknown ] || [ "$scratch_db" = unknown ]; then
    echo "Cannot list the databases in Postgres; nothing was changed." >&2
    exit 1
  fi
  if [ "$scratch_db" = yes ]; then
    if [ "$live_db" = no ]; then
      echo "'$SCRATCH' exists and '$DB' does not: a previous restore stopped between" >&2
      echo "dropping the old database and renaming the new one. '$SCRATCH' may be the" >&2
      echo "only copy. Rename it rather than restoring over it:" >&2
      echo "  $CMD exec -T db psql -U $POSTGRES_USER -d postgres -c 'ALTER DATABASE \"$SCRATCH\" RENAME TO \"$DB\"'" >&2
      exit 1
    fi
    if [ "$DROP_LEFTOVER" != 1 ]; then
      echo "A previous attempt left a scratch database '$SCRATCH'. The live '$DB' is" >&2
      echo "separate and intact. Rerun with --drop-leftover-scratch to replace it." >&2
      exit 1
    fi
  fi

  echo
  echo "    stack:    project $(ops_project), env file $MAKHZAN_ENV_FILE"
  echo "    database: '$DB' (exists: $live_db)"
  echo "    restore:  $FILE"
  if [ "$YES" != 1 ]; then
    if [ ! -t 0 ]; then
      echo "Refusing to restore without confirmation: no terminal to ask on. Pass --yes." >&2
      exit 1
    fi
    echo "    This REPLACES that database. api and ingestion stop until it is done."
    printf "    Type the database name (%s) to continue: " "$DB"
    local reply
    read -r reply
    if [ "$reply" != "$DB" ]; then
      echo "Aborted; nothing was changed." >&2
      exit 1
    fi
  fi

  # --- 2. Safety backup ---------------------------------------------------------
  if [ "$SAFETY" = 1 ]; then
    # Skipped only when there is no catalogue to lose: no database, no products
    # table, or an empty one (a fresh server). A query that fails is not "empty".
    local products_now=0 has_products
    if [ "$live_db" = yes ]; then
      # Two queries: a count over a table that does not exist fails at parse time.
      has_products="$(psql_on "$DB" <<<"SELECT to_regclass('public.products') IS NOT NULL")" || {
        echo "Cannot tell whether '$DB' holds products; nothing was changed." >&2
        exit 1
      }
      if [ "$has_products" = t ]; then
        products_now="$(psql_on "$DB" <<<"SELECT count(*) FROM products")" || {
          echo "Cannot count the products in '$DB'; nothing was changed." >&2
          exit 1
        }
      fi
    fi
    if [ "$products_now" = 0 ]; then
      echo "==> No safety backup: '$DB' holds no products, so there is nothing to keep"
    else
      SAFETY_FILE="$PWD/backups/makhzan-$(date +%Y%m%d-%H%M%S)-pre-restore.dump"
      echo "==> Backing up the current database to $SAFETY_FILE"
      # MAKHZAN_KEEP_FILE: its pruning must never take the file being restored.
      MAKHZAN_KEEP_FILE="$FILE" ./scripts/backup-db.sh "$SAFETY_FILE" || {
        echo "The safety backup failed; nothing was changed. (--no-safety-backup skips it.)" >&2
        exit 1
      }
    fi
  fi

  # --- 3. Stop what uses the database ------------------------------------------
  # Up means running or restarting: a crash-looping worker reconnects too.
  local up s r
  if ! up="$("${COMPOSE[@]}" ps --services --status running --status restarting)"; then
    echo "Cannot list the stack's services; nothing was changed." >&2
    exit 1
  fi
  for s in "${WRITERS[@]}"; do
    while read -r r; do [ "$s" = "$r" ] && WERE_UP+=("$s"); done <<<"$up"
  done

  PHASE=prepare
  echo "==> Stopping ${WRITERS[*]} (were up: ${WERE_UP[*]:-none})"
  "${COMPOSE[@]}" stop "${WRITERS[@]}"

  # --- 4. Load into a scratch database, and look at it ---------------------------
  PHASE=load
  echo "==> Loading into a scratch database '$SCRATCH'"
  psql_on postgres <<SQL
SET client_min_messages = warning;
DROP DATABASE IF EXISTS "$SCRATCH" WITH (FORCE);
CREATE DATABASE "$SCRATCH";
SQL
  case "$format" in
    custom)
      # --no-owner/--no-acl: a seed dump may come from a machine with other roles.
      "${COMPOSE[@]}" exec -T db pg_restore -U "$POSTGRES_USER" -d "$SCRATCH" \
        --exit-on-error --no-owner --no-acl < "$FILE"
      ;;
    gzip | sql)
      # Plain dumps from pg_dump >= 16.10 open with \restrict, which only psql
      # >= 16.10 understands; the db container's psql matches the server.
      { if [ "$format" = gzip ]; then gunzip -c "$FILE"; else cat "$FILE"; fi; } |
        "${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d "$SCRATCH" \
          -v ON_ERROR_STOP=1 -q -o /dev/null
      ;;
  esac

  PHASE=validate
  # Rows say the data arrived; keys say the post-data section did. A plain dump
  # cut before its constraints (and given a trailer by hand) still loads, and
  # still has a stray constraint or two, so a bare count would not do: the core
  # tables' primary keys and at least one foreign key must be there.
  local counts versions_n products listings core_pks fks
  counts="$(psql_on "$SCRATCH" <<'SQL'
SELECT (SELECT count(*) FROM alembic_version) || ' ' ||
       (SELECT count(*) FROM products) || ' ' ||
       (SELECT count(*) FROM listings) || ' ' ||
       (SELECT count(*) FROM pg_constraint
         WHERE contype = 'p' AND conrelid IN ('public.products'::regclass, 'public.listings'::regclass,
                                              'public.suppliers'::regclass, 'public.alembic_version'::regclass)) || ' ' ||
       (SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
         WHERE n.nspname = 'public' AND c.contype = 'f');
SQL
)"
  read -r versions_n products listings core_pks fks <<<"$counts"
  echo "    loaded: $versions_n alembic version, $products products, $listings listings,"
  echo "            primary keys on $core_pks of 4 core tables, $fks foreign keys"
  if [ "$versions_n" != 1 ] || [ "$products" = 0 ] || [ "$listings" = 0 ] ||
    [ "$core_pks" != 4 ] || [ "$fks" = 0 ]; then
    echo "That is not a whole makhzan database; refusing to swap it in." >&2
    exit 1
  fi

  # --- 5. Migrations, on the scratch database ------------------------------------
  PHASE=migrate
  echo "==> Migrating '$SCRATCH' to the current schema"
  "${COMPOSE[@]}" run --rm -e DATABASE_URL="$SCRATCH_URL" migrate
  echo "    now at: $(psql_on "$SCRATCH" <<<"SELECT string_agg(version_num, ', ') FROM alembic_version")"

  # --- 6. Swap -------------------------------------------------------------------------
  PHASE=swap
  echo "==> Replacing '$DB'"
  psql_on postgres <<SQL
SET client_min_messages = warning;
DROP DATABASE IF EXISTS "$DB" WITH (FORCE);
ALTER DATABASE "$SCRATCH" RENAME TO "$DB";
SQL

  # --- 7. Search index ------------------------------------------------------------------
  PHASE=reindex
  echo "==> Rebuilding the search index"
  "${COMPOSE[@]}" run --rm --no-deps ingestion python -m worker.reindex

  # --- 8. Back up -----------------------------------------------------------------------
  PHASE=restart
  if [ "${#WERE_UP[@]}" -gt 0 ]; then
    echo "==> Starting ${WERE_UP[*]}"
    "${COMPOSE[@]}" start "${WERE_UP[@]}"
  fi
  PHASE=finished

  echo
  echo "==> Restored $FILE into '$DB'"
  psql_on "$DB" <<'SQL' | sed 's/^/    /' || echo "    (the summary query failed; the restore itself finished)"
SELECT 'alembic version:  ' || string_agg(version_num, ', ') FROM alembic_version;
SELECT 'listed products:  ' || count(*) FROM products WHERE merged_into IS NULL AND delisted_at IS NULL;
SELECT 'listings:         ' || count(*) FROM listings;
SELECT 'newest run:       ' || coalesce(max(started_at)::text, 'none') FROM ingestion_runs;
SQL
  [ -z "$SAFETY_FILE" ] || echo "    previous database: $SAFETY_FILE"
  echo "    The crawl resumes from the backup's cursors; pages swept since are swept again."
  if [ "${#WERE_UP[@]}" -eq 0 ]; then
    echo "    api and ingestion were not up before, so they were left stopped. Start the stack: $CMD up -d"
  fi
  echo "    log: $LOG"
}

main "$@"; exit
