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

# Never alongside a restore or a backup (scripts/lib/ops.sh). Taken before the
# git pull and kept across the re-exec below, which inherits it.
. scripts/lib/ops.sh
ops_production_only
ops_lock "deploy.sh"

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

# Update first, then hand over to the version we just pulled.
#
# The re-exec is not ceremony. Bash reads a script incrementally as it runs, so
# a `git pull` that rewrites this file mid-execution makes the shell resume at a
# byte offset into different text — it silently runs garbage. Replacing the
# process with the new file is the fix, and the guard stops it looping.
if [ "${SKIP_PULL:-0}" != "1" ] && [ "${DEPLOY_REEXEC:-0}" != "1" ]; then
  echo "==> Updating the checkout"
  # 9>&-: git may leave gc --auto or an ssh master running; they must not hold the lock.
  git pull --ff-only 9>&-
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
# "Report a problem" counts each sender under a salted hash of their address,
# and the salt is this secret. Unset, the API refuses every report (503) rather
# than store reports it cannot rate-limit: docs/DEPLOYMENT.md.
report_salt="$(set -a; . ./.env.prod; echo "${REPORT_IP_SALT:-}")"
if [ -z "$report_salt" ]; then
  echo "REPORT_IP_SALT is not set in .env.prod. Set it to a random secret," >&2
  echo "e.g. REPORT_IP_SALT=\$(openssl rand -base64 32): docs/DEPLOYMENT.md." >&2
  exit 1
fi
if [ "${SKIP_PULL:-0}" != "1" ]; then
  echo "==> Updating the configuration in ${config_dir}"
  git -C "$config_dir" pull --ff-only 9>&-
fi
echo "    configuration at $(git -C "$config_dir" log -1 --format='%h %s')"

# The image the running web container was started from, before the pull.
web_image="$(set -a; . ./.env.prod; set +a; echo "${IMAGE_PREFIX}/web:${IMAGE_TAG}")"
web_container="$("${COMPOSE[@]}" ps -q web 2>/dev/null || true)"
web_before="$([ -n "$web_container" ] && docker inspect -f '{{.Image}}' "$web_container" 2>/dev/null || true)"

echo "==> Pulling images"
"${COMPOSE[@]}" pull

# The web app caches API responses (Next's data cache, the `revalidate` results)
# in the web_cache volume, which outlives the container so a restart starts
# warm. Across a new web image that is a hazard: the new code reads responses
# the old API shaped. The shop contact release did exactly that: three shop
# pages failed for up to five minutes, until each cached response expired.
# So a new web image gets that cache cleared once it is up (below); a plain
# restart keeps it. Not before `up`: the old container would refill it from the
# old API while migrations run, and stopping it early would lengthen the outage.
web_after="$(docker image inspect -f '{{.Id}}' "$web_image" 2>/dev/null || true)"

echo "==> Starting stack (migrations run first via 'migrate' service)"
"${COMPOSE[@]}" up -d

if [ -n "$web_before" ] && [ "$web_before" != "$web_after" ]; then
  # Cleared, then restarted: Next also holds recent entries in memory, and the
  # new container may have read old ones from disk in its first seconds.
  echo "==> New web image: clearing its cached API responses"
  if "${COMPOSE[@]}" exec -T web sh -c 'rm -rf /app/.next/cache/fetch-cache'; then
    "${COMPOSE[@]}" restart web
  else
    echo "    (could not clear it; cached responses expire within minutes)"
  fi
fi

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
# Where compose publishes the web app (WEB_BIND), not localhost: it is bound
# to the Docker bridge only.
bind="${WEB_BIND:-172.17.0.1}"

echo "==> Health check on ${bind}:${port}/api/health"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "http://${bind}:${port}/api/health" >/dev/null 2>&1; then
    echo "    healthy"
    exit 0
  fi
  sleep 2
done

echo "The stack started but /api/health did not answer within 60s." >&2
echo "Check: ${COMPOSE[*]} logs api web" >&2
exit 1
