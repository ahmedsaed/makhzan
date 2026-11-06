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
LINT_PATHS = packages apps/api apps/ingestion scripts

DB_URL ?= postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan
MEILI_URL ?= http://localhost:7700
MEILI_KEY ?= dev-master-key-change-me
RUN_ENV = DATABASE_URL="$(DB_URL)" MEILI_URL="$(MEILI_URL)" MEILI_MASTER_KEY="$(MEILI_KEY)"

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

.PHONY: help setup infra migrate deps test test-ingestion test-api lint fmt api web worker ingest sources status reindex db-pull db-load db-refresh deploy clean

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

migrate:  ## Apply database migrations
	cd packages/schemas && DATABASE_URL="$(DB_URL)" poetry run alembic upgrade head

test: test-ingestion test-api  ## Run every Python test suite

# The private configuration's tests check what each crosswalk maps and refuses
# to map, so they travel with it; they run here whenever the checkout is present.
test-ingestion:  ## Run the ingestion test suite, and the private configuration's tests
	cd apps/ingestion && poetry run pytest -c pyproject.toml tests $(PRIVATE_TESTS)

# Its own database, so the two suites can run side by side without one
# truncating the other's tables mid-test.
test-api:  ## Run the API test suite
	cd apps/api && poetry run pytest

lint:  ## Lint and format-check exactly what CI checks
	$(RUFF) check $(LINT_PATHS)
	$(RUFF) format --check $(LINT_PATHS)
	# The production build too: it is the only check that exercises
	# prerendering, and a page that is merely static-eligible fails there while
	# passing lint and typecheck.
	cd apps/web && pnpm lint && pnpm typecheck && NEXT_PUBLIC_API_URL=/api pnpm build

fmt:  ## Auto-format Python
	$(RUFF) format $(LINT_PATHS)

api:  ## Run the API on :8000
	cd apps/api && $(RUN_ENV) poetry run uvicorn app.main:app --reload

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

reindex:  ## Rebuild products and the search index from the database
	cd apps/ingestion && $(RUN_ENV) poetry run python ../../scripts/reindex.py

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
