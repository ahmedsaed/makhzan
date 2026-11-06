# Local development

## Prerequisites
- Docker (for Postgres, Meilisearch, Redis)
- Poetry (Python deps)
- pnpm (web deps) — `corepack enable pnpm`

## Quick start

```bash
make setup     # .env + services + dependencies + migrations
make test      # verify the ingestion + api suites pass
make api       # then, in another shell: make web
```

`make help` lists every target. The rest of this document explains what those
targets do and how to work with the pieces individually.

## 1. Environment
```bash
cp .env.example .env
```

## 2. Infrastructure
Bring up the backing services (no image builds needed):
```bash
docker compose up -d db search redis
```
Postgres → `localhost:5432`, Meilisearch → `localhost:7700`, Redis → `localhost:6379`.

## 3. Database migrations
Migrations live in `packages/schemas` (Alembic, async). Run from there.
`DATABASE_URL` points at `db` inside compose, so from the host use `localhost`:
```bash
cd packages/schemas
poetry install
DATABASE_URL="postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan" \
  poetry run alembic upgrade head
```
After changing a model in `makhzan_schemas/models.py`, autogenerate a revision:
```bash
DATABASE_URL="postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan" \
  poetry run alembic revision --autogenerate -m "describe change"
# review the generated file in migrations/versions/ before committing, then upgrade
```

## 4. Run an ingestion (bounded, for testing)

Sources are rows in the `sources` table, seeded from a `sources.toml`
(`make setup` does this; re-run `make sources` after editing the file):
```bash
make sources                              # upsert every source in the file
make ingest SOURCE=<source-id> LIMIT=10
```
The real suppliers and their crosswalks are in a private repository. Clone it
beside this one, as `../makhzan-config`, and every `make` target picks it up —
sources, crosswalks, bespoke adapters, and its tests in `make test-ingestion`
(`PRIVATE_CONFIG=<path>` if it lives elsewhere). Without it, a clone runs on
`config/sources.example.toml`: the fixture source only, no crosswalks, and the
per-crosswalk tests skip. That file also documents the format.
Omit `LIMIT` for a full run.

`limit=` also keeps the run *ephemeral*: cursors are left untouched and nothing
is archived, so testing never disturbs a real sweep's resume point.

A full run sweeps every partition of the source and checkpoints after each page.
To run one partition on its own — the unit of work for splitting a source across
workers — use `run_partition`:
```bash
DATABASE_URL="postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan" \
  poetry run python -c "
import asyncio
from worker.sources.registry import load_adapters, get
from worker.pipeline import run_partition
async def main():
    await load_adapters()
    await run_partition('shop-a', get('shop-a'), 'instock')
asyncio.run(main())
"
```
Inspect resume state with `select * from source_cursors;` — `next_page` is where
the next run picks up, and `exhausted` marks partitions already swept this cycle.

## 4b. Working against real data

Logic changes to grouping, crosswalks or search are hard to judge against a
handful of fixtures — the failures that matter (a family prefix gluing 22
listings together, a crosswalk key that stopped matching) only appear at
catalogue scale. So pull production down and work on a copy:

```bash
cp .env.local.example .env.local   # then fill in DEPLOY_HOST
make db-refresh                    # = db-pull + db-load
```

Separately if you prefer:

```bash
make db-pull                       # snapshot into seed/, read-only on the server
make db-load                       # replace the local DB with the newest dump
make db-load DUMP=seed/older.dump  # or a specific one
```

`db-pull` runs `pg_dump` inside the production db container and streams the
result back over SSH. It writes nothing on the server and does not block
writers, so it is safe against a live stack. Connection details come from
`DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_PATH` — the same variables `deploy.yml`
uses — read from `.env.local`, which is git-ignored along with the dumps.

`db-load` **drops your local database** and rebuilds it from the dump, then
applies migrations (a dump is only current to the day it was taken), resets the
sweep cursors, and rebuilds products and the search index. It only ever talks to
localhost. `SKIP_REINDEX=1` skips the last step; `CONFIRM=yes` skips the prompt.

> **Why the cursor reset is not optional.** A dump carries whatever sweep state
> the server had mid-cycle: which partitions were already visited, and when the
> cycle started. Archiving is cycle-gated and keys off `cycle_started_at`, so a
> restored mid-cycle state makes the first local sweep believe the partitions it
> did not visit were checked and never seen — and retire them. A dump taken
> mid-session would have archived roughly 16,600 live listings of the largest supplier. Cursors
> are progress, not data, so clearing them costs nothing.

After a load, `make status` shows what you have, and the product IDs will differ
from the server's if grouping has changed since the dump was taken.

## 5. Search index
The Meilisearch index (`listings`) is a rebuildable projection of the DB.
Ingestion indexes incrementally; to rebuild from scratch:
```bash
cd apps/ingestion
DATABASE_URL="postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan" \
MEILI_URL="http://localhost:7700" MEILI_MASTER_KEY="dev-master-key-change-me" \
  poetry run python -c "
import asyncio
from makhzan_schemas.db import SessionLocal
from worker.indexer import get_client, reindex_all
async def main():
    async with SessionLocal() as s:
        print('indexed', await reindex_all(s, get_client()))
asyncio.run(main())
"
```

## 6. API
```bash
cd apps/api
poetry install
DATABASE_URL="postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan" \
MEILI_URL="http://localhost:7700" MEILI_MASTER_KEY="dev-master-key-change-me" \
  poetry run uvicorn app.main:app --reload   # http://localhost:8000
```
Tests (needs Postgres running; creates its own `makhzan_api_test` database):
```bash
make test-api            # or: cd apps/api && poetry run pytest
```

Endpoints:
- `GET /health`
- `GET /search?q=ESP32&category=resistors&in_stock=true&min_price=&max_price=&supplier=&sort=price:asc&limit=&offset=`
- `GET /listings/{id}` (includes nested supplier + category + description)
- `GET /categories` (taxonomy with per-category listing counts)
- `GET /docs` (OpenAPI UI)

Web routes: `/` (search, category bar, load-more) and `/listings/[id]` (detail).

**Categories:** the taxonomy + keyword resolver live in `makhzan_schemas/taxonomy.py`.
Backfill existing listings + reindex with `poetry run python -m worker.backfill`
(from `apps/ingestion`). New ingestion assigns categories automatically.

## 7. Web (Next.js + shadcn/ui)
Uses **pnpm** (shadcn's Base UI template). Enable via corepack if needed: `corepack enable pnpm`.
```bash
cd apps/web
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev   # http://localhost:3000
```
Add UI components: `pnpm dlx shadcn@latest add <name>`.
The browser calls the API cross-origin, so the API must allow the web origin —
set `WEB_ORIGINS` when starting the API (default already allows :3000).

> **Port conflicts:** if 3000/8000 are already in use, run the web app on another
> port (`npm run dev -- -p 3100`), start the API on a free port
> (`uvicorn ... --port 8001`) with `WEB_ORIGINS=http://localhost:3100`, and set
> `NEXT_PUBLIC_API_URL=http://localhost:8001` for the web app.

> Full containerized run (`docker compose up` building api/ingestion images) also
> works, but the above host-side loop is faster for iterating.
