# makhzan web

Next.js 16 (App Router, React 19) + Tailwind v4 + shadcn/Base UI, pnpm. The
consumer site: server-rendered, English only, light and dark.

`docs/DESIGN.md` is the specification — pages, URLs, the palette and the rules
(C1–C4, F1–F3, P1–P4, S1–S5) the tests check.

## Structure (root `@/*` alias, no `src/`)

- `app/page.tsx` — home (renders its own header, without the search field)
- `app/(site)/…` — every other page, under the full header: `search`,
  `products/[id]`, `departments`, `departments/[department]`, `departments/[department]/[category]`,
  `shops`, `shops/[shop]`, `how-we-crawl`, `for-suppliers`
- `app/listings/[id]` — redirects an old listing URL to its product
- `proxy.ts` — 308s from the previous site's URLs (`lib/redirects.ts`)
- `app/globals.css` — the palette as CSS variables, mapped into Tailwind
  (`bg-surface text-ink-2 border-line`). The only file allowed a literal colour.
- `components/` — the shared pieces pages are built from: `ResultRow` /
  `ResultCard` / `ResultList` / `ViewToggle`, `PriceRange`, `Freshness` /
  `StaleNote`, `ShopsBadge`, `PhotoFrame`, `ShopLink`, `Chip` / `ChipBar`,
  `FilterPanel`, `Breadcrumb`, `ObjectTile`, `SiteHeader` / `SiteFooter`
- `lib/api.ts` — server-side API client and types

## Dev

```bash
pnpm install
API_INTERNAL_URL=http://localhost:8000 pnpm dev   # http://localhost:3000
```

## Tests

```bash
pnpm exec vitest run                                   # unit, incl. contrast and colour rules
WEB_PORT=3301 STUB_PORT=8801 pnpm exec playwright test # e2e against a stub API
```

The ports default to 3210/8787; override them to run the suite in several
checkouts at once.
