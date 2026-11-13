**Status:** design only (2026-11-13); waits for 4–8 weeks of Phase 0 data. Decisions P3-D1…D12 are open.

# Crawler scheduling, Phase 3: read what matters, sweep the rest slowly

**Status:** design only, 2026-11-13; nothing changed, no request sent to a supplier. Builds
on `crawler-scheduling-plan.md` (T1–T13, §3, §4, D1–D12). Umami figures: read-only
aggregate `SELECT`s inside `BEGIN TRANSACTION READ ONLY … ROLLBACK`.

**The owner's direction (2026-11-13):** "Measure what the users visit most and prioritize
it. Measure what changes more and adjust the pacing. We don't have to lock the crawling
sweep at 7 days. It could run for longer but prioritize the important or more changing
pages, giving the same result but gentler."

**In one paragraph.** Split today's single knob (a ~7-day cycle) into two lanes per source:
a **coverage sweep** that still reads every partition, but over 14–21 days, and a
**targeted lane** that spends the rest of a fixed **daily request budget** on the listings
(or partitions) whose expected *weighted staleness* is highest. Weight = importance (priors
now, visits later); staleness = per-listing change rate λ, shrunk towards its segment.
Archiving stays cycle-gated; a longer cycle is made safe by confirm-before-archive (T4), a
wave sentinel that doubles as an audit panel (T9), and a "not confirmed since" display state.
The modelled gain is real but smaller than "half the requests": **about 20–35 % fewer
requests at equal weighted staleness on WooCommerce shops**, more where structural savings
(T1, D4) stack on top. Bigger cuts are possible only by accepting staler low-weight listings.

---

## 1. Facts this design rests on

**Visits (Umami, makhzan's website only, since tracking began 2026-10-27):**

| Measure | Value |
|---|---:|
| Sessions per day, excluding 2026-11-06 | 1–5 (16 on 11-13) |
| Sessions on 2026-11-06 | 3,950, almost all on `/en/…` and `/ar/…` paths no current page has (a JS-running bot burst) |
| Product page views, all time | 75, on 43 distinct product paths, from 13 sessions |
| Product paths viewed by ≥ 2 distinct sessions | 5 |
| `shop-click` events | 12, from 6 sessions, all on product pages |
| `shop-contact` events | 0 |
| Event properties stored (`event_data`) | only `shop` (no product id; the product is in `url_path`) |

Umami 3.4.1 keeps one `website_event` row per view or event (`session_id`, `url_path`,
`url_query`, `referrer_*`, `event_name`, UTM and click ids). Search terms sit in `url_query`
and must never leave Umami.

**Conclusion:** visits are a design input, not yet a signal. With ~10⁴ products and a
handful of human sessions a day, almost every product has zero visits and the few non-zero
ones are noise. The pipeline should be built now so the data accrues, with its weight at
zero until a traffic gate is met (§3.5).

**Change** (plan §0): ~3 % of listings move in 3–4 weeks outside shop 2; ≥ 200 EGP listings
are 24 % of listings and ~76 % of price changes; out-of-stock listings restock at ~9 % per
3 weeks; categories range from 0 % (resistors, diodes, fuses) to 14 % (batteries); change
arrives in shop-wide reprice waves (shop 2: 74 %; shop 1 and the Odoo shop ~10 %, all up).
Per-listing rates are not estimable until Phase 0's `checks`/`changes` counters exist.

**Display lag:** product pages are ISR-cached for 6 h (bd37e7d); negligible against
day-scale intervals, but M4 should count age from `last_verified_at` plus 3 h.

---

## 2. The model in one formula

For listing *i*: importance **wᵢ**, change rate **λᵢ** (per day), time since last read
**aᵢ**. The expected stale share it shows is 1 − e^(−λᵢaᵢ). The objective is the
importance-weighted stale share averaged over time, subject to each source's daily request
budget Bₛ and the politeness rules.

Under a fixed budget the optimum visits each listing at frequency **fᵢ ∝ √(wᵢλᵢ)**
(plan §2). The scheduling rule that produces it, day by day, is an index on the
**staleness accumulated since the last read**:

  **Vᵢ = wᵢ · (aᵢ − (1 − e^(−λᵢaᵢ)) / λᵢ)  ≈  wᵢ·λᵢ·aᵢ² / 2** (for λa ≪ 1)

Read the highest-V units first until the budget is spent: a listing read when V crosses θ
gets interval √(2θ/(wλ)), the square-root rule.

**Correction to the plan's Phase 2.** The plan's lane priority, w·λ·(1 − e^(−λa)), is
≈ wλ²a, which visits at f ∝ wλ² — *more* skewed than proportional, which Cho &
Garcia-Molina show is worse than uniform. Use V above in Phase 2 as well.

**A unit** is whatever one request refreshes: 100 chosen listings (WooCommerce `include[]`),
one list page, or one partition (all its pages). Its value is **V_u = Σ_{i∈u} Vᵢ** and its
cost is its request count; rank units by V_u / cost.

---

## 3. Importance from visits

### 3.1 Getting the counts out of Umami — three routes

| Route | How | For | Against |
|---|---|---|---|
| **(a) Umami API** | Nightly job calls Umami's REST API with a dedicated view-only Umami user's API key (the `api_key` table exists), per day: product paths with visitor counts, and `shop-click` counts by path | Supported surface; survives Umami upgrades; returns aggregates only, so makhzan never holds a session id | Unverified on 3.4.1 that metrics can be broken down as *distinct visitors per path per day* and filtered by event; cannot drop heavy sessions |
| **(b) Read-only Postgres role** on `umami-db`, worker runs the aggregate `SELECT` itself | A role with `SELECT` on `website_event` only; query groups by day × path | Exact distinct-session counts; per-session bot filters possible | Couples makhzan to Umami's internal schema (v3 changed it); the role *can* read raw rows, so privacy rests on our query, not a grant |
| (c) A SQL view in `umami-db` with a role that may read only the view | Aggregation enforced by the grant | Strongest privacy | A view on `website_event` blocks Umami's own migrations that alter those columns (Postgres refuses `ALTER COLUMN TYPE` under a dependent view): an upgrade would fail |

Ruled out: counting in makhzan's own server; ISR renders a product page once per 6 h.

**Recommendation (P3-D1): (a)**, verified against 3.4.1 in a one-off check; **(b) as the
fallback** if the API cannot give visitors per path per day, with the query pinned in code
and a startup check that fails loudly when Umami's version changes.

### 3.2 What is stored in makhzan (privacy)

One nightly job (`export_demand`, in the ingestion worker, 02:30 UTC, before the 03:00
crawl) writes **yesterday only** into:

- `product_demand_daily(day, product_id, visitors, shop_clicks)` — distinct sessions that
  viewed `/products/<id>[-slug]`, and distinct sessions that clicked out from it. Path →
  id with the same rule as `productIdFrom`; merged ids followed to their successor;
  unknown ids dropped.
- `category_demand_daily(day, category_ref, visitors)` — category and department page
  visitors, for a coarser signal that fills up sooner.

Never exported: session or visit ids, query strings (search terms), referrers, UTM or
click ids, user agents, countries, timestamps finer than a day. Rows kept 180 days; after
that only the decayed score survives. Nothing from these tables is published, and none of
it touches `stats.pacing` or `/how-we-crawl`. The cookieless tracker and `data-do-not-track`
stay as they are. The privacy page should say that page-view counts per product help decide
what is re-checked first.

### 3.3 Bot filtering

Umami already counts only clients that run JavaScript and drops declared bots by user
agent. The 2026-11-06 burst shows that is not enough. On top of it:

1. **Count visitors, not views**: a session counts once per product per day.
2. **Spike quarantine**: a day whose site-wide sessions exceed 10× the trailing 28-day
   median is held, not used, until released by hand (`make demand-release DAY=…`). The
   11-06 burst would have been held.
3. **Only real products**: paths that do not resolve to a listed product are dropped
   (that alone removes the `/en/…` and `/ar/…` traffic).
4. Route (b) only: drop sessions that viewed > 30 product pages in a day. The owner's own
   browsing is excluded with Umami's per-browser opt-out.

### 3.4 Priors (what importance means before traffic exists)

**w₀ = 1 + 1·[product offered by ≥ 2 suppliers] + 0.5·[in stock]** (plan D6), times a
category-demand factor once that has data. Rationale: a stale price on a multi-supplier
product makes the comparison itself false; buyers act on in-stock offers.

Candidates not recommended now:

- **Search impressions from the API's own logs.** The API keeps no request log today. It is
  called by the Next server as well as by browsers, so it cannot tell a person from a
  render or a crawler, and `/search` is disallowed in robots.txt, so well-behaved bots
  never generate these anyway — what is left is the badly behaved ones. Revisit with
  traffic (P3-D4).
- **Price band as importance.** Already in λ; counting it twice would over-read them.

### 3.5 Blend, shrinkage, decay, gate

- **Decayed demand:** Dₚ = Σ_days 0.5^(age/28) · (visitorsₚ + 3·shop_clicksₚ). A click-out
  is the action the site exists for; half-life 28 days.
- **Shrinkage:** a product's demand rate is shrunk towards its category's rate per product
  (the same Gamma–Poisson machinery as §4). With little data the posterior is the category
  rate; with no category data it is 1.
- **Weight:** wᵢ = w₀ᵢ · (1 + κ · min(2, d̃ₚ / median d̃)), for every listing of the product
  (its page shows all offers). At most ×3, so the click/refresh feedback loop is bounded.
- **Gate:** κ = 0 until **≥ 1,000 human sessions in 28 days and ≥ 300 products with ≥ 2
  visitors**; then κ = 0.5, raised to 1 after a successful A/B (§7). Category demand is
  gated per category (≥ 30 visitors in 28 days). At today's rate the gate is months away;
  say so on the status report (`make freshness` shows progress towards it).

---

## 4. Change rate per listing

**What counts as a change:** a price change or an in-stock flip — what the site displays.
Title, description and the Odoo `?unique=` token are not changes for this purpose (the
details stage keeps its own token logic).

**Data (from Phase 0):** per listing, `checks` (n), `changes` (X) and `first_checked_at`;
exposure Tᵢ = `last_verified_at` − `first_checked_at`. A `limit=` run never counts.
Unchanged reads by any lane count as checks, so targeted reads do not bias the estimate
(change is memoryless; what matters is that every check is recorded).

**Estimator — Gamma–Poisson empirical Bayes:**

- Segment *s* = source × top-level category (`domain:slug`) × price band (< 50, 50–200,
  200–1,000, ≥ 1,000 EGP) × stock state at last read.
- Prior λ ~ Gamma(αₛ, βₛ). Posterior mean **λ̂ᵢ = (αₛ + Xᵢ) / (βₛ + Tᵢ)**: a new listing gets
  its segment's rate; one read 40 times speaks for itself.
- Fit αₛ, βₛ weekly by method of moments over the segment's listings: mean m of Xᵢ/Tᵢ;
  excess variance v' = variance − m·mean(1/Tᵢ); βₛ = m / v', αₛ = m·βₛ. If v' ≤ 0, the
  segment is homogeneous: pool it fully.
- Back off to source × price band, then source, below 30 listings or 5 changes. Stored in
  a small `change_priors` table; seeded from plan §0's interval-censored re-reads.
- **Censoring:** a check sees "changed or not", not how many times. Negligible for λI ≪ 1
  (every WooCommerce, Odoo and Shopify segment); for segments where λ̂·I > 0.1 (the Wix
  shop) convert X with the Cho–Garcia-Molina estimator before shrinking.
- **Exploration:** posterior mean only; the coverage floor is all the exploration needed.

**Waves are not per-listing change.** The daily sentinel panel (T9) flags a wave day when
its change share exceeds max(5 %, 10× the source's baseline). Check intervals that span a
wave day are left out of Xᵢ and Tᵢ, and the wave is counted in a source-level rate ρₛ. Waves
are answered by surge (§6.4), not by per-listing allocation; otherwise one inflation reprice
would mark a whole shop "volatile" for months.

---

## 5. From values to "what to read today", per adapter

Each run: compute w and λ̂ for the source's active listings (~25k rows in all; done at run
start, no stored state to drift), then spend the budget in this order: **sentinel/audit →
confirmations (T4) → coverage share → targeted share**. Coverage comes before targeting
because it carries a deadline; targeting is opportunistic and is what a cut-off run loses.

| Source | What it lets us target | Targeted lane | Coverage sweep |
|---|---|---|---|
| Shops 1, 2, 3, 5 (WooCommerce) | Single listings: Store API `include[]`, 100 ids a request (T3, pending D2 and verification) | Top listings by Vᵢ, 100 per request. Plus the modified-since lane (T5) on shops 1, 2, 5 | Stock partitions, offset paging, 14–21 days |
| The Odoo shop | Partitions only (leaf categories, `/shop` pages) | Revisit whole leaves ranked by V_u / pages, as a lane visit that does not move the cycle cursor (plan D12). Product page reads (1 request each) only for confirmations | Leaves and `/shop`; with D4(c), `/shop` every 7 days for price, leaves every N for category |
| The Shopify shop | Nothing finer than the 6–7-page feed, order unverified | None | Keep ~1 page a day (7 requests for 1,267 listings is already the cheapest source per listing) |
| The Wix shop | Gallery pages | None needed | Keep daily: λ is high (12 stock flips in 3 days over 53 listings) and it costs 7 requests |
| The marketplace (when unblocked) | Partitions (608 categories of ~2 pages) | Revisit categories ranked by V_u / pages | All 608 over 21 days |
| Shop 4 (when unblocked) | as WooCommerce | as WooCommerce | as WooCommerce |

Partition value needs membership: record on each listing the partitions it was last seen
through (Phase 0 item 5's Odoo leaf record is the start); its Vᵢ falls to zero once any of
them reads it.

A unit read in the last 24 h is not eligible: the lane never reads a page twice a day.

---

## 6. Gentler: coverage cycle ≠ freshness

### 6.1 The knob: a daily request budget per source

Replace `target_cycle_days` as the primary setting with:

- **`daily_requests`** (Bₛ): every request a run sends (pages, cycle data, lanes, details,
  sentinel, confirmations). Never above the source's current daily maximum without D1's
  approval.
- **`max_cycle_days`**: the coverage deadline. Every partition is read at least once in
  this window, whatever the weights.
- **`max_pages_per_run`**: unchanged, the hard ceiling on a run's total, lanes included.

`_page_budget` generalises directly. Today it spreads the last cycle's `cycle_pages` over
the days left of `target_cycle_days`; under the new knob that result becomes the **coverage
share** (with `max_cycle_days` in place of the target), and **targeted = Bₛ − reserved −
coverage**. If Bₛ cannot cover the deadline, coverage wins, targeting gets zero and
`make status` says "budget below coverage floor". `target_cycle_days` alone keeps meaning
exactly what it means today, so sources move over one at a time. `stats.budget` records the
split; a non-public `stats.schedule` records the chosen units and their values so any day's
choices can be audited.

### 6.2 What the model says it buys

Using plan §0's four price-band segments (λ = 0.0005, 0.0016, 0.0042, 0.0058 per day; w = 1),
against a uniform 7-day sweep:

| Allocation | Requests vs today | Stale share | vs today |
|---|---:|---:|---:|
| Uniform, 7 days (today) | 100 % | 0.60 % | — |
| √-rule, same budget | 100 % | 0.47 % | −22 % |
| √-rule, intervals 15 / 8 / 5 / 4 days | **78 %** | 0.60 % | equal |
| √-rule, 60 % budget | 60 % | 0.77 % | +30 % |
| √-rule, 50 % budget, 21-day floor | 50 % | 0.93 % | +56 % |
| Uniform, 21 days | 33 % | 1.76 % | ×3 |

The 21-day floor does not bind until the budget falls below ~50 %. Finer segments help: if
per-listing rates spread like a Gamma of shape 0.5 (plausible, with 0 % categories beside
14 % ones), equal staleness needs ~64 % of requests; importance skew helps further. These
gains need per-listing targeting; on partition sources a page averages its listings' rates,
and the Odoo shop's big saving is structural (T1, D4), not scheduling.

**So "same result, gentler" is about 20–35 % fewer requests on WooCommerce.** Going
further means the owner accepts staler low-weight listings (P3-D7).

### 6.3 Indicative daily requests

| Source | Today | After Phase 1 | Phase 3, 14-day coverage | Phase 3, 21-day coverage |
|---|---:|---:|---:|---:|
| Shop 1 | 22 | 21 | ~15 (11 + 3 lane + 1 sentinel) | ~12 |
| Shop 3 | 9 | 9 | ~7 | ~5 |
| Shop 2 | 7 | 7 | ~5 | ~4 |
| Shop 5 | 4 | 4 | ~2.5 | ~2 |
| Shopify shop | 1 | 1 | 1 | 1 |
| Odoo shop (+ ≤ 20 details) | 71 | 47 | ~28 | ~25 (D4(c): ~27 at any coverage) |
| Wix shop | 7 | 7 | 7 | 7 |
| **Total, enabled** | **~121** | **~96** | **~65** | **~56** |
| Marketplace (disabled) | (174) | | (~100) | (~73) |

Planning figures under the model. They become claims only after the audit panel (§7)
holds.

### 6.4 Consequences of a longer cycle, and their mitigations

**Removals are detected later.** Archiving runs only when every partition is exhausted and
reads `last_seen_at < cycle_started_at`, so a product removed mid-cycle stays listed until
the cycle closes: on average about one cycle, up to two. At 21 days that is up to six weeks
of a product shown as on sale that no longer is. Mitigations:

- **Targeted reads keep the important ones honest.** A high-weight listing read by the
  lane gets `last_seen_at`; one the lane asked for and did *not* get back becomes a
  **suspect**.
- **Suspects go to confirmation (T4) at once, not at cycle end.** A second, independent
  ask 24 h or more later (Woo: another `include[]`; Odoo: the product page; sitemap veto
  where it exists).
- **Two misses set a display state, not an archive** (P3-D8): "not found on the shop's site
  since <date>". The price stays visible as history; the "in stock" claim and the shop's
  rank in comparisons are dropped. Archiving itself stays cycle-gated, and a listing seen
  again clears the state at once. This keeps invariant 2 (absence is never grounds to
  archive) while removing the six-week wrong claim for the listings people actually see.
- **M6 and a removal-delay metric (M5b)** watch it.

**Repricing waves would take a whole cycle to propagate.** A source may go beyond 7 days
only once its sentinel (T9) is live, and surge then shrinks that cycle's deadline to what
`max_pages_per_run` allows (2–3 days), never above the ceiling (plan D8).

**Offset-drift skips (W5) last longer.** A listing skipped by shifting pages waits a longer
cycle and is then archived. T4 (Phase 1) must be live before any source lengthens its
cycle.

**New products appear later.** WooCommerce: the newest-page read (T13) keeps one-day
discovery. The Odoo shop: `/shop` weekly under D4(c). The marketplace: up to 21 days.

**Category moves on authoritative sources wait for the coverage sweep.** Lanes carry no
category signal (invariant 7).

**Cycle data** (variations, price breaks) halves with no work: it is fetched once a cycle,
and `CYCLE_DATA_MAX_AGE` (45 days) exceeds any proposed cycle. **Crosswalk drift `unused`**
is computed from complete sweeps only, so it is reported less often; say so in `make status`.

**The public promise has to change, in the same release or before.** "About weekly"
appears in `lib/content/crawling.ts` ("spread across about a week"), `for-suppliers`
("spread over about a week"), the home page and `home-sections.tsx` ("rechecks each about
weekly"), `shops/page.tsx`, and `lib/metadata.ts` ("rechecked weekly", on the share card).
Proposed wording (P3-D9): *"Every product is read at least once every three weeks.
Products whose prices change often, and those people look at most, are read every few days.
A full pass over a shop's catalogue is spread over two to three weeks, so a shop sees a
steady trickle, never a spike."* The shop pages and `/how-we-crawl#activity` already show
measured requests per 7 days; add a measured "typical product last checked N days ago"
(p50, from `last_verified_at`). That is a number, not a status code, so it is safe to
publish. "Removal within 7 days" on `for-suppliers` is the opt-out path, done by hand, and
unaffected.

---

## 7. Metrics, success criteria, experiment

Metrics as in plan §3 (M1–M7), with three changes:

- **Freeze the weights for evaluation.** M4 uses w₀ (the prior formula) on both sides of
  any comparison. Otherwise turning on demand weights moves the metric by definition.
- **M4-audit (new, model-free):** the T9 sentinel panel doubles as an audit. Each day, per
  source, read a random sample — stratified by price band and drawn with probability ∝ w₀·λ̂
  to find more stale items, then re-weighted by inverse probability. The share whose read
  differs from what the site was showing is a direct estimate of weighted staleness that
  does not depend on λ̂ being right. Cost: 1 request a day per WooCommerce shop; one random
  leaf page a day at the Odoo shop.
- **M8 calibration (new):** bucket listings by predicted λ̂ decile; compare with the change
  rate observed by *coverage* reads (which are not chosen by λ̂). If the deciles are not
  ordered, the targeting is noise.
- **M5b removal delay:** archive (or "not found") time − `last_seen_at`, p50 and p90.
- **M6** redefined in days (re-seen within 42 days of archiving), so it stays comparable as
  cycles lengthen.

**Success, per treated source against its own Phase 2 baseline:**

1. M1 (requests a day) down ≥ 25 %.
2. M4 (model, frozen w₀) ≤ baseline, overall and for the high-weight group.
3. M4-audit not worse than baseline by more than 0.3 percentage points (non-inferiority;
   see the power caveat).
4. M5 p90 for high-weight listings (w₀ ≥ 2) ≤ 3 days.
5. M5b p90 for high-weight listings ≤ 7 days; M6 not up.
6. M7 unchanged (gaps, error rate, no new `stats.stopped`).
7. M8: deciles ordered, top decile ≥ 3× the bottom.

**Power caveat.** At ~0.5 % staleness a panel of 100 a day finds one stale listing every
two days: over 4 weeks it catches a doubling, not a 20 % shift. It guards against the model
fooling itself; fine comparisons rest on the model, checked by M8.

**Experiment design.**

- **Stage A, within one source, listing-level randomisation** (shop 1, coverage unchanged at
  7 days): half the listings, chosen by a hash of the id, are eligible for the targeted lane.
  Compare M5 and changes found per request between the arms. Measures what a lane request is
  worth, free of week-to-week shop behaviour. 2 weeks.
- **Stage B, source-level, gentler:** shop 1 moves to `daily_requests` = 75 % of baseline
  with `max_cycle_days` = 14; shop 3 is the control (also WooCommerce, similar size, no
  modified lane). 2 coverage cycles = 4 weeks. Then crossover: shop 3 treated, shop 1 held.
  Then 21 days on whichever passed. Waves hit shops at different times, so compare
  wave-free weeks and report waves separately.
- **Stage C, partition sources:** the Odoo shop's value-ordered revisits, measured against
  its own Phase 1 baseline (no comparable control exists). The marketplace when unblocked.
- **Stage D, demand weights**, only once the gate is met: listing-level randomisation of
  κ (0 vs 0.5) within sources, success = M4 weighted by *observed* demand down, M4 frozen
  w₀ not up.

---

## 8. Rollout and prerequisites

| Step | Prerequisite | Duration | Behaviour change |
|---|---|---|---|
| 3.0 Demand export | P3-D1; privacy page line | 1–2 days of work | None; data accrues, κ = 0 |
| 3.1 Scheduler in shadow | Phase 0 counters ≥ **4 weeks and 2 closed cycles per source**; Phase 1 (T1, T4, T12) live | 2 weeks | None: daily "would read" plans, M8 computed |
| 3.2 Stage A on shop 1 | Phase 2 `include[]` lane verified (D2); sentinel/audit live ≥ 2 weeks | 2 weeks | Lane picks by V, half the listings eligible |
| 3.3 Stage B, gentler | Copy change (P3-D9) deployed; T4 live; surge live | 4 weeks + crossover | `daily_requests` = 75 %, `max_cycle_days` = 14 on shop 1 |
| 3.4 Other WooCommerce shops | Stage B passed | rolling, one shop a week | Same |
| 3.5 Odoo shop | D4 decided from Phase 0 churn | 2 cycles | Leaf revisits by value |
| 3.6 21-day coverage | Stage B at 14 days passed | 6 weeks | `max_cycle_days` = 21 |
| 3.7 Demand weights | Gate met (§3.5) | 4 weeks | κ = 0.5 under Stage D |

λ per listing (rather than per segment) becomes worth using at about **8 weeks** of
counters. Until then the scheduler runs on segment λ, which already captures most of the
gain (§6.2 uses only segments). **Rollback** at every step is config: remove
`daily_requests` and `max_cycle_days`, restore `target_cycle_days`, one deploy.

---

## 9. Invariants (plan §4 still holds; these are added or sharpened)

1. **Coverage floor.** Every partition of an enabled source is read at least once per
   `max_cycle_days` (≤ 28), whatever w or λ̂. Weights redistribute only the surplus above
   it.
2. **Archiving stays cycle-gated on `last_seen_at`.** Lanes, suspects, confirmations and
   the "not found since" state never archive and never close a cycle.
3. **Budget.** `daily_requests` ≤ today's per-source daily maximum (D1);
   `max_pages_per_run` caps the whole run, lanes included; `RUN_TIME_SHARE` still ends it;
   a host refusal stops every lane.
4. **Bounded importance.** Demand can at most triple a listing's weight; κ is a config
   value with a recorded decision, never fitted automatically.
5. **Privacy.** Only per-product and per-category daily counts leave Umami; no session
   ids, queries, referrers or user agents; 180-day retention; nothing from demand is
   published or put in `stats.pacing`.
6. **Truthful public copy.** The cadence promised on the site is true on the day the
   behaviour changes, and is backed by a measured number.
7. **Explainable choices.** Each run records its budget split and chosen units
   (non-public `stats.schedule`), so "why was this read, why not that" has an answer.
8. **`limit=` runs** count no checks, read no demand, schedule nothing.
9. **Waves never feed per-listing λ**, so one reprice cannot make a shop "volatile" for
   months.

---

## 10. Decisions for the owner

**P3-D1. How demand data gets out of Umami.** (a) Umami API, nightly, view-only API key;
(b) read-only Postgres role, our aggregate query; (c) a view in Umami's database.
**Recommend (a)**, (b) as the fallback if 3.4.1's API cannot give visitors per path per
day. Not (c): it would break Umami upgrades.

**P3-D2. When visits start to count.** (a) Now, small κ; (b) once ≥ 1,000 human sessions in
28 days and ≥ 300 products with ≥ 2 visitors; (c) never, priors only. **Recommend (b)**,
with the export built now. Today: 1–5 sessions a day, 5 products ever seen twice.

**P3-D3. Importance before traffic.** (a) w₀ = 1 + [multi-supplier] + 0.5·[in stock]
(plan D6); (b) also weight by price band; (c) uniform. **Recommend (a).** Price is already
in λ.

**P3-D4. Search impressions from the API.** (a) Build a counter now; (b) defer until
traffic; (c) never. **Recommend (b).** The API cannot tell a person from a render or a
bot, and `/search` is disallowed to crawlers.

**P3-D5. Coverage deadline.** (a) 14 days; (b) 21; (c) 28. **Recommend 14 first, 21 after
Stage B passes; 28 as the hard cap**, never more.

**P3-D6. Primary knob.** (a) `daily_requests` + `max_cycle_days` (+ the existing ceiling);
(b) keep `target_cycle_days` and add lanes on top. **Recommend (a).** It is what a shop
experiences and what `/how-we-crawl` reports.

**P3-D7. How much gentler.** (a) 75 % of baseline requests (model: equal staleness);
(b) 60 % (model: ~30 % staler on average, high-weight listings still fresher); (c) 50 %.
**Recommend (a) first**; go lower only if M4-audit shows headroom, and decide (b)
explicitly, because it trades freshness for gentleness.

**P3-D8. Removals under a longer cycle.** (a) Cycle-only archiving (up to ~2 cycles late);
(b) suspect → confirmation → "not found on the shop's site since <date>" display state,
archive still cycle-gated; (c) archive a listing after two confirmed misses.
**Recommend (b).** It fixes the visible wrong claim without letting absence archive.

**P3-D9. Public promise.** (a) Keep "about weekly" (false once cycles lengthen); (b) "at
least every three weeks; often-changing and often-viewed products every few days", plus a
measured "typically checked N days ago" per shop; (c) drop cadence claims. **Recommend
(b)**, shipped with or before the first lengthened source. This supersedes plan D7(a).

**P3-D10. Sentinel as a precondition.** May a source run a cycle longer than 7 days
without a live wave sentinel and surge? **Recommend no.**

**P3-D11. The Odoo shop's leaf cadence.** Ties to plan D4/D12: `/shop` weekly for price,
leaves every N cycles for category, plus value-ordered leaf revisits. **Recommend N from
Phase 0's measured category churn** (N = 4 if churn < 1 % a cycle).

**P3-D12. Adopt the corrected priority (§2) in Phase 2 too.** **Recommend yes**: the plan's
w·λ·(1 − e^(−λa)) over-reads volatile listings.

---

## 11. Caveats, said plainly

- **Every gain figure here is modelled**, from three days of interval-censored history over
  four price-band segments. Re-fit after Phase 0 before setting any budget.
- **The visits signal does not exist yet** at useful volume. Part 1 of the owner's direction
  ("measure what users visit most") is designed and can be plumbed now, but cannot steer
  the crawler for months at current traffic. Until then importance is a prior.
- **Unverified:** `include[]` on our shops (per-listing targeting depends on it) and the
  Umami API's per-path visitor breakdown on 3.4.1. The audit panel has low power (§7).
- **A longer cycle delays removals** for every listing the lane does not cover. P3-D8 fixes
  the display for important listings only; low-weight removals stay up to ~2 cycles late.
