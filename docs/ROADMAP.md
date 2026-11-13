# Roadmap & current state

**Last updated:** 2026-11-13

`PLAN.md` holds the original product plan and phase definitions. This file tracks
what is actually true today and what happens next. `PRODUCT.md` holds the product
decisions behind it; `DESIGN.md` is the frontend's specification.

## Where the project is

**Updated 2026-11-13**, from production's `./makhzan status`. The November
redesign has shipped and the site is public at makhzan.merope.dev: 60,974 active
listings → 59,613 products, from **9 suppliers across 16 domains**. Two of the
nine, the marketplace and shop 4 (35,585 listings between them, over half the
catalogue), block the production server's address and are paused; their data is
from 2026-08-24 (see "Live issue" below). The other seven are read daily.

### Suppliers

Named by role here; the key is in the private configuration (see `CLAUDE.md`).
Listings are active listings on 2026-11-13.

| Supplier | Adapter | Listings | State |
|---|---|---|---|
| The marketplace | bespoke (private) | 31,245 | paused: blocks the server |
| Shop 1 | `WooCommerceAdapter` | 13,434 | crawled daily |
| Shop 3 | `WooCommerceAdapter` | 5,604 | crawled daily |
| Shop 4 | `WooCommerceAdapter` | 4,340 | paused: blocks the server |
| The Odoo shop | `OdooAdapter` | 2,877 | crawled daily; product pages on |
| Shop 2 | `WooCommerceAdapter` | 1,761 | crawled daily |
| The Shopify shop | `ShopifyAdapter` | 1,267 | crawled daily |
| Shop 5 | `WooCommerceAdapter` | 393 | crawled daily |
| The Wix shop | `WixStoresAdapter` (since 2026-11-09) | 53 | crawled daily, as makhzanbot; product pages on |

Every supplier maps its own categories through a crosswalk.

### Domains

tools · seals-bearings · electronics · electrical · piping · chemicals · timber ·
machinery · welding · safety · garden · materials · cleaning · rigging ·
security · automotive

The site calls them **departments** (`/departments/{department}`).

### Shipped since the last update (2026-10-24)

- **The November redesign** (`docs/DESIGN.md`): English only (the Arabic
  interface and the `/en`, `/ar` routes are gone; old URLs redirect), direction D,
  departments, shop pages, product pages that lead with makhzan's own facts,
  readable product URLs, a sitemap and structured data, link previews, and the
  stale-results filter (rule C2b).
- **Stable product ids** (2026-11-09, `docs/decisions/0004-stable-product-ids.md`).
  A regroup merges, splits, empties and revives products without deleting or
  re-keying any; merged ids redirect, a withdrawn product's page says "no longer
  listed". Redirects retire per `docs/decisions/0005-url-retirement.md`, first
  review May 2027.
- **Crawler identity: makhzanbot with Web Bot Auth** (2026-11-10,
  `docs/crawler-identity.md`). Identity is per source; makhzanbot names itself,
  sends no browser hints and signs every request (RFC 9421, Ed25519), with the key
  directory published by the API. The Wix shop was switched first and its runs are
  signed. Two more, the Shopify shop and shop 5, are being switched on 2026-11-13;
  the other three crawled shops are still on the browser identity.
  **Not done:** the application to Cloudflare's verified bots directory was
  submitted on 2026-11-10 and came back on 2026-11-12 asking for a registered
  business, which the operator does not have yet. It is pending. (Shopify needs
  only the signature, no registration.) `python -m worker.probe` (`./makhzan
  probe`) compares the identities from the server with the crawler's own client.
- **Shop contact details** (2026-11-10): phone, WhatsApp, email, address, map
  link, opening hours and branches on each shop page, each field saying where it
  was read. Listed by hand in the private `sources.toml`, merged with what the
  crawler reads (`makhzan_schemas.contact.resolve_contact`).
- **The shop photo badge** (2026-11-10): every product photo names the shop it
  comes from.
- **Crawler activity on `/how-we-crawl#activity`** and each shop page
  (2026-11-09): when the shop was last read, requests in the last 7 days, the
  measured gap between them, "Active" or "Paused". Served by
  `GET /crawler/activity`.
- **Price history is recorded** (2026-11-09): one row per change of a listing's
  price or stock, plus archive and return, served by the API per listing and per
  product. 7,122 observations in the week to 2026-11-13. **Not shown on the site
  yet.**
- **The details stage** (2026-11-09, `worker/details.py`): descriptions, specs,
  documents and photos that only a product page has, read a few pages a run and
  again only on change. On for the Odoo shop and the Wix shop, 20 pages a run;
  the Odoo shop's backfill of 2,822 pages takes about 144 days at that pace.
- **Ingestion hardening:** each source is its own job with its own timeout (the
  old 300 s arq timeout had been cancelling the Odoo shop's runs); a finished
  partition is not re-swept in a cycle; `target_cycle_days` can plan a cycle's
  length (not enabled on any source yet); robots.txt outages are handled per RFC
  9309; a struggling host is slowed after three errors in a row; a run ends itself
  before the job timeout; an unmapped category no longer clears a mapped one.

### Shop data

Phase 1 (collecting more of what shops already publish) has shipped. Phase 2
(showing it), decided 2026-11-09 in `docs/PRODUCT.md`, is **in progress**:

| Phase 2 item | State |
|---|---|
| Shop contact details on the shop page | done |
| Crawler activity on `/how-we-crawl` and shop pages | done |
| Price history recorded and served by the API | done |
| Price history on the product page ("lowest in 90 days", chart) | not done |
| Options table, minimum order, quantity breaks, stated MPN | not done |
| "Ships from abroad" / "Fits: …" badges, videos, "Price on request" | not done |
| Grouping on the manufacturer part numbers shops state | not done |
| Grouping by material for products sold per colour | not done (needs the options table) |

### Before contacting the shops

The polish list in `docs/PRODUCT.md`:

- A working contact address — done (`crawler@makhzan.merope.dev`).
- Fresh data for the reachable shops — done (the crawl runs daily again since
  2026-11-06).
- A "For suppliers" page — done (`/for-suppliers`).
- `ref=makhzan` on shop links, and clicks per shop counted (Umami events) — done.
- Each shop's own makhzan page spot-checked — **not done.**
- No half-finished Arabic — done (English only).

### Infrastructure

- Tests, as run on 2026-11-13: 879 ingestion and 228 API (`make test`), 695
  Vitest and 226 Playwright cases in `apps/web` (not part of `make test`).
  CI runs lint, both Python suites, and web lint, typecheck, build and tests.
- Each test session gets a database of its own, so suites can run in parallel.
- Sweeps are resumable and checkpointed per page; archiving is cycle-gated.
- A cycle spans about a week: the cron stays daily and each run takes a slice.
  Cycles in October and early November ran long (up to 24 days) because of an
  11-day gap with no runs around the public release; the first full cycles
  after 2026-11-09 will show the real length.
- `make status` (`./makhzan status` from production) reports sweep progress,
  cycle history, crawler identity, robots.txt, crosswalk drift, product details,
  catalogue health, price observations and index drift.

## How it got here

Kept short; `git log` has the detail.

- **Crosswalks** (2026-09): every supplier maps its own categories. The Odoo shop
  is browsed by category (170 leaf categories) plus a whole-shop pass, because 8
  of its 2,875 products sit in no category and category partitioning alone would
  have archived them. That is why the pipeline has `knows_category`.
- **The September `apps/web` rewrite** (2026-09-07) made every page
  server-rendered and the site usable without JavaScript, and brought the first
  web tests. The November redesign replaced its look and dropped its bilingual
  routes.

## Next

### 1. In this order

1. **Shop data Phase 2 mockups**: the product page with the options table,
   minimum order, quantity breaks, badges and price history, designed before it
   is built.
2. **The `/how-we-crawl` redesign.** The page names the token, the block
   snippet and the activity record; it does not yet explain the signature or the
   key directory to a shop.
3. **A crawler scheduling plan.** Drafted; the owner is reviewing it.
4. **A caching and rendering review** of the web app and API.
5. **A bot traffic policy** for makhzan's own site.

### 2. The last polish item
The spot-check of each shop's makhzan page (prices, links, photos, categories),
before the shops that have not been written to are contacted.

### 3. Domain generalization
Phases 1–3 are done (`DomainProfile`, data-driven suppliers from a `sources`
table, 15 further verticals), and browse is now scoped to a department.
Remaining: an admin path for adding a source other than editing the private
`sources.toml`, and index-wide search settings — `search_attributes` comes from
the default profile because Meilisearch settings are per index, so a vertical
needing very different ranking will force a compromise order or a second index.
Identifier extraction exists only for electronics; the other domains extract
none and group less.

### 4. Open-sourcing — done
The platform is public under Apache-2.0; the supplier configuration is not. The
crawling code is commodity (public WooCommerce, Shopify, Odoo and Wix
endpoints), while the hand-authored crosswalks are the competitive asset, so
`sources.toml`, the crosswalks, their tests and the one bespoke adapter live in a
private repository that production mounts (`docs/DEPLOYMENT.md`, "Private
configuration").

### 5. Deferred
- **Drop `suppliers.phone`.** Migration `2b656e4b5adc` (shop contact details)
  replaced it with `phones` but kept the column, because the release still serving
  while `migrate` runs selects it. Once a release without it in the ORM is live,
  a migration drops it (expand/contract; docs/DEPLOYMENT.md).
- Supplier self-serve portal and "claim your shop" (PLAN Phase 3).
- Staleness-decay freshness policy (PLAN Phase 4).
- Proxy / multi-IP egress, so partitions of one source can be swept in parallel.
- `docs/decisions/0001` — the marketplace's detail pages for `sku`/`brand`.
- `docs/decisions/0002` — pack size and `Listing.unit`, which is on the model and
  has never been populated. Comparing "from EGP 0.45" against a 1000-pack is
  misleading until it is.
- **Category re-scoping is undetectable.** Drift detection catches renames,
  additions and removals; a supplier keeping a name but changing its contents
  stays silent. Judged rare enough to accept.

## Live issue: two suppliers block the production host

Found 2026-09-07: two suppliers, the largest among them, answer `403` to every
request from the production host's address while serving a residential one
normally, at any browser version. It is the address, not the User-Agent;
`./makhzan probe` run from the server and a laptop is how to tell. Both are
paused (`enabled = false`) rather than retried daily, and are never crawled from
another address to get past the block. Archiving is cycle-gated, so nothing is
lost; the cost is freshness, and their data is now from 2026-08-24.

Both shops were emailed on 2026-11-06 and again on 2026-11-10, asking them to
allow the crawler. **Neither has replied.** The next step, around 2026-11-16, is
to follow up through their other channels (phone, WhatsApp, social). The details
and options are tracked in the private configuration (`docs/live-issues.md`).

## Operational notes

Production is seeded from a `pg_dump` rather than by re-crawling — see
`seed/README.md` and `scripts/restore-seed.sh`. **Reset `source_cursors` before
dumping.** A dump carries mid-cycle cursor state, and restoring it can make the
first production cycle archive listings that were simply never re-verified; a
dump taken mid-session would have retired ~16,600 live listings of the largest supplier.

GHCR images are private because the repo is; the server needs
`docker login ghcr.io` with a classic token carrying `read:packages`, or the
packages must be made public.
