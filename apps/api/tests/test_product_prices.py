"""What a product page and a result row say about the low end of the range.

The rebuild computes it (makhzan_schemas.pricing, pinned in the ingestion
suite's test_product_pricing.py); the API's part is to serve it, with "price
on request" told apart from "no price listed", and to list offers in the
order the range was taken in.
"""

from __future__ import annotations

import pytest

from factories import make_category, make_listing, make_product, make_supplier


async def test_a_product_names_the_offer_shop_option_and_minimum_setting_its_lowest_price(
    client, db
):
    shop = await make_supplier(db, slug="cairo-makers", name="Cairo Makers")
    product = await make_product(
        db,
        min_price="320",
        max_price="400",
        min_price_supplier=shop,
        min_price_option="Without headers",
        min_price_quantity=10,
        price_each=True,
    )
    listing = await make_listing(db, supplier=shop, product=product, price="360")
    product.min_price_listing_id = listing.id
    await db.commit()

    body = (await client.get(f"/products/{product.id}")).json()

    assert body["min_price_offer_id"] == str(listing.id)
    assert body["min_price_offer_id"] in [o["id"] for o in body["offers"]]
    assert body["min_price_shop"] == {"slug": "cairo-makers", "name": "Cairo Makers"}
    assert body["min_price_option"] == "Without headers"
    assert body["min_price_quantity"] == 10
    assert body["price_each"] is True
    assert body["on_request_count"] == 0
    assert body["price_on_request"] is None


async def test_a_product_before_its_first_rebuild_says_nothing_about_the_low_end(client, db):
    product = await make_product(db, min_price="85", max_price="95")

    body = (await client.get(f"/products/{product.id}")).json()

    assert body["min_price_offer_id"] is None
    assert body["min_price_shop"] is None
    assert body["min_price_option"] is None
    assert body["min_price_quantity"] is None
    assert body["price_each"] is False


@pytest.mark.parametrize(
    ("min_price", "on_request", "expected"),
    [
        (None, 2, "all"),  # every counted offer on request: "Price on request"
        ("85", 1, "some"),  # priced, "· 1 more on request"
        (None, 0, None),  # no price listed at all
        ("85", 0, None),
    ],
)
async def test_price_on_request_is_told_apart_from_no_price(
    client, db, min_price, on_request, expected
):
    product = await make_product(
        db, min_price=min_price, max_price=min_price, on_request_count=on_request
    )

    body = (await client.get(f"/products/{product.id}")).json()

    assert body["price_on_request"] == expected
    assert body["on_request_count"] == on_request


async def test_similar_products_carry_the_low_end_too(client, db):
    servos = await make_category(db, slug="servos", name_en="Servos")
    shop = await make_supplier(db, slug="shop-a", name="Shop A")
    product = await make_product(db, category=servos, min_price="62")
    await make_product(
        db,
        category=servos,
        min_price="70",
        min_price_supplier=shop,
        min_price_quantity=5,
        price_each=True,
        on_request_count=1,
    )

    (row,) = (await client.get(f"/products/{product.id}/similar")).json()

    assert row["min_price_shop"] == {"slug": "shop-a", "name": "Shop A"}
    assert row["min_price_quantity"] == 5
    assert row["price_each"] is True
    assert row["price_on_request"] == "some"


async def test_offers_are_ordered_by_their_price_of_one_options_included(client, db):
    """The list leads with the offer that sets min_price: one whose in-stock
    option undercuts every listing price comes first; an out-of-stock option
    does not move its offer."""
    product = await make_product(db)
    shop_a = await make_supplier(db, slug="shop-a")
    shop_b = await make_supplier(db, slug="shop-b")
    shop_c = await make_supplier(db, slug="shop-c")
    await make_listing(db, supplier=shop_a, product=product, price="340")
    await make_listing(
        db,
        supplier=shop_b,
        product=product,
        price="360",
        attributes={"variants": [{"title": "Without headers", "price": 320, "in_stock": True}]},
    )
    await make_listing(
        db,
        supplier=shop_c,
        product=product,
        price="350",
        attributes={"variants": [{"title": "Type-C", "price": 300, "in_stock": False}]},
    )

    body = (await client.get(f"/products/{product.id}")).json()

    assert [o["supplier"]["slug"] for o in body["offers"]] == ["shop-b", "shop-a", "shop-c"]
