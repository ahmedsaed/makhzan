# Deployment

Docker Compose deployment for makhzan. Images are built and pushed by GitHub
Actions to GHCR; the server pulls them. **TLS and the reverse proxy are managed
by you** — the stack publishes only the web app on a host port for your proxy to
sit in front of. The API is not exposed: the web app proxies `/api` to it over
the internal network.

## Architecture

```
                        ┌──────────────── your server ────────────────┐
your proxy / TLS ─────▶ │  web (Next.js, host :WEB_PORT → 3000)        │
(nginx / traefik / …)   │    └─ /api/* ─rewrite─▶ api (FastAPI, internal :8000) │
                        │  ingestion (Arq worker) ─┐                   │
                        │                          ├─▶ db     (Postgres, internal) │
                        │                          ├─▶ search (Meili,    internal) │
                        │                          └─▶ redis  (Arq queue, internal)│
                        └──────────────────────────────────────────────┘
```

- **web** is the only published service (`WEB_PORT`); point your proxy at it.
  Next.js rewrites `/api/*` to the API (`API_INTERNAL_URL`, default
  `http://api:8000`) server-side, so the browser stays same-origin (no CORS) and
  the API is never exposed. Expose the API port yourself only if you need direct
  external access.
- **db / search / redis** are internal-only; state lives in named Docker volumes.
- **ingestion** runs the Arq worker; a daily cron (`REFRESH_HOUR`, UTC) re-scrapes
  all suppliers, regroups products, and reindexes search.
- **migrate** is a one-shot service that runs `alembic upgrade head` on every
  deploy before api/ingestion start.

Images: CI pushes `ghcr.io/<owner>/makhzan/{api,web,ingestion}`. The server pulls
them (it can also `docker compose ... build` if you prefer).

## One-time setup

### 1. GitHub / CI

Workflows live in `.github/workflows/`:

- `ci.yml` — ruff + web lint/typecheck/build on every PR and push.
- `build.yml` — builds & pushes the three images to GHCR on push to `main` and on
  `v*` tags. Uses the built-in `GITHUB_TOKEN`; needs **Settings → Actions →
  General → Workflow permissions → Read and write**.
- `deploy.yml` — SSHes to the server and runs `scripts/deploy.sh` on manual
  dispatch or when a Release is published. Add repo **Secrets**: `DEPLOY_HOST`,
  `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH` (e.g. `~/Documents/Projects/makhzan`).

The web image bakes in the repo **variable** `NEXT_PUBLIC_UMAMI_WEBSITE_ID`
(Settings → Secrets and variables → Actions → Variables); unset, it ships without
analytics.

After the first `build.yml` run, make the three `makhzan/*` packages **public**:
they are built from this repository and carry no supplier configuration, which
is mounted at runtime instead. Or keep them private and `docker login ghcr.io` on
the server.

### 2. Server

Docker Engine + Compose plugin are assumed present (your infra). Then:

```bash
git clone https://github.com/<owner>/makhzan.git ~/Documents/Projects/makhzan && cd ~/Documents/Projects/makhzan
cp .env.prod.example .env.prod
```

#### Private configuration

Which suppliers are crawled, their category crosswalks and any bespoke adapter
live in a separate private repository, not here and not in the images. Clone it
beside this checkout:

```bash
git clone git@github.com:<owner>/makhzan-config.git ~/Documents/Projects/makhzan-config
```

It is mounted read-only into `migrate` (which syncs `sources.toml` into the
`sources` table) and `ingestion` (which reads the crosswalks and imports the
bespoke adapters). Elsewhere, set `MAKHZAN_CONFIG_DIR` in `.env.prod`. The server
needs read access to it: a read-only deploy key on that repository is enough.
`deploy.sh` pulls it on every deploy and stops if it is missing.

Edit `.env.prod`:
- `IMAGE_PREFIX=ghcr.io/<owner>/makhzan`, `IMAGE_TAG=latest`
- strong `POSTGRES_PASSWORD` + `MEILI_MASTER_KEY` (`openssl rand -base64 32`);
  keep the password in `DATABASE_URL` in sync
- `WEB_PORT` — the host port your proxy targets (the API stays internal)
- `NEXT_PUBLIC_API_URL` — leave `/api` (the web app rewrites it to the API);
  `API_INTERNAL_URL` (default `http://api:8000`) is the internal rewrite target
- `SITE_URL` — the site's public origin, e.g. `https://makhzan.merope.dev`.
  Canonical links and the product pages' structured data are built from it (at
  runtime, never from request headers). `deploy.sh` stops if it is unset,
  because the fallback is `http://localhost:3000`
- `WEB_ORIGINS` — CORS allow-list; unused in the default same-origin topology

### 3. Seed the data

The catalog is seeded from an exported DB dump (real data, no first-run scrape).
See `seed/README.md`.

```bash
# From a machine that has the data:
docker compose exec -T db pg_dump -U makhzan -Fc makhzan > seed/makhzan-seed.dump
scp seed/makhzan-seed.dump <user>@<server>:~/Documents/Projects/makhzan/seed/

# On the server:
./scripts/restore-seed.sh      # restores the dump + rebuilds the search index
```

(To start empty and scrape instead, skip this and run `./scripts/seed.sh` after
the first deploy.)

### 4. Deploy

```bash
make deploy                    # or ./scripts/deploy.sh, if make isn't installed
```

Point your reverse proxy at `WEB_PORT` (and the API per `NEXT_PUBLIC_API_URL`),
terminate TLS there, and you're live.

## Day-2 operations

`./makhzan` (repo root) wraps the common ones: `status`, `deploy`, `crawl on|off`,
`logs`, `stop`, `start`, `backup`, `migrate`, `retire`. Run it on the server, or from a
laptop with `DEPLOY_HOST` set (it re-runs itself over SSH). `status` is the one
to reach for first: containers, health, whether the crawl is paused, and the full
crawler report from `scripts/status.py`, read from the live database.

| Task | Command |
|---|---|
| Deploy latest | `make deploy` (or publish a Release → auto-deploy) |
| Restart without updating | `SKIP_PULL=1 ./scripts/deploy.sh` |
| Run migrations only | `./scripts/migrate.sh` |
| Re-seed from a dump | `./scripts/restore-seed.sh [path]` |
| Full re-scrape + reindex now | `./scripts/seed.sh` |
| Remove a source and its listings | Delete it from `sources.toml` in the private configuration and deploy, then `./makhzan retire <source-id>` (a dry run) and again with `--yes`. Rebuilds products and the index. |
| What a regroup would do to product ids | `docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps ingestion python -m worker.regroup --dry-run` (kept / new / merged / split / emptied; changes nothing) |
| Drop redirects unused for a year | Runs daily after the regroup; by hand, the same `run` with `python -m worker.retire_redirects [--dry-run]` (`docs/decisions/0005-url-retirement.md`) |
| Pause / resume the daily crawl | `./makhzan crawl off` (or `on`); sets `CRAWL_ENABLED` in `.env.prod` and recreates the worker |
| Back up the DB | `./scripts/backup-db.sh` → `backups/*.sql.gz` |
| Logs | `docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api` |
| Status | `docker compose -f docker-compose.prod.yml --env-file .env.prod ps` |

Nightly backup cron:

```
0 2 * * * ~/Documents/Projects/makhzan/scripts/backup-db.sh >> ~/Documents/Projects/makhzan/backups/backup.log 2>&1
```

## Deploying

### November 2026 release

Once, in this order, on the server from `~/Documents/Projects/makhzan`:

0. **Back up the database:** `./makhzan backup`. The regroup in step 4 rewrites
   every product row; this is the way back.
1. **Set `SITE_URL`** in `.env.prod`: `SITE_URL=https://makhzan.merope.dev`.
   `deploy.sh` stops without it.
2. **Merge the code and wait for `build.yml` to publish the images** before
   anything pulls the private configuration. Its crosswalks now use `prefer`, and
   an image older than this release rejects a crosswalk key it does not know: the
   `migrate` service's sources sync fails and the deploy stops (as would the
   worker's next run). `deploy.sh` pulls the configuration itself, so do not
   pull it by hand beforehand.
3. **Deploy:** `make deploy`.
4. **Regroup once.** Grouping changed, and the command also rebuilds the search
   index, which gains `supplier_slugs` (search within a shop) and `category_refs`
   (a category and its ancestors). Until it runs, `/search?shop=`, every category
   filter and the trade pages' results fail:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps ingestion python -m worker.regroup
   ```

   Product ids follow group keys (`docs/decisions/0004-stable-product-ids.md`), so
   the products the new rules regroup get new ids: about 430 on the local
   snapshot. Their old URLs keep working: the rebuild records where each one's
   offers went (`product_redirects`, created by this release's migration) and the
   product page answers an old id with a 308. That only holds if this release's
   images are what runs the regroup, which is why it comes after step 3. Never
   `worker.backfill` here: it erases crosswalk categories. (From the permanent-ids
   release on, below, a regroup keeps ids instead: merges redirect, nothing is
   deleted.)
5. **Check it:**
   - `./makhzan status`: containers healthy, the search index in step with the
     database ("drift" none), the regroup's product count.
   - The site: home, a product, `/trades`, `/shops`, light and dark.
   - Old URLs: `curl -sI https://makhzan.merope.dev/en/browse/electronics` answers
     308 to `/trades/electronics`.
6. **Resume the crawl:** `./makhzan crawl on`. Categories, specs and the other
   enrichment, and the removal of non-products, land as each source is
   re-crawled: one cycle per source, about a week. Two sources still block the
   server's address and will not refresh until their shops allowlist it.

### Permanent product ids (November 2026)

`docs/decisions/0004-stable-product-ids.md`. Nothing to do by hand beyond the
usual order:

1. `./makhzan backup`.
2. Merge, wait for `build.yml`, `make deploy`. The migration (`32ed14ef673e`) adds
   `products.merged_into`/`merged_at`/`delisted_at`/`redirect_used_at`,
   `product_redirects.last_used_at` and `product_events`, and makes `group_key`
   non-unique. It moves no data.
3. Optionally, before the next regroup, see what it will do:
   `docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps ingestion python -m worker.regroup --dry-run`.
   Expect almost every id kept (on the local snapshot: all of them) and no merges.
4. The daily cron's regroup applies it; `python -m worker.regroup` does it now.
   `./makhzan status`'s search drift compares the index with *listed* products.

**Rollback** past this release is not image-only: an older image deletes products
by group key and trips over `merged_into`. Run
`alembic downgrade 96e50c11754e` first (it deletes merged-away and emptied rows so
`group_key` can be unique again), then roll the image back.

### Shop data release (November 2026)

New adapter settings live in the private configuration (`feat/woo-enrichment`:
price breaks, hidden out-of-stock items, description sections, compatibility). An
image older than this release rejects them, and the `migrate` service's sources sync
fails, which keeps **api and ingestion from starting at all**, not just the shops
concerned. So, strictly in this order:

1. Merge the code; wait for `build.yml` to publish the images.
2. Only then merge and push the private configuration's `feat/woo-enrichment`.
3. `make deploy`. Two migrations run on their own: `suppliers.contact` and
   `sources.cycle_data`, then `listings.last_seen_at` (backfilled from
   `last_verified_at`, so the cycle in flight archives nothing it should not).
4. `./makhzan status`. The first run of each source's next cycle makes its
   once-a-cycle requests (variations, category tree, shop contact; price breaks
   where enabled): a few to ~50 per shop.

If a deploy pulls a configuration the running image cannot read, restart on what
is there with `SKIP_PULL=1 ./scripts/deploy.sh` and finish the order above.

One command on the server, from `~/Documents/Projects/makhzan`:

```bash
make deploy          # = ./scripts/deploy.sh
```

It updates the checkout (`git pull --ff-only`), pulls the new images, brings the
stack up — which runs migrations first via the one-shot `migrate` service —
prunes dangling images, and then checks the site actually answers on
`/api/health`. That last step goes through the published web service, so one
request exercises web, the internal `/api` rewrite, the API and its database
connection; "the containers started" is not the same as "the deploy worked".

The `git pull` is part of it because only half of what runs comes from the
images. `docker-compose.prod.yml`, the `migrate` service's command and these
scripts all come from the checkout, so pulling images alone runs new code under
an old compose file. `--ff-only` means a server with hand-edits stops with an
error rather than merging; fix it there, then re-run.

`SKIP_PULL=1 ./scripts/deploy.sh` restarts on the current checkout without
updating — for restarting after an `.env.prod` change, or for staying put while
investigating something.

Two things worth knowing:

- **Images are `latest`.** `build.yml` takes a few minutes, so a deploy run
  immediately after a merge can pull a `latest` that predates it: the stack
  restarts cleanly and the change is not in it. Check the build has finished
  before deploying. (The script prints the commit it deployed, which is the
  checkout — not proof of which images came down.)
- **Rollback is by tag.** Set `IMAGE_TAG` in `.env.prod` to a published tag
  (`build.yml` tags every build `sha-<short>`) and re-run. Migrations already
  applied stay applied, so the older image must still work against the newer
  schema.

## Updating

- **Code** → merge to `main`. `build.yml` publishes new images; publish a Release
  (auto-deploy) or run `make deploy` on the server.
- **Schema** → add an Alembic revision under
  `packages/schemas/migrations/versions/`; it applies automatically on the next
  deploy via the `migrate` service.
- **New supplier, or a crosswalk fix** → add a `[[source]]` to `sources.toml`
  (and its crosswalk under `crosswalks/`) in the private configuration repository,
  push, deploy. No image is rebuilt: `deploy.sh` pulls that checkout and the
  `migrate` service
  syncs the file into the `sources` table on every deploy, and the next daily
  run picks the source up — no code change. To start it at once rather than at
  the next cron tick, `./scripts/seed.sh`.

## Notes & troubleshooting

- **API is proxied through the web app.** The browser calls `/api` (baked at
  build); the Next.js server rewrites it to `API_INTERNAL_URL` (runtime). To reach
  the API directly from outside instead, publish its port in
  `docker-compose.prod.yml` and set `NEXT_PUBLIC_API_URL` to that URL (rebuild web).
- **`migrate` fails** → check `DATABASE_URL` matches `POSTGRES_USER/PASSWORD/DB`,
  uses host `db` and the `+asyncpg` driver.
- **Search empty after restore** → `restore-seed.sh` rebuilds the index; rerun it,
  or `docker compose ... run --rm --no-deps ingestion python -m worker.reindex`.
- **Resources** → 2 vCPU / 2–4 GB is comfortable. Add swap if the box is small.
