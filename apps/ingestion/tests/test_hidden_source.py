"""A source with `listed = false`: crawled and stored, shown nowhere public.

The regroup is the one door to products and the search index, so a hidden
source's listings are kept out there: they make, join and change no product.
Hidden later, they leave their products the way archived listings do (the
product is emptied if nothing else offers it, never deleted); listed again,
the next regroup brings them back, reviving the same product ids.
"""

from __future__ import annotations

import textwrap
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from makhzan_schemas.ai import candidates as producers
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, ProductEventKind, SourceType
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import (
    AiListingState,
    Listing,
    Product,
    ProductEvent,
    Source,
    SourceCursor,
    Supplier,
)
from sqlalchemy import select, update
from test_indexer import FakeClient
from worker import status
from worker.indexer import reindex_all
from worker.sources.sync import read_sources, sync_sources


async def _shop(slug: str, *, listed: bool = True) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    source = Source(
        source_id=slug,
        adapter="woocommerce",
        base_url=f"https://{slug}.test",
        listed=listed,
        supplier={"slug": slug, "name": slug},
        config={},
    )
    async with SessionLocal() as session:
        session.add_all([supplier, source])
        await session.commit()
    return supplier


async def _listing(shop: Supplier, title: str, part_number: str | None = "SG90") -> uuid.UUID:
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=shop.id,
        source=shop.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        domain="electronics",
        title_en=title,
        part_number=part_number,
        price=Decimal("100"),
        images=[],
        attributes={},
        first_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    async with SessionLocal() as session:
        session.add(listing)
        await session.commit()
    return listing.id


async def _set_listed(slug: str, listed: bool) -> None:
    async with SessionLocal() as session:
        await session.execute(update(Source).where(Source.source_id == slug).values(listed=listed))
        await session.commit()


async def _rebuild() -> dict:
    async with SessionLocal() as session:
        stats = await rebuild_products(session)
        await session.commit()
        return stats


async def _product_of(listing_id: uuid.UUID) -> uuid.UUID | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Listing.product_id).where(Listing.id == listing_id))


async def _product(product_id: uuid.UUID) -> Product:
    async with SessionLocal() as session:
        return await session.get(Product, product_id)


async def _indexed() -> list[dict]:
    client = FakeClient()
    async with SessionLocal() as session:
        await reindex_all(session, client)
    return client.products.documents


# --------------------------------------------------------------------------- #
# sources.toml
# --------------------------------------------------------------------------- #


def _file(tmp_path, extra: str):
    path = tmp_path / "sources.toml"
    path.write_text(
        textwrap.dedent(
            f"""
            [[source]]
            id = "shop-a"
            adapter = "woocommerce"
            base_url = "https://shop-a.test"
            {extra}
            supplier = {{ slug = "shop-a", name = "Shop A" }}
            """
        ),
        encoding="utf-8",
    )
    return path


def test_listed_is_a_column_and_defaults_to_true(tmp_path):
    (row,) = read_sources(_file(tmp_path, ""))
    assert row.listed is True
    (row,) = read_sources(_file(tmp_path, "listed = false"))
    assert row.listed is False
    # A column, so never passed to the adapter as a setting.
    assert "listed" not in row.config


def test_listed_must_be_a_boolean(tmp_path):
    with pytest.raises(ValueError, match="listed must be true or false"):
        read_sources(_file(tmp_path, 'listed = "no"'))


async def test_the_sync_writes_listed_both_ways(tmp_path):
    async with SessionLocal() as session:
        await sync_sources(session, read_sources(_file(tmp_path, "listed = false")))
    async with SessionLocal() as session:
        assert await session.scalar(select(Source.listed)) is False
    # Removing the key lists it again: the file is the only writer.
    async with SessionLocal() as session:
        report = await sync_sources(session, read_sources(_file(tmp_path, "")))
    assert report["updated"] == ["shop-a"]
    async with SessionLocal() as session:
        assert await session.scalar(select(Source.listed)) is True


# --------------------------------------------------------------------------- #
# Products and search
# --------------------------------------------------------------------------- #


async def test_a_hidden_listing_makes_no_product_and_is_not_indexed():
    shown, hidden = await _shop("shop-a"), await _shop("shop-b", listed=False)
    a = await _listing(shown, "SG90 Micro Servo")
    b = await _listing(hidden, "SG90 Micro Servo")
    only_hidden = await _listing(hidden, "MG996R Servo", part_number="MG996R")

    stats = await _rebuild()

    assert stats["products"] == 1
    assert await _product_of(b) is None and await _product_of(only_hidden) is None
    product = await _product(await _product_of(a))
    assert (product.offer_count, product.supplier_count) == (1, 1)
    docs = await _indexed()
    assert [d["supplier_slugs"] for d in docs] == [["shop-a"]]


async def test_hiding_a_source_empties_its_products_and_listing_it_again_revives_them():
    shown, hidden = await _shop("shop-a"), await _shop("shop-b")
    a = await _listing(shown, "SG90 Micro Servo")
    b = await _listing(hidden, "SG90 Micro Servo")
    alone = await _listing(hidden, "MG996R Servo", part_number="MG996R")
    await _rebuild()
    shared, own = await _product_of(a), await _product_of(alone)
    assert await _product_of(b) == shared
    assert (await _product(shared)).supplier_count == 2

    # true -> false: they leave their products as archived listings do.
    await _set_listed("shop-b", False)
    stats = await _rebuild()
    assert stats["emptied"] == 1
    kept = await _product(shared)
    assert (kept.supplier_count, kept.delisted_at) == (1, None)
    gone = await _product(own)
    assert gone is not None and gone.delisted_at is not None
    async with SessionLocal() as session:
        kinds = list(
            await session.scalars(select(ProductEvent.kind).where(ProductEvent.product_id == own))
        )
    assert kinds == [ProductEventKind.EMPTIED]
    # The pointer stays, as an archived listing's does: the way back.
    assert await _product_of(alone) == own
    assert {d["id"] for d in await _indexed()} == {str(shared)}

    # false -> true: the same ids, grouped normally.
    await _set_listed("shop-b", True)
    stats = await _rebuild()
    assert stats["revived"] == 1 and stats["created"] == 0
    assert await _product_of(b) == shared and await _product_of(alone) == own
    assert (await _product(own)).delisted_at is None
    assert (await _product(shared)).supplier_count == 2
    assert {d["id"] for d in await _indexed()} == {str(shared), str(own)}


# --------------------------------------------------------------------------- #
# AI matching
# --------------------------------------------------------------------------- #


async def test_the_ai_producers_skip_a_hidden_source():
    shown, hidden = await _shop("shop-a"), await _shop("shop-b", listed=False)
    a = await _listing(shown, "carbon film resistor 10k ohm", part_number=None)
    await _listing(hidden, "carbon film resistor 10k ohm quarter watt", part_number=None)
    async with SessionLocal() as session:
        catalogue = await producers.load_catalogue(session)
        assert [x.id for x in catalogue.listings] == [a]
        await producers.daily(session)  # baseline
        result = await producers.backlog(session)
        await session.commit()
        assert result["queued"] == 0
        assert list(await session.scalars(select(AiListingState.listing_id))) == [a]


# --------------------------------------------------------------------------- #
# make status / the admin dashboard
# --------------------------------------------------------------------------- #


async def test_status_says_a_source_is_hidden():
    shown, hidden = await _shop("shop-a"), await _shop("shop-b", listed=False)
    await _listing(shown, "SG90 Micro Servo")
    await _listing(hidden, "SG90 Micro Servo")
    async with SessionLocal() as session:
        session.add_all(
            [SourceCursor(source=s, partition_key="", next_page=1) for s in ("shop-a", "shop-b")]
        )
        await session.commit()
        progress = await status.collect_sweep_progress(session, None)
        catalog = await status.collect_catalog(session, None)
    assert {e["source"]: e["hidden"] for e in progress["sources"]} == {
        "shop-a": False,
        "shop-b": True,
    }
    assert {r["shop"]: r["hidden"] for r in catalog} == {"shop-a": 0, "shop-b": 1}


async def test_an_archived_listing_of_a_hidden_source_stays_out_too():
    hidden = await _shop("shop-b", listed=False)
    b = await _listing(hidden, "SG90 Micro Servo")
    async with SessionLocal() as session:
        await session.execute(
            update(Listing).where(Listing.id == b).values(status=ListingStatus.ARCHIVED)
        )
        await session.commit()
    assert (await _rebuild())["products"] == 0
