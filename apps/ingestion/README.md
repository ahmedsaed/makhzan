# makhzan ingestion worker

Background service that acquires supplier data and turns it into normalized `Listing` records.

Pipeline: **source adapter** (WooCommerce, Shopify, Odoo, Wix, or a bespoke one named by import path from the private configuration) → **normalize** (units, bilingual fields, part numbers) → **upsert** listings with `last_verified_at` + `confidence` → **review queue** for low-confidence items.

After each crawl it regroups listings into products and rebuilds the search index (`rebuild_and_reindex`), then queues the AI matching candidates (`ai_candidates`).

Kept separate from the API on purpose: long-running, scheduled, and able to fail without taking the site down. Every source is a row in the `sources` table, seeded from `sources.toml`, and can be turned off there or paused in the database (`worker/pause.py`).

The same image runs the internal admin dashboard (`admin/`, `uvicorn admin.app:app` on port 8200): `docs/admin.md`. How ingestion works in detail is in the root `CLAUDE.md`; the commands are `make help` and `./makhzan help`.

## Local dev

Runs via the root `docker compose up` (service `ingestion`).

Standalone (Poetry):

```bash
poetry install
poetry run arq worker.main.WorkerSettings
```

Arq needs Redis for its queue (service `redis` in `docker-compose.yml`); `WorkerSettings.redis_settings` reads `REDIS_URL`. From the repo root, `make worker` runs it with the private configuration on the path.

Tests: `make test-ingestion` from the root (needs Postgres; the suite makes and drops its own database).
