#!/usr/bin/env bash
# Seed a fresh deployment from an exported database dump (see seed/README.md),
# then rebuild the search index from it — no scraping. Run this once on the
# first deploy, then ./scripts/deploy.sh.
#
#   ./scripts/restore-seed.sh [--yes] [path/to/dump]   # default: seed/makhzan-seed.dump
#
# There is one restore path: this is restore-db.sh with a default file, so it
# reads either dump format, migrates and confirms the same way. On a fresh
# server it skips the safety backup by itself: the empty database has nothing to keep.
set -euo pipefail
export MAKHZAN_CALLER_PWD="${MAKHZAN_CALLER_PWD:-$PWD}"
cd "$(dirname "$0")/.."
. scripts/lib/ops.sh

args=()
dump=""
for a in "$@"; do
  case "$a" in -*) args+=("$a") ;; *) dump="$a" ;; esac
done
if [ -n "$dump" ]; then dump="$(ops_abspath "$dump")"; else dump="$PWD/seed/makhzan-seed.dump"; fi

if [ ! -s "$dump" ]; then
  echo "Seed dump not found, or empty: $dump" >&2
  echo "Make one on a machine that has the data with ./makhzan backup, or:" >&2
  echo "  docker compose exec -T db pg_dump -U <user> -Fc <db> > seed/makhzan-seed.dump" >&2
  exit 1
fi

exec ./scripts/restore-db.sh "${args[@]}" "$dump"
