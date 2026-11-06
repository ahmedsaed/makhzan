#!/usr/bin/env bash
# Pull a snapshot of the production database to ./seed/.
#
#   ./scripts/db-pull.sh                 # newest snapshot into seed/
#   DEPLOY_HOST=… DEPLOY_USER=… ./scripts/db-pull.sh
#
# Read-only against production: it runs pg_dump inside the db container and
# streams the result back over SSH. Nothing is written on the server, so this is
# safe to run against a live stack — pg_dump takes a consistent snapshot without
# blocking writers.
#
# Connection details come from the same variables deploy.yml uses, so if the
# deploy workflow can reach the server, so can this. Put them in .env.local
# (git-ignored) to avoid retyping.
set -euo pipefail
cd "$(dirname "$0")/.."

# Optional local overrides — same file the other developer-side scripts read.
if [ -f .env.local ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.local
  set +a
fi

: "${DEPLOY_HOST:?set DEPLOY_HOST (the server hostname), e.g. in .env.local}"
DEPLOY_USER="${DEPLOY_USER:-ahmed}"
DEPLOY_PATH="${DEPLOY_PATH:-~/Documents/Projects/makhzan}"

mkdir -p seed
ts="$(date +%Y%m%d-%H%M%S)"
out="seed/makhzan-prod-${ts}.dump"

echo "==> Dumping ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}"

# The remote reads POSTGRES_USER / POSTGRES_DB from .env.prod, exactly as
# backup-db.sh and deploy.sh do. Custom format (-Fc) so pg_restore can drop and
# recreate objects on the way in; --no-owner/--no-acl so it lands cleanly under
# a different local role.
ssh "${DEPLOY_USER}@${DEPLOY_HOST}" "bash -s -- '${DEPLOY_PATH}'" > "$out" <<'REMOTE'
set -euo pipefail
# The path arrives quoted, so a leading ~ is literal — expand it here rather
# than letting `cd` fail on a directory named "~".
dir="$1"; case "$dir" in "~"|"~/"*) dir="$HOME${dir#\~}";; esac
cd "$dir"
set -a; . ./.env.prod; set +a
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db \
  pg_dump -U "$POSTGRES_USER" -Fc --no-owner --no-acl "$POSTGRES_DB"
REMOTE

if [ ! -s "$out" ]; then
  rm -f "$out"
  echo "The dump came back empty — check the server is up and .env.prod is readable." >&2
  exit 1
fi

ln -sfn "$(basename "$out")" seed/makhzan-prod-latest.dump
echo "==> Wrote $out ($(du -h "$out" | cut -f1))"
echo "    seed/makhzan-prod-latest.dump now points at it."
echo "    Load it with: make db-load"
