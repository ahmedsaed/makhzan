"""The shop details a listing carries, and the shop's contact, as the API shows them.

Ingestion writes these into a listing's `attributes` (and `suppliers.contact`)
from several platforms; the API is where they are whitelisted and validated.
What must hold: only the named keys reach a page, links are https, numbers are
numbers, lists are capped, "price on request" never sits beside a price, and the
shop page's rows stay slim.
"""

from __future__ import annotations

from factories import make_listing, make_product, make_supplier

DETAILS = {
    "min_quantity": 10,
    "multiple_of": "10",
    "price_on_request": False,
    "stock_quantity": 4,
    "variants": [
        {"title": "1 kg / Black", "price": 1500, "in_stock": True, "stock_quantity": 200,
         "sku": "V-1"},
        {"title": "0.25 kg / Black", "price": "500.00", "in_stock": False},
        {"title": "", "price": 1},  # no label: not a row anyone can read
        "not a variant",
    ],
    "price_breaks": [
        {"min_quantity": 100, "price": 7},
        {"min_quantity": 20, "price": "7.5"},
        {"min_quantity": 1, "price": 8},  # a "break" at one is the price itself
        {"min_quantity": 50, "price": "free"},
    ],
    "compatible_with": ["Neptune 4 Plus", {"nested": True}, "Neptune 4 Max"],
    "ships_from_abroad": True,
    "mfr_part_number": "FRC1206J561 TS",
    "videos": [
        {"label": "Unboxing", "url": "https://www.youtube.com/watch?v=abc"},
        {"label": "Insecure", "url": "http://video.test/v.mp4"},
        {"label": "Script", "url": "javascript:alert(1)"},
    ],
    "shop_category_path": ["Components", "Resistors"],
    "sku": "PRIVATE-1",
}  # fmt: skip


async def _offer(client, db, attributes, **listing):
    product = await make_product(db)
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier, product=product, attributes=attributes, **listing)
    (offer,) = (await client.get(f"/products/{product.id}")).json()["offers"]
    return offer


async def test_an_offer_carries_the_shared_detail_keys_validated(client, db):
    offer = await _offer(client, db, DETAILS)

    assert offer["min_quantity"] == 10
    assert offer["multiple_of"] == 10
    assert offer["price_on_request"] is False
    assert offer["stock_quantity"] == 4
    assert offer["variants"] == [
        {"title": "1 kg / Black", "price": 1500.0, "in_stock": True, "stock_quantity": 200,
         "sku": "V-1"},
        {"title": "0.25 kg / Black", "price": 500.0, "in_stock": False, "stock_quantity": None,
         "sku": None},
    ]  # fmt: skip
    # Ascending, and only real breaks.
    assert offer["price_breaks"] == [
        {"min_quantity": 20, "price": 7.5},
        {"min_quantity": 100, "price": 7.0},
    ]
    assert offer["compatible_with"] == ["Neptune 4 Plus", "Neptune 4 Max"]
    assert offer["ships_from_abroad"] is True
    assert offer["mfr_part_number"] == "FRC1206J561 TS"
    # https only.
    assert offer["videos"] == [{"url": "https://www.youtube.com/watch?v=abc", "label": "Unboxing"}]


async def test_internal_detail_keys_never_leave(client, db):
    product = await make_product(db)
    supplier = await make_supplier(db)
    await make_listing(db, supplier=supplier, product=product, attributes=DETAILS)

    raw = (await client.get(f"/products/{product.id}")).text

    for leaked in ("shop_category_path", "PRIVATE-1", "Components"):
        assert leaked not in raw


async def test_a_listing_without_details_reads_as_empty(client, db):
    offer = await _offer(client, db, {})

    assert offer["min_quantity"] is None
    assert offer["multiple_of"] is None
    assert offer["price_on_request"] is False
    assert offer["stock_quantity"] is None
    assert offer["variants"] == []
    assert offer["price_breaks"] == []
    assert offer["compatible_with"] == []
    assert offer["ships_from_abroad"] is None
    assert offer["mfr_part_number"] is None
    assert offer["videos"] == []


async def test_price_on_request_has_no_price_never_zero(client, db):
    offer = await _offer(client, db, {"price_on_request": True}, price=None)

    assert offer["price_on_request"] is True
    assert offer["price"] is None


async def test_a_price_overrides_a_stale_on_request_flag(client, db):
    offer = await _offer(client, db, {"price_on_request": True}, price="12.00")

    assert offer["price"] == 12.0
    assert offer["price_on_request"] is False


async def test_only_true_is_on_request(client, db):
    offer = await _offer(client, db, {"price_on_request": "yes"}, price=None)
    assert offer["price_on_request"] is False


async def test_quantities_must_be_whole_numbers_above_one(client, db):
    offer = await _offer(client, db, {"min_quantity": 1, "multiple_of": 2.5, "stock_quantity": -3})
    assert offer["min_quantity"] is None
    assert offer["multiple_of"] is None
    assert offer["stock_quantity"] is None


async def test_lists_are_capped(client, db):
    attributes = {
        "variants": [{"title": f"Option {i}", "price": i + 1} for i in range(80)],
        "price_breaks": [{"min_quantity": 10 + i, "price": 100 - i} for i in range(30)],
        "compatible_with": [f"Printer {i}" for i in range(40)],
        "videos": [{"url": f"https://video.test/{i}"} for i in range(30)],
    }
    offer = await _offer(client, db, attributes)

    assert len(offer["variants"]) == 50
    assert len(offer["price_breaks"]) == 10
    assert len(offer["compatible_with"]) == 20
    assert len(offer["videos"]) == 10


async def test_the_listing_page_carries_the_details_too(client, db):
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier, attributes=DETAILS)

    body = (await client.get(f"/listings/{listing.id}")).json()

    assert body["min_quantity"] == 10
    assert len(body["variants"]) == 2
    assert "shop_category_path" not in body


# --------------------------------------------------------------------------- #
# The shop's contact
# --------------------------------------------------------------------------- #

CONTACT = {
    "address": "31 شارع المثال",
    "area": "حي المثال",
    "governorate": "القاهرة",
    "phone": "01000000000",
    "whatsapp": "+201000000000",
    "email": "info@shop.test",
    "opening_hours": ["Mo,Tu,We,Th,Fr,Sa 10:00-20:00", 7],
    "source_url": "https://shop-a.test/",
    "fetched_at": "2026-11-08T20:00:00+00:00",
}


async def test_the_supplier_profile_carries_its_contact(client, db):
    await make_supplier(db, slug="shop-a", contact=CONTACT)

    contact = (await client.get("/suppliers/shop-a")).json()["contact"]

    assert contact == {
        **CONTACT,
        # Kept as the shop wrote it; only a non-text hour line is dropped.
        "opening_hours": ["Mo,Tu,We,Th,Fr,Sa 10:00-20:00"],
        "fetched_at": "2026-11-08T20:00:00Z",
    }


async def test_a_contact_source_that_is_not_https_is_dropped(client, db):
    await make_supplier(db, slug="shop-a", contact={**CONTACT, "source_url": "http://shop-a.test/"})
    contact = (await client.get("/suppliers/shop-a")).json()["contact"]
    assert contact["source_url"] is None
    assert contact["phone"] == "01000000000"


async def test_a_contact_with_nothing_to_show_is_none(client, db):
    await make_supplier(
        db,
        slug="shop-a",
        contact={"source_url": "https://shop-a.test/", "fetched_at": "garbage", "phone": 5},
    )
    assert (await client.get("/suppliers/shop-a")).json()["contact"] is None


async def test_an_offers_supplier_carries_its_contact(client, db):
    product = await make_product(db)
    supplier = await make_supplier(db, slug="shop-a", contact=CONTACT)
    await make_listing(db, supplier=supplier, product=product)

    (offer,) = (await client.get(f"/products/{product.id}")).json()["offers"]

    assert offer["supplier"]["contact"]["phone"] == "01000000000"


async def test_the_shop_pages_rows_stay_slim(client, db):
    supplier = await make_supplier(db, slug="shop-a", contact=CONTACT)
    await make_listing(db, supplier=supplier, attributes={**DETAILS, "specs": {"A": "1"}})

    (row,) = (await client.get("/suppliers/shop-a/listings")).json()["items"]

    for heavy in ("specs", "documents", "variants", "price_breaks", "compatible_with", "videos"):
        assert heavy not in row
    assert "contact" not in row["supplier"]
    # The unit of sale is part of a row's price, so it stays.
    assert row["min_quantity"] == 10
    assert row["price_on_request"] is False
