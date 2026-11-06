# Domain Generalization Refactor

**Status:** proposed · **Owner:** TBD · **Created:** 2026-07-14 · **Amended:** 2026-08-24

## Goal

Make makhzan a **multi-vertical** aggregator (electronics *and* wood, metals, plumbing, …)
without drifting into an electronics-only product. Today the spine is already
domain-agnostic; the electronics assumptions are concentrated in a handful of
enrichment modules and some UI copy. This plan turns those into **pluggable,
per-domain strategies** and makes suppliers **data-driven** instead of hardcoded.

## Current state (audit)

**Already domain-agnostic — no change needed:**

- Schema (`Listing`, `Product`): generic `title/description/brand/price/currency/unit/images/attributes(JSONB)/category`. `part_number` is just "identifier"; `unit` (piece/meter/sheet) already fits non-electronics. `attributes` JSONB is the escape hatch for domain-specific specs.
- Adapter layer (`SourceAdapter` ABC, registry, `SupplierInfo`): zero domain knowledge. A wood shop on WooCommerce ingests through the existing adapter unchanged.
- Pipeline, search infra (Meilisearch), API routers, UI shell (routing, i18n mechanism, RTL, cards).

**Electronics coupling (what this refactor targets):**

| Concern | File | Coupling |
|---|---|---|
| Category tree + keyword rules | `packages/schemas/makhzan_schemas/taxonomy.py` | 100% electronics |
| Identifier extraction | `packages/schemas/makhzan_schemas/part_number.py` | ~52 component-family regexes |
| Cross-supplier dedup | `packages/schemas/makhzan_schemas/grouping.py` | MPN-centric `base_key`; `_AMBIGUOUS`/`_NOISE` electronics tokens |
| Search ranking | `packages/schemas/makhzan_schemas/search.py` | `part_number` weighted first |
| Normalize wiring | `apps/ingestion/worker/normalize.py` | hardcodes `extract_part_number()` per item |
| UI copy | page copy in `apps/web/app/` (English only since the November 2026 redesign) | examples such as "ESP32" in the search placeholder |
| Supplier list | `apps/ingestion/worker/sources/*.py` | hardcoded `register(...)` calls |

**Core gap:** there is no first-class notion of a **domain/vertical**. Category is a
single global tree; search, taxonomy, and the homepage assume one universe.

## Target architecture

Introduce a **`Domain`** dimension and a **`DomainProfile`** strategy object that
bundles the per-vertical logic behind one interface. Electronics becomes the
*first* profile, not *the* logic.

```
DomainProfile (per vertical)
├── slug, name_en, name_ar
├── taxonomy: list[TaxonomyNode]          # the category tree for this domain
├── category_rules: list[CategoryRule]    # keyword → leaf resolver rules
├── extract_identifier(title) -> str|None # electronics: MPN; wood: dimension/spec key; None ok
├── grouping_key(listing) -> str          # how "same product across suppliers" is defined
├── ambiguous / noise token sets          # sub-clustering tuning (optional)
├── search_field_weights                  # ranked SEARCHABLE attributes
└── ui: { search_placeholder, hero_hint, category_emoji, identifier_label }
```

A `PROFILES: dict[str, DomainProfile]` registry maps `domain_slug -> profile`.

> **Amendment (2026-08-24).** An earlier draft had *every supplier declares its
> domain*, with listings inheriting it. That does not hold. The first
> non-electronics supplier we surveyed — is an industrial marketplace spanning
> ~17 top-level groups (tools, PPE, chemicals, piping, automotive **and**
> electronic components). One supplier, many domains, overlapping our existing
> one.
>
> So **domain is resolved per listing**, from its category, with `supplier.domain`
> serving only as a default for single-vertical shops. Phase 1 must put the
> authoritative `domain` on `Category` (and denormalize onto `Listing`/`Product`),
> not on `Supplier` alone — getting this wrong means redoing the migration.

Enrichment and search select the profile by the item's domain.

### Category source: authoritative vs inferred

A second distinction the original draft missed. `resolve_category_slug` infers a
category from keywords because Shopify/WooCommerce category strings are messy.
Some sources are not messy: a marketplace browsed *by category*, so every product's
category is known exactly, and inference would only add error.

A profile (or better, a source) should therefore declare whether its categories
are **authoritative** — mapped through a `source_category -> leaf` crosswalk held
as data — or **inferred** via keyword rules. Crosswalks are deterministic,
auditable, and fail visibly (unmapped → uncategorized) instead of silently
mis-filing. Running the electronics keyword rules over industrial goods actively
corrupts the existing taxonomy: `"socket"` matches socket wrenches into
*Connectors & Sockets*, `"transformer"` matches transformer oil into *Inductors*.

## Phases

### Phase 1 — `domain` field + `DomainProfile` seam (no behavior change) ✅ SHIPPED 2026-08-24

The unblocking step. Electronics is extracted verbatim into a profile; output is
byte-for-byte identical, proven by re-running ingestion + grouping.

1. **Schema:** add `Domain` table (`slug`, `name_en`, `name_ar`) or a `domain` enum
   column on `Supplier` (start with a column; promote to table if it grows).
   Add `domain` (denormalized) to `Listing` and `Product` for cheap filtering.
   One Alembic migration; backfill all existing rows to `"electronics"`.
2. **Profile interface:** new `packages/schemas/makhzan_schemas/domains/` package:
   - `base.py` — `DomainProfile` dataclass/protocol + `PROFILES` registry.
   - `electronics.py` — move `TAXONOMY`, `CATEGORY_RULES`, and wire
     `extract_identifier = extract_part_number`, `grouping_key` = current MPN logic,
     `_AMBIGUOUS`/`_NOISE`, search weights, UI strings.
3. **Rewire call sites to go through the profile:**
   - `normalize.py`: `profile.extract_identifier(title)` instead of `extract_part_number`.
   - `grouping.py`: `profile.grouping_key(listing)` / profile-supplied ambiguous+noise sets.
   - `taxonomy` seeding + `resolve_category_slug`: per-domain taxonomy & rules.
   - `search.py`: `build_product_document` adds `domain`; SEARCHABLE from profile.
   - `categorize.py` seeds each domain's taxonomy (namespaced category slugs, e.g. keep global slugs but tag with domain, or prefix).
4. **Category slug collision:** category slugs must be unique per (domain, slug).
   Either prefix (`electronics/dev-boards`) or add `domain` to the Category unique key.
5. **Verify:** re-ingest, rebuild_products, reindex → identical product count,
   multi-supplier count, and category coverage as before.

**Deliverable:** electronics runs exactly as today, but every domain-specific
decision now flows through a profile keyed by `supplier.domain`.

### Phase 2 — Data-driven suppliers

> **Done (2026-10-24)**, items 1 and 2. The `sources` table holds `supplier` as
> JSONB (the SupplierInfo fields) rather than as columns, so the Supplier table
> stays the one place supplier data is edited. Rows are seeded from
> `sources.toml` in the private configuration (`make sources`); item 3, an admin path, is still open.

Kill the hardcoded `register()` calls; new suppliers/domains need no redeploy.

> Also the prerequisite for open-sourcing, which adds one requirement to this
> phase: the `Source` table is populated from a seed file living outside the
> repository, so the supplier list can stay private.

1. **`Source` config table:** `(id, source_id, adapter_type, base_url, supplier_slug,
   supplier_name, domain, enabled, config JSONB)`. `adapter_type` ∈ {woocommerce,
   shopify, odoo, …}.
2. **Adapter factory:** `build_adapter(row) -> SourceAdapter` maps `adapter_type` +
   `config` to the concrete adapter. Registry loads from DB instead of module imports.
3. **Admin path:** a minimal internal endpoint / seed script / (later) portal form to
   add a `Source`. Feeds directly into Phase 3 ("claim your shop").
4. Keep the fixture adapter and a code-defined fallback for tests.

### Phase 3 — Prove it with a second domain (wood)

1. Author `domains/wood.py`: wood taxonomy (lumber, sheet goods, mouldings,
   hardware, finishes, …), keyword rules (Arabic + English), and an
   `extract_identifier` that keys on **species + dimensions + grade** rather than MPN
   (e.g. `pine-2x4-2.4m`). Expect weaker cross-supplier dedup — that's inherent to
   the domain; most wood listings become singletons, which is fine.
2. Onboard 1–2 real wood suppliers via the Phase-2 `Source` table.
3. Tune the grouping key with real data.

### Phase 4 — Domain-aware UI

1. Domain switcher (or domain-scoped landing routes, e.g. `/electronics`, `/wood`).
2. Move `search_placeholder`, hero hint, category emoji, and identifier label into
   the profile; the web app reads them per active domain (new API field or endpoint).
3. Search + category browse scoped to the active domain by default.

## Effort & risk

- **Code effort:** modest — roughly Phase 1 (1 PR, mechanical extraction + 1 migration),
  Phase 2 (1 PR), Phase 4 (1 PR). Seams are few because the spine is sound.
- **Real recurring cost is domain knowledge, not code:** each new vertical needs a
  hand-authored taxonomy, matching rules, and an identifier/spec parser. That's the
  bulk of the work per domain and can't be abstracted away.
- **Risks:**
  - Category slug collisions across domains → handled by domain-scoping the slug (Phase 1.4).
  - Grouping semantics differ per domain → the `grouping_key` strategy isolates this; wood simply groups less.
  - Search relevance differs per domain → per-profile field weights; may need per-domain Meilisearch index settings if ranking rules diverge sharply (revisit in Phase 3).

## Non-goals

- LLM-based extraction/categorization (still deferred; profiles make it easy to slot in per-domain later).
- Reworking the schema's core entities (they already generalize).
- Multi-currency/geography (orthogonal to domain; separate concern).

## Sequencing

**1 → 2 → 3 → 4.** Phase 1 is the keystone and safe (no behavior change). Ship it
first even if the others wait.
