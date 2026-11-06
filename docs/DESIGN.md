# Design: layout, style and rules

Settled 2026-11-06 and the reference `apps/web` is built against. It replaces the
September 2026 design (oxblood "Ledger/Souk" language, bilingual), which is in git
history. The data, research and alternatives behind every decision here are in the
private configuration repository (`docs/design/2026-11-layout-mocks/`), because the
mocks use real supplier names.

Visual references (private canvases):

- Layout directions A–D and the trade alternatives: https://claude.ai/artifact/L7EjzecZEk6sGRi2iTGYe7
- Styling, rounds 1–2 and the final light/dark palette: https://claude.ai/artifact/Q7ZSundQ9GhK81kzcY7f8C
- Page structure, and the page designs as they are drawn: https://claude.ai/artifact/LJR2GyNiMAYd2MnYsTZcWT

Where this document and a mock disagree, this document wins; fix the mock.

## What the data says, and what follows

Measured on 60.9k active listings (November 2026).

| Fact | Consequence |
|---|---|
| 98.6% of products have one shop; 1.4% have 2–7 | A parts search engine that hands off to a shop, and only sometimes a comparison. The product page is designed for one offer; comparison appears only with 2+ shops. Being sold by several shops is rare, so it is a badge and a filter. |
| 41% of listings are out of stock | Out of stock is **hidden by default**, and the count of hidden items is always shown. |
| A large share of listings are weeks or months old (two shops cannot be reached) | Freshness is shown everywhere and gets louder with age (rule F2). |
| Arabic titles 0.1%, Arabic descriptions 3% | **English only.** Arabic search queries keep working; the Arabic interface is gone. |
| Images on 99% of listings, 21% with several; descriptions on 41%, median ~900 chars | Photos can lead, inside a white frame. Descriptions are clamped. |
| No structured specs until November 2026; brand on 2%; part numbers on 15% | Since the enrichment, about 1,000 listings carry specs from their shop and about 5,400 datasheet links: shown when present, never as an empty table. No brand filter (brand is known on about a tenth of listings). Part numbers matter to ranking, not as a field. |
| Titles: median 38 characters, p90 67, p99 103 | Two-line titles everywhere; grid cards allow three. |
| Prices EGP 5 (p10) to 39,000 (p99); unit of sale never recorded | "From EGP X" for ranges; never imply a per-unit price. |
| 16 trades, very uneven (three hold 88% of products) | Trades are listed by size and each says what's inside; never equal tiles of names. |
| Supplier profiles have no location, phone or logo | The shop page is thin until shops add details (see `docs/PRODUCT.md`). |
| Offers per product exceed shops per product | One shop can list several variants of one product. |

## How aggregators do it (research, November 2026)

- Consumer comparison sites (idealo, Geizhals) open a product page of offers; parts
  search engines (Octopart, Findchips) link offers straight to distributors. makhzan
  always opens the product page: that is where the freshness warning lives.
- Geizhals splits a product family into variant cards, each with its own offers.
  makhzan keeps all variants in one list for now (rule P3) and designs rows so variant
  headers can wrap them later.
- Geizhals opens results with "Top categories" for the query. makhzan does too.
- McMaster-Carr names categories by what they do and shows each as a photo of one
  iconic object. makhzan's trade and category tiles follow it.
- "Last checked" is the timestamp that matters; show it relative, and tell people to
  confirm on the shop's site.

## Pages

```
/                               Home: search and examples, trades, sold by several shops, the shops, how it works
├── /search?q=…                 Results (list or grid), top categories, filters
│   └── /products/{id}          Product: one shop, or several (offers list)
│       └── shop's own page ↗   the only exit
├── /trades                     All 16 trades as a directory: each with its categories as links
│   └── /trades/{trade}         Group tiles, category tiles, results underneath
│       └── /trades/{trade}/{category}   the same page, narrowed
├── /shops                      Every shop: products, in stock, last checked (cards on desktop)
│   └── /shops/{shop}           Freshness, what they carry, its products as scoped results
├── /how-we-crawl               The crawling policy, written for suppliers
└── /for-suppliers              Remove, add or correct a shop (requests, by email)

Everywhere: header (logo, search, Trades, Shops), footer (For suppliers,
How we crawl, theme toggle, Made by Merope), 404 and error pages.
```

- **No language in URLs.** `/en/…` and `/ar/…` redirect permanently to the same path
  without the prefix.
- **Categories are addressed through their trade**, because category slugs are unique
  per trade only: `/trades/tools/calipers`.
- **No listing pages.** `/listings/{id}` redirects to its product.
- Old routes redirect: `/{lang}/browse/{trade}` → `/trades/{trade}`,
  `/{lang}/browse/{trade}/{category}` → `/trades/{trade}/{category}`,
  `/{lang}/suppliers/{slug}` → `/shops/{slug}`, and every other `/{lang}/x` → `/x`.

## Layout, page by page (direction D)

**Home.** A headline, one large search field, a line of totals (products, shops,
"rechecked about weekly"; figures for products, shops, trades and categories on desktop)
and a row of example searches, each checked to return results. Then the trades: on
phones as rows (an object photo, the trade, its count, its top categories in words),
the top 8 then "All 16 trades"; from `md` as cards, four across on desktop, whose
biggest categories are links, with the remaining trades named underneath. Then "Sold
by several shops" (a row of products with 2+ shops and their price ranges), the shops
(products, in stock, last checked), "How makhzan works" in three steps (beside the
search on desktop, lower down on phones) and a note for shop owners. Every block spans
the page container on desktop; each section is left out when its fetch fails.

**Results (search, trade, category, shop search).**
- A chip bar with the two everyday filters, **In stock** (on by default) and
  **2+ shops**, plus a "Category, price" chip that opens a sheet (a side rail on
  desktop) for the rest.
- "Top categories for “query”" above the results.
- A toolbar: the count, "N more out of stock" (one click shows them), sort (best match,
  price low first, most shops, recently checked) and the list/grid toggle.
- List rows: photo, two-line title, price, shop name or an "N shops" badge, freshness.
  Grid cards: the same facts. The toggle is remembered per visitor.

**Product.**
- Breadcrumb (trade › group › category), photo (contained, white frame), title, part
  number when known.
- One shop: price, stock, freshness note when stale, a "Sold by" card linking to the
  shop page, the description (clamped), similar products. A fixed bottom bar on phones:
  price, "checked …" and **View at {shop}**.
- What the shops wrote: description, specifications (name/value rows) and datasheets
  (PDF links), each labelled with its source ("From Shop A's listing"). With several
  shops, a **Details** section with a "From:" tab per shop that wrote anything, richest
  first; one shop at a time, never merged (shops contradict each other). The tabs are
  radio buttons and work without JavaScript. A shop that wrote nothing gets no tab;
  absent data means no section, never an empty one.
- Several shops: a summary ("5 offers in stock at 3 shops", the price range), then
  **Offers**: one list for all variants, lowest price first, each row led by the shop's
  own title, then shop and freshness, then price and **View**. Out-of-stock offers fold
  under "Show N out of stock offers". The bottom bar points to the cheapest.

**Trade and category.** Header (name, count, "Search in {trade}"); groups as object
tiles; the selected group's categories as smaller object tiles; then results with the
chip bar. No page is a dead-end list of links. From `lg` the search sits beside the
name and the tiles lie on their side (a small frame, the name, its count and, for a
group, its top three categories) in balanced rows across the full width: a row of
large squares holding the same stand-in icon said nothing and left half the screen
empty. Phones keep the square tiles. All trades (`/trades`) is a directory, full width, largest trade first. A trade
with 10% or more of all products (three today) is a full-width block listing every
group with up to six of its categories, as links with counts, in columns. The rest
share a grid of cards (2, 3, then 4 across), each listing its biggest categories:
4, 6 or 10 links depending on size, so a bigger trade gets more links. Cards for
trades with 1,000 or more products span two cells on wide screens. "Other …"
buckets are listed last. On a phone it is the home page's list of rows, with each
trade's links folded under a chevron.

**All shops and a shop.** Each shop with products, in stock and last checked: rows in
one card on phones; from `md` a grid of cards (2 across, 4 from `xl`), each adding a bar
of what the shop carries and its two counts as figures. A shop page: a header band with
name, stat tiles (products, in stock, last checked), a plain-language note when its data
is stale, "Visit {site}", search within the shop and what it carries (a bar by trade).
On desktop the band uses the full width: name and search on the left, tiles and "Visit"
on the right, the note and the bar across. Below it the page is search scoped to the
shop, on the same URL (`/shops/{shop}?category=…`): chips, rail, toolbar, list/grid,
paging. Rows leave out the shop's name, which would only repeat the heading (the one
exception to C1's "shop name"); a product other shops sell keeps its "N shops" badge.
"Biggest categories" is a phone list only, since the desktop rail already lists them.
Then "Own this shop? Add your details."

**Desktop.** Results get a side rail (category, price); the chips stay above the list;
list rows become columns (photo · title and category · shops and freshness · price).
Product pages go two columns: a narrow one (about 26rem) with the photo and, under it,
the way to the shop (price box, or the summary and the offers as two-line cards); and a
wide one with the title and what the shops wrote, which is the long part. A product no
shop wrote anything about keeps its offers in the wide column instead. Every page is
checked at 1280, 1440 and 1920px as well as on a phone: no content in a narrow strip
beside empty space.

## Style

Archivo for headings and prices, Inter for text, IBM Plex Mono for part numbers.
Burnt orange for actions. Hairline borders, 10–12px corners, no shadows.

| Token | Light | Dark |
|---|---|---|
| `ground` | `#F6F6F3` | `#121316` |
| `surface` | `#FFFFFF` | `#1B1D21` |
| `ink` | `#15171C` | `#ECECEA` |
| `ink-2` (secondary text) | `#4A4F5A` | `#B5B8BF` |
| `ink-3` (tertiary text) | `#6B7080` | `#9095A0` |
| `line` | `#E3E3DE` | `#2C2F35` |
| `line-strong` (controls) | `#D5D5CF` | `#3A3E45` |
| `action` (buttons) | `#C2410C`, white text | `#C2410C`, white text |
| `link` | `#C2410C` | `#FB923C` |
| `badge` / `badge-ink` ("3 shops") | `#FDECE3` / `#9A3412` | `#3A2416` / `#FDBA8C` |
| `chip-on` / `chip-on-ink` | `#15171C` / `#FFFFFF` | `#ECECEA` / `#121316` |
| `warn` / `warn-line` / `warn-ink` | `#FEF9C3` / `#E5D36A` / `#574500` | `#2A2710` / `#57501C` / `#F3E08A` |
| `age-muted` (15–45 days) | `#6E5A00` | `#D9C46C` |
| `photo-frame` | `#FFFFFF` | `#FFFFFF` |

| | |
|---|---|
| Headings | Archivo 700 (800 for the home headline) |
| Prices | Archivo 700 with tabular figures |
| Text | Inter 400/500/600 |
| Part numbers | IBM Plex Mono 500 |
| Corners | 10px controls, 12px cards and frames, pills fully round |
| Borders | 1px `line`; 1.5px for outlined buttons; no shadows |
| Touch targets | 44px minimum on phones |

Light and dark follow the device setting; the footer toggle overrides it.

## Rules

Each is meant to be checked by a test.

**Content**
- **C1** Every result, list or grid, shows: title, price (or range), shop name or "N shops", freshness. List and grid carry the same facts.
- **C2** Out of stock is hidden by default; when anything is hidden the page says how many and offers to show them.
- **C3** No per-unit price is ever implied; ranges read "EGP 260 – 400". Prices are the current price only: no struck-through "before" prices, no discount badges (some shops' before prices are standing markups).
- **C4** Specs and datasheets appear only when the shop provides them, with their source; never an empty or placeholder table. No brand filter, no Arabic interface text.

**Freshness**
- **F1** Every price shows when it was last checked, relative ("checked 12 days ago").
- **F2** Up to 14 days: quiet (`ink-2`). 15–45 days: muted (`age-muted`). Over 45: a warning, "Price may be out of date", in the `warn` colours, never in `action`.
- **F3** A shop whose data is stale says so on its own page, in plain language.

**Product**
- **P1** Every result opens the product page; nothing in a result links straight to a shop.
- **P2** The comparison list appears only with 2+ offers.
- **P3** All of a product's offers share one list, each row led by its own title (variants differ). Rows must not depend on their neighbours, so variant groups can wrap them later.
- **P4** The only link out of makhzan is to a shop's own page, and it carries `ref=makhzan`.

**Style and accessibility**
- **S1** Colours come only from the tokens above; no literal colours in components.
- **S2** Text meets 4.5:1 against its background in both themes (3:1 at 24px and up).
- **S3** Prices use tabular figures; part numbers use the monospace face.
- **S4** Touch targets are at least 44px on phones; no horizontal scroll at 320px.
- **S5** Photos are contained in a white frame in both themes; never cropped.
