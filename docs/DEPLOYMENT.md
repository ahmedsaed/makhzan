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
- **ingestion** runs the Arq worker; a daily cron (`REFRESH_HOUR`, UTC) queues one
  job per enabled supplier, each with its own timeout, and every supplier job
  queues a shared regroup-and-reindex when it ends; the first of those each day
  also retires product redirects unused for a year.
- **migrate** is a one-shot service that runs `alembic upgrade head` on every
  deploy before api/ingestion start. The previous release keeps serving while it
  runs, so a migration must not drop or rename anything that release reads:
  add the new column in one release and drop the old one in a later one
  (expand/contract). `suppliers.phone` went this way: kept by `2b656e4b5adc`,
  dropped by `772533d06b60` once the live release no longer mapped it.

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
- `REPORT_IP_SALT` — a random secret (`openssl rand -base64 32`). "Report a
  problem" (`POST /reports`) counts each sender under an HMAC of their address
  with it, kept 24 hours, never the address itself. `deploy.sh` stops if it is
  unset, and the API refuses reports without it. Changing it resets every
  sender's count, nothing else.
- `TRUSTED_PROXY_HOPS` — how many entries at the right of `X-Forwarded-For`
  our own proxies wrote (default 1). The API sees only the web container as its
  peer, so the visitor's address, for the report rate limit, is the entry that
  many from the right of that header, believed only when the peer is on a
  private network (`TRUSTED_PROXY_NETWORKS`, default loopback and the private
  ranges). Next's rewrite passes the header through unchanged. See "Visitor
  addresses behind the proxy" below for what the proxy must do.

#### Visitor addresses behind the proxy

The report rate limit is only as good as the address it counts, and in
production that address is decided by the reverse proxy, not by the app:

```
visitor -> Cloudflare -> Nginx Proxy Manager (host) -> 172.17.0.1:3000 web -> api
```

- **The proxy host restores the visitor's address.** Its nginx config has
  `real_ip_header CF-Connecting-IP;` with `set_real_ip_from` for each of
  Cloudflare's published ranges, so `$remote_addr` is the visitor, not a
  Cloudflare edge. Then `proxy_set_header X-Forwarded-For
  $proxy_add_x_forwarded_for;` appends it, and `TRUSTED_PROXY_HOPS=1` reads
  exactly that entry.
- **If those directives go, nothing errors.** `$remote_addr` becomes the edge,
  and everyone who reaches makhzan through one Cloudflare edge shares a single
  limit of 5 reports an hour. Setting `TRUSTED_PROXY_HOPS=2` instead is *not*
  the fix: the entry left of the edge is whatever arrived in the request's own
  `X-Forwarded-For`, which a visitor can write. Restore the visitor at the
  proxy, from the CDN's header, for the CDN's ranges only.
- **Keep the ranges current.** A Cloudflare range missing from
  `set_real_ip_from` makes its visitors look like that edge; a range listed that
  is not Cloudflare's lets anyone there send `CF-Connecting-IP` and pick their
  address.
- **The web port must not be reachable except through the proxy.** The API
  trusts `X-Forwarded-For` from the web container, and Next's rewrite forwards
  whatever a request carries, so a request straight to the web port picks the
  address the rate limit counts. Bind or firewall it so only the proxy reaches it.

This document is internal. /how-we-crawl does not name the CDN; /privacy
names Cloudflare as handling every request (the owner's decision, November
2026), and promises that **the web server's access log, with IP addresses, is
deleted after 30 days**. That promise is kept on the proxy host, not in this
repository: its log rotation must delete access logs older than 30 days
(`ACCESS_LOG_DAYS` in `apps/web/lib/content/privacy.ts`). Change one, change
both.

### 3. Seed the data

The catalog is seeded from an exported DB dump (real data, no first-run scrape).
See `seed/README.md`.

```bash
# From a machine that has the data:
docker compose exec -T db pg_dump -U makhzan -Fc makhzan > seed/makhzan-seed.dump
scp seed/makhzan-seed.dump <user>@<server>:~/Documents/Projects/makhzan/seed/

# On the server:
./scripts/restore-seed.sh      # restore-db.sh on seed/makhzan-seed.dump: restores,
                               # migrates, rebuilds the search index (asks first)
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
`logs`, `stop`, `start`, `backup`, `migrate`, `retire`, `probe`, `reports`. Run it on the server, or from a
laptop with `DEPLOY_HOST` set (it re-runs itself over SSH). `status` is the one
to reach for first: containers, health, whether the crawl is paused, and the full
crawler report from `scripts/status.py`, read from the live database.

| Task | Command |
|---|---|
| Deploy latest | `make deploy` (or publish a Release → auto-deploy) |
| Restart without updating | `SKIP_PULL=1 ./scripts/deploy.sh` |
| Run migrations only | `./scripts/migrate.sh` |
| Re-seed from a dump | `./scripts/restore-seed.sh [path]` (= `./makhzan restore`, default file `seed/makhzan-seed.dump`) |
| Full re-scrape + reindex now | `./scripts/seed.sh` |
| Remove a source and its listings | Delete it from `sources.toml` in the private configuration and deploy, then `./makhzan retire <source-id>` (a dry run) and again with `--yes`. Rebuilds products and the index. |
| What a regroup would do to product ids | `docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps ingestion python -m worker.regroup --dry-run` (kept / new / merged / split / emptied; changes nothing) |
| Drop redirects unused for a year | Automatic: the first product rebuild of each day (the worker's `rebuild_and_reindex` job) does it, and records the day and counts in `worker_state` under `redirects_retired`. By hand, the same `run` with `python -m worker.retire_redirects [--dry-run]` (`docs/decisions/0005-url-retirement.md`) |
| Review visitors' reports | `./makhzan reports` lists new ones, oldest first, each with the offers as the page showed them; `./makhzan reports show 12` adds the reporter's email; `./makhzan reports accept 12 13` / `reject 14` set `status` and `reviewed_at`. Nothing else happens on accept yet: correct the page by hand. |
| Erase reporters' data past its time | Automatic: the worker's `purge_reports` cron, every 10 minutes, erases an email 90 days after its report was sent (reviewed or not) and an address hash 24 hours after it, as /privacy says. By hand: `./makhzan reports purge` |
| Pause / resume the daily crawl | `./makhzan crawl off` (or `on`); sets `CRAWL_ENABLED` in `.env.prod` and recreates the worker, which states the flag in the database for /how-we-crawl |
| Back up the DB | `./makhzan backup` → `backups/makhzan-<ts>.dump`, read back before it is kept |
| Restore the DB | `./makhzan restore <file>`: see [Backup and restore](#backup-and-restore) |
| Logs | `docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f api` |
| Status | `docker compose -f docker-compose.prod.yml --env-file .env.prod ps` |

### Crawler signing key

Sources with `identity = "makhzanbot"` sign their requests with Web Bot Auth
(`docs/crawler-identity.md`). The key is an Ed25519 private key, held only in
`.env.prod` on the server. It is never committed to this repository or to the
private configuration.

Two services read it from `.env.prod`:

- `ingestion` uses it to sign the crawler's requests.
- `api` publishes the public key at `/.well-known/http-message-signatures-directory`
  and signs that response with the private key.

The API needs the private key, not only the public one: the directory response
must be signed by every key it lists, with a short `expires`, so the signature
is made per request. A signature made in advance would need a long expiry,
which verifiers distrust, and signing with a separate key would prove nothing
about the listed keys. Nothing else in the API uses the key.

`SITE_URL` must also be set, to the public `https://` origin: the User-Agent and
the `Signature-Agent` header both name it. A source set to makhzanbot without it
is refused when `migrate` syncs `sources.toml`, so the deploy fails rather than
every daily run.

**The clock must be right.** A signature is valid for 60 seconds after
`created`. A server clock that drifts by more than that makes every signed
request fail verification. Check with `timedatectl`; it should show
`System clock synchronized: yes` and `NTP service: active`. If not, run
`sudo timedatectl set-ntp true`.

**Generate a key.** This prints the env line, the public JWK and its keyid, and
sends nothing:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  run --rm --no-deps ingestion python -m worker.botauth keygen
```

Paste the `MAKHZANBOT_SIGNING_KEY=…` line into `.env.prod`. Then run
`./scripts/deploy.sh`, which recreates `api` and `ingestion` with it.

**Verify the directory** from outside:

```bash
curl -sS -D - -o - --max-redirs 0 \
  "$SITE_URL/.well-known/http-message-signatures-directory"
```

Expect all of the following:

- `HTTP/… 200`, not a 30x;
- `content-type: application/http-message-signatures-directory+json`;
- `signature-input: sig1=("@authority";req);…;tag="http-message-signatures-directory"`
  and a `signature` header;
- a body of `{"keys":[{"kty":"OKP","crv":"Ed25519","x":"…"}]}`.

A 404 means the API has no key. A redirect means a proxy in front of the web
app is rewriting the path, which verifiers reject; fix the proxy.

To check that the keyid matches what you registered:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  exec ingestion python -m worker.botauth show
```

**Rotate.** The research note's schedule; the waiting periods are for
verifiers, the code does not need them. The directory publishes up to three
keys. Only `MAKHZANBOT_SIGNING_KEY` ever signs requests.

1. Generate a new key and set it as `MAKHZANBOT_SIGNING_KEY_NEXT`, then deploy.
   The directory lists both keys and requests are still signed with the
   current one.
2. Once the directory has been live for a week, switch:
   - `MAKHZANBOT_SIGNING_KEY_PREVIOUS` = the old key;
   - `MAKHZANBOT_SIGNING_KEY` = the new key;
   - `MAKHZANBOT_SIGNING_KEY_NEXT` emptied.

   Deploy. Requests are now signed with the new key, and the old one stays
   published for verifiers with a cached directory.
3. A week later, empty `MAKHZANBOT_SIGNING_KEY_PREVIOUS` and deploy.
4. If a vendor registered the keyid rather than the directory, update it there.

**A leaked key:** replace `MAKHZANBOT_SIGNING_KEY` at once, leave `…_NEXT` and
`…_PREVIOUS` empty, and deploy. Signed requests then use only the new key, and
the leaked one leaves the directory.

## Backup and restore

**Not done yet:** scheduled backups and off-site copies are a separate, pending
task. Today backups are taken by hand and live only on the server, next to the
database they protect, so copy them off the box yourself. (Earlier versions of
this page suggested a nightly cron of `backup-db.sh`; if one was installed, it
keeps working and now writes `.dump` files. It fails, visibly, if it collides
with a deploy or restore.)

1. **Take one:** `./makhzan backup` writes `backups/makhzan-<ts>.dump`
   (`pg_dump -Fc`). It reads the whole file back with `pg_restore` and fails
   loudly if it cannot, or if it has no `alembic_version` data, so a 0-byte or
   truncated backup is never kept under its final name. It keeps the 14 newest
   backups, and separately every `*-pre-restore.dump` safety copy from the
   last 7 days (never fewer than 3). A pruning failure is only a warning.
2. **Copy it off the box**, from your laptop:
   `scp <user>@<server>:~/Documents/Projects/makhzan/backups/makhzan-<ts>.dump .`
3. **Test-restore it into a scratch database** now and then, without touching the
   live one:

   ```bash
   C="docker compose -f docker-compose.prod.yml --env-file .env.prod"
   $C exec -T db createdb -U makhzan restore_check
   $C exec -T db pg_restore -U makhzan -d restore_check --exit-on-error --no-owner < backups/makhzan-<ts>.dump
   $C exec -T db psql -U makhzan -d restore_check -c "SELECT version_num FROM alembic_version" \
     -c "SELECT count(*) FROM products WHERE merged_into IS NULL AND delisted_at IS NULL"
   $C exec -T db dropdb -U makhzan restore_check
   ```

   If a step fails, the last line still needs running: `restore_check` stays
   behind otherwise. An older plain-SQL backup (`*.sql.gz`) loads with
   `gunzip -c F | $C exec -T db psql -U makhzan -d restore_check -v ON_ERROR_STOP=1`.
4. **Full restore:** pause releases first (publishing one deploys), open `tmux`
   or `screen`, then `./makhzan restore backups/makhzan-<ts>.dump` (or a legacy
   `*.sql.gz`). It shows the stack and database and asks you to type the
   database name (`--yes` skips that), then:
   - backs up the current database to `backups/makhzan-<ts>-pre-restore.dump`
     (`--no-safety-backup` skips it; skipped by itself only when the database
     has no products table or an empty one, as on a fresh server);
   - stops `api` and `ingestion`;
   - loads the file into a scratch database `<db>_restoring`, stopping at the
     first error, and refuses it unless it has one alembic version, products,
     listings, the core tables' primary keys and foreign keys;
   - runs the deploy's `migrate` service against the scratch database, so an
     older backup comes up to the current schema and a broken one fails there;
   - only then drops the live database and renames the scratch one into place;
   - rebuilds the search index, starts `api` and `ingestion` again and prints the
     alembic version, listed products, listings and newest crawl run.

   Everything is also written to `backups/restore-<ts>.log`. A failure before
   the swap leaves the live database untouched and starts the services again,
   and that includes Ctrl-C, a dropped SSH session and a kill: the cleanup
   runs and its report reaches the log even when the terminal is gone. A
   failure during or after the swap prints what Postgres reports and the exact
   commands to finish, or to go back to the safety copy.

   Restore, backup, deploy (and the release workflow's `git pull`) and
   `migrate.sh` share a lock (`backups/.ops.lock`): while one runs, the others
   refuse to start. `./makhzan start`, `stop` and `crawl on|off` do not take
   it; do not use them while a restore runs, since starting `api` or
   `ingestion` mid-restore points them at a database being replaced.

   The crawl resumes from the backup: `source_cursors` come back with everything
   else, so a sweep in progress continues from the backup's page and the pages
   swept since are swept again. Runs the backup caught mid-way are closed as
   interrupted when the worker starts. Nothing needs resetting: cursors and
   listings are from the same moment. (`db-load.sh`, which loads a server dump into
   a *dev* database, does reset them.) Products come back as the backup had them;
   the worker regroups them on its next rebuild, after the next crawl.

`MAKHZAN_ENV_FILE` and `MAKHZAN_COMPOSE_FILE` point `backup-db.sh` and
`restore-db.sh` at another stack, for trying a restore without production. They
refuse unless `COMPOSE_PROJECT_NAME` is set too: without it another env file
still addresses the production containers.

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
2. Merge, wait for `build.yml`, `make deploy`. The migration (`32ed14ef673e`, after
   the crawler release's `afbb04810ff9`) adds
   `products.merged_into`/`merged_at`/`delisted_at`/`redirect_used_at`,
   `product_redirects.last_used_at` and `product_events`, and makes `group_key`
   non-unique. It moves no data.
3. Optionally, before the next regroup, see what it will do:
   `docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps ingestion python -m worker.regroup --dry-run`.
   Expect almost every id kept (on the local snapshot: all of them) and no merges.
4. The next product rebuild (the worker's `rebuild_and_reindex` job, queued when a
   source's daily job ends) applies it; `python -m worker.regroup` does it now.
   `./makhzan status`'s search drift compares the index with *listed* products.

**Rollback** past this release is not image-only: an older image deletes products
by group key and trips over `merged_into`. Run
`alembic downgrade afbb04810ff9` first (it deletes merged-away and emptied rows so
`group_key` can be unique again), then roll the image back. That is the revision
just before this one; `96e50c11754e` would also undo the crawler release's
`worker_state` and `price_observations.available`.

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
- **Search empty after restore** → `restore-db.sh` rebuilds the index after the
  swap; if that step failed, `docker compose ... run --rm --no-deps ingestion python -m worker.reindex`.
- **Resources** → 2 vCPU / 2–4 GB is comfortable. Add swap if the box is small.
