# Product ids never change

**Status:** accepted · **Raised:** 2026-11-06 · **Decided:** 2026-11-09 ·
**Unblocks:** projects, price history, saved lists · **See also:**
`0005-url-retirement.md`

## The problem

A product's id should identify the product for as long as it exists: it is the URL
people share, and projects and price history will reference it. Until this
decision it did not.

`rebuild_products` (`makhzan_schemas/grouping.py`) recomputed a `group_key` from
each product's current offers and looked the row up by that key:

- one shop: `single:<source>:<external_id>`
- shared part number: `mpn:<PN>:<words from the first listing's title>`

So a product got a new id, and its old row was deleted, whenever its key changed:

1. A second shop started selling it (`single:…` became `mpn:…`).
2. The listing whose title seeded the key went away, and the next one gave other words.
3. The grouping rules changed (the August 2026 fix re-keyed nearly every shared product).
4. All its offers went inactive (the product was deleted).

The first step, shipped earlier in November 2026, recorded a redirect from each
deleted id to where most of its offers went (`product_redirects`). That made old
links lead somewhere; it did not stop ids changing. A product's id still changed
the day a second shop started selling it.

## Decision

Identity belongs to the product; grouping only decides which offers belong together.

- **Ids are permanent.** A regroup never deletes a product row or gives it a new
  id. (The one exception is `worker.retire_redirects`, which drops a merged-away
  row nobody has followed in a year: `0005-url-retirement.md`.)
- **Offers attach to products, not keys.** A listing keeps its `product_id` once
  assigned, unless the grouping puts it with other offers. An archived listing
  keeps its product too: that is how a withdrawn product knows its last price.
- **The grouping itself is unchanged.** `_group_listings` computes the target groups
  exactly as before, every veto intact (same shop, value tokens, form, price span).
- **`group_key` is no longer identity.** It stays on the row as a diagnostic: the
  key the product's offers last formed, rewritten on every regroup, indexed, no
  longer unique (an emptied product keeps its last key, and a new product may form
  the same one).

### How a regroup matches groups to products

`plan_identity` (pure, deterministic) takes the target groups and each active
listing's current product (followed through any merge) and decides, in order:

1. **Undo.** A group formed only of one product's offers that is exactly the group
   a product merged into it last was (same key) gets that merged-away id back,
   provided the product keeps another part. A rule tried and reverted, or an offer
   gone for a sweep and back, leaves every id where it was instead of minting new
   ones beside redirects.
2. **Core.** Of what is left, a product's core is the group holding most of its
   active offers; **ties go to the group holding its earliest-seen listing**
   (`first_seen_at`, then the natural key). The product keeps its id there.
3. **Merge.** A group that is the core of several products keeps one: **the one
   that carried more active offers into the regroup, then the older** (`created_at`,
   then id). The others get `merged_into` = the survivor and `merged_at`; their
   aggregates are zeroed. Whatever led to an absorbed product (other merged-away
   ids, `product_redirects` rows) is repointed at the survivor, so every redirect
   is one hop.
4. **Split.** A product's offers that fall into groups other than its core go to
   whatever product that group is: a new product if it is no one's core.
5. **New.** A group no existing product claims is a new product.
6. **Emptied.** A product with no active offer left is not deleted: it gets
   `delisted_at`, its offer counts are zeroed, and its title, photo, category and
   last price range stay. **Revived:** if one of its listings becomes active again,
   it is matched by that listing's `product_id` and keeps its id.

A rule change goes through exactly this mechanism, so every existing id survives
it, as a product or as a redirect to one.

### The open questions, answered

- **Which offers are a split's core:** the subset holding the most active offers;
  ties to the earliest-seen listing. (Undo comes before this, see step 1.)
- **Applied automatically or queued for review:** automatically. A queue would mean
  a product page waiting on a person, and on the measured data almost every change
  is one of a handful of offers. Every change is auditable instead:
- **History:** every merge, split, emptying and revival is a row in
  `product_events` (`kind`, `product_id`, `other_id`, `detail` with the group key
  and offer counts, `created_at`). A merge is recorded on the absorbed id with the
  survivor as `other_id`; a split on the product that lost offers, with where they
  went; an undo is a `revived` with the survivor it left as `other_id`.
  `product_id` is deliberately not a foreign key, so the history outlives a retired
  row.
- **How existing ids migrate:** with no data migration at all. The migration adds
  columns and the events table; the first regroup after it matches every group to
  the product its listings already point at. On a copy of the development
  database (60,953 active listings, 59,608 products) it kept all 59,608 ids and
  recorded no event. `product_redirects` keeps its rows (ids deleted by the old
  code in the weeks before) and they keep working.

### What each state looks like

| State | Row | Page | Search, sitemap, counts, similar rails |
|---|---|---|---|
| listed | `merged_into`, `delisted_at` NULL | the product | yes |
| no longer listed | `delisted_at` set | 200, `noindex, follow`: title, last price range and when it was checked, when the last shop stopped, a search for it, similar products | no |
| merged | `merged_into` set | 308 to the survivor's readable URL, one hop | no |

**Why 200 + noindex and not 410 for "no longer listed".** Google treats 410 as
"gone" and drops the URL; `noindex` drops it from the index too. The difference is
for people and for coming back: the page tells whoever followed a link what the
product was, what it last cost and what is like it, and its links are followed. If
a shop lists it again the same URL turns back into the full page and is indexed
again by itself, whereas a 410 URL is recrawled ever more rarely. A soft-404
classification does not matter for a page that asks not to be indexed.

### Measured effect (copy of the development database, 2026-11-09)

| Scenario | Code before | Permanent ids |
|---|---|---|
| First regroup after deploy | 0 ids replaced | 59,608 kept, 0 events |
| A sweep archives 2% of listings (1,219) | 1,206 ids replaced or deleted | 1,179 emptied (kept, "no longer listed"), 5 merged, 2 split, 1 new |
| ...and they come back | 23 more ids replaced | all 59,608 listed under their original ids: 1,179 revived, 5 un-merged, 0 new |
| Title threshold 0.34 → 0.25 (more merging) | 307 ids replaced | 305 merged (redirect, one hop), 29 split, 14 new |
| ...and reverted to 0.34 | n/a | 301 un-merged, 4 new, 14 merged (the 14 split-offs) |

"Ids replaced" for the old code counts listed products whose key was not formed
again; it does not count the offers that silently moved to new products. A regroup
of the whole database takes about 8 seconds.

## Consequences

- `products` only grows, by merged-away and emptied rows. Merged-away rows retire
  after a year unused (`0005-url-retirement.md`); emptied rows stay, since their
  pages answer 200.
- Everything that lists products filters on `Product.is_listed()`: the search index,
  `/stats`, `/categories`, the sitemap and similar products. `make status`'s drift
  check compares the index with listed products.
- `/products/{id}` serves a withdrawn product with `status: "delisted"` and no
  offers, and a merged-away id as a 404; `/products/{id}/redirect` answers both
  merged-away ids and the older `product_redirects` ids. Offers are the active
  listings only.
- `worker.regroup --dry-run` (`make regroup-dry-run`) reports what a regroup would
  do to ids and changes nothing. Run it before deploying a grouping rule change.
- Retiring a source (`./makhzan retire`) still deletes the products only that source
  ever offered: a source being retired should never have been listed.
- Rolling back to an image older than this needs `alembic downgrade afbb04810ff9`
  (the revision before `32ed14ef673e`) first, which deletes merged-away and emptied rows so `group_key` can be unique
  again; the old code deletes products by key and would trip over `merged_into`.

## Not done

- **Projects and saved lists** do not exist yet; when they do, a reference to a
  merged-away id must follow `merged_into`, and one to an emptied product should
  show a note. Nothing enforces that today.
- **Undo is by exact group key.** A merged-away product comes back only when its
  old group forms again with the same key; a revert that forms the group under
  other words (a different seed listing) mints a new id instead. On the measured
  revert that was 4 of 305.
- **Emptied rows are never retired.** They are cheap and answer 200; if they ever
  need pruning, that is a new decision.
