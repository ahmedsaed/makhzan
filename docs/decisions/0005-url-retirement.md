# Old URLs retire; redirects are not kept for ever

**Status:** accepted · **Decided:** 2026-11-09 · **Review:** May 2027 · **See also:**
`0004-stable-product-ids.md`

## The problem

Every rename and every merge leaves a redirect behind, and nothing ever took one
away. Some are a few lines of code; some are rows that grow with the catalogue.
The owner does not want a redirect list that only grows. A redirect is worth
keeping while people or search engines still arrive through it, and not after.

## Every redirect makhzan answers

| # | Old URL | Goes to | Kind | Where it lives | Since |
|---|---|---|---|---|---|
| 1 | `/en/…`, `/ar/…` | the same path without the prefix | rule | `apps/web/lib/redirects.ts`, `proxy.ts` | Nov 2026 (the bilingual site ended) |
| 2 | `/browse/{dept}[/{cat}]` (with or without a prefix) | `/departments/{dept}[/{cat}]` | rule | same | Nov 2026 |
| 3 | `/trades[/{dept}[/{cat}]]` | `/departments[/…]` | rule | same | Nov 2026 ("trades" renamed) |
| 4 | `/suppliers/{slug}` | `/shops/{slug}` | rule | same | Nov 2026 |
| 5 | `/products/{id}`, an old or wrong slug, an uppercase id | `/products/{id}-{words-of-the-title}` | rule | `app/(site)/products/[id]/page.tsx`, `lib/routes.ts` | Nov 2026 |
| 6 | `/listings/{id}` | the listing's product | rule over data the site keeps anyway (listing rows) | `app/listings/[id]/page.tsx` | Nov 2026 (listing pages removed) |
| 7 | a merged-away product id | the product it was merged into | **data**: `products.merged_into` | API `/products/{id}/redirect` | Nov 2026 (permanent ids) |
| 8 | a product id deleted before ids were permanent | where most of its offers went | **data**: `product_redirects` | same | Nov 6 2026 until permanent ids shipped; no new rows since |

All answer 308 (permanent) in one hop and keep the query string.

**Rules cost nothing per URL** and retire by a decision: delete the rule and its
tests, and the old URLs 404. **Data retires by itself**, row by row, on use.

## Data: dropped after twelve months unused

Rows 7 and 8 record when they were last followed: `products.redirect_used_at` and
`product_redirects.last_used_at`, written by the API's redirect endpoint at most
once a day per row (so following a redirect is a read, not a write, almost every
time; a failed write is logged and the redirect still answers).

`worker.retire_redirects` drops every one **unused for 365 days**, counting from its
last use, or from its creation (`merged_at`, `created_at`) if never used:

- a merged-away product's row is deleted (it holds no offers; its
  `product_events` stay), and its URL becomes the site's 404 with a search;
- a `product_redirects` row is deleted.

It runs once a day, in the first of the worker's `rebuild_and_reindex` jobs that
day, after the regroup and under its lock; and by hand:
`make retire-redirects ARGS=--dry-run` (count only) or `make retire-redirects`;
on the server, `docker compose … run --rm --no-deps ingestion python -m
worker.retire_redirects [--dry-run]`. It cannot drop a row anything still leads
to, and nothing qualifies before **November 2027**.

A crawler counts as a use. That is intended: if a search engine still requests an
old URL, the redirect is still moving its index over.

A "no longer listed" product (`delisted_at`) is not a redirect: it is a page, answers
200 with noindex, and is never retired by this.

## Rules: retired by review

Rules 1–4 and 6 exist for links and index entries from before November 2026. They
retire when nobody arrives through them any more. Rule 5 is the URL scheme itself
(titles change, so slugs do) and is never retired.

The evidence is Google Search Console: Pages, and the Performance report filtered
by URL prefix, for each old prefix over the last three months. A prefix with no
impressions or clicks in that window, and none of its URLs still indexed, can go.
(The site keeps no access log of its own; if one is added, a 90-day count of 308s
by prefix is better evidence still.)

### Checklist

- [ ] **May 2027** — review rules 1–4 and 6 in Search Console. For each prefix with
  no impressions and no indexed URLs over the last 90 days: remove it from
  `lib/redirects.ts` and the `proxy.ts` matcher (rule 6: delete
  `app/listings/[id]`), remove its tests, and note the date here. Keep any prefix
  that still shows traffic, and set its next review six months on.
- [ ] **November 2027** — the first data redirects become eligible. Check that the
  daily retirement ran (`make retire-redirects ARGS=--dry-run` reports what is
  left to drop) and that `product_redirects` is shrinking; once it is empty,
  drop the table and the API's fallback to it in one release.
- [ ] **November 2027** — second review of any rule kept in May.

## Consequences

- The redirect list is bounded by use: a redirect survives exactly as long as
  someone follows it at least once a year.
- The API, otherwise read-only, writes one column on a redirect's first use each
  day.
- An old URL whose redirect retired is a 404, not an error: the product 404 page
  offers a search.
