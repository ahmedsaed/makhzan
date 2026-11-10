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
| A large share of listings are weeks or months old (two shops cannot be reached) | Freshness is shown everywhere and gets louder with age (rule F2). Results hide products not checked in over 45 days by default, with the count shown, like out of stock (C2b). |
| Arabic titles 0.1%, Arabic descriptions 3% | **English only.** Arabic search queries keep working; the Arabic interface is gone. |
| Images on 99% of listings, 21% with several; descriptions on 41%, median ~900 chars | Photos can lead, inside a white frame. Descriptions come after makhzan's own facts and the way to the shop, clamped to 25 lines behind Read more. |
| No structured specs until November 2026; brand on 2%; part numbers on 15% | Since the enrichment, about 1,000 listings carry specs from their shop and about 5,400 datasheet links: shown when present, never as an empty table. No brand filter (brand is known on about a tenth of listings). Part numbers matter to ranking, not as a field. |
| Titles: median 38 characters, p90 67, p99 103 | Two-line titles everywhere; grid cards allow three. |
| Prices EGP 5 (p10) to 39,000 (p99); unit of sale never recorded | "From EGP X" for ranges; never imply a per-unit price. |
| 16 departments, very uneven (three hold 88% of products) | Departments are listed by size and each says what's inside; never equal tiles of names. |
| Shops' contact details: listed by hand from where each shop's details are published (its site, its Facebook, its Google Maps listing; `sources.toml`) or read by the crawler from its JSON-LD; few shops have them yet, and none has a logo | The shop page shows what is known with where and when it was read, and names what is still missing; a product page offers WhatsApp or a call only for a shop that publishes one. |
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
  iconic object. makhzan's department and category tiles follow it.
- "Last checked" is the timestamp that matters; show it relative, and tell people to
  confirm on the shop's site.

## Pages

```
/                               Home: search and examples, departments, sold by several shops, the shops, how it works
├── /search?q=…                 Results (list or grid), top categories, filters
│   └── /products/{id}-{slug}   Product: one shop, or several (offers list)
│       └── shop's own page ↗   the only exit
├── /departments                All 16 departments as a directory: each with its categories as links
│   └── /departments/{department}         Group tiles, category tiles, results underneath
│       └── /departments/{department}/{category}   the same page, narrowed
├── /shops                      Every shop: products, in stock, last checked (cards on desktop)
│   └── /shops/{shop}           Freshness, what they carry, its products as scoped results
├── /how-we-crawl               The crawling policy, written for suppliers, and what the crawler did (#activity)
└── /for-suppliers              Remove, add or correct a shop (requests, by email)

Everywhere: header (logo, search, Departments, Shops), footer (For suppliers,
How we crawl, theme toggle, Made by Merope), 404 and error pages.
```

- **No language in URLs.** `/en/…` and `/ar/…` redirect permanently to the same path
  without the prefix.
- **Categories are addressed through their department**, because category slugs are
  unique per department only: `/departments/tools/calipers`.
- **"Trades" became "departments"** (November 2026): "trade" names a profession, not a
  kind of product, and "departments" is what people expect of a hardware store. The
  backend still calls the same thing a `domain`.
- **No listing pages.** `/listings/{id}` redirects to its product.
- **Product URLs read:** `/products/{id}-{words-of-the-title}`. The id is a UUID at the
  front, so the page always finds it; a bare id, an old title's words or a typo
  redirect permanently (308) to the current form. Ids are permanent
  (`docs/decisions/0004-stable-product-ids.md`): an id merged into another product
  redirects to the survivor's readable URL in the same single hop, and a product every
  shop has withdrawn keeps its URL as a "no longer listed" page (200, noindex): its
  title, last price and when, and similar products. Which redirects exist and when
  each retires: `docs/decisions/0005-url-retirement.md`.
- Old routes redirect permanently (308, query string kept), each in one hop:
  `/{lang}/browse/{department}[/{category}]` → `/departments/{department}[/{category}]`,
  `/{lang}/trades[/{department}[/{category}]]` → `/departments[/…]` (the same path),
  `/{lang}/suppliers/{slug}` → `/shops/{slug}`, and every other `/{lang}/x` → `/x`.
  `/en/browse/x` goes straight to `/departments/x`, never by way of `/trades/x`.

## Layout, page by page (direction D)

**Home.** A headline, one large search field, a line of totals (products, shops,
"rechecked about weekly"; figures for products, shops, departments and categories on desktop)
and a row of example searches, each checked to return results. Then the departments: on
phones as rows (an object photo, the department, its count, its top categories in words),
the top 8 then "All 16 departments"; from `md` as cards, four across on desktop, whose
biggest categories are links, with the remaining departments named underneath. Then "Sold
by several shops" (a row of products with 2+ shops and their price ranges), the shops
(products, in stock, last checked), "How makhzan works" in three steps (beside the
search on desktop, lower down on phones) and a note for shop owners. Every block spans
the page container on desktop; each section is left out when its fetch fails.

**Results (search, department, category, shop search).**
- A chip bar with the everyday filters, **In stock** and **Checked recently** (both
  on by default) and **2+ shops**, plus a "Category, price" chip that opens a sheet (a
  side rail on desktop) for the rest.
- "Top categories for “query”" above the results.
- A toolbar: the count, "N more out of stock" and "N more out of date" (one click on
  either shows them), sort (best match, price low first, most shops, recently checked)
  and the list/grid toggle. Each count is exactly what its own click adds: a product
  both out of stock and out of date is in neither, and turns up under the other link
  once one filter is off. A page whose every match is hidden says which filter hid
  them and offers them; when only both together did, it offers "Show all N".
- List rows: photo, two-line title, price, shop name or an "N shops" badge, freshness.
  Grid cards: the same facts. The toggle is remembered per visitor.

**Product.**
- Breadcrumb (department › group › category), photo (contained, white frame), title, part
  number when known.
- **makhzan's facts first.** The title, description and specs are copied from the
  shops (on 98.6% of pages from one shop), so what makhzan adds leads, under the title:
  unique value first, for a buyer and for a search engine. Each line only when its data
  is there, never empty: "Sold by 1 shop · checked 3 days ago" (several shops: "Sold by
  3 shops · in stock at 2 · EGP 260 – 295"), and "8 similar products, from EGP 40",
  linking down to them.
- Photos: a swipeable strip (scroll snap, works without JavaScript) with previous and
  next arrows (44px, disabled at the ends, absent with one photo). Each photo is a link
  to the image; with JavaScript it opens a full-screen viewer instead: a native modal
  dialog on the `scrim` colour, the photo in its white frame as large as the screen
  allows (the full-size original where there is one, fetched only when shown),
  swipe, arrows, Left/Right and Esc, an "n / N" counter, and focus back on the photo
  when it closes.
- One shop: price, stock, freshness note when stale, a "Sold by" card linking to the
  shop page and, under it when the shop publishes one, "Contact {shop} directly":
  outlined buttons for "Call 02 2345 6789", WhatsApp and Email, laid out as on the shop
  page, then its opening hours as the shop page reads them, then "Something wrong?
  Tell us" (an email to makhzan naming the product and the shop); then what the shop
  wrote. A fixed bottom bar on phones: price, "checked …"
  and **View at {shop}**.
- Similar products are always last, on every product page: a swipeable row with arrows
  on a phone, a grid from `sm`.
- **What the shops say** (a heading on its own line): description, specifications
  (name/value rows) and datasheets (PDF links), one shop at a time, never merged (shops
  contradict each other), each shop's panel opening with its source ("From Shop A's
  listing", rule C4). With several shops, an underline tab strip of their names under
  the heading, richest first: one row that never wraps and scrolls sideways on a phone
  (faded at the edge with more beyond), 44px tall on phones, a hairline under the
  strip, the selected tab in `ink` with a 2px `action` underline and the rest in
  `ink-2`. The tabs are a radio group (one tab stop, arrow keys between shops) and work
  without JavaScript. With one shop there is no strip. A shop that wrote nothing gets
  no tab; absent data means no section, never an empty one.
- The description is clamped to 25 lines (CSS `line-clamp`), faded at the cut, with
  **Read more** and **Show less** in a `<details>`, so it works without JavaScript.
  Whether a text is long is decided on the server, by estimated lines (paragraphs
  wrapped at about 48 characters on a phone, 105 in the wide column), so the page is
  drawn once in its final shape: nothing is measured or moves after load. A short
  description shows in full with no button.
- Several shops: a summary ("5 offers in stock at 3 shops", the price range), then
  **Offers**: one list for all variants, lowest price first, each row led by the shop's
  own title, then shop and freshness, then price and **View**. Under the list,
  **Contact the shops**: each shop that publishes a way to reach it, once, as a small
  block (its name; "Call 19123 · WhatsApp · Email"; its opening hours), never on the rows (a shop with three offers would
  say it three times, and a row leaving it out because a neighbour said it would break
  P3), then "Something wrong? Tell us". Out-of-stock offers fold
  under "Show N out of stock offers", out-of-date ones (any stock) under "Show N out of
  date offers". The summary counts the recently checked offers, and the bottom bar
  points to the cheapest of them. When every offer is out of date nothing folds for
  age: the page lists them all, and the summary carries the "Price may be out of
  date" note.

**Department and category.** Header (name, count, "Search in {department}"); groups as object
tiles; the selected group's categories as smaller object tiles; then results with the
chip bar. No page is a dead-end list of links. From `lg` the search sits beside the
name and the tiles lie on their side (a small frame, the name, its count and, for a
group, its top three categories) in balanced rows across the full width: a row of
large squares holding the same stand-in icon said nothing and left half the screen
empty. Phones keep the square tiles. All departments (`/departments`) is a directory, full width, largest department
first. A department with 10% or more of all products (three today) is a full-width block listing every
group with up to six of its categories, as links with counts, in columns. The rest
share a grid of cards (2, 3, then 4 across), each listing its biggest categories:
4, 6 or 10 links depending on size, so a bigger department gets more links. Cards
for departments with 1,000 or more products span two cells on wide screens. "Other …"
buckets are listed last. On a phone it is the home page's list of rows, with each
department's links folded under a chevron.

**All shops and a shop.** Each shop with products, in stock and last checked: rows in
one card on phones; from `md` a grid of cards (2 across, 4 from `xl`), each adding a bar
of what the shop carries and its two counts as figures. A shop page: a header band with
name, stat tiles (products, in stock, last checked), a plain-language note when its data
is stale, "Visit {site}", search within the shop and what it carries (a bar by department).
On desktop the band uses the full width: name and search on the left, tiles and "Visit"
on the right, the note across, then the bar and the crawl line on the left beside
Contact on the right. Below it the page is search scoped to the
shop, on the same URL (`/shops/{shop}?category=…`): chips, rail, toolbar, list/grid,
paging. A shop whose own data is stale shows its products anyway (C2b): the visitor
asked for that shop and the note already says the data is old, while hiding them would
empty the page, or leave only what a fresher shop also sells. The "Checked recently"
chip still hides them (`?stale=hide`). A search within the shop follows the same rule.
Rows leave out the shop's name, which would only repeat the heading (the one
exception to C1's "shop name"); a product other shops sell keeps its "N shops" badge.
"Biggest categories" is a phone list only, since the desktop rail already lists them.
**Contact** is a compact block, not a band of its own: from `lg` in the right-hand
column under "Visit" (beside what the shop carries and the crawl line), on a phone
straight under "Visit", before the search. One row of outlined buttons: "Call 02 2345
6789" (the first number), WhatsApp, Email; any other numbers follow the call as plain
links ("or 02 2345 6780"), worth a glance but not a button's weight. On a phone the call
takes the width and the rest go in pairs under it, so no row ends in one stray button.
Then one line each, behind a small icon: the address, without the area and governorate
the header already shows (or that the address names itself), ending "Open in maps"
("Main shop: …" when there are branches); each branch, "Giza branch: 3 Other Street,
Dokki, Giza · 02 3333 4444 · Open in maps"; the opening hours. Numbers read the
Egyptian way ("010 0123 4567", "02 2345 6789") and link in E.164. **Opening hours** read
in plain English (`lib/hours.ts`): schema.org strings ("Sa,Su,Mo,Tu,We,Th 10:00-20:30",
"Fr 14:00-20:00") become "Sat–Thu 10:00–20:30 · Fri 14:00–20:00": the week from
Saturday, consecutive days as a range, days with the same hours merged, "Daily" for all
seven, "Open 24 hours", and the days no line names said to be closed. Hours a person
wrote, and anything else that does not parse, show exactly as written; when one line of
a shop's hours does not parse, none is rewritten. Phrases joined by " · " wrap whole
(`components/dotted.tsx`): a dot never ends or opens a line. Last, quietly, one short
line: "From Nile Parts' website and Google Maps, checked 9–10 Nov · Something wrong?
Tell us", the places once each, the days as a span, the year only when it is not this
one. The line opens (a native `<details>`) into where each detail came from: "Phone,
WhatsApp and email from Nile Parts' website, checked 10 Nov 2026", "Opening hours from
Nile Parts' website, read automatically 9 Nov 2026", "Address and map link from Google
Maps, checked 10 Nov 2026". A page on the shop's own domain (either a subdomain of the
other) is "{shop}'s website"; Google Maps, Facebook and Instagram are named as such and
never called the shop's (a Google Maps listing is often unclaimed); anything else by its
host. "checked" is a person reading the page, "read automatically" the crawler reading
the shop's structured data; the short line says "checked" for both. "Tell us" is an
email to makhzan naming the shop. A shop nobody has found anything for has no section. At the foot of the
page one line names only what is still missing ("Phone and opening hours aren't listed
yet.") before "Own this shop? Add your details.", which stands alone when nothing is.
At the foot of the band, one line on what the crawler did there: "makhzan read this site
3 hours ago · 412 requests in the last 7 days · at least 15 s apart · How we crawl", the
link going to `/how-we-crawl#activity`; for a paused shop only "makhzan is not reading this
site at the moment." The line is left out, and the page still renders, when the activity
cannot be fetched. Then "Own this shop? Add your details."

**How we crawl.** The policy as prose, then **Crawler activity** (`#activity`): the measured
proof of it, from `GET /crawler/activity`, cached for ten minutes. Four tiles of totals
(shops read this week of all shops, requests this week, the next daily run as a relative
time with "Early morning, Egypt time (03:00 UTC)" under it, and "robots.txt: Honoured"),
then one row per shop: last read, requests over 7 days, the shortest and the typical
(median) gap between requests, and a status. A table from `md`; on phones a card per shop
with the same facts, never a sideways scroll. Times are relative ("3 hours ago") with the
absolute UTC time as a tooltip. Gaps are floored to the second, so a published figure never
flatters, and a gap not measured reads "—". A count that some run did not record reads
"at least 412". Status uses neutral words only: "Active" or "Paused", and a pause is never
given a reason. The section never shows errors, status codes, refusals or block counts,
resume points, crosswalk drift, the review queue, internal ids or anything about our
servers. A shop removed at its request is retired with its runs, so it is simply absent.
When the API cannot answer, the policy still renders and the section says the figures can't
be shown right now.

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
| `scrim` (behind the photo viewer) | `#0B0C0E` | `#0B0C0E` |
| `photo-tag` / `photo-tag-ink` (the shop badge on a photo, fill at 80%) | `#15171C` / `#FFFFFF` | `#15171C` / `#FFFFFF` |
| `pattern` (background icons) | `#E2E1D9` | `#24262B` |

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

**Background pattern.** The top of every page carries a scatter of line icons of
the things makhzan lists (resistor, chip, LED, wire, wrench, caliper, bearing,
O-ring, gear, valve, pipe elbow, plank, plug, breaker, bolt, spring, solder and
more), at seeded random positions, sizes and rotations, in the `pattern` token. It
fades to nothing by about 1.3 screen heights and scrolls away with the page; it is
never fixed and never animated. The tiles are masks drawn by
`apps/web/scripts/pattern-tile.mjs` (a fixed seed, so they are the same on every
build): a 1180×740 tile from `sm` up, a sparser 430×620 one on phones. It is
decoration: `aria-hidden`, no pointer events, behind all content, and hidden under
`prefers-reduced-transparency`. Header, cards, controls and photo frames are opaque
and cover it, and `ink` and `ink-2` keep 4.5:1 against the stroke colour itself
(S2).

### Brand

**The logo** ("organizer grid") is a 2×2 parts organizer: three outlined compartments
and one filled burnt-orange compartment, top right. Many shops, one picked. On a 48×48
grid: four 18×18 squares at (4,4), (26,4), (4,26), (26,26), 4px corners, the outlines
3.5px in `ink` (`#15171C` light, `#ECECEA` dark), the top-right one filled with the
`brand` token (`#C2410C` in both themes, named apart from `action` so the mark never
moves with a button). The wordmark is "makhzan" in Archivo 800, letter-spacing −0.02em,
beside the mark; the mark is 1.2em tall, Archivo's cap height plus x-height.
`components/logo.tsx` draws it in the header and footer, the outline in `currentColor`.
The headline is "Find parts and materials across Egypt's suppliers."

**Icons.** `app/icon.svg` is the mark alone, its outline switching ink with
`prefers-color-scheme`. The rasters are drawn by `apps/web/scripts/brand-icons.mjs`: a
32px PNG and a 16/32/48 `favicon.ico` as a rounded tile on `ground`, so the dark outline
reads on a dark tab bar; the 180px apple icon and the 192/512px manifest icons as full
squares (the platform rounds them), plus a 512px maskable one inside the safe zone.
`app/manifest.ts` names the app; there is no service worker.

**Link previews** are 1200×630 cards from `next/og` (`lib/og.tsx`): the `ground`, the
logo top left, an Archivo 800 headline, Archivo 700 for the key figure, Inter for the
rest, the site's domain at the foot and a 6px `brand` bar along the bottom. The site's
card has the headline and the live totals ("N products · N shops · rechecked weekly");
a product's has its title, price range, "at N shops" or the shop's name, and its photo
on the right in a white frame (none if the shop's photo fails, never no card); departments,
categories and shops have their name and counts. Fonts are committed under
`apps/web/assets/fonts` (OFL). Colours come from `lib/brand.ts`, which a test holds
equal to the tokens.

## Rules

Each is meant to be checked by a test.

**Content**
- **C1** Every result, list or grid, shows: title, price (or range), shop name or "N shops", freshness. List and grid carry the same facts.
- **C2** Out of stock is hidden by default; when anything is hidden the page says how many and offers to show them.
- **C2b** Stale (last checked more than 45 days ago: F2's warn tier, `STALE_AFTER_DAYS` in `apps/web/lib/freshness.ts` and `makhzan_schemas/freshness.py`) is hidden by default too, in results (`?stale=all` shows it) and folded on a product page. When anything is hidden the page says how many and offers to show them. A product is fresh when any of its offers is. A direct link always works: a product whose offers are all stale still renders, with the warning, and a stale shop's own page shows its products.
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
- **P4** The only link out of makhzan is to a shop's own page, and it carries `ref=makhzan`. The one exception is a way to reach a shop, as its details are published (its site, its Facebook, its Google Maps listing): `tel:`, `mailto:`, `https://wa.me/<its number>` and a Google or Apple Maps link, plus the "Something wrong? Tell us" email to makhzan. These carry no `ref` (it would break them) and are marked `data-contact`.

**Style and accessibility**
- **S1** Colours come only from the tokens above; no literal colours in components.
- **S2** Text meets 4.5:1 against its background in both themes (3:1 at 24px and up).
- **S3** Prices use tabular figures; part numbers use the monospace face.
- **S4** Touch targets are at least 44px on phones; no horizontal scroll at 320px.
- **S5** Photos are contained in a white frame in both themes; never cropped.
- **S6** Every shop photo carries, in its bottom-left corner, a badge naming the shop it comes from: an element drawn over the `<img>`, never a change to the image (the photo stays the shop's own file, decision 0003). It is `aria-hidden`, with the shop in the alt text ("<title> — photo from <shop>"). Never on the no-photo placeholder. Frames under 96px (the 72px list-row thumbnail) carry none, and say whose photo it is in alt and title; 96–119px frames carry a compact one.
