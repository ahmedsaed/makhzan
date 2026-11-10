"""`Product.image_supplier_id`: the shop a product's photo comes from.

Every photo on the site carries a badge naming its shop: the photo is hotlinked
from that shop's own site (decision 0003), so the badge credits it and tells a
buyer whose photo it is. The rebuild that picks the photo must record the shop
of the listing it was taken from, which is not always the representative's.
"""

from __future__ import annotations

import uuid

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType, StockSignal
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import Listing, Product, Supplier
from sqlalchemy import select, update


def _shop(slug: str) -> Supplier:
    return Supplier(id=uuid.uuid4(), slug=slug, name=slug.title(), source_type=SourceType.SCRAPED)


def _listing(shop: Supplier, price: int, images: list[str], **values) -> Listing:
    return Listing(
        id=uuid.uuid4(),
        supplier_id=shop.id,
        source=shop.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        title_en="SG90 Micro Servo 9g",
        part_number="SG90",
        price=price,
        stock_signal=StockSignal.IN_STOCK,
        images=images,
        attributes={},
        **values,
    )


async def _seed(*rows) -> None:
    async with SessionLocal() as session:
        session.add_all([r for r in rows if isinstance(r, Supplier)])
        await session.flush()
        session.add_all([r for r in rows if isinstance(r, Listing)])
        await session.commit()


async def _rebuild() -> Product:
    async with SessionLocal() as session:
        await rebuild_products(session)
    async with SessionLocal() as session:
        return (await session.execute(select(Product))).scalar_one()


async def _set(listing: Listing, **values) -> None:
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == listing.id).values(**values))
        await session.commit()


async def test_the_photo_is_credited_to_the_shop_whose_listing_it_came_from():
    shop_a, shop_b = _shop("shop-a"), _shop("shop-b")
    await _seed(
        shop_a,
        shop_b,
        _listing(shop_a, 80, ["https://shop-a.test/sg90.jpg"]),
        _listing(shop_b, 90, ["https://shop-b.test/sg90.jpg"]),
    )

    product = await _rebuild()

    assert product.image == "https://shop-a.test/sg90.jpg"
    assert product.image_supplier_id == shop_a.id


async def test_a_photo_from_a_dearer_shop_names_that_shop():
    """The cheapest offer has no photo, so the product shows another shop's:
    the badge must name the shop the photo is from, not the cheapest."""
    cheap, pictured = _shop("shop-a"), _shop("shop-b")
    await _seed(
        cheap,
        pictured,
        _listing(cheap, 60, []),
        _listing(pictured, 90, ["https://shop-b.test/sg90.jpg"]),
    )

    product = await _rebuild()

    assert product.image == "https://shop-b.test/sg90.jpg"
    assert product.image_supplier_id == pictured.id


async def test_the_credit_follows_the_photo_when_it_changes():
    shop_a, shop_b = _shop("shop-a"), _shop("shop-b")
    first = _listing(shop_a, 80, ["https://shop-a.test/sg90.jpg"])
    second = _listing(shop_b, 90, ["https://shop-b.test/sg90.jpg"])
    await _seed(shop_a, shop_b, first, second)
    assert (await _rebuild()).image_supplier_id == shop_a.id

    # Shop A drops it: its listing is archived, and shop B's photo takes over.
    await _set(first, status=ListingStatus.ARCHIVED)
    product = await _rebuild()

    assert product.image == "https://shop-b.test/sg90.jpg"
    assert product.image_supplier_id == shop_b.id


async def test_no_photo_no_credit():
    shop = _shop("shop-a")
    listing = _listing(shop, 80, ["https://shop-a.test/sg90.jpg"])
    await _seed(shop, listing)
    assert (await _rebuild()).image_supplier_id == shop.id

    await _set(listing, images=[])
    product = await _rebuild()

    assert product.image is None
    assert product.image_supplier_id is None
