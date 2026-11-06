# Supplier photos load from the supplier, not through us

**Status:** accepted · **Decided:** 2026-09-07 · **Supersedes:** the image-hosting
decision in `docs/DESIGN.md` (2026-09-06)

## What changed

Product photos are `<img src="https://supplier…">` again, lazily loaded, with a
spinner while they arrive and a glyph if they fail. `next/image` and the
`remotePatterns` supplier-host list are gone from `apps/web`.

The rewrite had routed them through `next/image`, which optimises **on the
server**: our Node process downloads each supplier photo, re-encodes it with
sharp, caches it under `.next/cache`, and serves the result. This reverses that.

## Why the original decision was reconsidered

It was taken on a bandwidth argument, and that argument is real. Measured on the
live "arduino uno" results, the source photos are:

| supplier | bytes |
|---|---|
| the marketplace (`…q-80-h-150.webp`) | 5.8 KB |
| shop 2 | 34 KB |
| shop 1 (`…643x643.jpg`) | 30 KB |
| shop 4 | 78 KB |
| shop 3 (`arduino-uno-develop.-kit.png`) | 365 KB |
| shop 3 (`Screen-Shot-2018-02-21….png`) | 491 KB |
| shop 1 (`71Q7-IbiWrL._AC_SL1000_.png`) | 1.13 MB |

The marketplace serves real thumbnails; the WordPress shops serve raw uploads. Those
average ~273 KB, so a 24-row page is roughly **6.5 MB** of photos rendered into
48-pixel boxes, against ~24 KB optimised. That is a genuine cost and it is being
accepted deliberately, not overlooked.

What outweighs it is what the server-side approach costs *us*:

**It puts our egress IP in front of the catalogue.** Every optimised photo is an
outbound request from one address to a supplier. Two suppliers already block that
address for the crawler (see `docs/ROADMAP.md`), and it showed up in the product UI as
the marketplace's photos 403-ing through `/_next/image` — the top four results on the
main demo query rendering as empty boxes. Sending all media through the same IP
compounds the exact problem the crawler is already fighting, and invites the rest
of the suppliers to rate-limit us too. Loading direct spreads those requests
across visitors' own connections, and it fixes those photos outright.

**It ties page speed to catalogue novelty.** A cached variant is good for a year
(Next takes `max(upstream max-age, minimumCacheTTL)`, and the shops send
`max-age=31536000`), so photos already seen are free. But the work scales with
*new* products being viewed — precisely the discovery browsing this product
exists to encourage — and it is paid on the request path, with the visitor
waiting. Any deploy that replaced the container reset it to zero, which is how
this surfaced: a search right after a deploy re-fetched and re-encoded every
thumbnail on the page.

**It makes us a bottleneck for something that need not go through us at all.**
We are a directory: we hand buyers off to suppliers. Serving their media from our
box adds a failure mode, a CPU cost and an IP-reputation cost to a directory that
owns none of the images.

## Rejected: optimise some suppliers and not others

Hotlinking the shops that already serve thumbnails (the marketplace) and optimising the
ones that do not (the WordPress four) is the bandwidth-optimal answer. Rejected
because it is two code paths, two failure modes, and per-supplier knowledge
hardcoded in the frontend — the same coupling `DESIGN.md` already listed as the
cost of `remotePatterns`. One predictable path is worth more than the bytes.

## How the bandwidth cost is contained

- **`loading="lazy"`** — offscreen rows never fetch. A 24-row page pays only for
  the handful of photos actually on screen, and the rest arrive as the buyer
  scrolls. This is most of the mitigation.
- **The box is reserved** before anything loads, so nothing shifts and the page
  is usable and interactive while photos are still arriving.
- **`priority`** on the one above-the-fold photo of a detail page loads eagerly.
- **`referrerPolicy="no-referrer"`**, which also sidesteps naive hotlink checks.

## What would reopen this

- A supplier serving genuinely enormous originals, or applying hotlink protection
  that `no-referrer` does not defeat.
- Ingestion storing a downscaled thumbnail per listing at crawl time. That is the
  real answer to both problems at once — the cost moves off the request path and
  is paid once per product rather than once per product per year — and it belongs
  with the ingestion pipeline that already fetches these pages, not in the
  frontend. Revisit when media storage exists.
