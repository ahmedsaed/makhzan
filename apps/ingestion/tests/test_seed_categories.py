"""Seeding the taxonomy is safe when every source's run starts at once."""

from __future__ import annotations

import asyncio

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.domains import PROFILES
from makhzan_schemas.models import Category
from sqlalchemy import delete, func, select

from worker.categorize import seed_categories


async def test_runs_starting_together_on_an_empty_taxonomy_all_seed():
    """The daily jobs start together. Seeding inside each run's transaction made
    every run but one fail on the unique key when the taxonomy was new to the
    database (found running the per-source jobs against a real Redis)."""
    async with SessionLocal() as session:
        await session.execute(delete(Category))
        await session.commit()

    async def run() -> int:
        async with SessionLocal() as session:
            index = await seed_categories(session)
            # Open, as a run's transaction is while it fetches its first page.
            await asyncio.sleep(0.05)
            await session.commit()
            return len(index)

    sizes = await asyncio.gather(*(run() for _ in range(4)))

    expected = sum(len(p.taxonomy) for p in PROFILES.values())
    assert sizes == [expected] * 4
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(Category)) == expected
