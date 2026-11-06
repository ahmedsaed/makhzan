"""Listing detail endpoint — the hand-off page to the supplier."""

from __future__ import annotations

import uuid

from app.deps import get_session
from fastapi import APIRouter, Depends, HTTPException
from makhzan_schemas.contracts import ListingRead
from makhzan_schemas.models import Listing
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(tags=["listings"])


@router.get("/listings/{listing_id}", response_model=ListingRead)
async def get_listing(
    listing_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Listing:
    listing = await session.get(
        Listing,
        listing_id,
        options=[selectinload(Listing.supplier), selectinload(Listing.category)],
    )
    if listing is None:
        raise HTTPException(status_code=404, detail="listing not found")
    return listing
