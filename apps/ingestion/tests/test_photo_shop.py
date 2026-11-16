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


async def test_the_representative_listing_is_recorded_with_the_title_it_gave():
    """The product page picks the representative on a plain load, so its h1
    and <title> are one listing's (owner decision, November 2026). The cheapest
    in-stock offer has no photo, so the representative is the dearer one."""
    cheap, pictured = _shop("shop-a"), _shop("shop-b")
    other = _listing(cheap, 60, [])
    other.title_en = "SG90 Servo, A"
    rep = _listing(pictured, 90, ["https://shop-b.test/sg90.jpg"])
    rep.title_en = "SG90 Servo, B"
    await _seed(cheap, pictured, other, rep)

    product = await _rebuild()

    assert product.representative_listing_id == rep.id
    assert product.title_en == "SG90 Servo, B"


async def test_an_in_stock_listing_outranks_an_out_of_stock_one_with_the_only_photo():
    """Owner decision (November 2026): stock first, then photo. The only listing
    with a photo is out of stock, so the in-stock one gives the product its
    title (and is the plain load's pick); the photo still comes from the
    listing that has one."""
    gone_shop, stocked_shop = _shop("shop-a"), _shop("shop-b")
    gone = _listing(gone_shop, 80, ["https://shop-a.test/sg90.jpg"])
    gone.title_en = "SG90 Servo, A"
    gone.stock_signal = StockSignal.OUT_OF_STOCK
    stocked = _listing(stocked_shop, 95, [])
    stocked.title_en = "SG90 Servo, B"
    await _seed(gone_shop, stocked_shop, gone, stocked)

    product = await _rebuild()

    assert product.representative_listing_id == stocked.id
    assert product.title_en == "SG90 Servo, B"
    assert product.image == "https://shop-a.test/sg90.jpg"
    assert product.image_supplier_id == gone_shop.id
