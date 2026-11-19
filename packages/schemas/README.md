# packages/schemas

`makhzan_schemas`, the code the API and the ingestion worker share, installed in
each as a path dependency (develop mode), so the service that *writes* listings
and the service that *reads* them can't drift:

- `models.py` — the SQLAlchemy models; `migrations/` — Alembic (autogenerate,
  then read the generated file before committing)
- `contracts.py` — Pydantic contracts: the ingestion DTOs (`RawItem` ->
  `NormalizedListing`) and the API's read models
- `domains/` — one `DomainProfile` per department (taxonomy, keyword rules,
  identifier rules, form markers); crosswalks are in the private configuration
- `grouping.py`, `rebuild.py`, `identifiers.py`, `values.py`, `overrides.py` —
  how listings become products, and the rulings that override it
- `search.py` — the search contract: one Meilisearch document per listed
  product, carrying every active listing's titles, brands and part numbers
  (`member_*` fields), rebuilt whole by the worker's `indexer.reindex_all`, never updated
  incrementally
- `ai/` — AI matching: the broker's logic, pipelines, policy, prompts, decisions
- `crawl.py`, `botauth.py`, `contact.py`, `freshness.py`, `reports.py` — crawl
  settings and pacing stats, Web Bot Auth, contact merging, freshness, reports

The web app does not import these; it has its own types in `apps/web/lib/api.ts`.
