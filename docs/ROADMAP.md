# Roadmap & current state

**Last updated:** 2026-10-24

`PLAN.md` holds the original product plan and phase definitions. This file tracks
what is actually true today and what happens next.

## Where the project is

**Updated 2026-08-24.** Phase 2 has shipped and the catalogue is now
multi-vertical: 60,559 listings → 57,207 products across **8 suppliers and 16
domains**, with 1,029 products offered by more than one supplier (max 8).

### Suppliers

Named by role here; the key is in the private configuration (see `CLAUDE.md`).

| Supplier | Adapter | Listings | Categories |
|---|---|---|---|
| The marketplace | bespoke (private) | 31,245 | crosswalk (608) |
| Shop 1 | `WooCommerceAdapter` | 13,259 | crosswalk (313) |
| Shop 3 | `WooCommerceAdapter` | 5,574 | crosswalk (130) |
| Shop 4 | `WooCommerceAdapter` | 4,340 | crosswalk (184) |
| The Odoo shop | `OdooAdapter` | 2,877 | crosswalk (162) |
| Shop 2 | `WooCommerceAdapter` | 1,624 | crosswalk (102) |
| The Shopify shop | `ShopifyAdapter` | 1,243 | crosswalk (87) |
| Shop 5 | `WooCommerceAdapter` | 395 | crosswalk (15) |

### Domains

tools · seals-bearings · electronics · electrical · piping · chemicals · timber ·
machinery · welding · safety · garden · materials · cleaning · rigging ·
security · automotive

### Infrastructure

- CI green (lint, 68 ingestion tests, 86 API tests, web lint/typecheck/build).
  It had been red from 2026-07-15 to 2026-08-24 on an unpinned ruff and a
  misconfigured pnpm action.
- Sweeps are resumable and checkpointed per page; archiving is cycle-gated.
- A cycle now spans ~a week: the cron stays daily and each run takes a slice.
- `make status` reports sweep progress, cycle history, crosswalk drift, catalogue
  health and index drift.
- `apps/api` has a test suite as of 2026-09-05 (86 tests, real Postgres, the app
  driven in-process; only Meilisearch is faked). `apps/web` still has none, held
  until the rewrite lands.

## Next

Everything below is genuinely outstanding; the finished work is described above.

### 0. The November redesign — in progress (2026-11-06)
The frontend is being redesigned from the data up: English only, direction D,
burnt orange on Archivo and Inter. `docs/DESIGN.md` is the specification (it
replaces the September design below); `docs/PRODUCT.md` holds what comes after it
(projects, blog, accounts, supplier pages) and the polish list to finish before the
suppliers are contacted. Product ids becoming permanent is
`docs/decisions/0004-stable-product-ids.md`.

### 1. The `apps/web` rewrite — done (2026-09-07), superseded by 0
Built to the September version of `docs/DESIGN.md`. Nine server-rendered surfaces under `/en` and `/ar`
with `hreflang` pairs; language is a route rather than React state, so an Arabic
page is finally linkable and indexable. Search, sort, facets and paging are links
and a GET form, so the site works with JavaScript disabled.

Tests came with it, and CI now runs four suites: 38 Vitest cases over the logic
that fails silently (language negotiation, dictionary parity, `domain:slug`
handling, the two timestamp shapes, the image fallback) and 21 Playwright cases
over what only a browser can see — server-rendered direction, no-JS search, the
tombstone, the hand-off's `nofollow`. Playwright runs against a stub API, so it
needs no Postgres, Meilisearch or Python and cannot fail because the catalogue
changed.

The history, for anyone wondering why it was worth doing:

The rewrite is a re-architecture, not a re-platform: the stack (Next 16, React
19, Tailwind 4, Base UI) is current and the API layer, i18n strings and RTL CSS
are reusable. What is wrong is structural. Every page is a client component
fetching in `useEffect`, so nothing is server-rendered — for a discovery product
whose whole value is being found for "LM358 القاهرة", that means no SEO at all.
And language lives in React state, so `<html lang>` is always `en` on the server,
an Arabic URL does not exist, and the choice resets on reload. For a bilingual
Egyptian directory that is the biggest functional gap in the product.

The no-tests exemption was justified by the pending rewrite; it has expired.

**Everything it was blocked on is now settled** (2026-09-06):

- Design language, layout for all ten surfaces, and the responsive system —
  `docs/DESIGN.md`.
- Image hosting: `next/image` with `remotePatterns`. Archived listings: a
  tombstone page, not a 404. Pack size: show the supplier's unit, never compute
  a normalised one.
- The three API endpoints the layouts assumed are built and tested —
  `/search?facets=true`, `/search?min_suppliers=N`, `/products/{id}/similar`.
  **`min_suppliers` needs `make reindex` before it returns anything**, because
  `supplier_count` became a filterable attribute and that is an index setting.

So the rewrite is unblocked and its first slice is the part nothing depends on:
`/en` and `/ar` routing with `hreflang`, the server-rendered shell, chrome, the
design tokens, and the test harness in CI.

`apps/api` was covered on 2026-09-05 — 86 tests over the routers and the
Meilisearch query builder, aimed at the failures that are silent rather than
loud: a filter on the wrong attribute, a category identified by bare slug, a
sort key the index does not have, priceless offers sorting as if free. Verified
by mutation: seven deliberate breakages each failed the test that names them.

### 2. Crosswalks — done
All eight suppliers now map their own categories rather than inferring them.
Shops 1 and 2 and the Shopify shop landed on 2026-09-05 (uncategorized 1,392 ->
359); the Odoo shop followed on 2026-09-06.

The Odoo shop was the awkward one. `OdooAdapter` swept `/shop`, whose product cards carry
no category, so it now partitions by category instead: 170 leaf categories, 162
of them mapped, `authoritative_categories` on. The categories come out of the
`/shop` sidebar, which renders them as `data-link-href` attributes rather than
`<a href>` — a link scrape finds none.

The coverage crawl that gated it is worth keeping in mind for the next source:
all 194 categories against a full `/shop` sweep gave 2,867 vs 2,875, i.e. **8
products filed under no category at all** — magnetrons, lead-acid batteries,
PETG filament, all live and priced. Category partitioning alone would have
archived them. That shop therefore also sweeps `/shop`, and the pipeline gained
`knows_category` so that pass cannot erase what the category pass set.

### 3. Domain generalization
**Phase 1 is done** (2026-08-24). `DomainProfile` exists, electronics was moved
into it verbatim, and `domain` is a real column on Supplier / Category / Listing /
Product with slugs unique per domain. Verified as a no-op for electronics: 796
resolver probes matched the old implementation exactly, and re-ingesting a source
produced identical category assignments.

Phase 3 is done too — 15 further verticals were authored and populated. Remaining:

- ~~**Phase 2, data-driven suppliers.**~~ Done 2026-10-24: adapters are built
  from a `sources` table seeded from `sources.toml`, which lives in the private
  configuration. Still open: an admin path for adding a source other than
  editing the file.
- **Phase 4, domain-aware UI.** The API identifies categories by `domain:slug`
  and search is deliberately cross-domain, but browse is not scoped to a
  vertical. With 16 domains that matters.
- **Index-wide search settings.** `search_attributes` comes from the default
  profile because Meilisearch settings are per index. Documents carry `domain`,
  and identifier-shaped queries are handled by narrowing `attributesToSearchOn`,
  but a vertical needing very different ranking will force a compromise order or
  a second index.

### 4. Open-sourcing
The platform is public under Apache-2.0; the supplier configuration is not. The
crawling code is commodity (public WooCommerce, Shopify and Odoo endpoints),
while the 2,568 lines of hand-authored crosswalks are the competitive asset, so
`sources.toml`, the crosswalks, their tests and the one bespoke adapter live in a
private repository that production mounts (`docs/DEPLOYMENT.md`, "Private
configuration"). The tests are supplier-agnostic, crosswalks are TOML data behind
a loader, and suppliers are rows in a table, so none of it needs code here.

### 5. Deferred
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
`scripts/probe-suppliers.sh` run from both machines is how to tell. Archiving is
cycle-gated, so nothing is lost; the cost is freshness. The details and options
are tracked in the private configuration (`docs/live-issues.md`).

## Operational notes

Production is seeded from a `pg_dump` rather than by re-crawling — see
`seed/README.md` and `scripts/restore-seed.sh`. **Reset `source_cursors` before
dumping.** A dump carries mid-cycle cursor state, and restoring it can make the
first production cycle archive listings that were simply never re-verified; a
dump taken mid-session would have retired ~16,600 live listings of the largest supplier.

GHCR images are private because the repo is; the server needs
`docker login ghcr.io` with a classic token carrying `read:packages`, or the
packages must be made public.
