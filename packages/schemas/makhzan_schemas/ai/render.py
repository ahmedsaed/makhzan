"""What a judge would be sent now, from the current rows.

The broker renders at lease time and checks freshness by request hash; the
triggers render to settle pairs whose requests are already scored; the
decision writer takes the listings' content hashes at decision time. All of
them read a listing the same way, here: `prompt.record(prompt.listing_row(...))`
with the category's English name, and `hashing.listing_hash` over the same.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.ai.hashing import listing_hash
from makhzan_schemas.ai.pipelines import Stage
from makhzan_schemas.ai.prompt import listing_row, record, request_sha256, requests
from makhzan_schemas.models import Category, Listing


@dataclass(frozen=True)
class Shown:
    """One listing as a judge would see it now."""

    listing: Listing
    record: dict
    content_sha256: bytes


def shown(listing: Listing, category: str | None) -> Shown:
    return Shown(listing, record(listing_row(listing, category)), listing_hash(listing, category))


async def load_shown(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Shown]:
    """The listings `ids` as a judge would see them; a missing id is left out."""
    wanted = list(set(ids))
    out: dict[uuid.UUID, Shown] = {}
    for start in range(0, len(wanted), 5000):
        rows = await session.execute(
            select(Listing, Category.name_en)
            .outerjoin(Category, Category.id == Listing.category_id)
            .where(Listing.id.in_(wanted[start : start + 5000]))
        )
        for listing, category in rows:
            out[listing.id] = shown(listing, category)
    return out


@dataclass(frozen=True)
class Rendered:
    """One stage's two reading orders of one pair: payload and request hash."""

    payloads: dict[str, dict]
    sha256: dict[str, bytes]

    def hex(self) -> dict[str, str]:
        return {order: digest.hex() for order, digest in self.sha256.items()}


def render(stage: Stage, a: Shown, b: Shown) -> Rendered:
    """`stage`'s requests for the pair (a, b), "ab" showing `a` as LISTING A."""
    payloads = requests(stage.prompt, a.record, b.record)
    return Rendered(payloads, {order: request_sha256(p) for order, p in payloads.items()})
