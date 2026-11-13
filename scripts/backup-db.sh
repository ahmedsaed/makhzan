#!/usr/bin/env bash
# Dump the production Postgres database to ./backups/ and check the dump reads back.
#
#   ./scripts/backup-db.sh            # or: ./makhzan backup
#   ./scripts/backup-db.sh PATH       # write to PATH instead (restore-db.sh's safety copy)
#
# Custom format (pg_dump -Fc): compressed, and pg_restore can list it, restore
# selectively and restore into any database. Restore with ./makhzan restore FILE.
#
# Retention (scripts/lib/prune.sh): the 14 newest backups (old *.sql.gz and new
# *.dump counted together), none older than 30 days except the newest, and
# separately every *-pre-restore.dump safety copy from the last 7 days (never
# fewer than 3), so repeated restore attempts never push out the
# last good backups, nor the safety copy taken before the trouble started.
# A pruning failure is a warning, never a failed backup.
# MAKHZAN_KEEP_FILE (a realpath) names one file never to prune: the one being restored.
#
# Takes the operations lock (scripts/lib/ops.sh), so it never runs during a
# restore or deploy. MAKHZAN_ENV_FILE / MAKHZAN_COMPOSE_FILE with
# COMPOSE_PROJECT_NAME point it at another stack (default: production).
set -euo pipefail
export MAKHZAN_CALLER_PWD="${MAKHZAN_CALLER_PWD:-$PWD}"
cd "$(dirname "$0")/.."
. scripts/lib/ops.sh
out_arg=""
[ -z "${1:-}" ] || out_arg="$(ops_abspath "$1")"

ops_stack
ops_lock "backup-db.sh"

out="${out_arg:-$PWD/backups/makhzan-$(date +%Y%m%d-%H%M%S).dump}"
mkdir -p "$(dirname "$out")"
partial="${out}.partial"
trap 'rm -f "$partial"' EXIT

if ! "${COMPOSE[@]}" exec -T db pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > "$partial"; then
  echo "BACKUP FAILED: pg_dump exited non-zero; nothing was written to $out" >&2
  exit 1
fi

# A backup that silently wrote nothing has happened before (a 0-byte .dump sat in
# seed/ for weeks). So read it back, all of it: --list alone parses only the
# table of contents at the head, and passes a dump cut off halfway. pg_restore
# must turn the whole archive into SQL, and it must carry the data of
# alembic_version, the one table every real database has. Only then does it get
# its final name.
if [ ! -s "$partial" ]; then
  echo "BACKUP FAILED: pg_dump wrote 0 bytes to $partial" >&2
  exit 1
fi
if ! "${COMPOSE[@]}" exec -T db pg_restore -f /dev/null < "$partial" ||
  ! toc="$("${COMPOSE[@]}" exec -T db pg_restore --list < "$partial")"; then
  echo "BACKUP FAILED: pg_restore cannot read $partial back" >&2
  exit 1
fi
if ! grep -q 'TABLE DATA public alembic_version' <<<"$toc"; then
  echo "BACKUP FAILED: $partial has no alembic_version data; not a makhzan database?" >&2
  exit 1
fi
mv "$partial" "$out"
echo "==> Wrote $out ($(du -h "$out" | cut -f1), $(grep -c 'TABLE DATA' <<<"$toc") tables, verified)"

# Pruning never fails the backup: the dump above is written and verified, and
# a restore would read a failure here as "the safety backup failed".
#
# The rules are scripts/lib/prune.sh: the 14 newest regular backups, none
# older than 30 days but the newest, and a week of safety copies.
. scripts/lib/prune.sh
prune_backups || echo "warning: pruning old backups failed; the new one is kept" >&2
