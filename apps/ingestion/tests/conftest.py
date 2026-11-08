"""Test fixtures for the ingestion worker.

Tests run against a real Postgres because the schema leans on Postgres-specific
types (JSONB, UUID); SQLite would not exercise the same code. The database is
created on demand and is separate from the dev database — DATABASE_URL is forced
here, before makhzan_schemas is imported, because db.py builds its engine at
import time and would otherwise bind to whatever the developer has exported.
"""

from __future__ import annotations

import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan_test",
)
# Must happen before any makhzan_schemas import. Assignment, not setdefault: a
# developer with DATABASE_URL pointed at their dev database must not have these
# tests truncate it.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from makhzan_schemas.db import SessionLocal, engine  # noqa: E402
from makhzan_schemas.models import Base  # noqa: E402
from sqlalchemy import text  # noqa: E402


async def _ensure_database() -> None:
    """CREATE DATABASE if the test database does not exist yet."""
    dsn = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    target = dsn.rsplit("/", 1)[-1]
    admin_dsn = dsn.rsplit("/", 1)[0] + "/postgres"
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", target)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{target}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema():
    """Rebuild the schema once per session, from the ORM metadata.

    Dropped first so a model change is picked up: create_all leaves existing
    tables alone, which would silently test against a stale schema. The test
    database is disposable, so this is safe.
    """
    await _ensure_database()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(_schema):
    """Truncate every table between tests so cases cannot leak into each other."""
    tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    async with SessionLocal() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
    yield


@pytest.fixture(autouse=True)
def _fresh_host_gate(monkeypatch):
    """The per-host pace gate is process-wide state: no test inherits another's."""
    from worker import http as http_mod

    monkeypatch.setattr(http_mod, "_HOST_PACE", {})
    monkeypatch.setattr(http_mod, "_LAST_SENT", {})
    monkeypatch.setattr(http_mod, "_TURN_LOCKS", {})


@pytest.fixture
def session_factory():
    return SessionLocal
