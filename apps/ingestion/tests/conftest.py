"""Test fixtures for the ingestion worker.

Tests run against a real Postgres because the schema leans on Postgres-specific
types (JSONB, UUID); SQLite would not exercise the same code. The database is
created for each test session and dropped at its end, so it is never the dev
database or another session's — DATABASE_URL is forced here, before makhzan_schemas is imported, because db.py builds its engine at
import time and would otherwise bind to whatever the developer has exported.
"""

from __future__ import annotations

import os
import re

_BASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://makhzan:makhzan@localhost:5432/makhzan_test",
)
# One database per test session, created at its start and dropped at its end.
# A fixed name was shared by every run at once (two worktrees, two agents), and
# each one's schema reset and truncation landed mid-test in the other's:
# StaleDataError, "cache lookup failed for type", a branch's extra tables
# breaking another's drop_all. The suffix is the process id unless
# TEST_DB_SUFFIX names one; either way the name always carries it, so this can
# never be the dev database, whatever TEST_DATABASE_URL says.
_SUFFIX = re.sub(r"[^a-z0-9_]", "_", os.environ.get("TEST_DB_SUFFIX", f"p{os.getpid()}").lower())
_PREFIX, _, _BASE_NAME = _BASE_URL.rpartition("/")
TEST_DATABASE_NAME = f"{_BASE_NAME}_{_SUFFIX}"[:63]
TEST_DATABASE_URL = f"{_PREFIX}/{TEST_DATABASE_NAME}"
_dev_name = os.environ.get("DATABASE_URL", "").rpartition("/")[2]
assert TEST_DATABASE_NAME != _dev_name, "refusing to run the tests against DATABASE_URL"
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


async def _admin(statement: str) -> None:
    """Run one statement against the server's `postgres` database."""
    dsn = _PREFIX.replace("postgresql+asyncpg://", "postgresql://") + "/postgres"
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(statement)
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema():
    """This session's own database, built from the ORM metadata and dropped after.

    Fresh every time, so a model change is always picked up and nothing another
    session (or another branch's schema) left behind can be in it. Dropped
    even if a test failed; a session killed outright leaves its database
    behind, which the next session with the same suffix replaces.
    """
    await _admin(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}" WITH (FORCE)')
    await _admin(f'CREATE DATABASE "{TEST_DATABASE_NAME}"')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
    finally:
        await engine.dispose()
        await _admin(f'DROP DATABASE IF EXISTS "{TEST_DATABASE_NAME}" WITH (FORCE)')


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
    monkeypatch.setattr(http_mod, "_SLOWDOWN", {})


@pytest.fixture
def session_factory():
    return SessionLocal
