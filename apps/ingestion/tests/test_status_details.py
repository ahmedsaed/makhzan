"""`make status` PRODUCT DETAILS covers every shop, not only the page readers.

A shop whose list feed carries the description, specs and photos needs no
product pages, but its content still has to be watched: a feed that stops
carrying descriptions would otherwise go unnoticed.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType
from makhzan_schemas.models import Listing, Supplier
from worker.sources import registry
from worker.sources.base import DetailsSettings, SourceAdapter, SupplierInfo


def _status():
    path = Path(__file__).resolve().parents[3] / "scripts" / "status.py"
    spec = importlib.util.spec_from_file_location("makhzan_status", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeedShop(SourceAdapter):
    source_type = SourceType.SCRAPED

    def partitions(self):
        return [""]

    async def fetch_page(self, partition, page):
        raise NotImplementedError


class PageShop(FeedShop):
    token_kind = "modified"

    async def fetch_details(self, listing, fetcher):
        return {}


def _adapter(cls, source_id, **kw):
    adapter = cls.__new__(cls)
    adapter.source_id = source_id
    adapter.supplier = SupplierInfo(slug=source_id, name=source_id)
    adapter.enabled = True
    for key, value in kw.items():
        setattr(adapter, key, value)
    return adapter


async def _listings(source_id: str, rows: list[dict]) -> None:
    supplier = Supplier(
        id=uuid.uuid4(), slug=source_id, name=source_id, source_type=SourceType.SCRAPED
    )
    async with SessionLocal() as session:
        session.add(supplier)
        await session.flush()
        for i, row in enumerate(rows):
            session.add(
                Listing(
                    id=uuid.uuid4(),
                    supplier_id=supplier.id,
                    source=source_id,
                    source_type=SourceType.SCRAPED,
                    external_id=str(i),
                    title_en=f"Item {i}",
                    status=row.get("status", ListingStatus.ACTIVE),
                    description_en=row.get("description"),
                    images=row.get("images", []),
                    attributes=row.get("attributes", {}),
                )
            )
        await session.commit()


async def test_every_shop_gets_a_content_line_and_page_readers_their_queue(capsys):
    status = _status()
    await _listings(
        "feed-shop",
        [
            {
                "description": "A 5 V relay",
                "images": ["a", "b"],
                "attributes": {"specs": {"Coil": "5 V"}, "documents": [{"url": "d"}]},
            },
            {"description": "", "images": ["a"]},
            # Archived listings are not what the site shows.
            {"description": "gone", "status": ListingStatus.ARCHIVED},
        ],
    )
    await _listings("page-shop", [{"description": "card text"}])

    registry._REGISTRY.clear()
    try:
        registry.register(_adapter(FeedShop, "feed-shop"))
        registry.register(
            _adapter(
                PageShop,
                "page-shop",
                details=DetailsSettings(enabled=True, per_run=20, max_age_days=90),
            )
        )
        registry.register(_adapter(PageShop, "unconfigured-shop"))
        async with SessionLocal() as session:
            await status.product_details(session, None)
    finally:
        registry._REGISTRY.clear()

    out = capsys.readouterr().out
    feed = out[out.index("feed-shop") : out.index("page-shop")]
    assert "list feed only" in feed
    assert "2 active" in feed
    assert "description  50%" in feed and "specs  50%" in feed
    assert "2+ photos  50%" in feed and "documents  50%" in feed
    assert "due:" not in feed, "a list-feed shop has no page queue"

    page = out[out.index("page-shop") : out.index("unconfigured-shop")]
    assert "product pages on" in page and "20 a run" in page
    assert "never fetched 1" in page

    unconfigured = out[out.index("unconfigured-shop") :]
    assert "not configured" in unconfigured
    assert "no active listings" in unconfigured
