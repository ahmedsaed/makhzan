"""makhzan shared data layer.

Imported by both apps/api (reads listings) and apps/ingestion (writes them)
so the two services can never drift on what a Listing / Supplier / Category is.

- enums     : shared enumerations (SourceType, StockSignal, ...)
- models    : SQLAlchemy ORM (the Postgres schema)
- contracts : Pydantic DTOs (ingestion payloads + API read models)
- db        : engine/session helpers
"""

from makhzan_schemas import contracts, db, enums, models

__all__ = ["contracts", "db", "enums", "models"]
