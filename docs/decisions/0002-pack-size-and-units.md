# Deferred: pack size and units as a real dimension

**Status:** deferred · **Raised:** 2026-08-24 · **Surfaced by:** grouping precision work

**Since (noted 2026-11-19):** still deferred. One part now rests on evidence
rather than accident: the value veto (`makhzan_schemas.values`) reads a stated
quantity ("3Pcs", "pack of 10") and treats a title that states one as a
different offer from a title that states none, so a pack and a single unit no
longer merge. Nothing parses pack size into a quantity field, and no unit price
exists: the product page compares offers by the price of one *as each shop
publishes it* (`makhzan_schemas.pricing.unit_price`). `Listing.unit` is written
from an adapter's `unit_text`, which no adapter in this repository sets.

## The observation

`1N4007` appeared as one product spanning 0.45 to 350 EGP. Both listings are
genuinely 1N4007 diodes — one is a single diode, the other a **pack of 1000**.
That is not a wrong identifier and not really a wrong merge; it is an
*un-normalised* one. The same happens with XT60 connectors (single pair vs
multi-pack) and resistor assortments.

Corroborated grouping now splits these, because a 778x price gap and dissimilar
titles disagree. That is the right outcome today, but it is right by accident:
they are separated because they look different, not because the system
understands that one contains a thousand of the other.

## Why it matters

- **Price comparison is misleading across pack sizes.** "From EGP 0.45" against
  "EGP 350" is not a useful comparison unless the unit is shown.
- **The obvious fix — compare unit price — needs the quantity**, which is only
  present in free text today ("Pack of 1000", "10pcs", "Set of 5", "1 meter").
- Some domains care far more than others. Fasteners, resistors and o-rings are
  bought by the hundred; a pressure washer is not.

## What already exists

`Listing.unit` is on the model (`piece`, `meter`, `sheet`) and is **never
populated**. The field was designed for exactly this and has no writer.

## Rough shape of a fix

1. Parse quantity and unit out of titles per domain (`pack of N`, `N pcs`,
   `N-pack`, `N m`) into `Listing.unit` and a new quantity field.
2. Derive a unit price and use it for comparison and for the "from EGP X" badge.
3. Let the domain profile decide whether pack size is a *variant* of one product
   or a distinct product — for resistors it is a variant, for a hand tool it is
   not.

## Why not now

It is a data-extraction problem of the same family as identifier extraction, and
this session has just finished demonstrating how those fail when they are trusted
too much. It deserves its own pass, with the same discipline: make it evidence,
show it in the UI, and never let it silently rewrite prices.
