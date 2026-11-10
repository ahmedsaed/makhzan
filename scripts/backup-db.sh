#!/usr/bin/env bash
# Dump the production Postgres database to ./backups/ and check the dump reads back.
#
#   ./scripts/backup-db.sh            # or: ./makhzan backup
#   ./scripts/backup-db.sh PATH       # write to PATH instead (restore-db.sh's safety copy)
#
# Custom format (pg_dump -Fc): compressed, and pg_restore can list it, restore
# selectively and restore into any database. Restore with ./makhzan restore FILE.
# Keeps the 14 newest backups (old *.sql.gz and new *.dump counted together);
# BACKUP_PRUNE=0 skips that, so a safety copy never evicts the file being restored.
#
# COMPOSE_FILE / ENV_FILE point it at another stack (default: production).
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
case "$ENV_FILE" in /* | ./* | ../*) ;; *) ENV_FILE="./$ENV_FILE" ;; esac
export ENV_FILE  # docker-compose.prod.yml's env_file: follows it
COMPOSE=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")

# Load POSTGRES_USER / POSTGRES_DB (and everything else) from the env file.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

out="${1:-backups/makhzan-$(date +%Y%m%d-%H%M%S).dump}"
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

if [ "${BACKUP_PRUNE:-1}" != "0" ]; then
  shopt -s nullglob
  backups=(backups/makhzan-*.dump backups/makhzan-*.sql.gz)
  if [ "${#backups[@]}" -gt 14 ]; then
    # shellcheck disable=SC2012 # our own names, no newlines
    ls -1t -- "${backups[@]}" | tail -n +15 | xargs -r -d '\n' rm --
  fi
fi
