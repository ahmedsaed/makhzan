# makhzan ingestion worker

Background service that acquires supplier data and turns it into normalized `Listing` records.

Pipeline: **source adapter** (scrape / manual / portal) → **normalize** (units, bilingual fields, part numbers) → **upsert** listings with `last_verified_at` + `confidence` → **review queue** for low-confidence items.

Kept separate from the API on purpose: long-running, scheduled, and able to fail without taking the site down. Every source is a swappable adapter that can be toggled off by config.

## Local dev

Runs via the root `docker compose up` (service `ingestion`).

Standalone (Poetry):

```bash
poetry install
poetry run arq worker.main.WorkerSettings
```

> Note: Arq needs Redis for its queue (service `redis` in `docker-compose.yml`); set `WorkerSettings.redis_settings` from `REDIS_URL` when wiring up the first real queued task.
