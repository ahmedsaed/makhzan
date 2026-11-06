# makhzan web

Next.js 16 (App Router, React 19) + **shadcn/ui (Base UI variant, `base-nova` preset)**, Tailwind v4, pnpm. The consumer search UI; later the supplier portal.

- **Design system:** shadcn components in `components/ui/` (built on `@base-ui/react`), themed via the preset in `app/globals.css`. Dark mode via `next-themes` (toggle button, or press `d`).
- **Bilingual EN/AR + RTL:** a language toggle flips the whole UI. Base UI's `DirectionProvider` (`@/components/ui/direction`) drives component direction; `<html dir>` is synced for CSS logical properties. Arabic glyphs fall back to Noto Sans Arabic.
- **Data:** talks to the FastAPI backend via `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).
- Search is debounced; empty query browses the catalog. In-stock filter + price sort apply immediately.

## Structure (root `@/*` alias, no `src/`)
- `app/page.tsx` — search page (client component)
- `components/listing-card.tsx` — result card
- `components/mode-toggle.tsx` — dark-mode toggle
- `components/ui/*` — shadcn components
- `lib/api.ts` — API client + types · `lib/i18n.ts` — bilingual strings

## Dev
```bash
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev   # http://localhost:3000
```
Requires the API running with its `WEB_ORIGINS` including this app's origin (CORS).
Add more components with `pnpm dlx shadcn@latest add <name>`.

> If 3000/8000 are taken: `pnpm dev -p 3100` and point `NEXT_PUBLIC_API_URL` at the API's port.
