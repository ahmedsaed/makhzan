# makhzan — Project Plan

> An online hardware-store **aggregator** for local Egyptian suppliers — the one place to find your project materials (wood, metals, electronics, and beyond). A directory/discovery product, not a marketplace.

Status: **Phase 2 complete, entering Phase 3** · Last updated: 2026-08-24

---

## 1. What makhzan is (and isn't)

**Is:** A bilingual, search-first directory that aggregates products + prices from many local suppliers and hands the user off to the supplier to buy.

**Is not (in V1):** A marketplace. No cart, no payment, no orders, no delivery/logistics, no disputes.

The core problem is a **data problem**, not a web-app problem: accurately acquiring, normalizing, and keeping fresh the inventory/pricing of suppliers who mostly don't publish structured data.

---

## 2. Locked V1 decisions

| Decision | Choice |
|---|---|
| Business model | **Directory / discovery only** — hand off to supplier |
| First category | **Electronics components** |
| First geography | **Greater Cairo** (Cairo, Giza, ...) |
| Data sourcing | Supplier **portal** + **website scraping** + **manual ops entry** (social/WhatsApp excluded from V1) |
| Search | Real AR-aware engine (**Meilisearch/Typesense**), part-number weighted |
| UI language | **English-primary**, Arabic fully supported |
| Cross-supplier product matching | **Deferred** — ship raw listings first |
| Legal stance | Compliant where practical, pragmatic to launch; every source is a toggleable adapter |

Why electronics/Cairo first: electronics suppliers have the best online footprint (scraping actually pays off), and search is **part-number driven** (`ESP32`, `LM358`, `STM32F103`) — a well-defined retrieval problem rather than semantic guessing.

---

## 3. Architecture

```
┌─────────────────┐     ┌─────────────────┐
│  Consumer web   │     │ Supplier portal │   Next.js (one app,
│  (search/browse)│     │ (list/manage)   │   two route groups)
└────────┬────────┘     └────────┬────────┘
         └───────────┬───────────┘
                     ▼
              ┌─────────────┐        ┌──────────────────┐
              │  FastAPI    │◄──────►│  Search engine   │  Meilisearch/
              │  (API)      │        │  (AR-aware)      │  Typesense
              └──────┬──────┘        └──────────────────┘
                     │
              ┌──────▼──────┐
              │  Postgres   │  suppliers, listings, categories,
              └──────▲──────┘  units, ingestion_runs, review_queue
                     │
   ┌─────────────────┴──────────────────┐
   │      Ingestion subsystem            │  separate worker service
   │  scrapers → normalize (+LLM) → review queue
   │  scheduler: Arq                     │
   └─────────────────────────────────────┘
```

**Stack:** Next.js · FastAPI · Postgres · Meilisearch (or Typesense) · Arq workers (Redis-backed) · object storage for images.

### Repository structure

**Monorepo, three deployable services** (not microservices — just a frontend, an API, and a background worker). Monorepo ≠ monolith: each app ships as its own container, but they share one git history and `api`/`ingestion` share data contracts via `packages/schemas` so the writer and reader can't drift.

```
makhzan/
├── apps/
│   ├── web/          # Next.js — consumer + supplier portal (two route groups)
│   ├── api/          # FastAPI backend
│   └── ingestion/    # Arq worker — scrapers → normalize → review queue
├── packages/
│   └── schemas/      # shared Pydantic contracts
├── docs/
└── docker-compose.yml   # db, search, redis, api, ingestion (+ web later)
```

Polyglot repo (TS + Python), so no Nx/Turborepo — just a layout convention, per-app `pyproject.toml`/`package.json`, and root `docker-compose.yml` for local dev.

**Design rules**
- Ingestion is a **separate service**, not FastAPI request handlers.
- Every source sits behind a **swappable adapter**; turning a source off is a config change.
- Every listing carries `last_verified_at` + `confidence`; freshness is shown in the UI (stale data destroys trust).
- `Listing` (per-supplier atom) is kept distinct from a future canonical `Product`, but dedup is deferred.

---

## 4. Data model (minimal)

- **Supplier** — name, contact, location, `source_type` (scraped | manual | portal), verification status
- **Category** — self-referencing tree, bilingual labels
- **Listing** — title (ar/en), category, price, currency, `unit`, `part_number`, stock_signal, product_url, images, `supplier_id`, `source`, `last_verified_at`, `confidence`
- **IngestionRun** — per-source job log (ran when, counts, errors)
- **ReviewQueueItem** — low-confidence extractions a human confirms before going live

---

## 5. Search requirements

Electronics search is part-number + keyword driven, across three input modes:
1. **English tech terms / part numbers** — primary; part numbers need exact + prefix match, heavily weighted.
2. **Arabic** — with normalization (alef/hamza variants, ta-marbuta, tatweel).
3. **Franco / Arabizi** — aware of, not fully solved in V1.

Index carries per-listing EN + AR fields plus a separately-weighted exact-matchable `part_number`.

---

## 6. Phased roadmap

- **Phase 0 — Field research.** ✅ Done. Manually catalog 10–15 real Greater-Cairo electronics suppliers + their sites. This list becomes the scraper backlog and validates the data exists.
- **Phase 1 — Ingestion spine + schema.** ✅ Done. Postgres schema, first scraper (best-structured site), manual-entry admin, normalization pipeline, review queue. Target: a few hundred trustworthy listings. No public UI.
- **Phase 2 — Search + consumer frontend.** ✅ Done. Wire the search engine; build search/browse/filter/detail with EN/AR + RTL. First demoable product.
- **Phase 3 — Supplier portal.** ⬅️ Next. Self-serve listing management + "claim your shop" flow for scraped/manual suppliers.
- **Phase 4 — Freshness & scale.** Scheduled re-scrapes, staleness decay, more suppliers; begin cross-supplier canonicalization. *Partly pulled forward:* the daily re-scrape and cross-supplier canonicalization already exist; staleness decay does not.

---

## 7. Open questions / risks

- Franco-Arabic search handling — punt to a later phase, but keep index design open to it.
- Scraper fragility — supplier sites change; adapters must fail loud and isolated.
- Freshness SLA — how stale is "too stale" to show a price? Needs a decay policy in Phase 4.
- Supplier onboarding incentive — what makes a shop claim its listings in the portal?
