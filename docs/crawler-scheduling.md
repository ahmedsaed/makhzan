# Crawler scheduling: more freshness from the same requests

Status, 2026-11-13: **Phase 1 is implemented, with T1 shipped in shadow.** The
owner approved Phase 1 that day. Phase 0 (measurement) is being built in
parallel. Phases 2 and 3 are not started. Suppliers are named by role, as in
CLAUDE.md.

## The rule that does not change

Better *choices* of which requests to send, never more requests:

- one request at a time per host, at least 15 s apart (or the host's Crawl-delay);
- every request goes through `take_turn` (`worker/http.py`), robots.txt
  checked on the full URL, the source's identity, and its Retry-After and
  error slowdown;
- `max_pages_per_run` stays the hard ceiling;
- `stats.pacing` is what was sent, and stays public-safe. New request purposes go
  in `stats.requests` as labels only.

Archiving stays cycle-gated and keyed on `last_seen_at`. Nothing archives on
partial evidence: a listing's absence from a confirmation, a sitemap or a failed
check is never the reason it is archived. Per-page checkpointing is untouched.

## What production showed

`price_observations` (one row per change, since 2026-11-09) gives each listing
one interval-censored sample. Read these as orders of magnitude, not rates:

- **Most listings almost never change.** About 3 % moved in 3–4 weeks (shop 2's
  bulk reprice aside). A uniform weekly sweep spends almost every request
  confirming an unchanged price.
- **Change is concentrated.** Listings at 200 EGP or more are about 24 % of
  listings and carry about 76 % of price changes. Out-of-stock listings restock
  at ~9 % in three weeks.
- **Change comes in shop-wide repricing waves** (median ×1.10, almost all up),
  not as independent events.
- **Multi-day offset paging skips listings.** Shop 1 archived 173 listings on
  2026-11-12. 48 of them came back within two cycles under the same id: they
  had not gone, the sweep had missed them (W5).

## Where the requests went (the waste)

- **W1.** The Odoo shop reads each product twice a cycle (170 leaf categories
  plus the whole-shop pass), and every partition pays one request for the repeat
  page Odoo serves after its last. That is 497 requests a cycle for 2,877
  listings.
- **W2.** Every WooCommerce and Shopify partition pays one request to read an
  empty page.
- **W3.** Every listing is re-read at the same cadence, whatever its volatility.
- **W4.** The order is fixed regardless of value. The details backfill is
  newest-first.
- **W5.** Offset paging over several days skips listings, and a skipped listing
  is archived.

## The plan

| Phase | What | State |
|---|---|---|
| 0 | Measure: a per-listing check log, a freshness report, validator logging, category churn | in progress (separate branch) |
| 1 | T1 short-page end, T2 (a), T4 confirm before archiving, T12 sitemap veto, T10 details ordering | **implemented**; T1 ships in shadow |
| 2 | WooCommerce lanes: modified-since (T5), `include[]` recheck (T3), wave sentinels (T9), newest page (T13) | not started; needs decision D2 |
| 3 | Per-listing change rates (T7), click-weighted importance (T8), T2 (c), marketplace partition order | not started; needs Phase 0 data |

### Phase 1, as built

**T1, ending a partition on a short page** (`worker/sources/short_page.py`). The
Odoo, WooCommerce Store API and Shopify adapters can end a partition on the page
that says it is the last. For Odoo that is the pager's disabled "next" item, or
no pager on page 1. For WooCommerce it is fewer than 100 products, or
`X-WP-TotalPages`. For Shopify it is fewer than 250 products. This saves the
terminal request: about a third of the Odoo shop's cycle.

Each source sets it with `end_on_short_page = "shadow" | "live" | "off"`. The
default is **shadow**: behaviour is unchanged, and each run records in
`stats.source_report.short_page` whether the stop would have been right:

- the next page is empty, or (Odoo) adds no new ids: the stop agrees;
- anything new on that page is a disagreement.

A verdict that falls in the next run (one page a run) travels in the report's
`pending`. `make status` shows, per source, the partitions compared and the
disagreements since the last completed cycle began. It says "ready" after a full
cycle with zero disagreements. **Going live is a config change per source, made
by the owner after that cycle; it is not done.**

**T2, the Odoo shop's double read: option (a).** Both passes stay, the leaf
categories and `/shop`, and T1 provides the saving: ≈ 497 → ≈ 326 requests a
cycle, once T1 is live. There is no structural change.

**T4, confirm before archiving** (`pipeline.Confirmer`). When a cycle completes,
its candidates (active, `last_seen_at` before the cycle began) are first put to
the source, most recently seen first, up to 500 a run. Beyond 500 the cycle
archives as before: that is a shop that changed, not drift.

- WooCommerce: `include=<ids>&per_page=100` on the Store API, 100 ids a request.
  - A returned product is upserted like any card: seen and verified, with
    `via = "confirm"` on its history row. It never clears a category and
    does not count as category churn.
  - A returned product that is not upserted (skipped as not a product, routed
    to review, failed) is not kept: it archives like an absence.
  - One not returned is archived.
- Requests are counted as `stats.requests.confirm`. Every one goes through
  `take_turn`, and counts against the run's ceiling as one more partition
  would: at most `max_pages_per_run`, within what an adaptive page budget has
  left. The run's time and its host's refusal are checked before each one.
- Candidates not asked about (the asking failed, the budget or time ran out)
  are not archived. The cycle stays open with every cursor exhausted, and the
  next run asks again. The hold is bounded:
  - after 2 runs whose asking failed, the unasked archive as before;
  - after 3 runs held for want of room to ask (the Odoo shop's 20 pages a
    run), the remainder archives as before;
  - after one cycle of time from when the sweep finished (the source's
    `target_cycle_days`, else as long as the cycle took, at least a day),
    whatever is left archives as before.
- Hold time is not part of `stats.cycle.cycle_seconds`: a held cycle's length
  ends when its sweep did.
- Never on a `limit=` run.
- Sources without a cheap way to ask (Shopify, Wix, the marketplace) archive as
  before.

**T12, the sitemap as an archive veto (the Odoo shop).** One `/sitemap.xml`
request per confirmation:

- a candidate it does not list is archived;
- one it lists is held, and its product page is read, at most 20 a run:
  - the product's own page keeps the listing, setting `last_seen_at` only,
    since no price is read;
  - a 404/410, or a redirect elsewhere, archives it;
  - any other page error leaves only that candidate unasked; a refusing host
    leaves the rest unasked;
  - held candidates with no room left this run wait for the next.

Sitemap presence never sets `last_seen_at`, because a sitemap can lag the shop.
A sitemap that is no usable census vetoes nothing, and the cycle archives as
before: a 404, gzip-only files, an index of more than 5 files, no product
pages, or one disallowed by robots.txt. A 5xx or a refusing host on the sitemap
is a failed attempt. `sitemap_veto = false` turns the veto off.

**T10, details ordering.**

- Never-fetched listings are read in order of importance,
  w = 1 + 1·[in a product several suppliers offer] + 0.5·[in stock], then
  newest first.
- For card-hash sources (the Wix shop, the marketplace), the age-based refresh
  adapts per listing, as Nutch's AdaptiveFetchSchedule does:
  - ×0.8 after a re-read that found the page changed (a change never
    lengthens the interval);
  - ×1.4 after one that found it unchanged;
  - kept between 30 days (or `max_age_days`, if lower) and the source's own
    `max_age_days`, in `attributes.details_interval_days`. The configured age
    stays the ceiling, so adapting only brings a volatile page forward. It
    never leaves a page longer than the owner set. This departs from the
    plan's [30, 180] range, which would have stretched past a 90-day setting.
- That key is carried over by the list-page upsert, like the other details keys.
- The Odoo shop's token is its own last-write stamp, so its age stays fixed.

`make status` shows the T1 tally under SHORT-PAGE END and each source's last
confirmation under CONFIRM BEFORE ARCHIVING.

### Known gaps in Phase 1

- **T1 is not live anywhere.** It needs one shadow cycle per source with zero
  disagreements, then a config change.
- **A held confirmation pauses the sweep.** While a cycle is held, no new cycle
  starts, so the source sweeps nothing until the confirmation succeeds or a cap
  passes. That is normally one day, at most two runs on failure or three on a
  page backlog. Holding is still preferred to archiving stock the shop still
  sells.
- **Hidden out-of-stock products.** A WooCommerce shop that hides out-of-stock
  products may leave them out of an `include` answer too. Those archive as
  before; `hides_out_of_stock` shops keep them through their unlisted pass.
- **Unverified on the live shops:** `include` with 100 ids, and the Odoo
  shop's pager markup and sitemap layout. Shadow runs and the confirmation's
  own report settle them. A sitemap that lists no products vetoes nothing; it
  is never read as "nothing exists".

## T2 option (c), for later

Sweep `/shop` every cycle for price and stock, and the 170 leaf categories only
every Nth cycle, for category.

- **Cost.** With T1 live, ≈ 96 + 230/N requests a week: ≈ 154 at N = 4. Or, at
  today's spend, prices and stock checked about three times a week instead of
  once.
- **Why it is safe for categories.** The `/shop` pass already carries no
  category signal (`knows_category` is False), so it never erases one.
- **Risks:**
  - a new product stays uncategorized until the next leaf sweep, because the
    source is authoritative and nothing is inferred for it;
  - a product the shop moves between categories keeps the old category for up
    to N cycles;
  - the crosswalk-drift `unused` report only means something on cycles that
    swept the leaves, so it must be computed from those alone;
  - a leaf-only product (one `/shop` does not show) would be seen only every Nth
    cycle and archived in between. The two passes must be diffed first, as
    CLAUDE.md requires before any partitioning change.
- **What Phase 0 must show first.** The per-sweep leaf-category record must show
  **category churn below ~1 % of listings a cycle**, measured over at least two
  closed cycles. It must also show that no product is reachable only through a
  leaf. Then N can be chosen from the churn, with N = 4 as the starting point.
- **What it needs in code.** A per-partition cadence in
  `_partitions_for_this_run`: a leaf partition is due only every Nth cycle, and
  the cycle-close check expects only the partitions due this cycle. Archiving
  must then key on the partitions that ran. A listing seen only by leaves keeps
  its `last_seen_at` from the last leaf cycle, so it needs the T4/T12
  confirmation, or an exemption, before any archive.

## Decisions and their state

- D1, what to do with the savings: bank the Odoo shop's T1 saving.
- D3, lane sightings may set `last_seen_at`/`last_verified_at`: applied to T4's
  WooCommerce re-reads.
- D4, the Odoo shop's double read: (a) now; (c) in Phase 3 if churn is low.
- D5, sitemap as a veto, never as "seen": applied.
- D6, importance weights before click data: the starting weights above.
- D11, details backfill order: importance first, then newest.
- D2, D7–D10 and D12 belong to Phases 0, 2 and 3.
