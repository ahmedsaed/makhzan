"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from makhzan_schemas.db import SessionLocal
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
