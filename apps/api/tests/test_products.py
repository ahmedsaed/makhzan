"""/products/{id} — a canonical product and every supplier's offer of it.

Comparing offers is the point of the page, so offer order is the behaviour worth
pinning: cheapest first, and offers without a price last rather than treated as
free.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Product, ProductRedirect
from sqlalchemy import select

from factories import BASE_TIME, make_category, make_listing, make_product, make_supplier


async def test_returns_the_product_with_its_aggregates_and_category(client, db):
    category = await make_category(db, slug="op-amps", name_en="Op-Amps")
    product = await make_product(
        db,
        part_number="LM358",
        title_en="LM358 Dual Op-Amp",
        title_ar="إل إم ٣٥٨",
        brand="TI",
        category=category,
        image="https://shop-a.test/lm358.jpg",
        offer_count=2,
        supplier_count=2,
        min_price="10.00",
        max_price="14.00",
        in_stock=True,
    )

    body = (await client.get(f"/products/{product.id}")).json()

    assert body["id"] == str(product.id)
    assert body["part_number"] == "LM358"
    assert body["title_en"] == "LM358 Dual Op-Amp"
    assert body["title_ar"] == "إل إم ٣٥٨"
    assert body["brand"] == "TI"
    assert body["image"] == "https://shop-a.test/lm358.jpg"
    assert body["offer_count"] == 2
    assert body["supplier_count"] == 2
    assert body["min_price"] == 10.00
    assert body["max_price"] == 14.00
    assert body["currency"] == "EGP"
    assert body["in_stock"] is True
    assert body["category"] == {
        "ref": "electronics:op-amps",
        "domain": "electronics",
        "slug": "op-amps",
        "name_en": "Op-Amps",
        "name_ar": None,
    }


async def test_offers_are_cheapest_first(client, db):
    product = await make_product(db)
    shop_a = await make_supplier(db, slug="shop-a", name="Shop A")
    shop_b = await make_supplier(db, slug="shop-b", name="Shop B")
    shop_c = await make_supplier(db, slug="shop-c", name="Shop C")
    await make_listing(db, supplier=shop_a, product=product, price="14.00")
    await make_listing(db, supplier=shop_b, product=product, price="9.50")
    await make_listing(db, supplier=shop_c, product=product, price="12.00")

    body = (await client.get(f"/products/{product.id}")).json()

    assert [o["price"] for o in body["offers"]] == [9.50, 12.00, 14.00]
    assert [o["supplier"]["slug"] for o in body["offers"]] == ["shop-b", "shop-c", "shop-a"]


async def test_offers_without_a_price_sort_last_not_first(client, db):
    """A missing price is unknown, not zero — sorting it first would put a
    "price on request" offer above the genuinely cheapest one."""
    product = await make_product(db)
    shop_a = await make_supplier(db, slug="shop-a")
    shop_b = await make_supplier(db, slug="shop-b")
    shop_c = await make_supplier(db, slug="shop-c")
    await make_listing(db, supplier=shop_a, product=product, price=None)
    await make_listing(db, supplier=shop_b, product=product, price="20.00")
    await make_listing(db, supplier=shop_c, product=product, price="5.00")

    body = (await client.get(f"/products/{product.id}")).json()

    assert [o["price"] for o in body["offers"]] == [5.00, 20.00, None]


async def test_every_offer_carries_the_supplier_it_belongs_to(client, db):
    """Without the supplier an offer row is unattributable, and the hand-off —
    the only thing this product page exists to do — has nowhere to point."""
    product = await make_product(db)
    supplier = await make_supplier(db, slug="shop-a", name="Shop A")
    await make_listing(db, supplier=supplier, product=product, source_url="https://a.test/p/1")

    (offer,) = (await client.get(f"/products/{product.id}")).json()["offers"]

    assert offer["supplier"]["slug"] == "shop-a"
    assert offer["supplier"]["name"] == "Shop A"
    assert offer["source_url"] == "https://a.test/p/1"


#: What a shop's listing carries in `attributes` once ingestion has read it: the
#: public details beside a crossed-out price and internal keys that must not leak.
SHOP_ATTRIBUTES = {
    "specs": {"Operating Voltage": "5V", "Channels": 2, "Pinout": {"1": "VCC"}},
    "documents": [
        "https://shop-a.test/files/lm358.pdf",
        {"url": "https://shop-a.test/files/app-note.pdf", "label": "Application note"},
        "javascript:alert(1)",
        "https://shop-a.test/files/lm358.pdf",
    ],
    "regular_price": "15.00",
    "compare_at_price": "15.00",
    "sku": "A-1001",
    "platform": "shop-platform",
    "price_id": 77,
}


async def test_an_offer_carries_the_shops_brand_specs_and_datasheets(client, db):
    product = await make_product(db)
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(
        db, supplier=supplier, product=product, brand="Acme", attributes=SHOP_ATTRIBUTES
    )

    (offer,) = (await client.get(f"/products/{product.id}")).json()["offers"]

    assert offer["brand"] == "Acme"
    # Scalars become text; a nested value is not a spec row.
    assert offer["specs"] == {"Operating Voltage": "5V", "Channels": "2"}
    # Web links only, each once.
    assert offer["documents"] == [
        {"url": "https://shop-a.test/files/lm358.pdf", "label": None},
        {"url": "https://shop-a.test/files/app-note.pdf", "label": "Application note"},
    ]


async def test_an_offer_never_exposes_before_prices_or_internal_keys(client, db):
    """Rule C3: current price only. The attributes bag is whitelisted, not passed on."""
    product = await make_product(db)
    supplier = await make_supplier(db)
    await make_listing(db, supplier=supplier, product=product, attributes=SHOP_ATTRIBUTES)

    raw = (await client.get(f"/products/{product.id}")).text

    assert "attributes" not in raw
    for leaked in ("regular_price", "compare_at_price", "A-1001", "price_id", "shop-platform"):
        assert leaked not in raw


async def test_an_offer_without_details_has_empty_specs_and_documents(client, db):
    product = await make_product(db)
    supplier = await make_supplier(db)
    await make_listing(db, supplier=supplier, product=product)

    (offer,) = (await client.get(f"/products/{product.id}")).json()["offers"]

    assert offer["brand"] is None
    assert offer["specs"] == {}
    assert offer["documents"] == []


async def test_listings_of_other_products_are_not_included(client, db):
    product = await make_product(db, group_key="mpn:LM358")
    other = await make_product(db, group_key="mpn:NE555")
    supplier = await make_supplier(db)
    await make_listing(db, supplier=supplier, product=product, title_en="LM358")
    await make_listing(db, supplier=supplier, product=other, title_en="NE555")
    await make_listing(db, supplier=supplier, product=None, title_en="ungrouped")

    body = (await client.get(f"/products/{product.id}")).json()

    assert [o["title_en"] for o in body["offers"]] == ["LM358"]


async def test_a_product_with_no_offers_still_resolves(client, db):
    product = await make_product(db, offer_count=0, supplier_count=0)

    body = (await client.get(f"/products/{product.id}")).json()

    assert body["offers"] == []


async def test_unknown_id_is_404(client):
    response = await client.get(f"/products/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "product not found"


async def test_a_malformed_id_is_rejected_before_the_query(client):
    response = await client.get("/products/not-a-uuid")

    assert response.status_code == 422


async def test_the_nested_category_can_be_turned_into_a_browse_link(client, db):
    """Same contract as the listing page, and for the same reason: the product
    page's category link must name one vertical, not every one sharing the slug."""
    tools = await make_category(db, slug="measurement", domain="tools", name_en="Measuring Tools")
    product = await make_product(db, category=tools, domain="tools")

    category = (await client.get(f"/products/{product.id}")).json()["category"]

    assert category["domain"] == "tools"
    assert category["ref"] == "tools:measurement"


# --------------------------------------------------------------------------- #
# Similar products
# --------------------------------------------------------------------------- #


async def test_similar_products_come_from_the_same_category(client, db):
    """Category is the strongest signal available: the taxonomy is curated per
    domain, so "same leaf" already means "same kind of thing"."""
    servos = await make_category(db, slug="servos", name_en="Servos")
    resistors = await make_category(db, slug="resistors", name_en="Resistors")
    product = await make_product(db, category=servos, title_en="SG90", min_price="62")
    await make_product(db, category=servos, title_en="MG996R", min_price="120")
    await make_product(db, category=resistors, title_en="10k resistor", min_price="1")

    body = (await client.get(f"/products/{product.id}/similar")).json()

    assert [p["title_en"] for p in body] == ["MG996R"]


async def test_similar_products_exclude_the_product_itself(client, db):
    servos = await make_category(db, slug="servos")
    product = await make_product(db, category=servos, title_en="SG90", min_price="62")
    await make_product(db, category=servos, title_en="MG996R", min_price="120")

    body = (await client.get(f"/products/{product.id}/similar")).json()

    assert str(product.id) not in [p["id"] for p in body]


async def test_similar_products_are_ordered_by_nearest_price(client, db):
    """Price separates a 9g hobby servo from an industrial one inside a leaf
    that legitimately holds both."""
    servos = await make_category(db, slug="servos")
    product = await make_product(db, category=servos, title_en="SG90", min_price="62")
    await make_product(db, category=servos, title_en="far", min_price="900")
    await make_product(db, category=servos, title_en="near", min_price="70")
    await make_product(db, category=servos, title_en="middle", min_price="150")

    body = (await client.get(f"/products/{product.id}/similar")).json()

    assert [p["title_en"] for p in body] == ["near", "middle", "far"]


async def test_unpriced_products_sort_last_among_similar(client, db):
    """An unpriced product is not "close" to any price."""
    servos = await make_category(db, slug="servos")
    product = await make_product(db, category=servos, min_price="62")
    await make_product(db, category=servos, title_en="priced", min_price="400")
    await make_product(db, category=servos, title_en="unpriced", min_price=None, max_price=None)

    body = (await client.get(f"/products/{product.id}/similar")).json()

    assert [p["title_en"] for p in body] == ["priced", "unpriced"]


async def test_an_uncategorized_product_falls_back_to_its_vertical(client, db):
    """Thousands of listings are uncategorized. A page with nothing on it is
    worse than one with loosely related stock."""
    product = await make_product(db, category=None, domain="tools", min_price="50")
    await make_product(db, category=None, domain="tools", title_en="same vertical", min_price="55")
    await make_product(db, category=None, domain="electronics", title_en="other", min_price="51")

    body = (await client.get(f"/products/{product.id}/similar")).json()

    assert [p["title_en"] for p in body] == ["same vertical"]


async def test_similar_products_carry_no_offers(client, db):
    """The rail needs a summary, not a join per row."""
    servos = await make_category(db, slug="servos")
    product = await make_product(db, category=servos, min_price="62")
    other = await make_product(db, category=servos, title_en="MG996R", min_price="120")
    supplier = await make_supplier(db)
    await make_listing(db, supplier=supplier, product=other, price="120")

    (row,) = (await client.get(f"/products/{product.id}/similar")).json()

    assert "offers" not in row
    assert row["supplier_count"] == 1
    assert row["category"]["ref"] == "electronics:servos"


async def test_similar_respects_the_limit(client, db):
    servos = await make_category(db, slug="servos")
    product = await make_product(db, category=servos, min_price="62")
    for index in range(5):
        await make_product(db, category=servos, title_en=f"p{index}", min_price=str(60 + index))

    body = (await client.get(f"/products/{product.id}/similar?limit=2")).json()

    assert len(body) == 2


@pytest.mark.parametrize("query", ["limit=0", "limit=25", "limit=-1"])
async def test_similar_rejects_an_out_of_range_limit(client, db, query):
    product = await make_product(db)

    response = await client.get(f"/products/{product.id}/similar?{query}")

    assert response.status_code == 422


async def test_similar_for_an_unknown_product_is_404(client):
    response = await client.get(f"/products/{uuid.uuid4()}/similar")

    assert response.status_code == 404


async def test_a_product_with_no_neighbours_returns_an_empty_list(client, db):
    servos = await make_category(db, slug="servos")
    product = await make_product(db, category=servos, min_price="62")

    response = await client.get(f"/products/{product.id}/similar")

    assert response.status_code == 200
    assert response.json() == []


# --- permanent ids: no longer listed, merged, and older redirects -------------
# docs/decisions/0004-stable-product-ids.md, 0005-url-retirement.md


async def _withdraw(db, product, when=BASE_TIME):
    product.delisted_at = when
    product.offer_count = product.supplier_count = 0
    product.in_stock = False
    await db.commit()


async def _merge(db, product, into):
    product.merged_into = into.id
    product.merged_at = BASE_TIME
    await db.commit()


async def test_a_withdrawn_product_is_served_as_no_longer_listed(client, db):
    """Its id is permanent: the page says it is gone, with the last price seen."""
    product = await make_product(
        db, title_en="SG90 Micro Servo", min_price="85.00", max_price="95.00"
    )
    shop = await make_supplier(db, slug="shop-a")
    await make_listing(
        db, supplier=shop, product=product, price="85.00", status=ListingStatus.ARCHIVED
    )
    await _withdraw(db, product)

    response = await client.get(f"/products/{product.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "delisted"
    assert body["delisted_at"] is not None
    assert body["title_en"] == "SG90 Micro Servo"
    assert (body["min_price"], body["max_price"]) == (85.0, 95.0)
    assert body["last_verified_at"] is not None
    assert body["offers"] == [], "an archived listing is not an offer"


async def test_a_listed_product_says_so(client, db):
    product = await make_product(db)

    assert (await client.get(f"/products/{product.id}")).json()["status"] == "listed"


async def test_an_archived_offer_is_left_off_a_listed_product(client, db):
    product = await make_product(db)
    live, gone = await make_supplier(db, slug="shop-a"), await make_supplier(db, slug="shop-b")
    await make_listing(db, supplier=live, product=product)
    await make_listing(db, supplier=gone, product=product, status=ListingStatus.ARCHIVED)

    offers = (await client.get(f"/products/{product.id}")).json()["offers"]

    assert [o["supplier"]["slug"] for o in offers] == ["shop-a"]


async def test_a_merged_product_has_no_page_but_redirects_to_its_survivor(client, db):
    survivor = await make_product(db)
    merged = await make_product(db)
    await _merge(db, merged, survivor)

    assert (await client.get(f"/products/{merged.id}")).status_code == 404
    response = await client.get(f"/products/{merged.id}/redirect")

    assert response.status_code == 200
    assert response.json() == {"id": str(survivor.id)}


async def test_an_id_deleted_before_ids_were_permanent_still_redirects(client, db):
    product = await make_product(db)
    old_id = uuid.uuid4()
    db.add(ProductRedirect(old_id=old_id, new_id=product.id))
    await db.commit()

    response = await client.get(f"/products/{old_id}/redirect")

    assert response.status_code == 200
    assert response.json() == {"id": str(product.id)}


async def test_a_product_with_a_page_of_its_own_has_no_redirect(client, db):
    listed = await make_product(db)
    withdrawn = await make_product(db)
    await _withdraw(db, withdrawn)

    for product in (listed, withdrawn):
        assert (await client.get(f"/products/{product.id}/redirect")).status_code == 404
    assert (await client.get(f"/products/{uuid.uuid4()}/redirect")).status_code == 404


async def _used(db, model, key, column):
    db.expire_all()
    return (await db.execute(select(column).where(key))).scalar_one()


async def test_following_a_redirect_records_when_it_was_used(client, db):
    survivor = await make_product(db)
    merged = await make_product(db)
    await _merge(db, merged, survivor)
    old_id = uuid.uuid4()
    db.add(ProductRedirect(old_id=old_id, new_id=survivor.id))
    await db.commit()

    await client.get(f"/products/{merged.id}/redirect")
    await client.get(f"/products/{old_id}/redirect")

    now = datetime.now(UTC)
    merged_used = await _used(db, Product, Product.id == merged.id, Product.redirect_used_at)
    legacy_used = await _used(
        db, ProductRedirect, ProductRedirect.old_id == old_id, ProductRedirect.last_used_at
    )
    assert now - merged_used < timedelta(minutes=1)
    assert now - legacy_used < timedelta(minutes=1)


async def test_a_redirect_used_today_is_not_written_again(client, db):
    """At most one write a day per redirect: following one costs a read."""
    survivor = await make_product(db)
    merged = await make_product(db)
    await _merge(db, merged, survivor)
    earlier = datetime.now(UTC) - timedelta(hours=3)
    yesterday = datetime.now(UTC) - timedelta(days=2)
    merged.redirect_used_at = earlier
    old_id = uuid.uuid4()
    db.add(ProductRedirect(old_id=old_id, new_id=survivor.id, last_used_at=yesterday))
    await db.commit()

    await client.get(f"/products/{merged.id}/redirect")
    await client.get(f"/products/{old_id}/redirect")

    assert await _used(db, Product, Product.id == merged.id, Product.redirect_used_at) == earlier
    legacy_used = await _used(
        db, ProductRedirect, ProductRedirect.old_id == old_id, ProductRedirect.last_used_at
    )
    assert legacy_used > yesterday, "a day old, so this use is recorded"


async def test_similar_products_are_listed_ones_only(client, db):
    servos = await make_category(db, slug="servos")
    product = await make_product(db, category=servos, min_price="60")
    listed = await make_product(db, category=servos, min_price="61")
    withdrawn = await make_product(db, category=servos, min_price="60")
    merged = await make_product(db, category=servos, min_price="60")
    await _withdraw(db, withdrawn)
    await _merge(db, merged, listed)

    body = (await client.get(f"/products/{product.id}/similar")).json()

    assert [item["id"] for item in body] == [str(listed.id)]


async def test_a_withdrawn_product_still_has_similar_products(client, db):
    """What its "no longer listed" page offers instead."""
    servos = await make_category(db, slug="servos")
    gone = await make_product(db, category=servos, min_price="60")
    await _withdraw(db, gone)
    other = await make_product(db, category=servos, min_price="70")

    body = (await client.get(f"/products/{gone.id}/similar")).json()

    assert [item["id"] for item in body] == [str(other.id)]


async def test_a_product_names_the_shop_its_photo_comes_from(client, db):
    """For the badge on the photo: whose photo it is, as slug and name only."""
    shop = await make_supplier(db, slug="shop-b", name="Shop B")
    product = await make_product(
        db, image="https://shop-b.test/sg90.jpg", image_supplier=shop, title_en="SG90"
    )

    body = (await client.get(f"/products/{product.id}")).json()

    assert body["image_shop"] == {"slug": "shop-b", "name": "Shop B"}


async def test_a_photo_whose_shop_is_unknown_has_no_image_shop(client, db):
    """A product not rebuilt since the column was added: the page shows no badge."""
    product = await make_product(db, image="https://shop-a.test/lm358.jpg")

    body = (await client.get(f"/products/{product.id}")).json()

    assert body["image"] == "https://shop-a.test/lm358.jpg"
    assert body["image_shop"] is None


async def test_similar_products_name_the_shop_of_each_photo(client, db):
    servos = await make_category(db, slug="servos")
    shop = await make_supplier(db, slug="shop-c", name="Shop C")
    product = await make_product(db, category=servos, min_price="62")
    await make_product(
        db,
        category=servos,
        title_en="MG996R",
        min_price="120",
        image="https://shop-c.test/mg996r.jpg",
        image_supplier=shop,
    )
    await make_product(db, category=servos, title_en="No photo", min_price="130")

    body = (await client.get(f"/products/{product.id}/similar")).json()

    assert [(p["title_en"], p["image_shop"]) for p in body] == [
        ("MG996R", {"slug": "shop-c", "name": "Shop C"}),
        ("No photo", None),
    ]
