#!/usr/bin/env bash
# Apply Alembic migrations against the production DB (alembic upgrade head).
# `deploy.sh` already does this via the `migrate` service; use this to run
# migrations on their own.
#
#   ./scripts/migrate.sh
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib/ops.sh
ops_lock "migrate.sh"

docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm migrate
echo "==> Migrations applied"
