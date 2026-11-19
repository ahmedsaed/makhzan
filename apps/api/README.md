# makhzan API

FastAPI backend for makhzan. Serves the consumer search/browse API (read-only,
apart from "Report a problem", `POST /reports`). Reads from Postgres +
Meilisearch; search returns products from the `products` index the worker
rebuilds (`docs/DEV.md`, "Search index"). There is no supplier portal.

The same image also runs the AI broker, a separate app object
(`app.broker.main:app`, port 8100, never under `/api`): `docs/ai/broker-api.md`,
`docs/ai/broker-deploy.md`, `make broker` locally.

## Local dev

Runs via the root `docker compose up` (service `api`, port 8000).

Standalone (Poetry):

```bash
poetry install
poetry run uvicorn app.main:app --reload
```

Health check: http://localhost:8000/health · Docs: http://localhost:8000/docs

## Tests

```bash
poetry run pytest          # or, from the repo root: make test-api
```

They need a reachable Postgres (`docker compose up -d db` at the root) and
nothing else — the suite creates its own database (`makhzan_api_test` suffixed
with the process id or `TEST_DB_SUFFIX`), builds the schema from the ORM
metadata, truncates between tests and drops it at the end. It is a different
database from the ingestion suite's, so the two can run at the same time.

The app is exercised in-process over an ASGI transport with its real dependency
graph and a real database. Only Meilisearch is faked: the interesting behaviour
in `app/search.py` is which filters and attributes get sent, and a filter on the
wrong attribute comes back as a plausible result set rather than an error.
