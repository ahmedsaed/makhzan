# Product direction

Where makhzan goes after the November 2026 redesign: what has been decided, what has
been proposed and not yet discussed, and in what order. `docs/PLAN.md` is the original
plan; `docs/DESIGN.md` is how it looks; this is what it becomes.

Last updated 2026-11-06. Decisions are Ahmed's; "proposed" items are suggestions
recorded so the discussion can resume, not commitments.

## Now: polish, then ask the suppliers

The project depends on suppliers tolerating the crawl, so that is tested before
anything large is built. Six of the eight current shops are crawled without trouble;
two (over half the catalogue) block the production host's address, which may be a
default security setting rather than a decision about makhzan. Nobody has refused.

The current site is polished just enough to show, then the shops are asked. The
redesign continues in parallel: it does not depend on who says yes.

Before the emails go out:

1. **A working contact address.** The crawler's `From` header and the crawling page
   named `crawler@makhzan.eg`, a domain with no mail records: a shop that wrote would
   get a bounce.
2. **Fresh data for the reachable shops.** The crawl is paused; a shop owner checks
   their own products first.
3. **A "For suppliers" page**: remove my shop, add my shop, correct my details. Even a
   plain form or mail link. Shops have to see they can leave before they agree to stay.
4. **Links to shops carry `ref=makhzan`**, and clicks per shop are counted, so "we
   sent you N visitors" can be said with numbers.
5. **Each shop's own page on makhzan, spot-checked**: prices, links, photos, categories.
6. **No half-finished Arabic** anywhere visible (the redesign is English only).

Then: the two blocked shops first (the ask is specific: allowlist one address, or send
a feed), with their own makhzan page as the pitch; the others later with a short note
and the referral numbers.

## Decided

- **The redesign** (direction D) as specified in `docs/DESIGN.md`. English only.
- **Product ids never change.** Regrouping must not reassign them; merges leave a
  redirecting id behind. Needs a design pass: `docs/decisions/0004-stable-product-ids.md`.
- **Projects.** A project is a full build guide: documentation plus a list of
  products. Projects reference products (by permanent id). When a part becomes
  unavailable, the project shows a note rather than dropping it. Ahmed writes them
  first; the community publishes later; featured projects appear on the home page.
- **Blog** for news and changes, written by Ahmed only.
- **Report a problem** on products: important (wrong price, stock, match, category).
- **Supplier pages:** remove, add or correct a shop, as requests handled by hand for
  now (through code). Self-service comes with the supplier portal.
- **Price history** on product pages.
- **Shop details** (location, WhatsApp, opening hours): wanted; they arrive through
  supplier requests.
- **Install to home screen** (a progressive web app).
- **Log searches with no results**, to see demand.
- **Parts-list import** belongs in the plan, but not in this phase.
- **Accounts matter**: they unlock most postponed features (Ahmed's view; how and when
  is still open, below).
- **Enrichment without extra requests ships now** (brand, specs, datasheets, cleaner
  descriptions and titles from what the crawler already downloads).
- **Product details that cost a request per product are fetched slowly and only on
  change** (clarified 2026-11-09; this replaces "wait until the shops have answered",
  which was meant for the shops that block the crawler, not for all of them). A small,
  fixed number of product pages per shop per daily run, never a burst; a product's page
  is fetched once, then again only when the shop's own listing data shows it changed.
  Shops that block the crawler are not crawled at all until they reply. Stock counts
  are not wanted. Each shop's details are switched on individually, after deploy, on
  Ahmed's approval.
- **Current price only.** The crawler keeps shops' "before" prices, but makhzan shows
  no discounts: one shop's before prices are a standing markup on most of its stock.
- **Specs and datasheets are shown when the shop provides them** (DESIGN.md, C4).

## Shop data: what is collected, and what is shown next (November 2026)

Phase 1 (shipped) collects more of what shops already publish: units of sale, variants,
quantity breaks, manufacturer part numbers, compatibility, "ships from abroad", videos,
shop contact details; it also keeps hidden out-of-stock items and flags "price on
request". The per-shop findings and costs are in the private configuration's
`docs/qa/2026-11-discovery-summary.md`. Per-product details are fetched slowly and only on
change, switched on shop by shop (see "Decided" above).

Phase 2 shows it, decided 2026-11-09:

- **Product page:** minimum order ("EGP 0.25 each · min. 10 (EGP 2.50)"), the
  manufacturer part number, an options table (each option with its own price, stock
  and the date it was read), quantity breaks, "Ships from abroad" and "Fits: …"
  badges, videos, "Price on request". Stock counts only where the shop itself shows
  them.
- **Shop page:** address, phone, WhatsApp and opening hours, from the shop's own site.
- **Price history**, recorded from now (a row only when a listing's price or stock
  changes) and shown once there is history: "lowest in 90 days", a small chart, "in
  stock N of the last 12 weeks".
- **Grouping by material for products sold per colour.** A maker lists one product per
  colour; its resellers list one product per material with colour as an option. Until
  the options table exists they stay separate products. With it, one product per
  material (for example a filament type and weight) can hold every colour from every
  shop, each with its own price.
- **Group on manufacturer part numbers shops state.** Grouping already merges
  listings that share a part number *extracted from their titles*, and only when the
  titles agree, with three vetoes (same shop, different values, different form). Some
  shops now state the manufacturer's part number outright (`attributes.mfr_part_number`,
  e.g. one shop's "Mfr. Part #" field), which is stronger evidence than a title guess.
  Use it as the listing's part number when the title gives none, and as corroboration
  when both exist and agree; a disagreement keeps the title's and is logged. Title
  agreement and the vetoes still apply: a shop can mistype or list a kit under the part
  it contains. Measure first: how many groups form or change across the catalogue, read
  a sample, as CLAUDE.md asks of every grouping change.
- **Crawler activity** on `/how-we-crawl` and each shop page: when we last read the
  site, requests in the last 7 days, the measured gap between requests, and "Active" or
  "Paused" with no reason given.

## Proposed, not yet discussed

From the last round of the discussion, recorded to resume later.

- **Admin sign-in first, public accounts later.** The first thing that needs accounts
  is admin tooling: reviewing reports and supplier requests, featuring projects,
  writing posts. Build sign-in (email magic link and Google) with an admin role now,
  design the public account pages, and open them to the public with the first feature
  that needs them (community projects). A public sign-in with nothing behind it reads
  as half-built.
- **Project authoring in an in-app editor**, rather than files in the repository:
  build guides have photos, steps and parts lists, and the editor Ahmed uses becomes
  the community's later.
- ~~**Stale offers ranked below fresh ones** in default results.~~ Replaced (November
  2026) by a filter: stale products are hidden by default, like out of stock, with the
  count shown and one click to include them (DESIGN.md rule C2b). Nothing disappears
  for good, and ranking stays relevance.
- **Report a problem without an account**: a reason, an optional email, rate limited,
  into the review queue (which needs an admin screen; it has none today).
- **Parts-list import by parsing, not AI**: CSV, KiCad and spreadsheet parts lists and
  plain lines ("10x 1k 0805", "ESP32-WROOM-32"), each matched with the existing
  part-number-aware search and confirmed by the person. AI only for lines parsing
  cannot read.
- **Supplier pages in detail:** the opt-out prominent, with a stated turnaround; each
  request saved and emailed.
- **Discoverability:** indexable product pages, a sitemap, structured product and offer
  data, and link previews for WhatsApp and Facebook sharing.
- **Privacy policy, terms and a contact page**, required once emails are collected
  (Egypt's Personal Data Protection Law, No. 151 of 2020).
- **An admin area**: reports, supplier requests, projects, posts, featuring.
- **Blog categories**: News and Changes; Changes doubles as the public changelog.

## Proposed phases

| Phase | What ships | Accounts |
|---|---|---|
| 1 | The redesign; the polish list above; blog; report a problem | Admin only |
| 2 | Lists without login: build, save on the device, share by link; parts-list import; "cheapest shops for this list" | Admin only |
| 3 | Accounts for everyone: saved projects, build guides, back-in-stock and price alerts | Yes |
| 4 | Community: project gallery, profiles, copying a project, comments, moderation | Yes |
| Alongside | Supplier portal: claim a shop, location, WhatsApp | Suppliers |

## Open questions

1. Accounts: admin sign-in now and public accounts with community projects, or public
   accounts in the first release?
2. Project authoring: in-app editor, or files in the repository?
3. ~~Stale offers: warn, hide after a cutoff, or rank below fresh ones?~~ Decided:
   warn after 45 days (F2), and hide by default after the same cutoff, counted and one
   click away (C2b).
4. Notifications for alerts, later: email, WhatsApp or browser push?
5. Price history: a small chart, or "lowest in 30 days"?
6. Reviews, ratings, questions and answers: wanted at all?
