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


async def test_variants_say_when_they_were_read(client, db):
    """Variants come from once-a-cycle data, so can be older than the price."""
    stamp = "2026-10-20T08:00:00+00:00"
    offer = await _offer(client, db, {**DETAILS, "variants_checked_at": stamp})
    assert offer["variants_checked_at"].startswith("2026-10-20T08:00:00")

    product = await make_product(db)
    for n, attributes in enumerate(
        (
            {**DETAILS, "variants_checked_at": "yesterday"},  # not a time
            {**DETAILS, "variants_checked_at": "2026-10-20T08:00:00"},  # no zone
            {"variants_checked_at": stamp},  # no variants for it to date
        )
    ):
        supplier = await make_supplier(db, slug=f"shop-{n}")
        await make_listing(db, supplier=supplier, product=product, attributes=attributes)
    offers = (await client.get(f"/products/{product.id}")).json()["offers"]
    assert len(offers) == 3
    assert all(offer["variants_checked_at"] is None for offer in offers)


async def test_a_listing_without_details_reads_as_empty(client, db):
    offer = await _offer(client, db, {})

    assert offer["min_quantity"] is None
    assert offer["multiple_of"] is None
    assert offer["price_on_request"] is False
    assert offer["stock_quantity"] is None
    assert offer["variants"] == []
    assert offer["variants_checked_at"] is None
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


#: What a person listed in sources.toml, as sync writes it onto the row.
LISTED = {
    "phones": ["+20223456789", "+20223456780"],
    "email": "sales@shop-a.test",
    "address": "12 Example Street",
    "area": "Bab El Louk",
    "governorate": "Cairo",
    "maps_url": "https://maps.app.goo.gl/shopA",
    "branches": [{"name": "Giza", "address": "3 Other Street", "phones": ["+20233334444"]}],
    # Per page, as sync stores them: the address from a Google Maps listing.
    "contact_sources": [
        {
            "url": "https://shop-a.test/contact-us",
            "checked_on": "2026-11-03",
            "fields": ["phones", "email", "branches"],
        },
        {
            "url": "https://www.google.com/maps/place/Shop+A",
            "checked_on": "2026-11-04",
            "fields": ["address", "area", "governorate", "maps_url"],
        },
    ],
}


async def test_the_supplier_profile_carries_what_the_crawler_read(client, db):
    await make_supplier(db, slug="shop-a", contact=CONTACT)

    contact = (await client.get("/suppliers/shop-a")).json()["contact"]

    assert contact == {
        # Normalized to E.164, so the page can link it.
        "phones": ["+201000000000"],
        "whatsapp": "+201000000000",
        "email": "info@shop.test",
        "address": "31 شارع المثال",
        "area": "حي المثال",
        "governorate": "القاهرة",
        "maps_url": None,
        # Kept as the shop wrote it; only a non-text hour line is dropped.
        "opening_hours": ["Mo,Tu,We,Th,Fr,Sa 10:00-20:00"],
        "branches": [],
        "sources": [
            {
                "origin": "read",
                "url": "https://shop-a.test/",
                "checked_on": "2026-11-08",
                "fields": [
                    "phones",
                    "whatsapp",
                    "email",
                    "address",
                    "area",
                    "governorate",
                    "opening_hours",
                ],
            }  # fmt: skip
        ],
    }


async def test_listed_details_win_per_field_and_the_crawler_fills_gaps(client, db):
    """A person checked the listed details; the crawler's are one page's markup.
    Where both name a phone the listed one is shown, but the hours and the
    WhatsApp only the crawler found are shown too, each said to come from where
    it came from."""
    await make_supplier(db, slug="shop-a", contact=CONTACT, **LISTED)

    body = (await client.get("/suppliers/shop-a")).json()
    contact = body["contact"]

    assert contact["phones"] == ["+20223456789", "+20223456780"]
    assert contact["email"] == "sales@shop-a.test"
    assert contact["address"] == "12 Example Street"
    assert (body["area"], body["governorate"]) == ("Bab El Louk", "Cairo")
    assert contact["whatsapp"] == "+201000000000"
    assert contact["opening_hours"] == ["Mo,Tu,We,Th,Fr,Sa 10:00-20:00"]
    assert contact["branches"] == [
        {
            "name": "Giza",
            "address": "3 Other Street",
            "area": None,
            "governorate": None,
            "phones": ["+20233334444"],
            "maps_url": None,
        }
    ]
    assert contact["maps_url"] == "https://maps.app.goo.gl/shopA"
    assert contact["sources"] == [
        {
            "origin": "listed",
            "url": "https://shop-a.test/contact-us",
            "checked_on": "2026-11-03",
            "fields": ["phones", "email", "branches"],
        },
        {
            "origin": "listed",
            "url": "https://www.google.com/maps/place/Shop+A",
            "checked_on": "2026-11-04",
            "fields": ["address", "area", "governorate", "maps_url"],
        },
        {
            "origin": "read",
            "url": "https://shop-a.test/",
            "checked_on": "2026-11-08",
            "fields": ["whatsapp", "opening_hours"],
        },
    ]


async def test_a_contact_source_that_is_not_https_is_dropped(client, db):
    await make_supplier(db, slug="shop-a", contact={**CONTACT, "source_url": "http://shop-a.test/"})
    contact = (await client.get("/suppliers/shop-a")).json()["contact"]
    assert contact["sources"][0]["url"] is None
    assert contact["phones"] == ["+201000000000"]


async def test_a_number_that_does_not_parse_is_left_out_not_guessed(client, db):
    await make_supplier(
        db, slug="shop-a", contact={**CONTACT, "phone": "2345 6789 / 2345 6780 ext 4"}
    )
    contact = (await client.get("/suppliers/shop-a")).json()["contact"]
    assert contact["phones"] == []
    assert contact["whatsapp"] == "+201000000000"


async def test_a_contact_with_nothing_to_show_is_none(client, db):
    await make_supplier(
        db,
        slug="shop-a",
        contact={"source_url": "https://shop-a.test/", "fetched_at": "garbage", "phone": 5},
    )
    assert (await client.get("/suppliers/shop-a")).json()["contact"] is None


async def test_an_offer_carries_the_compact_contact_only(client, db):
    """Enough for "Contact the shop" on the product page; the addresses, hours
    and branches are the shop page's, not repeated for every offer."""
    product = await make_product(db)
    supplier = await make_supplier(db, slug="shop-a", contact=CONTACT, **LISTED)
    await make_listing(db, supplier=supplier, product=product)

    (offer,) = (await client.get(f"/products/{product.id}")).json()["offers"]

    assert offer["supplier"]["contact"] == {
        "phone": "+20223456789",
        "whatsapp": "+201000000000",
        "email": "sales@shop-a.test",
    }
    assert offer["supplier"]["area"] == "Bab El Louk"


async def test_an_offer_from_a_shop_with_no_way_to_reach_it_carries_none(client, db):
    product = await make_product(db)
    supplier = await make_supplier(db, slug="shop-a", area="Bab El Louk")
    await make_listing(db, supplier=supplier, product=product)

    (offer,) = (await client.get(f"/products/{product.id}")).json()["offers"]

    assert offer["supplier"]["contact"] is None


async def test_a_shop_listing_only_branch_numbers_is_still_reachable_by_phone(client, db):
    product = await make_product(db)
    supplier = await make_supplier(
        db,
        slug="shop-a",
        branches=[{"name": "Giza", "phones": ["+20233334444"]}],
        contact_sources=[
            {
                "url": "https://shop-a.test/branches",
                "checked_on": "2026-11-03",
                "fields": ["branches"],
            }
        ],  # fmt: skip
    )
    await make_listing(db, supplier=supplier, product=product)

    (offer,) = (await client.get(f"/products/{product.id}")).json()["offers"]

    assert offer["supplier"]["contact"]["phone"] == "+20233334444"


async def test_the_shop_pages_rows_stay_slim(client, db):
    supplier = await make_supplier(db, slug="shop-a", contact=CONTACT)
    await make_listing(
        db,
        supplier=supplier,
        attributes={**DETAILS, "specs": {"A": "1"}, "variants_checked_at": "2026-10-20T08:00:00Z"},
    )

    (row,) = (await client.get("/suppliers/shop-a/listings")).json()["items"]

    heavy_fields = ("specs", "documents", "variants", "variants_checked_at", "price_breaks",
                    "compatible_with", "videos")  # fmt: skip
    for heavy in heavy_fields:
        assert heavy not in row
    assert "contact" not in row["supplier"]
    # The unit of sale is part of a row's price, so it stays.
    assert row["min_quantity"] == 10
    assert row["price_on_request"] is False
