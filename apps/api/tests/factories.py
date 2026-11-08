"""Row builders for the API tests.

The API is read-only, so every test starts by putting rows in the database. These
keep that to one line and fill in the columns the endpoints do not care about.

Defaults are deliberately boring; anything a test asserts on should be passed
explicitly, so the assertion and the data that drives it sit next to each other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

from makhzan_schemas.enums import ListingStatus, SourceType, StockSignal
from makhzan_schemas.models import Category, Listing, Product, Supplier
from sqlalchemy.ext.asyncio import AsyncSession

_seq = count(1)

#: Fixed so ordering assertions are about the values under test, not "now".
BASE_TIME = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


async def make_supplier(
    session: AsyncSession,
    *,
    slug: str | None = None,
    name: str = "Shop A",
    name_ar: str | None = None,
    area: str | None = None,
    governorate: str | None = None,
    website_url: str | None = None,
    domain: str = "electronics",
) -> Supplier:
    supplier = Supplier(
        slug=slug or f"supplier-{next(_seq)}",
        name=name,
        name_ar=name_ar,
        area=area,
        governorate=governorate,
        website_url=website_url,
        domain=domain,
        source_type=SourceType.SCRAPED,
    )
    session.add(supplier)
    await session.commit()
    return supplier


async def make_category(
    session: AsyncSession,
    *,
    slug: str,
    domain: str = "electronics",
    name_en: str = "Category",
    name_ar: str | None = None,
    parent: Category | None = None,
    path: str | None = None,
    position: int = 0,
) -> Category:
    category = Category(
        domain=domain,
        slug=slug,
        name_en=name_en,
        name_ar=name_ar,
        parent_id=parent.id if parent else None,
        path=path or (f"{parent.path}/{slug}" if parent else f"/{slug}"),
        position=position,
    )
    session.add(category)
    await session.commit()
    return category


async def make_listing(
    session: AsyncSession,
    *,
    supplier: Supplier,
    category: Category | None = None,
    product: Product | None = None,
    title_en: str | None = "LM358 Op-Amp",
    title_ar: str | None = None,
    description_en: str | None = None,
    part_number: str | None = None,
    brand: str | None = None,
    price: str | float | None = "10.00",
    currency: str = "EGP",
    unit: str | None = None,
    stock_signal: StockSignal = StockSignal.IN_STOCK,
    status: ListingStatus = ListingStatus.ACTIVE,
    images: list[str] | None = None,
    attributes: dict | None = None,
    source_url: str | None = "https://example.test/p/1",
    last_verified_at: datetime = BASE_TIME,
) -> Listing:
    listing = Listing(
        supplier_id=supplier.id,
        category_id=category.id if category else None,
        product_id=product.id if product else None,
        source=supplier.slug,
        source_type=SourceType.SCRAPED,
        external_id=f"ext-{next(_seq)}",
        domain=category.domain if category else supplier.domain,
        source_url=source_url,
        title_en=title_en,
        title_ar=title_ar,
        description_en=description_en,
        part_number=part_number,
        brand=brand,
        price=None if price is None else Decimal(str(price)),
        currency=currency,
        unit=unit,
        stock_signal=stock_signal,
        status=status,
        images=images if images is not None else [],
        attributes=attributes if attributes is not None else {},
        last_verified_at=last_verified_at,
    )
    session.add(listing)
    await session.commit()
    return listing


async def make_product(
    session: AsyncSession,
    *,
    group_key: str | None = None,
    part_number: str | None = None,
    domain: str = "electronics",
    title_en: str | None = "LM358 Op-Amp",
    title_ar: str | None = None,
    brand: str | None = None,
    category: Category | None = None,
    image: str | None = None,
    supplier_name: str | None = None,
    offer_count: int = 1,
    supplier_count: int = 1,
    min_price: str | float | None = "10.00",
    max_price: str | float | None = "10.00",
    currency: str = "EGP",
    in_stock: bool = True,
    last_verified_at: datetime | None = BASE_TIME,
    content_changed_at: datetime = BASE_TIME,
) -> Product:
    product = Product(
        group_key=group_key or f"single:test:{next(_seq)}",
        part_number=part_number,
        domain=domain,
        title_en=title_en,
        title_ar=title_ar,
        brand=brand,
        category_id=category.id if category else None,
        image=image,
        supplier_name=supplier_name,
        offer_count=offer_count,
        supplier_count=supplier_count,
        min_price=None if min_price is None else Decimal(str(min_price)),
        max_price=None if max_price is None else Decimal(str(max_price)),
        currency=currency,
        in_stock=in_stock,
        last_verified_at=last_verified_at,
        content_changed_at=content_changed_at,
    )
    session.add(product)
    await session.commit()
    return product
