#!/usr/bin/env bash
# Deploy on the server: update the checkout, pull the new images, restart.
# Migrations, and the sync of the sources table from sources.toml, run
# automatically via the one-shot `migrate` service on `up`.
#
#   ./scripts/deploy.sh            # or: make deploy
#   SKIP_PULL=1 ./scripts/deploy.sh   # restart on the current checkout
#
# The git pull is part of the deploy because half of what runs comes from the
# checkout, not the images: docker-compose.prod.yml, the migrate service's
# command, and these scripts. Pulling images without it deploys new code under
# an old compose file.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

# Update first, then hand over to the version we just pulled.
#
# The re-exec is not ceremony. Bash reads a script incrementally as it runs, so
# a `git pull` that rewrites this file mid-execution makes the shell resume at a
# byte offset into different text — it silently runs garbage. Replacing the
# process with the new file is the fix, and the guard stops it looping.
if [ "${SKIP_PULL:-0}" != "1" ] && [ "${DEPLOY_REEXEC:-0}" != "1" ]; then
  echo "==> Updating the checkout"
  git pull --ff-only
  DEPLOY_REEXEC=1 exec "$0" "$@"
fi

echo "==> Deploying $(git log -1 --format='%h %s')"

# The supplier configuration is a separate private checkout, mounted into the
# migrate and ingestion services. Updated here so a deploy never syncs the
# sources table from a stale copy; checked here so a missing one fails with an
# explanation rather than a compose mount error.
config_dir="$(set -a; . ./.env.prod; echo "${MAKHZAN_CONFIG_DIR:-../makhzan-config}")"
if [ ! -f "${config_dir}/sources.toml" ]; then
  echo "No sources.toml in ${config_dir}. Clone the private configuration there" >&2
  echo "(or set MAKHZAN_CONFIG_DIR in .env.prod): docs/DEPLOYMENT.md, 'Private configuration'." >&2
  exit 1
fi
# Canonical links and structured data are built from SITE_URL. Unset, the web
# app falls back to localhost and every canonical in production points there,
# which is silent until a search engine reads it.
site_url="$(set -a; . ./.env.prod; echo "${SITE_URL:-}")"
if [ -z "$site_url" ]; then
  echo "SITE_URL is not set in .env.prod. Set it to the public origin," >&2
  echo "e.g. SITE_URL=https://makhzan.example.com: docs/DEPLOYMENT.md." >&2
  exit 1
fi
if [ "${SKIP_PULL:-0}" != "1" ]; then
  echo "==> Updating the configuration in ${config_dir}"
  git -C "$config_dir" pull --ff-only
fi
echo "    configuration at $(git -C "$config_dir" log -1 --format='%h %s')"

echo "==> Pulling images"
"${COMPOSE[@]}" pull

echo "==> Starting stack (migrations run first via 'migrate' service)"
"${COMPOSE[@]}" up -d

echo "==> Pruning dangling images"
docker image prune -f >/dev/null

echo "==> Status"
"${COMPOSE[@]}" ps

# "up" only means the containers started. The web app is the one published
# service and it proxies /api to the API, so a single request through it
# exercises web, the internal rewrite, the API and its database connection at
# once — which is what "deployed" is meant to mean.
if ! command -v curl >/dev/null 2>&1; then
  echo "==> curl not installed; skipping the health check"
  exit 0
fi

set -a; . ./.env.prod; set +a
port="${WEB_PORT:-3000}"

echo "==> Health check on localhost:${port}/api/health"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "http://localhost:${port}/api/health" >/dev/null 2>&1; then
    echo "    healthy"
    exit 0
  fi
  sleep 2
done

echo "The stack started but /api/health did not answer within 60s." >&2
echo "Check: ${COMPOSE[*]} logs api web" >&2
exit 1
