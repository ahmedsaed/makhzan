# packages/schemas

Shared data contracts used across services — the canonical shape of a `Listing`, `Supplier`, `Category`, ingestion payloads, etc.

The API and ingestion worker (both Python) share these as Pydantic models so the service that *writes* listings and the service that *reads* them can't drift. If/when the web app needs the same types, generate TypeScript definitions from here rather than hand-maintaining a copy.

_To be populated alongside the Postgres schema (next planning step)._
