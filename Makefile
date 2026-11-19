# makhzan developer entrypoints.
#
# The monorepo has three Python projects with their own virtualenvs plus a pnpm
# app, so most tasks are "cd somewhere specific and run the right tool". These
# targets are the supported way to do that; docs/DEV.md explains what they do.

# Ruff lives in the ingestion venv, but is invoked from the repo root with the
# same paths CI uses. Running it from inside a project directory changes which
# config ruff discovers for files outside any project (scripts/), which once made
# `make lint` pass while CI failed on the same commit.
RUFF = $(shell cd apps/ingestion && poetry env info --path)/bin/ruff
LINT_PATHS = packages apps/api apps/ingestion scripts ml

DB_URL ?= postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan
MEILI_URL ?= http://localhost:7700
MEILI_KEY ?= dev-master-key-change-me
# A shop on the makhzanbot identity names the public site in its User-Agent, so
# the Python commands need it even in development: without it `make sources` and
# the worker refuse such a shop. Unsigned locally (no key), and only these
# commands see it, so the local web app keeps its own localhost canonicals.
CRAWLER_SITE_URL ?= https://makhzan.merope.dev
RUN_ENV = DATABASE_URL="$(DB_URL)" MEILI_URL="$(MEILI_URL)" MEILI_MASTER_KEY="$(MEILI_KEY)" SITE_URL="$(CRAWLER_SITE_URL)"

# The real supplier configuration is a private checkout beside this one. When it
# is there, every target uses it — sources, crosswalks, bespoke adapters, and its
# own tests. Without it a clone still works, on config/sources.example.toml.
PRIVATE_CONFIG ?= $(abspath ../makhzan-config)
ifneq ($(wildcard $(PRIVATE_CONFIG)/sources.toml),)
export MAKHZAN_SOURCES := $(PRIVATE_CONFIG)/sources.toml
export MAKHZAN_CROSSWALKS := $(PRIVATE_CONFIG)/crosswalks
export PYTHONPATH := $(PRIVATE_CONFIG)$(if $(PYTHONPATH),:$(PYTHONPATH))
PRIVATE_TESTS := $(wildcard $(PRIVATE_CONFIG)/tests)
endif

.PHONY: help setup infra migrate deps test test-ingestion test-api test-worker lint fmt api web worker ingest sources status freshness probe reindex regroup-dry-run retire-redirects reports overrides categories-seen ai broker admin pause db-pull db-load db-refresh deploy clean

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: infra deps migrate sources  ## One-shot: env file, services, dependencies, schema
	@echo "Ready. 'make api' and 'make web' to run the stack."

infra:  ## Start Postgres, Meilisearch and Redis
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")
	docker compose up -d db search redis

deps:  ## Install Python and web dependencies
	cd packages/schemas && poetry install
	cd apps/ingestion && poetry install
	cd apps/api && poetry install
	cd apps/web && pnpm install

# The search index's settings too, as the deploy's migrate step does: the API
# names the attributes it searches, and Meilisearch rejects a query naming one
# an older index does not list. A changed set also queues a reindex for the
# worker (`make worker` runs it).
migrate:  ## Apply database migrations and the search index's settings
	cd packages/schemas && DATABASE_URL="$(DB_URL)" poetry run alembic upgrade head
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.ensure_index

test: test-ingestion test-api test-worker  ## Run every Python test suite

# The private configuration's tests check what each crosswalk maps and refuses
# to map, so they travel with it; they run here whenever the checkout is present.
test-ingestion:  ## Run the ingestion test suite, and the private configuration's tests
	cd apps/ingestion && poetry run pytest -c pyproject.toml tests $(PRIVATE_TESTS)

# Every test session creates and drops its own database (see the conftests),
# so the suites, and several checkouts at once, can run side by side.
test-api:  ## Run the API test suite
	cd apps/api && poetry run pytest

# The AI-matching worker (ml/makhzan_ml/worker): no database and no model. The
# ingestion environment runs it because it has makhzan_schemas, which the tests
# hold the worker's pins and request hashing to.
test-worker:  ## Run the AI worker's tests (ml/tests)
	cd apps/ingestion && poetry run pytest -c pyproject.toml ../../ml/tests

lint:  ## Lint and format-check exactly what CI checks
	$(RUFF) check $(LINT_PATHS)
	$(RUFF) format --check $(LINT_PATHS)
	# The production build too: it is the only check that exercises
	# prerendering, and a page that is merely static-eligible fails there while
	# passing lint and typecheck.
	cd apps/web && pnpm lint && pnpm typecheck && NEXT_PUBLIC_API_URL=/api pnpm build

fmt:  ## Auto-format Python
	$(RUFF) format $(LINT_PATHS)

# "Report a problem" refuses reports without a salt to hash senders with; any
# value does locally.
REPORT_IP_SALT ?= dev-report-salt-change-me

api:  ## Run the API on :8000
	cd apps/api && $(RUN_ENV) REPORT_IP_SALT="$(REPORT_IP_SALT)" poetry run uvicorn app.main:app --reload

web:  ## Run the Next.js app on :3000
	cd apps/web && NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev

worker:  ## Run the Arq ingestion worker
	cd apps/ingestion && $(RUN_ENV) poetry run arq worker.main.WorkerSettings

ingest:  ## Ingest one source: make ingest SOURCE=<source-id> [LIMIT=10]
	@test -n "$(SOURCE)" || (echo "usage: make ingest SOURCE=<source-id> [LIMIT=n]"; exit 1)
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.ingest $(SOURCE) $(LIMIT)

# The table is what the worker reads; sources.toml is how rows get into it. The
# file is the private checkout's when present (see PRIVATE_CONFIG above), else
# config/sources.example.toml.
sources:  ## Seed the sources table from sources.toml (private config, else the example)
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.sources.sync $(if $(FILE),$(abspath $(FILE)))

status:  ## Show crawler progress, recent runs, catalog health and index drift
	cd apps/ingestion && $(RUN_ENV) poetry run python ../../scripts/status.py $(ARGS)

# Read-only, like status, and sends nothing to any shop: what the requests buy.
freshness:  ## Requests, staleness, changes found, false archivals per source (ARGS="--days 14")
	cd apps/ingestion && $(RUN_ENV) poetry run python ../../scripts/freshness.py $(ARGS)

# Sends real requests to every enabled source (read-only, 15 s apart per host).
probe:  ## Ask each supplier what it thinks of each crawler identity (ARGS="--source x")
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.probe $(ARGS)

reindex:  ## Rebuild products and the search index from the database
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.regroup

regroup-dry-run:  ## What a regroup would do to product ids; changes nothing (ARGS=--ai previews AI decisions)
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.regroup --dry-run $(ARGS)

retire-redirects:  ## Drop product redirects unused for a year: make retire-redirects [ARGS=--dry-run]
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.retire_redirects $(ARGS)

reports:  ## Review visitors' reports: make reports [ARGS="show 12" | "accept 12 13" | "reject 14"]
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.reports $(ARGS)

overrides:  ## Grouping rulings: make overrides [ARGS="add A B --kind never --note why" | "remove 3"]
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.overrides $(ARGS)

categories-seen:  ## Shop categories each product was listed under: make categories-seen [ARGS="--source ID"]
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.categories_seen $(ARGS)

ai:  ## AI matching: make ai ARGS="status" | "worker add NAME --models kev" | "backlog" | "mode off"
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.ai $(ARGS)

# The AI broker on :8100, its own app object (docs/ai/broker-api.md). Workers point
# at http://localhost:8100/ai/v1 locally; in production, over Tailscale.
broker:  ## Run the AI broker on :8100
	cd apps/api && DATABASE_URL="$(DB_URL)" poetry run uvicorn app.broker.main:app --reload --port 8100

# The admin dashboard on :8200 (docs/admin.md). Needs ADMIN_PASSWORD_HASH and
# ADMIN_SECRET in the environment: `cd apps/ingestion && poetry run python -m admin.password --secret`.
admin:  ## Run the admin dashboard on :8200 (ADMIN_PASSWORD_HASH, ADMIN_SECRET from the env)
	cd apps/ingestion && $(RUN_ENV) poetry run uvicorn admin.app:app --reload --port 8200

pause:  ## Crawl or shop pause: make pause ARGS="crawl off --note why" | "shop pause ID"
	cd apps/ingestion && $(RUN_ENV) poetry run python -m worker.pause $(ARGS)

# Working against real data locally. db-pull is read-only against production;
# db-load only ever touches localhost. Set DEPLOY_HOST/DEPLOY_USER/DEPLOY_PATH
# in .env.local — the same variables the deploy workflow uses.
db-pull:  ## Download a snapshot of the production database into seed/
	./scripts/db-pull.sh

db-load:  ## Replace the local database with a dump: make db-load [DUMP=seed/x.dump]
	./scripts/db-load.sh $(DUMP)

db-refresh: db-pull db-load  ## db-pull then db-load, in one step

# Runs on the server, not here: it needs .env.prod and the production stack.
# Everything a deploy consists of — update the checkout, pull the images, run
# migrations, restart, check it answers — is in the one script.
deploy:  ## Deploy on the server: update, pull images, migrate, restart
	./scripts/deploy.sh

clean:  ## Stop services (keeps volumes)
	docker compose down
