# CLAUDE.md

Working notes for this repo. Read this before changing ingestion, taxonomy, or
grouping — several things here are non-obvious and have already caused wrong
diagnoses.

## What makhzan is

An English-language **directory / discovery** aggregator for Egyptian hardware
suppliers (supplier titles may be Arabic; the interface is not). It finds products across supplier catalogs and hands the buyer off to
the supplier. There is no cart, payment, or delivery, and adding one is out of
scope — see `docs/PLAN.md`.

## Layout

```
apps/web         Next.js consumer frontend (pnpm, shadcn/Base UI, English only, dark mode)
apps/api         FastAPI read-only API over Postgres + Meilisearch
apps/ingestion    Arq worker: source adapters -> normalize -> upsert -> review queue
packages/schemas  SQLAlchemy models, Alembic migrations, taxonomy, grouping, search contract
scripts/          Operational scripts (deploy, backup, probes)
config/           sources.example.toml only; the real configuration is ../makhzan-config (private)
```

`apps/api` and `apps/ingestion` share the schema through `packages/schemas`, which
is a path dependency installed in develop mode. Each Python project has its own
Poetry virtualenv — there is no single root env.

## Commands

`make help` lists everything. The common ones:

```bash
make setup                      # .env + services + deps + migrations, from a clean clone
make test                       # every Python test suite (ingestion + api)
make lint                       # exactly what CI checks
make api / make web / make worker
make sources                    # seed the sources table from sources.toml
make ingest SOURCE=<source-id> LIMIT=10
make reindex                    # rebuild products + search index
make status                     # crawler progress, recent runs, catalog health
./makhzan status                # the same report, plus containers/health/crawl flag, from production
```

Completing a cycle resets the cursors, which would otherwise erase the evidence
it happened, so the run's `stats.cycle` records when it started, finished, how
long it took and over how many partitions. That is what makes past sweeps
comparable — the cycle in flight tells you nothing on its own.

`stats.pacing` (`makhzan_schemas/crawl.py`) is what each run actually sent — requests, retries included, and the gaps between them per host, measured in `worker/http.py` — and is published to shops on `/how-we-crawl#activity`, so never add errors or status codes to that endpoint.

`make status` is the first thing to run when a sweep looks stuck or a catalog
looks wrong: it reports per-source partition progress and resume points, recent
runs with their errors, uncategorized/unpriced counts per supplier, the review
queue, and whether the search index has drifted from the database.

## How ingestion works

A source is split into **partitions** — independently pageable slices. WooCommerce
partitions by stock status; the marketplace and the Odoo shop partition by category (which is
also how their listings get categorized); a Shopify feed is one partition.
Adapters implement `partitions()` and `fetch_page(partition, page) -> Page`.

**Suppliers are data, not code.** The worker builds its adapters from the
`sources` table (`registry.build_adapter`): a row names an adapter type — or an
import path, for one kept in another package — and its config is passed through
as constructor arguments, so an unknown key is an error rather than a setting
silently ignored. The table is seeded from `sources.toml` by `make sources`,
and in production by the `migrate` service on every deploy.

**The real configuration is not in this repository.** `sources.toml`, the
crosswalks, their tests and a bespoke adapter (named in `sources.toml` by
import path) live in the private `makhzan-config` repository, checked out
beside this one. `make` finds it at `../makhzan-config` and points `MAKHZAN_SOURCES`, `MAKHZAN_CROSSWALKS` and
`PYTHONPATH` at it; production mounts it into `migrate` and `ingestion`. Without
it a clone runs on `config/sources.example.toml`. A crosswalk fix is a commit
there, not here. A source id is stored on every listing, run and cursor —
renaming one orphans all three.

These notes name suppliers by role, not by name: **the marketplace** (a
bespoke, multi-vertical catalogue, the largest source), **the Odoo shop**, **the
Shopify shop**, and WooCommerce **shops 1–5**. The key is in the private
configuration's README.

**Browsing by category can orphan stock.** A shop's category pages need not cover
its catalogue: 8 of the Odoo shop's 2,875 products are filed under nothing, so partitioning
on categories alone would stop seeing them and a completed cycle would archive
them — real stock, deleted, silently. That shop therefore also sweeps `/shop`, and
`OdooAdapter` sweeps **leaf** categories only, because a parent page repeats
everything its children list and the two need not map to the same leaf.

Before switching any source to category partitioning, crawl every category once
and diff the product ids against a whole-catalogue sweep. That is the only way
the gap shows up, and its cost is one crawl.

**A sweep that carries no category must not erase one.** The whole-shop pass has
no category to offer, so `SourceAdapter.knows_category(raw)` returns False for it
and the pipeline leaves the stored category alone. Returning True — the default,
and what every category partition returns — means "I was in a position to know,
and there is none", which *does* clear it, so a supplier dropping a category is
still visible. Without this the /shop pass would blank the category on all 2,867
products the category pass had just set.

Progress is **durable per page**: after each page the pipeline commits and advances
a `SourceCursor`. A run that dies on page 40 of 43 keeps 39 pages, and the next
run resumes at 40. This is not a nicety — without it, a host that rate-limits
mid-catalog makes the tail permanently unreachable, because every run restarts at
page 1 and dies in the same place.

A **cycle** is one full sweep of every partition and may span several runs.
Archiving waits for a complete cycle and keys off `cycle_started_at`, not the
individual run. **Never archive based on a single run** — a partial run would
retire everything it simply never reached.

Archiving reads `last_seen_at` (the source said the listing exists, by any
route), not `last_verified_at` (its price and details were read). They differ
for a shop that lists out-of-stock products by id alone: that keeps the listing
alive without re-pricing it, and the site shows `last_verified_at` as "checked".

`limit=` makes a run ephemeral: cursors untouched, nothing archived. Use it for
testing so you don't disturb a real sweep's resume point.

### Pacing

The cron stays daily, but each run sweeps only a slice: `max_pages_per_run` for
sources with few partitions, `max_partitions_per_run` for sources split into many
small ones (the marketplace has 608 categories of ~2 pages, so capping pages would
spread nothing). A cycle therefore takes about a week, which is how often a
product gets re-checked.

The Odoo shop needs both: 170 small category partitions *and* one 96-page whole-shop pass.
**Order matters when one partition is much bigger than the rest.** A run takes
`max_partitions_per_run` of whatever is still outstanding, in list order, so a
big partition left at the end is not started until the small ones are nearly
done and then needs several runs of its own — 15 daily runs instead of 7, for
exactly the same 497 pages. Sweep the big one first.

Prefer this over a weekly cron. Same freshness, but the load is a steady trickle
instead of one heavy day, and a daily run means a breakage surfaces in a day
rather than a week. Archiving is unaffected — it is cycle-gated, so it fires once
per completed sweep.

## Domains

Every vertical-specific decision — category tree, identifier extraction, what
"same product" means, search ranking — lives in a `DomainProfile`
(`packages/schemas/makhzan_schemas/domains/`). Electronics is the first profile,
not the logic; call sites select one via `get_profile(domain)`.

**Domain is resolved per listing, from its category.** `Supplier.domain` is only a
fallback for listings that stayed uncategorized. Do not key enrichment off the
supplier: a marketplace can span many verticals at once, and that assumption puts
gaskets and microcontrollers in the same taxonomy.

Category slugs are unique **per domain**, not globally — two verticals may both
define "tools" and mean different things. `hand-tools` and `measurement` already
exist in two domains each. Categories are therefore identified by
**`ref` = `domain:slug`** everywhere it matters: the `/categories` payload, the
category filter, browse links and React keys. A bare slug is ambiguous.

**Domains are not folded together.** A vertical gets its own domain unless it is
genuinely the same trade — electrical installation gear (breakers, contactors,
PLCs) is not electronics components, and automotive tools are not hand tools.
Collapsing them produces a tidy-looking taxonomy that no buyer recognises.

**Search stays cross-domain.** Domain is a facet, not a partition: someone
searching "multimeter" should see electronics and tools results together, and
ranking decides the order. Only explicit category browse is scoped to one domain.

Adding a vertical means authoring a profile (taxonomy, rules, identifier
strategy). That domain knowledge is the real cost; the code seam is already there.

### Authoritative categories vs keyword inference

Two ways a listing gets a category, and picking the wrong one corrupts data.

*Inference* (`profile.resolve_category_slug`) matches keywords against titles. It
exists because Shopify/WooCommerce category strings are unreliable. It is
probabilistic and fails invisibly.

*Crosswalk* is a lookup table from a source's own category to ours, held as data
(`crosswalks/<name>.toml` in the private configuration, each name mapped to a `domain:slug` ref). Use it
whenever the source is browsed **by** category — then the category is known
exactly and inferring it would replace fact with a guess. Set `authoritative_categories = True` on the adapter and implement
`category_for`.

A crosswalk is **always consulted first**, whatever the source: a mapping is a
fact and inference is a guess. `authoritative_categories` controls only what
happens on a *miss*.

Set it when the source's categories cover its catalogue (the marketplace is browsed by
category, so a miss is genuinely unmapped) — then a miss stays uncategorized.
**Never fall back to inference there**: the electronics rules match `"socket"`,
so socket wrenches would land in *Connectors & Sockets*.

Leave it False when the categories are a **tag cloud** rather than a taxonomy.
Shop 3 tags a listing with an unordered mix of type (`Ceramic Capacitors`),
package facet (`0805`, which holds both resistors and capacitors) and brand
(`Uni-T`), so a miss often means "tagged by something other than its type" and
the title is the better evidence. Map only the type-bearing names and let the
rest fall through.

WooCommerce returns those names **alphabetically, not most-specific-last** —
`["Capacitors", "Ceramic Capacitors", "Components"]` ends on the vaguest. Resolve
across every tag; never read a fixed position. The same ordering is why a generic
bucket must never be mapped: `category_for` takes the first tag that matches, and
"Accessories" sorts ahead of the "Sensors" beside it.

When two *mapped* tags disagree, a crosswalk's top-level `prefer = [...]` ranks the
ones that should win, ahead of the alphabet: shop 2's "Displays (LCD & 7-Seg &
LED)" sorts before its "LEDs", and filed 33 plain 3 mm LEDs as displays until
`prefer = ["LEDs"]`. A preference is global to that shop, so before adding one,
list every listing that carries both tags and read what moves. An image older than
`prefer` rejects the key outright, so publish the code before the crosswalk that uses it.

**A tag name is a hint; check what is actually under it.** Shop 1's "3D Printer
Filament" holds 94 listings of which 21 are filament — the rest are bearings,
nozzles and a stepper driver. The Shopify shop's `product_type: "ic"` covers real ICs but also
BZX79 zeners and L7809 regulators. Mapping either would have filed the majority
wrongly *and confidently*, which is worse than inference, because inference at
least reads the title. Both were caught by measuring the crosswalk against
inference over the real catalogue before committing it — do that, it is the only
way this shows up.

Shopify sources crosswalk on `product_type` instead. It is a single value per
product, so there is no ordering question — but it is free text, and a shop will
spell it "Sensor", "sensor" and "SENSOR". `ShopifyAdapter` folds case; write the
table lowercase.

Keyword guessing belongs offline, when authoring the crosswalk, where a human can
read and correct the result.

### Crosswalk drift

A crosswalk is a snapshot of a supplier's taxonomy, and suppliers change theirs.
A rename makes the mapping stop matching and those listings quietly lose their
category — indistinguishable from the supplier discontinuing stock.

So every sweep records the category names it actually saw and diffs them against
the crosswalk, reporting `unmapped` (new or renamed, with listing counts) and
`unused` (retired or renamed away). `make status` shows both under CROSSWALK
DRIFT. Act on it: this is how "Resistors", "Raspberry Pi" and "Teensy Board" were
found missing from shop 4's map.

`unused` is only reported when a run swept the whole catalogue itself. A run that
*resumed* mid-partition finishes the cycle without having seen the earlier pages,
so its absences prove nothing — the first version of this check cried wolf on
exactly that.

**Punctuation drift is not a rename.** A shop that re-types "Diodes - General
Purpose" with an en-dash, or "0603x4" with a multiplication sign, keeps the same
category and the same products — but an exact-string key stops matching, and the
drift report calls it both `unmapped` and `unused`. Six keys were already dead
this way when the July crosswalks were diffed against the live shops. Lookups
therefore go through `crosswalks.normalize_category_name`, which folds dashes,
smart quotes, `×`, whitespace and case, and `fold_crosswalk` raises if two keys
collide under it. It folds punctuation only — never words, so "Power Resistors"
can never become "Resistors".

**Re-scoping stays invisible.** If a supplier keeps a name but changes what goes
under it, the mapping still matches and is now silently wrong. No diff can catch
that; only a shift in the category's price or title distribution would.

**The seed dump is not the live catalogue.** Crosswalks authored from a `pg_dump`
are a snapshot of whenever it was taken. Diffing the July seed against the live
shops in September found shop 1 had added 34 categories — a whole sensor
sub-tree, "Cooling Solutions" (401 listings), a plain "Resistors" (385) — none of
which existed to be mapped. Author from the dump if you like, but diff against
the live category list before committing.

## Gotchas that have already bitten

**A 429 is not necessarily rate limiting.** Cloudflare scores stale browser
versions as bots and answers with `429`, a zero-length body, and no `Retry-After`.
Shop 3 was diagnosed as rate-limited twice before the real cause was
found: our `User-Agent` advertised Chrome/124, about two years old. `CHROME_VERSION`
in `worker/http.py` is load-bearing — bump it when it ages, and suspect it before
building elaborate pacing theories. The site staying reachable in a browser while
our client gets 429 is the tell.

`scripts/probe-suppliers.sh` answers that question directly: it sends the
crawler's exact headers to every source at two browser versions and prints the
status codes. Run it on the server *and* on a laptop and compare — the same
result in both places means the header or the site, different results mean the
egress IP, and no amount of header tuning will fix an address problem.

**Cloudflare caches successful responses per URL.** During an investigation this
makes already-fetched URLs keep returning 200 while never-fetched ones fail, which
looks exactly like a pagination cap. Test with URLs you have never successfully
fetched, or you will measure your own cache.

**`Retry-After` binds the host, not the retry.** A survey once sent six more
requests 12 s apart after a 429 asking for 60. `worker/http.py` now waits at least
what was asked before retrying, records it per host so the next partition waits
too, and gives up for the run (cursor kept) when asked for more than
`RETRY_AFTER_CAP`. Never shorten that wait to make a sweep finish.

**robots.txt is matched by `worker/robots.py`, not `urllib.robotparser`.** On the
Python the worker runs (3.12) the standard parser ignores `*` and `$` and lets the
first matching line win, so `Disallow: /collections/*sort_by*` matched nothing.
Every request is checked against its full URL, query included — which matters most
for paths the crawler discovers at runtime, like a shop's collection handles.

**WooCommerce prices are minor units** (÷ 10^`currency_minor_unit`); Shopify's are
major units. Getting this wrong is silent — prices are just 100x off.

**Odoo never serves an empty page.** It repeats its last page forever, so the end
signal is "this page has the same ids as the previous one".

**An identifier is evidence, not proof.** Part numbers are extracted from titles,
so they also match titles that merely *reference* a part — "bracket for SG90",
"robot arm kit with 4x SG90". Listings sharing an identifier are only merged when
their **titles** agree they are the same thing (see `grouping._subcluster`).

**Price is not evidence of identity.** It used to be sufficient on its own, and
that was wrong: an extracted identifier is often a *family* prefix — `ESP32`,
`ESP8266`, `CR2025` — and within a family everything costs about the same, so
price agreed with everything. One "product" ended up holding 22 offers from 99 to
850 EGP: an MP3 player, a battery shield and a SIM800L module inside an ESP32
board. Price now only *vetoes* — identical titles priced 15x apart are a pack and
a single unit — and the veto is measured across the whole cluster's span, because
a band centred on one mid-priced member reached 65–1040 EGP and swallowed the
family.

**Compare a candidate against every member of a cluster, not its first.** After
the identifier and noise words are stripped, "ESP32 Development Board 30 pin"
reduces to `{pin}`. A cluster seeded by a title-poor listing could never be
matched on title by anything, which is what left price as the only way in.

The cost is deliberate: some genuinely identical parts described very differently
now split into separate products. Under-merging shows fewer suppliers on a page;
over-merging publishes a price range that is false. The second is worse.

There is deliberately **no list of "ambiguous" part families**. One used to exist
and was unmaintainable by construction: SG90 and CR10 were never on it, and there
was no reason to expect the next one to be. Corroboration applies to every group.

**Title agreement admits; three things veto, checked against every member.**
(1) *Same shop never merges*: a shop lists two SKUs because they differ, and its
two listings in one product were always variants collapsed together (KSD301 at
40 and 140 °C). (2) *Value tokens* (`makhzan_schemas.values`): titles stating
different values of one unit — 30 vs 38 pin, 180° vs 360°, a 3-pack vs one — are
different products. (3) *Form* (`DomainProfile.form_markers`): a bare chip, a
module and an accessory are not one product, and an accessory conflicts even with
a title silent on form. Form words must say what the listing *is*: "PCB Mount",
"Panel Mount" and "with adapter" describe the part, and matching bare `mount`
kept DB15 and WAGO connectors from merging across shops.

**Non-products are skipped before they are stored** (`normalize.not_a_product`):
placeholder titles ("Item", "point1"), delivery fees, and anything the shop files
under exactly "Services". Narrow on purpose — a false positive deletes real stock.
It reads `source_categories`, so an adapter that does not implement it is never
checked for services.

Suppliers do publish SKUs, but they are **private catalogue codes, not MPNs**
(one shop uses numeric ids, another descriptive ones). Across ~10k SKUs only 15
are shared by two suppliers, and those are coincidences. Do not group on them.

## Conventions

- Python: ruff, line length 100. `make fmt` before committing. CI pins ruff — do
  not float it, an unpinned formatter silently changed its rules and kept CI red
  for a month.
- Migrations: autogenerate from `packages/schemas`, then **read the generated file**
  before committing.
- Tests live in `apps/ingestion/tests` and `apps/api/tests`, and run against a
  real Postgres (the schema needs JSONB/UUID). Each `conftest.py` forces
  `DATABASE_URL` to a separate test database so it can never truncate your dev
  data, and the two suites use *different* test databases so they can run side
  by side. `make test-ingestion` / `make test-api` run one on its own.
- The API suite drives the real app in-process over an ASGI transport and hits a
  real database; only the Meilisearch client is faked, because a filter built on
  the wrong attribute returns a plausible result set rather than an error, and
  that is exactly what needs asserting.
- Commits: conventional prefixes (`feat:`, `fix:`, `docs:`, `ci:`, `style:`).
  Explain *why* in the body, especially for anything that corrects a wrong
  earlier diagnosis.

## Current state

See `docs/ROADMAP.md` for what is done, in progress, and next.

The frontend is built to `docs/DESIGN.md` (the November 2026 redesign): the data
behind each layout decision, the page tree and URLs, the style tokens, and rules
(C1–S5) that tests enforce. Read it before touching the frontend. What comes next
(projects, blog, accounts, supplier pages) is `docs/PRODUCT.md`.

`apps/web` has vitest unit tests and Playwright e2e specs under `apps/web/tests`
(`pnpm exec vitest run`, `pnpm exec playwright test`); they are not part of
`make test`, which is the Python suites. Run them when touching the frontend —
they catch prop and state changes the build does not.

Known gaps worth naming: the taxonomy and identifier extraction are electronics-only
(`docs/DOMAIN_GENERALIZATION.md`).
