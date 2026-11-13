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
make freshness                  # requests, staleness, changes found, false archivals (read-only)
./makhzan status                # the same report, plus containers/health/crawl flag, from production
```

Completing a cycle resets the cursors, which would otherwise erase the evidence
it happened, so the run's `stats.cycle` records when it started, finished, how
long it took and over how many partitions. That is what makes past sweeps
comparable — the cycle in flight tells you nothing on its own.

`stats.pacing` (`makhzan_schemas/crawl.py`) is what each run actually sent — requests, retries and robots.txt included, and the gaps between them per host, measured at `worker/http.py`'s `take_turn`, the per-host gate that holds every request to the source's pace — and is published to shops on `/how-we-crawl#activity`, so never add errors or status codes to that endpoint. That holds only because nothing reaches a shop any other way: the client does not follow redirects itself (`make_client`), `_request` follows each hop through `take_turn`, robots-checked and logged, and every per-host table keys on `host_of()`, which folds case and default ports so robots.txt and the pages share one gate. It and `stats.requests` go on the run's row with every per-page commit (the pipeline's `checkpoint`), not only when the run ends, so a run a deploy cuts off still publishes what it sent.

`make status` is the first thing to run when a sweep looks stuck or a catalog
looks wrong: it reports per-source partition progress and resume points, each
source's crawler identity and whether its last run was signed, recent runs with
their errors, uncategorized/unpriced counts per supplier, the review
queue, and whether the search index has drifted from the database.
Before investigating a line that looks wrong, read `docs/status-known-normals.md`
in the private configuration: what status shows that is normal, and when it is not.

## How ingestion works

A source is split into **partitions** — independently pageable slices. WooCommerce
partitions by stock status; the marketplace and the Odoo shop partition by category (which is
also how their listings get categorized); a Shopify feed is one partition. A Wix
Stores shop partitions by its configured gallery pages, read from the JSON each
page embeds (`?page=N` is cumulative — page 2 repeats page 1 — and
`comparePrice` is the *sale* price), merchandising galleries such as "New
Arrival" carrying no category, then a products-sitemap pass that creates nothing
but reports, in `stats.source_report`, any product no gallery showed.
Adapters implement `partitions()` and `fetch_page(partition, page) -> Page`.

**Suppliers are data, not code.** The worker builds its adapters from the
`sources` table (`registry.build_adapter`): a row names an adapter type — or an
import path, for one kept in another package — and its config is passed through
as constructor arguments, so an unknown key is an error rather than a setting
silently ignored. The table is seeded from `sources.toml` by `make sources`,
and in production by the `migrate` service on every deploy.

**A shop's contact details have two writers, merged per field.** What a person
read where the shop's details are published (its site, its Facebook, its Google
Maps listing, which the shop may not have claimed) goes in its
`[source.supplier]` table (phone, whatsapp, email, address, maps_url,
opening_hours, branches), with `[[source.supplier.contact_sources]]` saying
where and when each field was read: every field named by exactly one source, so
the page can say "address from Google Maps" rather than call it the shop's.
`SupplierInfo` validates them and normalizes numbers to E.164. `worker.sources.sync`
writes every one of those columns on each deploy, so the file is their only
writer and removing a value clears it. The crawler's reading of the shop's
JSON-LD lives apart, in `Supplier.contact`. `makhzan_schemas.contact.resolve_contact`
merges them — listed wins, the crawler fills gaps, the address (with area,
governorate and map link) as one — and is the only thing that should read
either for display.

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
Shopify shop**, **the Wix shop**, and WooCommerce **shops 1–5**. The key is in the private
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

**On an authoritative source, only a mapped category knows.** A product can sit
in two categories, one the crosswalk maps and one it does not, and then whichever
partition was swept later decided: the unmapped one cleared what the mapped one
had just set (the Odoo shop's servos, SG90 and MG996R among them, lost their
category this way). So when `authoritative_categories` is set and the listing's
own category misses the crosswalk, the pipeline treats the sweep as not knowing:
it leaves a stored category alone, and a listing with none stays uncategorized
(never inferred). A mapped partition still sets the category, and the whole-shop
pass still never clears one. The cost: a product the supplier *moves* from a
mapped category to an unmapped one keeps the old category until a mapped one
says otherwise. Tag-cloud sources (`authoritative_categories` False) are
unchanged — a miss there falls through to inference, and "I was in a position to
know, and there is none" still clears.

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

**Archive candidates are asked about first** (`pipeline.Confirmer`, T4/T12 in
`docs/crawler-scheduling.md`). A multi-day offset sweep skips listings (48 of
173 that shop 1 archived in one cycle came back under the same id), so at cycle
end the candidates go to `adapter.confirm_listed`: WooCommerce re-reads them by
id (`include`, 100 a request), and the Odoo shop checks its sitemap, then reads the
product page of each one the sitemap still lists (20 a run). Returned is kept,
asked-and-absent is archived. A failed or unfinished check archives nothing
more and holds the cycle open (cursors exhausted) for the next run, capped at
one cycle. Sitemap presence is never a sighting. Requests count as
`stats.requests.confirm`.

**A short page can end a partition** (`worker/sources/short_page.py`, T1):
`end_on_short_page` on the Odoo, WooCommerce and Shopify adapters, default
`"shadow"`, which changes nothing and records in `stats.source_report.short_page`
whether the stop would have been right. `make status` tallies it; go `"live"`
only after a full shadow cycle with zero disagreements.

`limit=` makes a run ephemeral: cursors untouched, nothing archived. Use it for
testing so you don't disturb a real sweep's resume point.

### Product-page details

Descriptions, specs, documents and gallery photos that only a product page has
are read by a **details stage** (`worker/details.py`) after a run's sweep: at
most `details.per_run` pages a run, through the same paced client, counted as
`stats.requests.details`. Off unless `details = { enabled = true }` in the
source's config; only adapters with `fetch_details` accept the key. A listing is
due, in this order, when its change token moved since its page was read, when
it was never read (most important first: multi-supplier, in stock; then
newest), or when it was read over `max_age_days` ago (oldest first). For a
card-hash source that age adapts per listing (`details_interval_days`, ×1.4
unchanged, ×0.8 changed, 30–180 days). A failed page backs off 1, 2, 4… days; a host backing off, a
429 or a network failure stops the stage and blames no listing. A `limit=` run
reads none.

The change token comes free from the list page (`change_token(raw)`), and its
kind matters: Odoo's `?unique=` is the shop's own last-write stamp
(`token_kind = "modified"`) and moves on any edit; Wix's and the marketplace's
are hashes of the card (`"card_hash"`) and **cannot see an edit to the
description alone** — only `max_age_days` catches that.

**The list-page upsert rebuilds a listing from the card, so it must carry the
details over.** What a page gave lives in `attributes.details` (plus
`details_token`, `details_fetched_at` and the failure keys); `_upsert_listing`
copies those keys from the stored row and re-applies them (`apply_details`).
Drop that and every sweep silently erases what cost a request per product.

### Pacing

The cron stays daily, but each run sweeps only a slice: `max_pages_per_run` for
sources with few partitions, `max_partitions_per_run` for sources split into many
small ones (the marketplace has 608 categories of ~2 pages, so capping pages would
spread nothing). A cycle therefore takes about a week, which is how often a
product gets re-checked.

**Each source is its own job.** The cron (`refresh_all`) only queues one
`crawl_source` job per enabled source, with the job id `crawl:<source>:<day>`, so
a source is never queued twice a day; each has its own timeout
(`REFRESH_TIMEOUT_SECONDS`), so a host stuck in a long `Retry-After` or a 429
loop is cut off alone instead of holding every other source and the rebuild. A
per-source lock in the worker (`_exclusive`) keeps a run enqueued by hand from
overlapping the daily one: cursors and the pace gate assume one run per source.
Every source job, however it ends — timeout included — queues
`rebuild_and_reindex` for the end of the current 10-minute window, deduplicated
by the window's job id, so sources finishing together share one rebuild and a
straggler gets its own. All of this assumes **one worker process**: the pace
gate is process-wide, and `close_interrupted_runs` on startup treats every
RUNNING row as orphaned.

The Odoo shop needs both: 170 small category partitions *and* one 96-page whole-shop pass.
**Order matters when one partition is much bigger than the rest.** A run takes
`max_partitions_per_run` of whatever is still outstanding, in list order, so a
big partition left at the end is not started until the small ones are nearly
done and then needs several runs of its own — 15 daily runs instead of 7, for
exactly the same 497 pages. Sweep the big one first.

A partition finished this cycle is not swept again until the next one starts,
whatever the caps (`_partitions_for_this_run`, and `_sweep_partition` refuses an
exhausted cursor). It used to be skipped only under `max_partitions_per_run`:
without it, a finished partition's cursor sat at page 1 and every later run of
the cycle re-read it, so shop 1 read its 49 out-of-stock pages 90 times a cycle.

Prefer this over a weekly cron. Same freshness, but the load is a steady trickle
instead of one heavy day, and a daily run means a breakage surfaces in a day
rather than a week. Archiving is unaffected — it is cycle-gated, so it fires once
per completed sweep.

**A cycle can be given a length instead of a slice.** `target_cycle_days` on a
source (any adapter; the registry sets it) makes each run's page budget a plan:
what the cycle still owes, from the last completed cycle's `stats.cycle.cycle_pages`,
spread over the daily runs the target leaves (`pipeline._page_budget`). A shop
that grows then gets more pages a run, rather than a cycle that stretches with
its catalogue. `max_pages_per_run` stays the hard ceiling, read in this mode as
the cap on the **whole run** across partitions, and a floor of half a day's even
share keeps a cycle that is ahead moving. Each run records `stats.budget`;
`make status` shows the target, the projected cycle length, and when the
ceiling rather than the target is setting the pace. Without a completed cycle
to plan from (the first after enabling it), the ceiling alone applies.

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
can never become "Resistors". The drift check compares folded names too: it once
compared exact strings, and reported "LED" and "Raspberry Pi" as unmapped while
every listing under them was being mapped.

**Deliberate skips are written down.** A crosswalk's optional top-level
`ignore = [...]` lists source categories left unmapped on purpose — brand tags,
generic buckets — so they stop reappearing under `unmapped` in `make status`.
They are never mapped or guessed from; a name both mapped and ignored is refused
at load. A crosswalk without the key ignores nothing, but an image older than it
rejects the key outright, so publish the code before a crosswalk that uses it.

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

**A 429 is not necessarily rate limiting — and a bot check is not to be dodged.**
Cloudflare scores clients it thinks are bots and answers with `429`, a
zero-length body, and no `Retry-After`. Shop 3 was diagnosed as rate-limited
twice before the real cause was found: our browser `User-Agent` advertised
Chrome/124, about two years old, and Cloudflare scored it as a bot. The fix then
was to bump the Chrome version, and these notes used to say to keep bumping it.
That advice is withdrawn (November 2026, `docs/crawling-practices.md` in the private
configuration): the score was right, the crawler *is* a bot, and passing a bot
check by looking more like a browser is circumvention — the pattern Cloudflare
publicly calls stealth crawling. The site staying reachable in a browser while
our client gets 429 is still the tell; the response now is the honest identity.

**Identity is per source: `browser` (default) or `makhzanbot`** (`worker/identity.py`,
`docs/crawler-identity.md`). makhzanbot sends `makhzanbot/1.0 (+<SITE_URL>/how-we-crawl;
crawler@makhzan.merope.dev)`, no client hints, and — with `MAKHZANBOT_SIGNING_KEY` set —
a Web Bot Auth signature on every request (`makhzan_schemas/botauth.py`; the API
publishes the key at `/.well-known/http-message-signatures-directory`). The
identity is a context variable the pipeline sets for the run, so every client
(`make_client`, robots.txt, the details stage, the private adapter) takes it;
never build a client with headers of its own. Shops move to makhzanbot one at a
time after a probe; a shop that refuses makhzanbot gets a registered key and a
letter, never the browser headers back. `CHROME_VERSION` stays as it is for the
browser sources that remain; do not bump it to get past a WAF.

`python -m worker.probe` (wrapped by `./makhzan probe`, `scripts/probe-suppliers.sh` and `make probe`)
answers "is it the headers or is it us?". For each source it requests the real
first page (`SourceAdapter.probe_url`) as browser, as makhzanbot, and as
makhzanbot signed. It also asks for robots.txt and obeys it. Requests are 15 s
apart per host, and it prints each status code and HTTP version.

**A probe must use the crawler's own client** (`make_client` with the identity
under test), never curl. curl's TLS fingerprint (JA3/JA4), its HTTP/2 and its
header order and defaults all differ from httpx's, and Cloudflare scores them.
curl with browser headers got 429 from a shop the crawler read fine with the
same headers. The probe used to be a curl script.

Run it on the server *and* on a laptop and compare. The same result in both
places means the headers or the site; different results mean the egress IP, and
no header will fix an address problem.

**Cloudflare caches successful responses per URL.** During an investigation this
makes already-fetched URLs keep returning 200 while never-fetched ones fail, which
looks exactly like a pagination cap. Test with URLs you have never successfully
fetched, or you will measure your own cache.

**`Retry-After` binds the host, not the retry.** A survey once sent six more
requests 12 s apart after a 429 asking for 60. `worker/http.py` now waits at least
what was asked before retrying, records it per host so the next partition waits
too, and gives up for the run (cursor kept) when asked for more than
`RETRY_AFTER_CAP`. Never shorten that wait to make a sweep finish.

**A struggling host is slowed down, not pushed** (`worker/http.py`, `_HEALTH`).
Errors are 429/500/502/503/504 and timeouts.

- Every third error in a row doubles the host's pace, up to 4x. An occasional
  error changes nothing.
- Three 2xx in a row halve the pace again.
- An hour after the host's last error, the slowdown is forgotten, so it does
  not carry into the next day's run.

The slowdown acts inside `take_turn`, so `stats.pacing` measures the wider gaps,
and never records why, because that endpoint is public. The first version
doubled on every error and took off only 10% per success. It pinned a host with
13% errors at 8x and pushed a busy source past the job timeout.

**A run ends itself before the job timeout**
(`pipeline.RUN_TIME_SHARE` × `REFRESH_TIMEOUT_SECONDS`). It starts no page after
that point, keeps its cursors and records `stats.stopped`. This bound covers
everything that can stretch a run — Crawl-delay, Retry-After and the slowdown —
so arq never has to cancel a run mid-page.

**robots.txt is matched by `worker/robots.py`, not `urllib.robotparser`.** On the
Python the worker runs (3.12) the standard parser ignores `*` and `$` and lets the
first matching line win, so `Disallow: /collections/*sort_by*` matched nothing.
Every request is checked against its full URL, query included — which matters most
for paths the crawler discovers at runtime, like a shop's collection handles.
Groups are matched on our token `makhzanbot` in every identity. It used to be
"mozilla", taken from the browser User-Agent, so no shop could name us.

A robots.txt that answers 5xx or 429, or cannot be reached, is handled per RFC
9309 §2.3.1.4, never as "allow all" as it once was:

1. It is retried once, after the host's pace.
2. Then the host's last good copy is used, up to 30 days old. Copies are kept
   in the `robots_copies` table, so a deploy does not forget them.
3. Otherwise the host is refused (`RobotsUnavailable`) for 10 minutes.

A run whose own host refuses it — robots.txt unavailable, or a `HostBackingOff`
— stops at once. It records one error and `stats.stopped`, keeps every cursor,
and does not stamp its cycle data as attempted. Before this, one blip after a
deploy cost a source its day: one error per partition, with a pace's sleep
between each.

`RobotsUnavailable` is deliberately not a `DisallowedByRobots`. The latter lets a
caller skip one path and carry on; the former must fail the page.

Each run records what robots.txt said per host in `stats.robots`. `make status`
shows it under ROBOTS.TXT and flags any copy more than 7 days old.

A page refused before anything was sent is not counted in `stats.requests.pages`.

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

**A group key is not a product's identity.** Product ids are permanent
(`docs/decisions/0004-stable-product-ids.md`): `plan_identity` matches each group
to the products its listings already point at, so a regroup merges (the absorbed
id gets `merged_into` and redirects), splits (the core keeps the id), empties
(`delisted_at`, "no longer listed") and revives, recording each in
`product_events`. Never delete a product or look one up by `group_key`; anything
that lists products filters on `Product.is_listed()`. Before deploying a grouping
change, `make regroup-dry-run` shows how many ids it merges and splits.

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
  `DATABASE_URL` to a database of its **own test session**: the base name
  (`makhzan_test`, `makhzan_api_test`, or `TEST_DATABASE_URL`'s) suffixed with
  the process id or `TEST_DB_SUFFIX`, created at the start and dropped at the
  end. So it can never truncate your dev data, and any number of runs (both
  suites, two worktrees, two agents) can go at once; one shared database used to
  fail them with `StaleDataError` and "cache lookup failed for type". A session
  killed outright leaves its database behind; drop it by hand.
  `make test-ingestion` / `make test-api` run one suite on its own.
- The API suite drives the real app in-process over an ASGI transport and hits a
  real database; only the Meilisearch client is faked, because a filter built on
  the wrong attribute returns a plausible result set rather than an error, and
  that is exactly what needs asserting.
- **Say plainly when something is not fully done.** A first step, a stopgap, a config
  workaround instead of a code fix, or a known remaining gap is named as such, up front,
  in the commit, the PR description and any report, with what the full fix would be.
  Never let a partial fix read as complete (product ids once looked "handled" when only
  redirects had shipped).
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

Known gaps worth naming: identifier extraction exists only for electronics. The
other 15 domains have their own taxonomies but extract no identifier, so their
listings group less (`docs/DOMAIN_GENERALIZATION.md`).
