"""Migration a9a0252aacef downgrades with flags the old index could not hold.

Runs alembic itself (in a subprocess, so its env.py reads its own
DATABASE_URL) against a scratch database of its own, created and dropped
here: never this session's test database, which the ORM built directly.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg

# The conftest has forced DATABASE_URL to this session's own test database.
_PREFIX, _, TEST_DATABASE_NAME = os.environ["DATABASE_URL"].rpartition("/")


async def _admin(statement: str) -> None:
    dsn = _PREFIX.replace("postgresql+asyncpg://", "postgresql://") + "/postgres"
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(statement)
    finally:
        await conn.close()


SCHEMAS = Path(__file__).resolve().parents[3] / "packages" / "schemas"
BEFORE, AFTER = "895dafa67c0d", "a9a0252aacef"


def _alembic(url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(SCHEMAS / "alembic.ini"), *args],
        cwd=SCHEMAS,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


async def test_the_downgrade_closes_flags_the_old_unique_index_cannot_hold():
    name = f"{TEST_DATABASE_NAME}_mig"[:63]
    url = f"{_PREFIX}/{name}"
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    await _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await _admin(f'CREATE DATABASE "{name}"')
    try:
        await asyncio.to_thread(_alembic, url, "upgrade", AFTER)
        conn = await asyncpg.connect(dsn)
        try:
            for subject in ("w1/kev", "w2/kev", "w1/pplx"):
                await conn.execute(
                    "INSERT INTO ai_flags (kind, subject, detail, status) "
                    "VALUES ('version_drift', $1, '{}', 'open')",
                    subject,
                )
        finally:
            await conn.close()

        await asyncio.to_thread(_alembic, url, "downgrade", BEFORE)

        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch("SELECT kind, status FROM ai_flags ORDER BY id")
        finally:
            await conn.close()
        assert [tuple(r) for r in rows] == [
            ("version_drift", "open"),
            ("version_drift", "dismissed"),
            ("version_drift", "dismissed"),
        ]
        await asyncio.to_thread(_alembic, url, "upgrade", AFTER)  # and back
    finally:
        await _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
