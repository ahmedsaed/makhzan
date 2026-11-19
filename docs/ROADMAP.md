# Roadmap & current state

**Last updated:** 2026-11-19

`PLAN.md` holds the original product plan and phase definitions. This file tracks
what is actually true today and what happens next. `PRODUCT.md` holds the product
decisions behind it; `DESIGN.md` is the frontend's specification.

## Where the project is

**Updated 2026-11-19.** The November redesign has shipped and the site is public
at makhzan.merope.dev: about 61,300 active listings → 56,255 products (3,130 sold
by two or more shops), from **9 suppliers across 17 domains**. AI matching went
live on 2026-11-19 and took multi-shop products from 1,048 to 3,130
(`docs/ai/decision-review.md`, "Go-live"). Two of the
nine, the marketplace and shop 4 (35,585 listings between them, over half the
catalogue), block the production server's address and are paused; their data is
from 2026-08-24 (see "Live issue" below). The other seven are read daily.

### Suppliers

Named by role here; the key is in the private configuration (see `CLAUDE.md`).
Listings are active listings on 2026-11-13. Every crawled shop is read as
makhzanbot, signed, since 2026-11-18.

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
| The Wix shop | `WixStoresAdapter` (since 2026-11-09) | 53 | crawled daily; product pages on |

Every supplier maps its own categories through a crosswalk.

### Domains

tools · seals-bearings · electronics · electrical · piping · chemicals · timber ·
machinery · welding · safety · garden · materials · cleaning · rigging ·
security · automotive · photography

Photography (lights, tripods, bags, camera accessories) was added 2026-11-18,
with `electronics:cameras` and `electronics:kits`, for listings that had no
honest slot. It is filled by crosswalk only (see CLAUDE.md, "Domains").

The site calls them **departments** (`/departments/{department}`).

### Shipped 2026-11-13 to 2026-11-19

- **AI matching, live since 2026-11-19** (`docs/ai/`). Local models judge
  candidate pairs; the regroup reads their "same" decisions last, behind every
  veto and a person's rulings. The broker, the configurable worker and the
  producers (#58–#60); a backlog scored on the desktop GPU, imported with
  `./makhzan ai import` (#69): 91,199 decisions, 6,249 "same"; the home server's
  CPU workers as a compose stack waiting for their windows (Kev 01:00–05:00, pplx
  05:05–07:00 Cairo), behind a broker-only proxy (#72), on images CI builds,
  smoke-tests and publishes to GHCR (#70, #71); what became of each decision
  (`ai_decisions.effect`) shown in `./makhzan ai status` (#75). Electronics only.
  **Not done:** the queue left after the import (1,571 re-queued backlog jobs,
  new pairs and the rules-merged audit) drains slowly at CPU speed in the home
  server's windows; the owner approved draining it once on the desktop GPU.
- **Grouping rulings** (#55): a person's never/must merge between two listings,
  written by accepting a report or with `./makhzan overrides`. The shop view and
  the "Matched by AI" badge on product pages (#56).
- **Identifiers for every department with codes** (#45, #47): tools, chemicals
  and seals-bearings as well as electronics, with a family guard and incumbency
  in sub-clustering; a manufacturer part number a shop states is a fallback.
- **Search never depends on grouping** (#76): every active listing's titles,
  brands and part numbers are searchable on its product. The index is still one
  document per product, rebuilt in full.
- **The internal admin dashboard** (#62, `docs/admin.md`), durable pauses in the
  database, and a reported listing re-checked first.
- **Taxonomy** (#67): the photography department, `electronics:cameras` and
  `electronics:kits`, and `!word` vetoes and `a ... b` phrases in keyword rules.
- **Frontend** (#68): our own icons for every group and category of all 17
  departments, browse layout B (a sidebar tree on desktop, a Browse pill and
  bottom sheet on a phone) and the sheet's option A look and motion. Then
  (#77) 30 results a page, so a full page ends on a complete grid row (rule S8),
  and the search rail drawn like the browse tree.
- **Categories seen** (#74): which shop categories each product of the Odoo and
  Wix shops was listed under, per cycle, and `./makhzan categories-seen`.
  Record-only.
- **Shop data Phase 2 product page** (2026-11-13, #37, #39–#41): options,
  minimums, quantity prices, part numbers, videos, price history. Search-engine
  metadata (#43), the site pages (#50), "Report a problem" (#48).
- **Crawler scheduling Phases 0 and 1** (2026-11-13, #36, #38,
  `docs/crawler-scheduling.md`): the per-listing check log and `make freshness`;
  T1 short-page stop (in shadow), T4 confirm before archiving, T10, T12. The
  robots.txt AI policy (#32) and the `/how-we-crawl` redesign (#30).
- **All crawled shops on makhzanbot** (2026-11-18): shops 1, 2 and 3 and the Odoo
  shop joined the Wix shop, the Shopify shop and shop 5.

### Shipped 2026-10-24 to 2026-11-13

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
  signed. The Shopify shop and shop 5 were switched and deployed on 2026-11-13;
  their first signed runs are due on 2026-11-14. The other four crawled shops
  (shops 1, 2 and 3 and the Odoo shop) are still on the browser identity.
  **Not done:** the application to Cloudflare's verified bots directory was
  submitted on 2026-11-10 and came back on 2026-11-12 asking for a registered
  business, which the operator does not have yet. It is pending. For Shopify,
  see the Shopify section of `docs/crawler-identity.md`: a signed 429 may mean
  the registration is not yet activated. `python -m worker.probe` (`./makhzan
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
  the Odoo shop's backfill of 2,822 pages takes about 141 days at that pace.
- **Ingestion hardening:** each source is its own job with its own timeout (the
  old 300 s arq timeout had been cancelling the Odoo shop's runs); a finished
  partition is not re-swept in a cycle; `target_cycle_days` can plan a cycle's
  length (not enabled on any source yet); robots.txt outages are handled per RFC
  9309; a struggling host is slowed after three errors in a row; a run ends itself
  before the job timeout; an unmapped category no longer clears a mapped one.

### Shop data

Phase 1 (collecting more of what shops already publish) has shipped. Phase 2
(showing it), decided 2026-11-09 in `docs/PRODUCT.md`, has shipped except grouping:

| Phase 2 item | State |
|---|---|
| Shop contact details on the shop page | done |
| Crawler activity on `/how-we-crawl` and shop pages | done |
| Price history recorded and served by the API | done |
| Price history on the product page ("lowest in 90 days", chart) | done (2026-11-13) |
| Options table, minimum order, quantity breaks, stated MPN | done (2026-11-13) |
| "Ships from abroad" / "Fits: …" badges, videos, "Price on request" | done (2026-11-13) |
| Grouping on the manufacturer part numbers shops state | partly: a fallback when the title names none (#45, #47) |
| Grouping by material for products sold per colour | not done; moved into the AI plan (product families) |

### The polish list, and contacting the shops

The polish list in `docs/PRODUCT.md`. The blocked two were emailed on 2026-11-06;
first emails went to the reachable shops on 2026-11-10: shop 3, the Odoo shop,
shop 1, shop 2, the Shopify shop and the Wix shop by email. Shop 5 has not
been contacted yet. The per-shop spot-check (the fifth item) was **not done** before those
emails went out.

- A working contact address — done (`crawler@makhzan.merope.dev`).
- Fresh data for the reachable shops — done (the crawl runs daily again since
  2026-11-06).
- A "For suppliers" page — done (`/for-suppliers`).
- `ref=makhzan` on shop links, and clicks per shop counted (Umami events) — done.
- Each shop's own makhzan page spot-checked — **not done.**
- No half-finished Arabic — done (English only).

### Infrastructure

- Tests, as last reported (2026-11-19): about 1,610 ingestion, 362 API and 250
  AI worker (`ml/tests`) cases (`make test`), 2,208 Vitest and 442 Playwright
  cases in `apps/web` (not part of `make test`). The ingestion count includes the
  private configuration's crosswalk tests, which `make test` runs when it finds
  the private checkout; public CI runs the public ones only. CI runs lint, the
  Python suites, and web lint, typecheck, build and tests, and builds, smoke-tests
  and publishes the CPU AI worker images.
- Each test session gets a database of its own, so suites can run in parallel.
- Sweeps are resumable and checkpointed per page; archiving is cycle-gated.
- A cycle spans about a week: the cron stays daily and each run takes a slice.
  Cycles in October and early November ran long (up to 24 days) because of an
  11-day gap with no runs around the public release; the first full cycles
  after 2026-11-09 will show the real length.
- `make status` (`./makhzan status` from production) reports sweep progress,
  cycle history, crawler identity, robots.txt, crosswalk drift, product details,
  catalogue health, price observations, AI matching and index drift; the admin
  dashboard renders the same report.

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

### 1. In progress

1. **Products in several categories** (the Odoo shop, the Wix shop). After one
   full cycle of `categories_seen` recording (#74), the owner reviews
   `./makhzan categories-seen` and decides how a multi-category product is
   filed; until then the last mapped partition swept wins.
2. **The audit review**: the owner reviews the AI audit of merges the rules
   made (the producers' rules-merged audit), to find wrong rules merges.
3. **Per-listing category overrides**, like grouping rulings (note required,
   soft removal, audited, never overwritten by a sweep); first use, about 11
   non-photographic lamps a shop files with its photo lights. The admin screen is
   mocked first. Tracked; not started.
4. **T1 short-page stop to "live"**, per source, once a full shadow cycle shows
   zero disagreements (`make status`).

### 2. Open, not yet ordered

1. **Crawler scheduling Phase 2** (WooCommerce lanes) waits for the owner's
   decisions; Phase 3 (`docs/crawler-phase3-design.md`) waits for 4–8 weeks of
   Phase 0 data.
2. **More AI use cases**, one at a time (`docs/ai/plan.md`): product families
   (grouping by material), a per-listing category for mixed shop tags, and
   departments beyond electronics once there is labelled data for them.
3. **A caching and rendering review** of the web app and API (parked).
4. **A bot traffic policy** for makhzan's own site.
5. **The two blocked shops**: follow up through their other channels (see "Live
   issue").

### 3. The last polish item
The spot-check of each shop's makhzan page (prices, links, photos, categories).
It was meant to come before the emails and did not: every reachable shop except
shop 5 has already been written to (see "The polish list, and contacting the shops").

### 4. Domain generalization
Phases 1–3 are done (`DomainProfile`, data-driven suppliers from a `sources`
table, 15 further verticals, and photography since 2026-11-18), and browse is
scoped to a department.
Remaining: an admin path for adding a source other than editing the private
`sources.toml`, and index-wide search settings — `search_attributes` comes from
the default profile because Meilisearch settings are per index, so a vertical
needing very different ranking will force a compromise order or a second index.
Identifiers are read for electronics, tools, chemicals and seals-bearings
(`makhzan_schemas/identifiers.py`, with a family guard); the other 13 domains
have no rules yet — their codes are family-level or sizes and each is one shop
today — and group less.

### 5. Open-sourcing — done
The platform is public under Apache-2.0; the supplier configuration is not. The
crawling code is commodity (public WooCommerce, Shopify, Odoo and Wix
endpoints), while the hand-authored crosswalks are the competitive asset, so
`sources.toml`, the crosswalks, their tests and the one bespoke adapter live in a
private repository that production mounts (`docs/DEPLOYMENT.md`, "Private
configuration").

### 6. Deferred
- ~~**Drop `suppliers.phone`.**~~ Done 2026-11-13: migration `772533d06b60` drops it, the
  contract step for `2b656e4b5adc`, which replaced it with `phones` and kept the
  column while a release that selected it was still serving (docs/DEPLOYMENT.md).
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

Both shops were emailed on 2026-11-06 and followed up on 2026-11-10, asking them
to allow the crawler. **Neither has replied.** The follow-up through their other channels (phone,
WhatsApp, social), planned for around 2026-11-16, is still open. The details
and options are tracked in the private configuration (`docs/live-issues.md`).

## Operational notes

Production is seeded from a `pg_dump` rather than by re-crawling — see
`seed/README.md` and `scripts/restore-seed.sh`. **Reset `source_cursors` before
dumping.** A dump carries mid-cycle cursor state, and restoring it can make the
first production cycle archive listings that were simply never re-verified; a
dump taken mid-session would have retired ~16,600 live listings of the largest supplier.

A GHCR package's visibility is its own, not the repository's, so a new package
starts private even though the repository is public: the server needs `docker
login ghcr.io` with a classic token carrying `read:packages`, or the packages
must be made public.
