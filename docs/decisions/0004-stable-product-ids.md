# Product ids never change

**Status:** proposed, needs a design pass · **Raised:** 2026-11-06 · **Blocks:** projects, price history, saved lists

## The problem

A product's id should identify the product for as long as it exists: it is the URL
people share, and projects and price history will reference it. Today it does not.

`rebuild_products` (`makhzan_schemas/grouping.py`) recomputes a `group_key` from each
product's current offers and looks the row up by that key:

- one shop: `single:<source>:<external_id>`
- shared part number: `mpn:<PN>:<words from the first listing's title>`

So a product gets a new id, and its old row is deleted, whenever its key changes:

1. A second shop starts selling it (`single:…` becomes `mpn:…`).
2. The listing whose title seeded the key goes away, and the next one gives other words.
3. The grouping rules change (the August 2026 fix re-keyed nearly every shared product).
4. All its offers go inactive (the product is deleted).

## Direction

Identity belongs to the product; grouping only decides which offers belong to it.

- **Ids are permanent.** A product row is never deleted or re-keyed.
- **Offers attach to products, not keys.** An offer keeps its product once assigned.
  A new offer joins an existing product or creates one.
- **Merge:** one product survives; the other is marked `merged_into` and its URL
  redirects. References (projects, links) follow the redirect. Two ids for one product
  is fine when one of them only redirects.
- **Split:** offers that no longer belong move to a new product; the original id keeps
  its core.
- **Empty:** a product with no active offers stays, shown as "no longer listed" with
  similar products. Projects referencing it show a note.
- **Rule changes produce proposed merges and splits**, applied with history, instead of
  a silent rebuild.

## Open questions

- Which offers are a product's "core" when a split is ambiguous.
- Whether a merge or split is applied automatically, or queued for review.
- How existing ids migrate: the first run must keep today's ids where the grouping
  agrees, or links already shared break once more.
