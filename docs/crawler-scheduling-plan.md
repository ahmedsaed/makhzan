# Crawler scheduling: get more freshness from the same requests

**Status:** written 2026-11-13; Phase 0 and Phase 1 shipped the same day (PRs #36, #38) — see `docs/crawler-scheduling.md` for what is built. This is the research and the full plan.

Original status: plan only, 2026-11-13. No code, config or PR has been changed. No request
went to a supplier. The numbers come from the code, `sources.toml`, the November QA
surveys in `makhzan-config/docs/qa/`, and read-only `SELECT`s on production, each run
inside a `BEGIN TRANSACTION READ ONLY … ROLLBACK`.

Suppliers are named by role, as CLAUDE.md does; the key is in the private configuration's README.

**The politeness rules don't change.** Every rule below stays:

- one request at a time per host, at least 15 s apart (or the host's Crawl-delay);
- the slowdown on errors, robots.txt and Retry-After;
- every request goes through `take_turn`;
- `max_pages_per_run` stays the hard ceiling.

The goal is better *choices* of which requests to send. It is not more requests.

---

## 0. What we know about change, from production

Price history is recorded one row per change (`price_observations`) since commit
3fbec86 (2026-11-09). The migration seeded one baseline row per listing, dated at its
`last_verified_at`. So the first re-read after 2026-11-10 is an *interval-censored*
sample: did the price or stock move between the baseline and today? We only have three
days of runs, so read the figures below as orders of magnitude, not as rates to tune
against.

**Listings first re-read 2026-11-10 to 11-12, against their baseline:**

| Source | n | Median gap since baseline | Price moved | Stock moved | Either |
|---|---:|---:|---:|---:|---:|
| shop 1 (Woo) | 3,213 | 27 d | 2.9 % | 1.6 % | 3.9 % |
| shop 3 (Woo) | 2,095 | 24 d | 1.2 % | 0.6 % | 1.8 % |
| shop 2 (Woo) | 727 | 27 d | **74.1 %** | 0.3 % | 74.1 % |
| shop 5 (Woo) | 241 | 16 d | 2.9 % | 0.4 % | 3.3 % |
| Shopify shop | 748 | 19 d | 0.7 % | 0.4 % | 1.1 % |
| Odoo shop | 1,409 | 19 d | 6.1 % | 2.4 % | 8.4 % |

The Wix shop has 53 listings and 12 stock flips in 3 daily cycles. It is a manufacturer
restocking spools, so it is genuinely volatile. The marketplace and shop 4 are disabled
(blocked), so there is no data for them.

### Four findings that shape the plan

**1. Most listings almost never change.** Excluding shop 2, about 3 % of listings moved
in roughly 3–4 weeks. As a Poisson rate that is λ ≈ 0.0015 per day for shop 1, one change
every ~2 years per listing. A uniform weekly sweep spends almost every request
re-confirming an unchanged price.

**2. Change is concentrated, and predictable from data we already hold.** Excluding
shop 2:

| Segment | n | Price moved | Stock moved |
|---|---:|---:|---:|
| price < 50 EGP | 4,415 | 0.6 % | 0.6 % |
| price 50–200 | 1,394 | 1.8 % | 2.2 % |
| price 200–1,000 | 1,124 | 8.0 % | 2.0 % |
| price ≥ 1,000 | 693 | 10.4 % | 3.0 % |
| out of stock at baseline | 728 | 2.9 % | **9.1 %** (restocks) |
| in stock at baseline | 6,964 | 2.8 % | 0.5 % |
| offered by more than one supplier | 797 | 5.4 % | 1.3 % |
| offered by one supplier | 6,909 | 2.5 % | 1.3 % |

- **The ≥ 200 EGP listings are 24 % of listings but carry ≈ 76 % of the price changes.**
- **Category spread:**
  - batteries 14.4 %, measurement 9.9 %, dev boards 9.1 %, displays 8.5 %;
  - resistors (1,132 listings), diodes, regulators and fuses 0.0 %;
  - ICs 0.2 %, capacitors 0.4 %.

**3. Change comes in shop-wide repricing waves, not independent events.**

| Source | Changes | Median new/old ratio | Direction |
|---|---:|---:|---|
| shop 2 | 539 | 1.10 | 457 up, 81 down |
| shop 1 | 92 | 1.11 | 89 up, 3 down |
| Odoo shop | 86 | 1.10 | all up |

That pattern is an inflation reprice, applied in bulk. Two consequences:

- A per-listing Poisson model alone mis-predicts this.
- A cheap *sentinel* sample per shop can detect a wave the day it starts.

**4. We can't estimate per-listing rates yet, because unchanged re-reads leave no
trace.** `price_observations` writes only on change, and `last_verified_at` keeps only
the latest check. The standard estimators need *n checks and X detected changes* per
listing (§2, T7). Phase 0 adds that counter.

---

## 1. What the crawler wastes today

### 1a. Request spend per cycle (enabled sources)

| Source | Requests per cycle | Listings | Listings per request | Cycle (target) | Notes |
|---|---:|---:|---:|---|---|
| shop 1 | 157 (141 pages + 16 cycle data) | 13,434 | ~86 | 7 d | last closed cycle took 24 d (timeout, since fixed) |
| shop 3 | 64 | 5,604 | ~88 | 7 d | |
| shop 2 | 43 (21 + 22, of which 18 are price breaks) | 1,761 | ~41 | 6 d | |
| shop 5 | 20 | 393 | ~20 | 5 d | |
| Shopify shop | 7 | 1,267 | ~181 | 7 d | |
| Odoo shop | 497 | 2,877 | **~5.8** | 7 d | plus details at 20 a run (140 a week) |
| Wix shop | 7 a day = 49 a week | 53 | ~7.6 | daily | plus details on change |
| **Total** | **≈ 837 list requests a week + ≤ 140 details** | ≈ 25,400 | | | |

The marketplace (~1,216 a cycle over 608 partitions, 31,245 listings) and shop 4 (~50)
are disabled and not counted.

### 1b. The waste, in order of size

**W1. The Odoo shop reads each product twice a cycle, and pays a request to learn a
partition has ended.**

- Its 170 leaf categories (~400 pages) and the whole-shop `/shop` pass (97 pages) cover
  the same 2,877 products. `/shop` exists to catch 8 products filed under no category
  (CLAUDE.md).
- Odoo never serves an empty page, so the end is detected by fetching a *repeat* of the
  last page (`odoo.py:163`). Leaves average ~2.35 pages, which implies ≈ 170 of the
  ~400 leaf requests are that terminal repeat.
- The Odoo shop's robots.txt disallows `ppg=` and `order=`, so neither bigger pages nor a
  sort by modification date is available.
- The upshot: 497 requests a cycle for 2,877 listings, against a floor of ~96 if one
  `/shop` pass were enough.

**W2. Every partition pays one request to read "nothing".**

- WooCommerce Store API partitions end on an empty page (`woocommerce.py:296`). That is
  3 partitions × 4 shops = 12 requests a cycle, ~4 %.
- Shopify ends on an empty page: 1 of 7, 14 %.
- The adapter already knows how to avoid this: `_fetch_unlisted` uses `X-WP-TotalPages`
  or `len(rows) == PER_PAGE`. The Store API path doesn't.

**W3. A uniform cadence.** Every listing is re-read once a cycle whatever its volatility.
From §0:

- resistors (0 changes) are read as often as batteries (14 %);
- out-of-stock listings, which restock at 9 % per ~3 weeks, are read as often as cheap
  in-stock parts (0.6 %).

The waste here is in *staleness*, not in request count: expensive, volatile listings
wait the full cycle.

**W4. The order is fixed regardless of value.**

- `_partitions_for_this_run` takes outstanding partitions in list order.
- The details stage spends its budget on never-fetched listings *newest first*. At 20 a
  run the Odoo shop's backfill takes 144 days: 55 of 2,877 read so far.
- Nothing prefers the 2,252 listings in multi-supplier products, where a stale price
  makes the comparison false.

**W5. Multi-day offset paging can skip listings, and a skipped listing is archived (a
hypothesis, to measure).** A WooCommerce stock partition is read over ~7 daily runs by
page offset. Two kinds of event during the cycle cause skips:

- A listing that leaves an already-read page shifts later items onto pages already
  read.
- A listing that moves from in-stock to out-of-stock lands in a partition already
  swept.

Each such event can skip one listing for the whole cycle. That listing is then archived
at cycle end and restored when next seen. The scale is plausible: shop 1 moves ~0.4 % of
listings between stock partitions a week, giving an estimated 10–40 skips a cycle. Shop 1
archived 173 listings on 2026-11-12, 66 on 2026-10-18; most were in stock when last seen.
We can't yet separate real removals from skips; M6 (§3) measures it.

**W6. Conditional requests and sitemaps.** These are not a waste today, but also not the
lever they are for search engines (T11, T12).

### 1c. How to estimate waste, repeatably

- **Requests per cycle** = `stats.cycle.cycle_pages` + cycle data + details, from
  `ingestion_runs`.
- **Changes per 1,000 requests** = new `price_observations` rows with a changed price or
  stock (excluding first rows and archive rows) ÷ `stats.requests` total, per source per
  cycle. Today, roughly: shop 1 ≈ 0.9 changes per request outside waves, the Odoo shop
  ≈ 0.3.
- **Redundant-read share (Odoo shop)** = listings read in both `/shop` and a leaf ÷
  listings read. Needs the check log (Phase 0).

---

## 2. Techniques

Each technique below gives its research basis, what our sources actually expose, the
gain, cost and risk, and how it fits the partition/cursor model.

### Research basis (short)

- **Cho & Garcia-Molina** introduced the *freshness* (0/1, is the copy current) and
  *age* (how long it has been wrong) metrics. They showed that under a fixed budget,
  revisiting in proportion to change rate is *worse* than uniform for average freshness:
  pages changing faster than you can revisit should get *fewer* visits.
  - "Synchronizing a database to improve freshness", SIGMOD 2000.
  - "Effective page refresh policies for web crawlers", ACM TODS 28(4), 2003.
- **The regime we are in.** For λ·I ≪ 1, which is all of our segments, the expected
  stale fraction of an element is ≈ λ/(2f). Minimising Σ wᵢλᵢ/(2fᵢ) subject to Σfᵢ = B
  gives **fᵢ ∝ √(wᵢλᵢ)**, the square-root rule. This is our derivation, consistent with
  their result in the low-change limit.
  - Our two-segment split (24 % of listings at ~10× the rate) gives a **~27 % staleness
    cut at equal requests**.
  - Finer segments (category × price band × stock) gain more.
- **Estimating change frequency from incomplete observation.** Cho & Garcia-Molina,
  "Estimating frequency of change", ACM TOIT 3(3), 2003. When a check sees only "changed
  or not" (our case, and we miss multiple changes between checks), the naive X/T is
  biased. Their estimator for n checks at interval I with X changes detected is
  `λ̂ = −ln((n − X + 0.5)/(n + 0.5)) / I`, with a variant for irregular intervals. A
  last-modified date, where one exists, gives a better estimator.
- **Sampling to detect change.** Cho & Ntoulas, "Effective change detection using
  sampling", VLDB 2002: sample a few pages per site, then spend the budget where the
  sample shows change. This is the basis for our sentinel idea.
- **Importance-weighted and politeness-constrained scheduling:**
  - Wolf et al., "Optimal crawling strategies for web search engines", WWW 2002
    (the "embarrassment" metric);
  - Pandey & Olston, "User-centric web crawling", WWW 2005 (weight by user impact);
  - Kolobov, Peres, Lubetzky & Horvitz, "Optimal freshness crawl under politeness
    constraints", SIGIR 2019 (per-host rate limits, which is exactly our constraint);
  - Kolobov et al., "Staying up to date with online content changes using
    reinforcement learning for scheduling", NeurIPS 2019 (complete vs incomplete change
    observations);
  - Azar et al., "Tractable near-optimal policies for crawling", PNAS 2018.
  - Survey: Olston & Najork, "Web Crawling", Foundations and Trends in IR, 2010.
- **Production crawlers:**
  - Apache Nutch `AdaptiveFetchSchedule` (`conf/nutch-default.xml`): the interval grows
    by `inc_rate` 0.4 when a page is unchanged and shrinks by `dec_rate` 0.2 when it
    changed, bounded by min/max interval, with optional `sync_delta` towards the
    observed modification time.
  - StormCrawler's AdaptiveScheduler is the same idea, keyed on a content signature.
  - Common Crawl's CCBot is built on Nutch and seeds from sitemaps.
  - Heritrix has fetch history with content-digest dedup and conditional requests.
- **Google:**
  - Crawl budget = capacity × demand ("Large site owner's guide to managing your crawl
    budget"; developers.google.com/crawling/docs/crawl-budget).
  - Google supports `ETag`/`If-None-Match` and `Last-Modified`/`If-Modified-Since`,
    preferring ETag ("Crawling December: HTTP caching", Search Central blog, Dec 2024).
  - Sitemap `lastmod` is used only when it is consistently accurate (Search Central
    blog, June 2023, when the sitemap ping endpoint was retired).
  - **IndexNow** (indexnow.org; Bing and Yandex) is a *push* protocol: a site notifies
    engines of changed URLs. Our shops don't push to us, so it doesn't apply to fetching.
    It could later announce makhzan's *own* changed product pages to Bing; that is out
    of scope here.
- **E-commerce price-monitoring practice.** Commercial monitors such as Prisync and
  Price2Spy sell per-SKU check frequency tiers and prioritise key SKUs, and use delta
  feeds where a merchant offers them. That is consistent with the tiering below. These
  are vendor product pages, not research; treat them as practice, not evidence.

### Which levers our sources expose (from docs, code and the QA surveys; no probing)

| Lever | WooCommerce (shops 1–5) | Shopify shop | Odoo shop | Wix shop | Marketplace |
|---|---|---|---|---|---|
| Changed-since listing | **Store API `after=…&date_column=modified`** (documented values `date`, `date_gmt`, `modified`, `modified_gmt`); `orderby=modified` documented. QA: shop 1 306 changed in 8 d, shop 4 133. **Useless on shop 3**: a nightly job touches all ~5,600. **Unverified whether order-driven stock changes bump `modified`** | `updated_at` is fake (= request time, QA) | `order=` disallowed by robots.txt | none | no sort by update (QA) |
| Fetch arbitrary ids in one request | Store API `include[]`, up to `per_page=100` (documented). Not disallowed by robots.txt for our token | no (one `/products/<h>.json` each) | no | no | no |
| Per-product change token on list page | none needed (price and stock are on the card) | none usable | **`?unique=`** = Odoo write_date (used) | card hash (used) | card hash (used) |
| Sitemap `lastmod` | real dates but no product ids; same as `wp/v2.modified` | fake | none for products; full URL census (2,864 URLs, 1 request) | bulk-save date (unproven) | no sitemap |
| `X-WP-TotalPages` / page count | yes on wp/v2 (used for the unlisted pass); Store API to confirm from a stored response | no; short page means end | pager in HTML; short page means end (fixed 30 per page) | n/a | ? |
| ETag / Last-Modified honoured | not observed on dynamic routes | not observed | not observed | weak ETag on every page | **ignored** (QA test) |

### The techniques

The headline figures, before the detail:

- **T1** is the single biggest pure saving: **~34 % of the Odoo shop's cycle** (~165 of
  497).
- **T3** is the enabling technique: it brings per-listing scheduling to WooCommerce at
  list-page efficiency.

**T1. End a partition without the terminal request.**

- **What:** stop when a page is shorter than the page size, or when the page count or
  pager says it is the last. Odoo: page size 30 (fixed; `ppg` is forbidden), or parse
  the pager. Woo Store API: `len < per_page` or `X-WP-TotalPages`. Shopify:
  `len < 250`.
- **Gain:** Odoo shop ≈ 165 of 497 requests a cycle (−33 %). Woo ≈ 12. Shopify 1.
- **Cost:** small, inside each adapter's `fetch_page` and `has_more`.
- **Risk:** a short page that isn't the last. That is impossible on offset-paginated
  WP_Query or Odoo, but run in **shadow** for one cycle first: record "would have
  stopped" beside the real end, and require zero disagreements.
- **Fit:** perfect. The cursor and per-page checkpointing are untouched.

**T2. Stop reading the Odoo shop twice.** Three options; this is decision D4.

- (a) Keep both passes and apply T1. The cycle becomes ≈ 326 requests.
- (b) Replace the 97-page `/shop` pass with the sitemap census (1 request), plus a
  product-page read for each product that is in the sitemap but in no category
  (≈ 8–15).
  - Cycle ≈ 245.
  - Risk: the sitemap matched the database to 99.5 %, so 15 ids missing would be read
    only if they are in a category.
- (c) Sweep `/shop` (96 pages with T1) every cycle for price and stock, and the leaves
  (≈ 230 with T1) every Nth cycle for category.
  - Weekly cost ≈ 96 + 230/N, which is ≈ 154 at N = 4.
  - Or, at today's budget, price and stock checked about 3× a week.
  - Risk: a new product is uncategorized until the next leaf sweep, since the source is
    authoritative and nothing is inferred. A category move waits N cycles.
  - `knows_category` is already False for `/shop`, so existing categories are never
    erased.
  - Measure category churn first: in Phase 0, how many listings change category
    between leaf sweeps.

**T3. A WooCommerce "recheck lane" with `include[]`.**

- **What:** a daily request with `include=<up to 100 chosen ids>&per_page=100` re-reads
  the 100 listings that most need it, at the same 100 listings per request as a list
  page.
- **Gain:** this is what makes importance- and volatility-based scheduling (T7, T8)
  possible on WooCommerce shops. Example: 3 requests a day on shop 1 re-check the ~1,800
  priciest volatile listings every ~6 days *on top of* the weekly sweep, or the top 300
  every day.
- **Cost:**
  - an adapter method plus a scheduler query, and a new `stats.requests` label
    (`recheck`);
  - it goes through `take_turn`, so `stats.pacing` stays truthful automatically.
- **Risk:**
  - unverified on these shops (does `include` honour 100 ids; is there a URL-length or
    WAF issue?);
  - a new request pattern the shop sees.
- **Fit:**
  - a second lane *beside* the cycle, never replacing it;
  - it uses no cursor and never closes a cycle;
  - a listing it returns gets `last_verified_at` and `last_seen_at` (true: the source
    just listed it with a price);
  - a listing it *doesn't* return is never archived for that reason (see T4).

**T4. Confirm before archiving (reduces W5).**

- **What:** at cycle end, archive candidates (`last_seen_at < cycle_started_at`) are
  first re-asked:
  - Woo: `include[]` with 100 per request, so shop 1's 173 candidates cost 2 requests;
  - Odoo: the product page, capped at about 20;
  - Wix: the sitemap already exists.
- **Rules:**
  - a candidate the source returns is kept and its `last_seen_at` set;
  - a candidate it doesn't return is archived as today;
  - if the confirmation fails, archiving waits for the next run (cursors stay
    exhausted).
- **Gain:** fewer false archivals; product ids stop flapping between "no longer listed"
  and back.
- **Cost:** 1–20 requests a cycle.
- **Risk:** a delayed archive if confirmation keeps failing. Cap the wait at one cycle,
  then archive as today.
- **Fit:**
  - strengthens "never archive on partial evidence";
  - keeps the cycle gate, and `last_seen_at` remains what archiving reads.

**T5. A WooCommerce "modified-since" lane.**

- **What:** daily, `after=<last lane run − 1 h>&date_column=modified&orderby=modified&per_page=100`.
  That is 1–4 requests on shops 1, 2 and 5 (QA: shop 1 had 306 in 8 days, ≈ 1 page a
  day). Not on shop 3.
- **Gain:** a price edit is seen within ~1 day instead of ~3.5 (half of a 7-day cycle),
  for ≈ 1–2 % more requests.
- **Risk:**
  - **stock changes from orders may not bump `post_modified`** (WooCommerce updates
    stock by direct query; QA flagged this as unverified);
  - a nightly bulk job, as on shop 3, would make the lane read the whole catalogue.
    Guard: if a lane run returns more than X pages, stop and disable it for that source
    (`stats.lane.disabled`).
- **Shadow first:** run it for one cycle without upserting, only recording ids. Then
  compare with the changes the full sweep detected: recall for price, recall for stock.
- **Fit:** same as T3. A side lane, no cursor, never archives.

**T6. Cadence tiers by partition (an alternative to T3 where `include` isn't
acceptable).**

- **What:** split a Woo partition by `category=` or `orderby=price&order=desc` head
  pages, swept more often than the tail.
- **Risk:** price-sorted paging drifts while prices change, which is W5 again.
- **Verdict:** T3 dominates it. Keep T6 as the fallback and for the marketplace, whose
  partitions *are* categories: there, schedule partitions by Σ wλ of their listings
  rather than round-robin (Phase 3).

**T7. Per-listing change-rate estimates.**

- **What:**
  - record checks: per listing, `checks`, `changes` and `first_checked_at` (or a
    per-cycle aggregate table);
  - estimate λ with the Cho–Garcia-Molina estimator;
  - **shrink towards a segment prior** (domain:category × price band × stock state ×
    source; a Gamma–Poisson empirical-Bayes prior), because one listing has only a few
    checks a month.
- **Gain:** the input every scheduling decision needs. Without it T3 and T8 run on
  segment rates only, which is fine to start with.
- **Cost:** a migration (two or three columns, or one small table), and one extra
  update per upsert, which is already happening.
- **Risk:**
  - waves violate the Poisson assumption. Detect them separately (T9) and exclude wave
    days from λ fitting, or cap a wave's contribution per listing;
  - a `limit=` run must not count as a check (consistent with `record_history`).

**T8. Importance weights.** What exists now:

- multi-supplier products (891 products, 2,252 listings; a stale price there makes the
  comparison false);
- in stock vs out of stock (a buyer acts on in-stock);
- *volatility* belongs in λ, not in w;
- category demand: none yet;
- later: product page views and shop click-outs.

Those last two signals live in Umami (`data-umami-event`), not in Postgres. They would
need a nightly export, an extra row in the `sources` config, or a small events table.

- **Suggested start:** w = 1 + 1·[multi-supplier] + 0.5·[in stock]. Revisit when there
  are four weeks of click data.
- **Gain:** staleness goes where it is seen (Pandey & Olston).
- **Risk:** feedback loops (fresh items get clicked, clicked items get refreshed). Keep
  a floor: every listing stays in the weekly cycle regardless.

**T9. Wave sentinels and surge mode.**

- **What:**
  - each daily run re-reads a fixed random panel per source: 100 listings stratified by
    price band, one `include[]` request on Woo; the first page of a busy leaf on Odoo;
  - if the panel's change share exceeds a threshold (for example 5 % against a baseline
    of ~0.3 % a day), the source enters *surge* for this cycle: its run budget rises to
    the existing ceiling (`max_pages_per_run`, never above), so the wave propagates in
    2–3 days instead of 7.
- **Gain:** shop 2's 74 % reprice and the ~10 % waves at shop 1 and the Odoo shop would
  be on the site within days.
- **Cost:** 1 request a day per source, plus a flag in `stats.budget`.
- **Risk:** threshold tuning; a false surge only spends up to the approved ceiling.
- **Fit:** reuses `_page_budget`, which already plans per run under a ceiling.

**T10. Adaptive details revisit (Nutch-style).**

- **What:** for card-hash sources (the Wix shop, the marketplace), `max_age_days` adapts
  per listing:
  - when a page re-read finds no change: interval × 1.4;
  - when it finds a change: × 0.8;
  - bounded to [30, 180] days.
- Also order never-fetched listings by importance (T8), not newest first: the Odoo
  shop's 144-day backfill then reaches multi-supplier and in-stock listings first.
- **Gain:** details where they are read; fewer blind 90-day re-reads.
- **Cost:** small (`details.py` orderings, one attribute).
- **Risk:** low. A changed token always wins first, as today.

**T11. Conditional requests (ETag / If-Modified-Since).**

- **Measure only.** Our budget is *requests*, and a 304 still costs one, so the gain is
  bandwidth and the shop's CPU, not freshness.
- Validators are absent on the Woo and Odoo dynamic routes, ignored by the marketplace,
  and weak on Wix.
- **Plan:** log the presence of `ETag` and `Last-Modified` per response for one cycle;
  this costs zero requests. Build it only if more than ~30 % of pages carry a validator.

**T12. Sitemaps as a census, never as a change feed.** No source has an honest
per-product `lastmod` that we lack another way to get. Uses:

- the Odoo shop (1 request for 2,864 URLs) as an **archive veto**: a listing missing
  from the sweep but present in the sitemap is held and confirmed (T4), not archived;
- the Wix shop already compares its sitemap.

Don't let sitemap presence set `last_seen_at`. A sitemap can lag the shop, and "seen"
would then outlive the product.

**T13. New-product discovery.**

- Woo: `orderby=date&order=desc` page 1 daily, 1 request. A new product appears within a
  day instead of up to 7. It rides the recheck lane's budget.
- The Wix shop's "New Arrival" gallery is already daily. The Shopify shop has
  `created_at`; the default order of `products.json` is to be checked from stored pages
  before relying on it.

### Summary table

| | Gain | Requests | Effort | Risk | Needs owner? |
|---|---|---|---|---|---|
| T1 short-page end | −33 % for the Odoo shop | −180 a cycle | S | low (shadow) | no |
| T2 Odoo restructure | −80 to −340 a week | −80 to −340 | S–M | medium | **D4** |
| T3 include[] lane | targeted freshness | +3–5 a day per Woo shop | M | medium (unverified) | **D2** |
| T4 confirm before archive | fewer false archivals | +1–20 a cycle | S | low | D3 |
| T5 modified lane | ~1-day price detection | +1–4 a day | S | medium (stock recall) | **D2** |
| T7 λ estimates | scheduling input | 0 | M (migration) | low | D10 |
| T8 importance | staleness where seen | 0 | S | low | D6 |
| T9 sentinels and surge | waves in 2–3 d | +1 a day, surge ≤ ceiling | M | low | D8 |
| T10 adaptive details | better details budget | 0 | S | low | D11 |
| T11 conditional GET | bandwidth only | 0 | S (log only) | none | D9 |
| T12 sitemap veto | safer archiving | +1 a cycle | S | low | D5 |

---

## 3. Phased plan

### Metrics (definitions used before and after)

- **M1 Requests**, per source per day and per cycle (`stats.requests`, `stats.pacing`).
  Hard limit: never above today's per-source daily maximum without decision D1.
- **M2 Coverage**: cycle length (`stats.cycle.cycle_seconds`); share of active listings
  seen per cycle; `last_verified_at` p50, p90 and p99 age per source.
- **M3 Changes detected per 1,000 requests**, per source per week:
  - price and stock change rows ÷ requests;
  - split by lane (sweep, recheck, modified, sentinel), using a new
    `price_observations.via` column or the run's stats counters.
- **M4 Estimated staleness**: Σᵢ wᵢ·(1 − e^(−λ̂ᵢ·ageᵢ)) / Σᵢ wᵢ, where ageᵢ = now −
  `last_verified_at`. This is the expected share of *displayed* prices that are wrong,
  weighted by importance.
  - Report it overall, for the high-weight group, and for the ≥ 200 EGP band.
  - Until T7 lands, use segment λ from §0.
- **M5 Detection delay**: for each detected change, `observed_at` − previous check time
  (an upper bound on how long the site was wrong). Report the median and p90, by lane
  and by segment.
- **M6 False archivals**: listings archived and re-seen within 2 cycles, per cycle per
  source. Already observable: an `available=false` row followed by `available=true`.
- **M7 Politeness unchanged**:
  - min gap ≥ 15 s (or Crawl-delay) per host;
  - error and 429 rate no higher than baseline;
  - no new `stats.stopped`.

### Phase 0: measure (2 weeks ≈ 2 cycles; zero extra requests)

1. Add the check log (T7 schema): `checks`, `changes` and `first_checked_at` per
   listing, updated in `_upsert_listing` and `_mark_out_of_stock`, skipped for `limit=`.
2. A `make freshness` report computing M2–M6 from the database: a read-only SQL report
   beside `make status`. Include the §0 segment table, so it can be re-run each week.
3. Shadow T1 in the Odoo, Woo and Shopify adapters: `stats.source_report.would_stop`
   per partition. No behaviour change.
4. Log the presence of response validators (T11) into run stats. Nothing is published:
   keep it out of `stats.pacing` and out of the `/how-we-crawl` payload.
5. For the Odoo shop, record each listing's leaf category per sweep, to measure category
   churn for D4.

**Exit:** two closed cycles per enabled source with baselines for M1–M7, and zero
"would stop" disagreements.

### Phase 1: pure savings and safety (≈ 1 week of work)

- T1 live. Expected: the Odoo shop 497 → ≈ 326 a cycle; Woo −12; Shopify −1.
- T10 ordering (importance-first backfill; adaptive `max_age`).
- T4 and T12: confirm before archive; the sitemap veto for the Odoo shop.

**Success:**

- the Odoo shop M1 down ≥ 30 %, with an *identical* seen set: the ids seen per cycle
  equal the Phase 0 baseline, give or take real additions and removals;
- M6 down;
- M7 unchanged.

### Phase 2: WooCommerce lanes (after D2; ≈ 2 weeks of work and 2 cycles of shadow)

- T5 in shadow for one cycle on shops 1, 2 and 5. Go live only if price recall ≥ 95 %.
  If stock recall is poor, the lane covers price only and stock stays with the sweep.
- T3 recheck lane at 3 requests a day on shop 1, 1 on shops 2 and 5, and 2 on shop 3.
  Priority = w·λ̂_segment × (1 − e^(−λ̂·age)), the expected weighted staleness removed
  by a check (the greedy form of the square-root rule).
- T9 sentinels (one `include[]` request a day per Woo shop). Surge stays capped at the
  existing ceiling.
- T13 newest page, inside the lane budget.
- Optionally, reinvest the T1 savings at the Odoo shop as a recheck there: the busiest
  leaves (batteries, measurement, dev boards) on a 2–3 day cadence. That would need a
  per-partition cadence. It is a small generalisation of `_partitions_for_this_run`: an
  exhausted partition becomes *eligible again* after its cadence, as a lane visit that
  doesn't reset its cycle cursor.

**Success, measured against the Phase 0 baseline on the same sources:**

- M5 median for the ≥ 200 EGP band: from ~3.5 d to ≤ 1 d;
- M4 for the high-weight group down ≥ 40 %;
- M3 up ≥ 50 %;
- M1 within +5 % of baseline. Phase 1 savings more than pay for it at the Odoo shop,
  but Woo lanes are per host, so each Woo shop is checked against its own baseline.

**A/B:** stagger it. Shop 1 and shop 5 start with lanes; shop 3 (no modified lane) is
the control for one cycle, then gets the recheck lane only.

### Phase 3: per-listing scheduling and the marketplace (after 4+ weeks of check data)

- T7 estimates per listing with segment shrinkage. They replace segment λ in the lane
  priority.
- T8 with click and page-view data from Umami, once ≥ 4 weeks exist (D6).
- T2(c) for the Odoo shop if Phase 0 showed low category churn (D4).
- Marketplace, when unblocked: partition order by Σ w·λ̂ per page (T6) instead of list
  order, keeping the coverage cycle. Its 608 category partitions are where
  prioritisation pays most: 31k listings and ~1,216 requests a cycle.

**Success:** M4 down a further 20 % at equal M1, and M5 p90 for high-weight listings
≤ 3 days.

---

## 4. Invariants that must not break

1. **Archiving is cycle-gated and reads `last_seen_at`.**
   - Only `_finish_cycle_if_swept` archives, only after every partition is exhausted,
     and only on `last_seen_at < cycle_started_at`.
   - Lanes (recheck, modified, sentinel, newest) never mark a partition swept, never
     close a cycle and never archive.
   - A lane *may* set `last_seen_at` and `last_verified_at` on listings it returned
     with price data (D3).
2. **Never archive on partial evidence.**
   - A listing's absence from a lane response, a sitemap or a confirmation that failed
     is not evidence.
   - T4 can only *prevent* an archive.
   - A `limit=` run still archives nothing and records nothing (no checks, no history).
3. **Per-page checkpointing.**
   - Each page commits and advances its cursor.
   - Lanes commit per request, but own no cursor; a lane interrupted mid-way loses
     nothing but its own unfinished request.
   - The coverage sweep's resume point is never moved by a lane.
4. **`stats.pacing` is public and is what was sent.**
   - Every lane request goes through `take_turn`, robots.txt (full URL, query included)
     and the source's identity.
   - New labels go in `stats.requests` (purposes only).
   - Never add errors, status codes, lane hit rates or "why slowed" to the public
     endpoint.
   - Validator logging and sentinel results go in non-public stats keys.
5. **Politeness:**
   - one request at a time per host, at least 15 s or Crawl-delay;
   - Retry-After binds the host;
   - slowdown on errors;
   - `max_pages_per_run` stays the hard ceiling on a run's total, lanes included: count
     lane requests against the same run budget in `_page_budget`;
   - `RUN_TIME_SHARE` still ends the run.
   - A host that refuses (`HostBackingOff`, `RobotsUnavailable`) stops lanes too.
6. **One run per source, one worker process.** Lanes run inside the source's
   `crawl_source` job, under `_exclusive`, never as separate jobs.
7. **Category semantics.**
   - A lane carries no category signal: `knows_category` is False for lane items.
   - An `include[]` response does carry the item's categories. Even so, treat it like
     `/shop` (never clear a category) unless and until a decision says otherwise.
   - Crosswalk drift `unused` stays computed from complete sweeps only; lane
     observations never feed it.
8. **Details carry-over.** Lane upserts go through `_upsert_listing`, so
   `carry_details` and `apply_details` keep page-derived details.
9. **Grouping and ids** are unaffected. More frequent price updates still go through
   `rebuild_and_reindex` per 10-minute window.

---

## 5. Decisions for the owner

**D1. What to do with the savings.**

- Options:
  - (a) Bank them: fewer requests to shops.
  - (b) Reinvest all of them in freshness lanes.
  - (c) Split.
- **Recommendation: (c).** Bank the Odoo shop's T1 saving (−33 % there). Spend
  WooCommerce lane requests only within +5 % of each Woo shop's own baseline. Never
  exceed today's per-source daily maximum.

**D2. New request patterns on WooCommerce shops** (`include[]` recheck lane,
modified-since lane, newest page).

- Options:
  - (a) Approve for shops 1, 2 and 5 (the modified lane not on shop 3).
  - (b) Approve the recheck lane only.
  - (c) Neither; use T6 partition tiers instead.
- **Recommendation: (a).** Start with shadow runs, not ad-hoc probes. Shop 4 and the
  marketplace wait until they are unblocked.

**D3. Can a lane sighting update `last_seen_at` and `last_verified_at`?**

- Options: (a) both; (b) `last_verified_at` only; (c) neither, lanes only update price.
- **Recommendation: (a).** It is true: the shop just listed the product with a price.
  Lanes still never archive or close a cycle.

**D4. The Odoo shop's double read.**

- Options:
  - (a) Keep both passes, T1 only (≈ 326 a cycle).
  - (b) Sitemap census plus orphan product pages instead of `/shop` (≈ 245).
  - (c) `/shop` every cycle, leaves every Nth (≈ 154 a week at N = 4, or 3× fresher
    prices at today's spend).
- **Recommendation: (a) now; (c) in Phase 3** if Phase 0 shows category churn below
  ~1 % a cycle.

**D5. Sitemap as an archive veto.**

- Options:
  - (a) Veto: hold and confirm a candidate the sitemap still lists.
  - (b) Treat sitemap presence as "seen".
  - (c) Don't use it.
- **Recommendation: (a).** Never (b): a sitemap can lag.

**D6. Importance weights before click data exists.**

- Options:
  - (a) w = 1 + [multi-supplier] + 0.5·[in stock].
  - (b) Uniform weights; volatility only.
  - (c) Wait for Umami clicks.
- **Recommendation: (a) now**, re-fit with clicks after 4 weeks. Exporting Umami events
  into Postgres is its own small decision (what, how often, retention).

**D7. A freshness promise.**

- Options:
  - (a) Keep the public "about weekly".
  - (b) Publish a tiered promise ("volatile items within ~2 days").
  - (c) Internal targets only.
- **Recommendation: (a) public plus (c) internal:** 95 % of high-weight listings
  checked within 3 days; M4 tracked weekly.

**D8. Surge mode on a detected repricing wave.**

- Options:
  - (a) Allowed up to the existing `max_pages_per_run` ceiling.
  - (b) Allowed above it, temporarily.
  - (c) Off.
- **Recommendation: (a).** Never above the ceiling the owner approved per shop.

**D9. Conditional requests.**

- Options: (a) log validator presence for a cycle, then decide; (b) build now; (c) skip.
- **Recommendation: (a).** A 304 saves bytes, not requests.

**D10. Where the check log lives** (prerequisite for T7, M4 and M5).

- Options:
  - (a) Columns on `listings` (`checks`, `changes`, `first_checked_at`).
  - (b) A per-cycle aggregate table.
  - (c) A row per check (too big: ~25k rows a week).
- **Recommendation: (a)**, plus `via` on `price_observations` for lane attribution.

**D11. Details backfill order.**

- Options: (a) importance-first (multi-supplier, in stock); (b) keep newest-first.
- **Recommendation: (a).** Newest-first still applies within each importance tier.

**D12. Odoo per-partition cadence** (busy leaves re-visited every 2–3 days as a lane).

- Options: (a) yes, funded by part of the T1 saving; (b) no.
- **Recommendation: decide after Phase 0** shows per-leaf change rates. Batteries,
  measurement and dev boards are the likely candidates.

---

## Caveats (said plainly)

- **The change rates rest on three days of recorded history.** Each listing has one
  interval-censored sample against a seeded baseline (16–27 days), and shop 2's figures
  are one bulk reprice. Re-run §0 after Phase 0 before tuning any threshold.
- **W5 (skips from offset drift) is a hypothesis**, consistent with the archiving
  numbers but not demonstrated. M6 decides it.
- **Several levers are unverified on our shops:**
  - `include[]` with 100 ids;
  - whether order-driven stock changes bump `modified`;
  - Store API `X-WP-TotalPages`;
  - the Shopify `products.json` default order.

  Each is to be settled by a shadow run through the crawler's own client, after
  approval, never by curl.
- **The research numbers are general results.** The "~27 % at equal requests" is our
  calculation from §0's two-segment split under the square-root rule, not a measured
  outcome.
