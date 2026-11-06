# Design language and layout system

Settled 2026-09-06, ahead of the `apps/web` rewrite. This is the reference the
rewrite is built against; `docs/ROADMAP.md` tracks whether it has been built yet.

Two artifacts hold the visual version of this document:

- Directions (why this language won): https://claude.ai/code/artifact/450cc27f-5afc-4323-a194-6ea946718d45
- Layouts (all nine surfaces): https://claude.ai/code/artifact/4df06394-728f-416f-98a1-702ebd053b3e

## The language

Chosen from four directions. It takes the **build** of the "Souk" direction —
Cairo shop-front weight — on the **palette** of the "Ledger" direction — a
printed trade catalogue. Geometric type on a print palette reads as neither
parent: industrial and printed, which is what a parts catalogue should be.

### Colour

| Role | Light | Dark |
|---|---|---|
| Ground | `#FCFBF7` | `#121210` |
| Surface | `#FFFFFF` | `#1A1A17` |
| Ink | `#1A1A17` | `#ECE9E0` |
| Muted | `#6E6C63` | `#98958A` |
| Rule | `#E5E3DA` | `#2A2A25` |
| Accent (oxblood) | `#7A2E2E` | `#CE7263` |
| In stock | `#3F6B46` | `#86B08C` |
| Chip / inset | `#F2F0E8` | `#232320` |

The dark accent is deliberately **not** Ledger's `#C97A70`: against this
direction's heavier geometry it read washed, so it is deepened to `#CE7263`.

**The accent has a budget.** Oxblood marks the supplier hand-off button and the
part number, and nothing else. Borders — all of them, in both themes — use the
rule colour. Oxblood on 2px edges turns the whole page burgundy, which is the
one way this palette fails.

### Type

| Role | Face | Notes |
|---|---|---|
| Display | Archivo 600/700 | Tight tracking (`-0.02em`) on titles and logo |
| Body | Tajawal 400/500 | Carries Latin and Arabic, so weights match across scripts |
| Arabic | Tajawal | Same family — not a fallback |
| Data | IBM Plex Mono | Part numbers, prices, counts. Always `tabular-nums` |

Fonts were chosen **Arabic-first**. Plenty of better Latin pairings exist that
would leave Arabic on a browser fallback; for a bilingual Egyptian directory that
is disqualifying.

### Geometry

- Radius `7px`; `2px` borders on cards, panels and tiles; `1px` on inputs and rows.
- Rows separated by hairlines, not boxes. Cards are for objects, rules are for lists.
- The one filled button per page is the hand-off.

**Risk to hold in mind:** warm paper + bold grotesque + oxblood is also the house
style of every craft brewery. What keeps it out of that territory is density —
real part numbers, tabular prices, eight offers on a page. Keep the content dense.

## Layout rules that hold everywhere

- **Rows for comparing, tiles for surveying.** A grid of product cards looks
  nicer and compares worse, because prices stop lining up in a column. Tiles
  appear only on vertical landings and the homepage.
- **Server-rendered by default.** Every surface is a URL with real metadata.
  Only the facet rail and the search box need client state. The current app is
  client-only, which is why none of it is indexable — see the rewrite rationale
  in `docs/ROADMAP.md`.
- **Two URLs per page, `/en/…` and `/ar/…`**, with `hreflang` pairs. Language is
  never React state: today it is, so `<html lang>` is always `en` on the server,
  an Arabic page cannot be linked or indexed, and the choice resets on reload.
- **Logical properties only** (`padding-inline`, `margin-inline-start`), so RTL
  is a `dir` attribute rather than a second stylesheet.
- **Part numbers stay `dir="ltr"` inside Arabic text.** Without it `ESP32-WROOM-32`
  reorders around its hyphens. This is the detail that most often ships broken.
- **Freshness is always visible**, and sits on each *offer*, not on the product.
  A 12-day-old price and a 2-day-old price are not equally trustworthy.
- **Categories are linked by `ref` (`domain:slug`), never the bare slug.**
- **Domain is a facet on search and a scope on browse** — never a hard filter on
  search, matching the API's deliberate cross-domain behaviour.

## Surfaces

| # | Surface | Route | The decision that matters |
|---|---|---|---|
| 01 | Chrome | every page | 16 verticals behind one `Browse` control; search in the header everywhere; no cart, ever |
| 02 | Home | `/{lang}` | All 16 verticals shown, no "see all"; a rail of multi-supplier products — the one thing no supplier site can show |
| 03 | Vertical landing | `/{lang}/browse/{domain}` | Category tiles with counts, straight from `/categories?domain=` |
| 04 | Category | `/{lang}/browse/{domain}/{slug}` | Same layout as search; pins `category`, scopes the rail to one vertical |
| 05 | Search | `/{lang}/search` | Domain facet stays **open** with counts; identifier-shaped queries get a band explaining the re-ranking |
| 06 | Product | `/{lang}/products/{id}` | The offers panel *is* the page. Cheapest first, priceless last but visible |
| 07 | Listing | `/{lang}/listings/{id}` | Always offers the way back up to the comparison |
| 08 | Supplier | `/{lang}/suppliers/{slug}` | "also at N others" is the hook back; without it the page competes with the supplier's own site |
| 09 | Comparison | — | Offer comparison only. See below |
| 10 | Media | — | Images are load-bearing; descriptions are not. See below |

### Comparison: build one kind, not two

*Offer comparison* — same part, N suppliers, price/stock/freshness — is the
product, and `/products/{id}` already returns sorted offers. Build it.

*Product comparison* — a tray pinning 2–4 different products into a spec table —
is deferred. It needs structured attributes that do not exist: `Listing.attributes`
is schema-less JSONB holding platform noise, not specs. The table would compare
title, price and supplier count, which a sorted result list already shows side by
side. It is the feature buyers ask for and do not use. Revisit only if attribute
extraction becomes real work.

### Media and description, measured

Taken from the catalogue on 2026-09-06, not assumed:

| Supplier | Listings | With image | With description | Image host |
|---|---|---|---|---|
| Shop 1 (WooCommerce) | 13,026 | 97.2% | 96.7% | the shop's own domain |
| The Odoo shop | 2,900 | 100% | 56.9% | the shop's own domain |
| Shop 2 (WooCommerce) | 1,612 | 100% | 99.4% | the shop's own domain |
| The Shopify shop | 1,251 | 99.2% | 84.7% | `cdn.shopify.com` |
| Shop 5 (WooCommerce) | 371 | 100% | 55.8% | the shop's own domain |

11,076 listings carry exactly one image, ~6,500 carry two to five, and 375 carry
none. So:

- **Images are a primary layout element**, not a nicety, and the product page
  earns a gallery.
- **`object-fit: contain`, never `cover`.** Supplier photos arrive at wildly
  different aspect ratios and cropping a component photo can remove the
  component. Fixed square box, part centred, neutral ground.
- **Reserve the box before the image loads** — fixed aspect ratio, so a list of
  24 rows does not shift as it fills in.
- **The fallback is a category glyph**, not a broken-image icon, wired to the
  image's error handler so it covers both "never had one" (2%) and "the supplier
  rotated their media" (which will happen).
- **Nothing may depend on a description existing.** When absent the section is
  not rendered — no "no description available" placeholder. Descriptions are
  supplier prose: bounded block, attributed, and never allowed to push the offers
  panel below the fold.

## Responsive

Mobile-first, and not as a courtesy: the buyer this is for is standing in a shop
in Bab El Louk with a phone, checking whether the price in front of them is fair.
Desktop is the secondary case.

### Breakpoints

Named for the layout change they cause, not for devices.

| Token | Width | What changes |
|---|---|---|
| base | `< 640px` | One column. Rail becomes a sheet. Header is two rows |
| `sm` | `≥ 640px` | Tiles go 3-up; row price returns to its own column |
| `md` | `≥ 768px` | Header is one row; product gallery sits beside the title |
| `lg` | `≥ 1024px` | Facet rail is permanent; product page gets its offers aside |

### How each surface reflows

- **Header** keeps search *visible* on phones — logo, `Browse`, language and
  theme on the first row, the search field full-width on the second. Search is
  the primary action of the whole site; collapsing it behind a magnifier to save
  40px is the wrong trade.
- **Search and category** replace the facet rail with a `Filters` button opening
  a bottom sheet. Active filters stay visible as inline chips even when the
  sheet is closed, so the result count is never unexplained. Sort stays an inline
  `<select>` — it is one tap and belongs next to the count.
- **Product page reorders, it does not merely stack.** Phone order is gallery →
  title and price range → **offers** → description → similar. The offers panel
  must never sit below a supplier's description: comparing prices is why the
  page exists, and some suppliers' descriptions are long.
- **Listing page** pins the hand-off to a sticky bottom bar. It is the only
  action on the page.
- **Supplier page** stacks the profile above the listing list.
- **Product rows** keep the price in its own end-aligned column down to 380px,
  where it wraps to its own line still end-aligned — the column alignment is the
  comparison, so it is the last thing to give.
- **Tiles** run 2-up on phones, 3-up at `sm`, up to 8-up on wide screens. All 16
  verticals stay visible at every width.

### Rules

- Touch targets are at least 44px; chips and icon buttons get padding to reach
  it rather than a larger font.
- Nothing horizontally scrolls except deliberately overflowing containers
  (a wide table), never the page body.
- Every reflow is expressed with logical properties, so RTL needs no separate
  mobile work.
- Images keep their fixed aspect box at every width, so a slow supplier host
  cannot shift a list that is already rendered.

## What the layouts need that the backend does not have

| Need | For | Size |
|---|---|---|
| Facet counts | Domain/category counts in the search rail | Small — pass Meilisearch `facets` through; the attributes are already filterable |
| Multi-supplier feed | Homepage rail | Small — empty query sorted `supplier_count:desc` |
| Similar products | Product page | Small — same category, nearby price, exclude self. **Not implemented** |
| Listing status policy | Archived listings | A decision. `/listings/{id}` currently serves any status |
| Image hosting policy | Every list and detail page | A decision. See below |
| Pack size / unit | Every price shown | Real work — `docs/decisions/0002`. Blocks honest price ranges |

## Decisions taken (2026-09-06)

**Image hosting — `next/image` with `remotePatterns`.** ~~Every supplier is a
different host and WordPress uploads arrive full-size; 24 of those on a results
page is punishing on Egyptian mobile, so optimisation wins over the
alternatives.~~

> **Superseded 2026-09-07** — see `docs/decisions/0003-supplier-images-load-direct.md`.
> Photos load straight from the supplier again, lazily, with a spinner. The
> bandwidth argument above is correct and was measured (a 24-row page is ~6.5 MB
> of source photos against ~24 KB optimised), but optimising on our server put
> our egress IP in front of the whole catalogue — two suppliers already block it,
> and the largest supplier's photos were 403-ing in the UI — and tied page speed to how many
> *new* products get viewed. `loading="lazy"` carries most of the mitigation.
> A downscaled thumbnail stored at ingestion time is the answer to both, when
> media storage exists.

**Archived listings — a tombstone, not a 404.** The page renders "this listing
was withdrawn", carries `noindex`, and links to the canonical product and its
remaining offers. Sweeps retire stock constantly; a hard 404 throws away the
inbound link and strands a buyer who is one click from a supplier who does have
the part. The API currently serves listings of any status, so this is enforced in
the frontend for now.

**Pack size — show the supplier's unit, never compute a normalised one.** Where
`Listing.unit` is populated it is displayed next to the price; where it is not,
no unit is shown and no per-unit price is derived. That keeps "from EGP 0.45"
from silently implying a single piece when it is a 1000-pack, without waiting on
the full extraction work in `docs/decisions/0002`. Comparisons stay
listing-to-listing, which is what the offers panel already does.

## Backend added for these layouts (2026-09-06)

- `GET /search?facets=true` returns `facets` — counts over the whole matching
  set, for the browse rail. `domain`, `category_ref` and `in_stock` only;
  `min_price` is a range and faceting it would return one bucket per price.
- `GET /search?min_suppliers=N` filters on `supplier_count`, which is now
  filterable as well as sortable. This is the homepage's multi-supplier rail.
  **Requires `make reindex`** — filterable attributes are index settings.
- `GET /products/{id}/similar` — same category, nearest price first, falling
  back to the vertical when the product is uncategorized. Deliberately not a
  recommender: there is no behavioural data, and a wrong "similar" on a parts
  catalogue sends someone to the wrong component.
- `ProductSummary` contract — a product without its offers, which is what every
  row and rail needs. `ProductRead` now extends it.
