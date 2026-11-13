"""A product's price range and what is said about its low end.

The approved product-page rules (makhzan_schemas.pricing): offers compared by
the price of one; an offer's cheapest in-stock option counts and is named; on
request never enters the range but is counted; out of date counts nowhere
while anything is fresh; and the stock tiers of the shipped web page
(apps/web/lib/product.ts): in stock (low stock included), else not known to be
gone, else all. The card, the price sort and filter, and the page's headline all read
the result, so it is pinned here once, then through the rebuild and into the
search document.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from makhzan_schemas.contracts import ProductSummary
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType, StockSignal
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import Listing, Product, Supplier
from makhzan_schemas.pricing import summarize_prices, unit_price
from makhzan_schemas.search import build_product_document
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

NOW = datetime(2026, 11, 13, tzinfo=UTC)
FRESH = NOW - timedelta(days=2)
STALE = NOW - timedelta(days=81)
IN, OUT = StockSignal.IN_STOCK, StockSignal.OUT_OF_STOCK
LOW, UNKNOWN, MTO = StockSignal.LOW_STOCK, StockSignal.UNKNOWN, StockSignal.MADE_TO_ORDER


@dataclass
class Offer:
    price: Decimal | None
    stock_signal: StockSignal = IN
    last_verified_at: datetime | None = FRESH
    attributes: dict = field(default_factory=dict)
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    supplier_id: uuid.UUID = field(default_factory=uuid.uuid4)


def offer(price, **kwargs) -> Offer:
    return Offer(price=None if price is None else Decimal(str(price)), **kwargs)


def options(*rows) -> dict:
    return {"variants": [{"title": t, "price": p, "in_stock": s} for t, p, s in rows]}


ON_REQUEST = {"price_on_request": True}


def test_a_cheaper_in_stock_option_sets_the_lowest_and_is_named():
    plain = offer(340)
    cheap = offer(360, attributes=options(("Soldered", 360, True), ("Without headers", 320, True)))

    summary = summarize_prices([plain, cheap], NOW)

    assert (summary.min_price, summary.max_price) == (320, 340)
    assert summary.listing_id == cheap.id
    assert summary.supplier_id == cheap.supplier_id
    assert summary.option == "Without headers"


def test_an_out_of_stock_option_never_sets_the_lowest():
    o = offer(350, attributes=options(("Type-C", 300, False), ("Unknown", 290, None)))

    assert unit_price(o) == (Decimal("350"), None)
    assert summarize_prices([o], NOW).option is None


def test_an_offer_is_one_price_in_the_range_not_its_dearest_option():
    """max_price is the dearest offer's price of one, not any option's price:
    the range spans what each shop would charge at its cheapest."""
    o = offer(300, attributes=options(("Small", 300, True), ("Big", 900, True)))

    summary = summarize_prices([o, offer(320)], NOW)

    assert (summary.min_price, summary.max_price) == (300, 320)
    # The cheapest option costs what the listing says: nothing to name.
    assert summary.option is None


def test_a_listing_price_from_an_out_of_stock_option_gives_way_to_the_in_stock_one():
    """Shopify shows the first variant's price and WooCommerce the cheapest
    variation's, whatever their stock: the price a buyer can pay today is the
    cheapest option in stock, even above the listing's."""
    o = offer(250, attributes=options(("Black", 250, False), ("White", 280, True)))

    assert unit_price(o, NOW) == (Decimal("280"), "White")
    summary = summarize_prices([o, offer(300)], NOW)
    assert (summary.min_price, summary.option) == (280, "White")


def test_options_with_unknown_price_or_stock_never_set_the_price():
    o = offer(
        300,
        attributes={
            "variants": [
                {"title": "No price", "in_stock": True},
                {"title": "No stock flag", "price": 100},
                {"title": "Null stock", "price": 120, "in_stock": None},
            ]
        },
    )

    assert unit_price(o, NOW) == (Decimal("300"), None)


def test_options_read_over_45_days_ago_do_not_count():
    attributes = options(("Without headers", 200, True))
    old = offer(
        300,
        attributes={**attributes, "variants_checked_at": (NOW - timedelta(days=60)).isoformat()},
    )
    recent = offer(
        300, attributes={**attributes, "variants_checked_at": (NOW - timedelta(days=3)).isoformat()}
    )
    unstamped = offer(300, attributes=attributes)  # read with the listing itself

    assert unit_price(old, NOW) == (Decimal("300"), None)
    assert unit_price(recent, NOW) == (Decimal("200"), "Without headers")
    assert unit_price(unstamped, NOW) == (Decimal("200"), "Without headers")


def test_on_request_never_enters_the_range_but_is_counted():
    summary = summarize_prices([offer(85), offer(None, attributes=ON_REQUEST)], NOW)

    assert (summary.min_price, summary.max_price) == (85, 85)
    assert summary.on_request == 1


def test_all_on_request_has_no_range_even_beside_a_priced_out_of_stock_offer():
    """The page's headline is "Price on request" while a shop has it in stock;
    an out-of-stock shop's price does not stand in for it."""
    summary = summarize_prices(
        [
            offer(None, attributes=ON_REQUEST),
            offer(None, attributes=ON_REQUEST),
            offer(500, stock_signal=OUT),
        ],
        NOW,
    )

    assert summary.min_price is None and summary.max_price is None
    assert summary.on_request == 2
    assert summary.listing_id is None


def test_a_stale_flag_beside_a_price_is_not_on_request():
    summary = summarize_prices([offer(85, attributes=ON_REQUEST)], NOW)

    assert summary.min_price == 85
    assert summary.on_request == 0


def test_an_out_of_date_offer_counts_nowhere_even_when_cheapest():
    stale = offer(40, last_verified_at=STALE)
    summary = summarize_prices(
        [stale, offer(None, last_verified_at=STALE, attributes=ON_REQUEST)]
        + [offer(52), offer(60)],
        NOW,
    )

    assert (summary.min_price, summary.max_price) == (52, 60)
    assert summary.on_request == 0


def test_out_of_stock_counts_only_when_nothing_fresh_is_in_stock():
    assert summarize_prices([offer(40, stock_signal=OUT), offer(60)], NOW).min_price == 60

    summary = summarize_prices([offer(40, stock_signal=OUT), offer(55, stock_signal=OUT)], NOW)

    assert (summary.min_price, summary.max_price) == (40, 55)


def test_low_stock_is_stock():
    summary = summarize_prices([offer(70, stock_signal=LOW), offer(50, stock_signal=UNKNOWN)], NOW)

    assert (summary.min_price, summary.max_price) == (70, 70)


def test_unknown_and_made_to_order_come_before_out_of_stock():
    """The web's middle tier: not known to be gone ("stock not confirmed")."""
    summary = summarize_prices(
        [
            offer(90, stock_signal=UNKNOWN),
            offer(110, stock_signal=MTO),
            offer(40, stock_signal=OUT),
        ],
        NOW,
    )

    assert (summary.min_price, summary.max_price) == (90, 110)


def test_an_in_stock_offer_with_no_price_leaves_no_price():
    """As the page's summary: the in-stock tier is the one counted, and it has
    no price; an out-of-stock shop's price does not stand in for it."""
    summary = summarize_prices([offer(None), offer(70, stock_signal=OUT)], NOW)

    assert summary.min_price is None
    assert summary.on_request == 0


def test_a_fresh_unpriced_offer_is_never_replaced_by_a_stale_price():
    summary = summarize_prices([offer(None), offer(50, last_verified_at=STALE)], NOW)

    assert summary.min_price is None


def test_with_nothing_fresh_in_stock_comes_first_among_the_stale():
    summary = summarize_prices(
        [
            offer(150, last_verified_at=STALE),
            offer(120, last_verified_at=STALE, stock_signal=OUT),
            offer(170, last_verified_at=STALE, stock_signal=LOW),
        ],
        NOW,
    )

    assert (summary.min_price, summary.max_price) == (150, 170)


def test_with_nothing_fresh_and_nothing_in_stock_every_offer_counts():
    summary = summarize_prices(
        [
            offer(120, last_verified_at=STALE, stock_signal=OUT),
            offer(150, last_verified_at=STALE, stock_signal=OUT),
        ],
        NOW,
    )

    assert (summary.min_price, summary.max_price) == (120, 150)


def test_offers_compete_on_the_price_of_one_and_the_minimum_is_named():
    tens = offer("0.15", attributes={"min_quantity": 10})
    single = offer("1.25")

    summary = summarize_prices([single, tens, offer(2)], NOW)

    assert summary.min_price == Decimal("0.15")
    assert summary.listing_id == tens.id
    assert summary.quantity == 10
    assert summary.each is True


def test_the_range_reads_each_when_any_offer_in_it_has_a_minimum():
    summary = summarize_prices([offer(1), offer(2, attributes={"min_quantity": 5})], NOW)

    assert summary.quantity is None
    assert summary.each is True


def test_a_step_larger_than_the_minimum_is_the_minimum():
    """Sold only in tens is at least ten, whatever min_quantity says."""
    stepped = offer(1, attributes={"min_quantity": 2, "multiple_of": 10})
    only_step = offer(1, attributes={"multiple_of": 5})

    assert summarize_prices([stepped], NOW).quantity == 10
    assert summarize_prices([only_step], NOW).quantity == 5


def test_a_minimum_of_one_is_no_minimum():
    summary = summarize_prices([offer(1, attributes={"min_quantity": 1})], NOW)

    assert (summary.quantity, summary.each) == (None, False)


def test_nothing_priced_and_nothing_on_request_is_no_price():
    summary = summarize_prices([offer(None), offer(None, stock_signal=OUT)], NOW)

    assert summary.min_price is None and summary.on_request == 0


# --- Through the rebuild, and out to the document and the contract ---------- #


async def _listing(slug: str, price, stock=IN, attributes=None, name=None) -> Supplier:
    supplier = Supplier(
        id=uuid.uuid4(), slug=slug, name=name or slug, source_type=SourceType.SCRAPED
    )
    async with SessionLocal() as session:
        session.add(supplier)
        await session.flush()
        session.add(
            Listing(
                id=uuid.uuid4(),
                supplier_id=supplier.id,
                source=slug,
                source_type=SourceType.SCRAPED,
                external_id="1",
                title_en="ESP32-S 38Pin Development Board",
                part_number="ESP32",
                price=price,
                stock_signal=stock,
                images=[],
                attributes=attributes or {},
                last_verified_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await session.commit()
    return supplier


async def _rebuilt() -> Product:
    async with SessionLocal() as session:
        await rebuild_products(session)
        await session.commit()
        query = select(Product).options(
            selectinload(Product.category),
            selectinload(Product.image_supplier),
            selectinload(Product.min_price_supplier),
        )
        (product,) = (await session.execute(query)).scalars().all()
        return product


async def test_the_rebuild_stores_the_low_end_and_the_document_and_summary_carry_it():
    await _listing("nile-parts", 340)
    makers = await _listing(
        "cairo-makers",
        360,
        attributes={**options(("Without headers", 320, True)), "min_quantity": 2},
        name="Cairo Makers",
    )
    await _listing("giza", None, attributes=ON_REQUEST)
    await _listing("delta", 300, stock=OUT)

    product = await _rebuilt()

    assert (product.min_price, product.max_price) == (320, 340)
    assert product.min_price_supplier_id == makers.id
    assert product.min_price_option == "Without headers"
    assert product.min_price_quantity == 2
    assert product.price_each is True
    assert product.on_request_count == 1

    doc = build_product_document(
        product, None, None, min_price_shop={"slug": "cairo-makers", "name": "Cairo Makers"}
    )
    assert doc["min_price"] == 320.0
    assert doc["min_price_offer_id"] == str(product.min_price_listing_id)
    assert doc["min_price_shop"] == {"slug": "cairo-makers", "name": "Cairo Makers"}
    assert doc["min_price_option"] == "Without headers"
    assert doc["min_price_quantity"] == 2
    assert doc["price_each"] is True
    assert doc["on_request_count"] == 1
    assert doc["price_on_request"] == "some"

    # A search hit and the product summary use one vocabulary: every field the
    # summary has about the low end is in the document, under the same name.
    low_end = {
        "min_price_offer_id",
        "min_price_shop",
        "min_price_option",
        "min_price_quantity",
        "price_each",
        "on_request_count",
        "price_on_request",
    }
    summary = ProductSummary.model_validate(product).model_dump()
    assert summary["min_price_shop"] == {"slug": "cairo-makers", "name": "Cairo Makers"}
    assert low_end <= set(summary) and low_end <= set(doc)
    assert summary["price_on_request"] == doc["price_on_request"]


async def test_an_all_on_request_product_has_no_price_and_says_why():
    await _listing("giza", None, attributes=ON_REQUEST)
    await _listing("delta", None, attributes=ON_REQUEST)

    product = await _rebuilt()
    doc = build_product_document(product, None, None)

    assert product.min_price is None
    assert doc["price_on_request"] == "all"
    assert doc["min_price_shop"] is None


async def test_a_withdrawn_product_keeps_its_range_but_names_no_offer():
    await _listing("cairo-makers", 360, attributes={"min_quantity": 3})
    await _listing("giza", None, attributes=ON_REQUEST)
    before = await _rebuilt()
    assert before.min_price_listing_id is not None and before.on_request_count == 1

    async with SessionLocal() as session:
        await session.execute(update(Listing).values(status=ListingStatus.ARCHIVED))
        await session.commit()
    product = await _rebuilt()

    assert product.delisted_at is not None
    assert product.min_price == 360  # the last range seen
    assert product.min_price_listing_id is None
    assert product.min_price_supplier_id is None
    assert product.min_price_option is None
    assert product.min_price_quantity is None
    assert product.price_each is False
    assert product.on_request_count == 0


async def test_a_change_at_the_low_end_alone_is_a_content_change():
    """The sitemap's lastmod: an option taking over the lowest price at the
    same figure still changes what the page says."""
    await _listing("cairo-makers", 300, attributes=options(("Black", 300, True)))
    first = await _rebuilt()

    async with SessionLocal() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        listing.attributes = options(("Black", 400, False), ("White", 300, True))
        listing.price = Decimal("400")
        await session.commit()
    second = await _rebuilt()

    assert (first.min_price, second.min_price) == (300, 300)
    assert (first.min_price_option, second.min_price_option) == (None, "White")
    assert second.content_changed_at > first.content_changed_at


def test_the_option_column_fits_the_longest_option_title_kept():
    from makhzan_schemas import contracts

    assert Product.__table__.c.min_price_option.type.length == contracts._MAX_TEXT
