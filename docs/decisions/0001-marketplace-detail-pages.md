# Deferred: fetching the marketplace's product detail pages

**Status:** deferred · **Raised:** 2026-08-24 · **Decision:** revisit before scaling the marketplace beyond tools

## The gap

The marketplace's listing endpoint returns everything needed for a usable listing —
title, price, stock, image, URL — but **not `sku` or `brand`**. Both exist, one
request away, in the JSON-LD on each product page:

```json
{"sku": "S5825", "brand": {"name": "Amtech"},
 "offers": {"price": "209", "salePrice": "187", "priceCurrency": "EGP"}}
```

So today every listing from it has `brand = NULL` and no identifier.

## Why it was deferred

Enriching means roughly **one extra request per product**. Across the mapped
tools tree that is thousands of requests per sweep; across the whole marketplace,
tens of thousands. At polite pacing that is hours of traffic for fields that are
nice to have.

The obvious mitigation — fetch details only for newly-seen products, making it a
one-time cost per product rather than per sweep — is weaker here than it sounds.
The catalog is large and largely static, so the "new products only" set is small
precisely because the *initial* backfill is the expensive part. The saving
applies to the cheap case and not the expensive one.

## What we lose by waiting

- **Brand is empty** for the marketplace's listings. It is a `SEARCHABLE_ATTRIBUTE`, so
  "Bosch drill" only matches products with the brand in their *title*. In
  practice many of its titles do carry the brand ("Spirit Level 25 Cm Bosch"),
  which softens this.
- **No identifier**, so every listing is a singleton and cannot merge with the
  same product from another supplier. For hand tools that is largely correct
  anyway — see below.

## Constraint on any future implementation

`sku` must **not** be written to `Listing.part_number` unqualified.
`grouping.base_key()` merges listings across suppliers on `mpn:<part_number>`, and
the marketplace's `sku` is sometimes a real manufacturer part (`GBM 1600RE` is Bosch's
own model) and sometimes a private code (`S5825`). A private code colliding with
another supplier's string would merge unrelated products, which is the failure
`part_number.py` explicitly warns about: under-extraction is always safer than a
false merge.

The safe shape is to store it as `attributes.supplier_sku` and promote it to
`part_number` only when it validates as a real manufacturer part — which is a
per-brand judgement, not a regex.

## Revisit when

- Brand-faceted search or brand filtering is wanted for tools, or
- The marketplace expands into a vertical where cross-supplier matching actually pays
  (its Electronic Components tree, where MPNs are real and the existing
  electronics grouping would apply), or
- A cheaper source for the fields appears (a feed, or an API from the marketplace).
