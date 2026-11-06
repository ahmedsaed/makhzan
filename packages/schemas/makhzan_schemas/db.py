"""Async engine/session helpers shared by api and ingestion.

Reads DATABASE_URL from the environment (see .env.example). For dev you can
create the schema with `await init_models()`; real migrations use Alembic
(added in the next step — the ORM in models.py is the source of truth).
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from makhzan_schemas.models import Base

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan"
)

engine: AsyncEngine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """Create all tables. Dev convenience only — use Alembic in real environments."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
