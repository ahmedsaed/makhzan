"""/suppliers, /suppliers/{slug} and /suppliers/{slug}/listings — the shop pages.

All three are scoped to ACTIVE listings. That is the load-bearing part: a sweep
archives listings it no longer sees, and a page that kept counting them would
advertise stock the supplier has withdrawn.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from factories import BASE_TIME, make_category, make_listing, make_supplier
from makhzan_schemas.enums import ListingStatus, StockSignal


async def test_returns_the_supplier_profile(client, db):
    supplier = await make_supplier(
        db,
        slug="shop-b",
        name="Shop B",
        name_ar="متجر ب",
        area="Bab El Louk",
        governorate="Cairo",
        website_url="https://shop-b.test",
    )
    await make_listing(db, supplier=supplier)

    body = (await client.get("/suppliers/shop-b")).json()

    assert body == {
        "slug": "shop-b",
        "name": "Shop B",
        "name_ar": "متجر ب",
        "area": "Bab El Louk",
        "governorate": "Cairo",
        "website_url": "https://shop-b.test",
        # An area entered before details carried their source: shown, unsourced.
        "contact": {
            "phones": [],
            "whatsapp": None,
            "email": None,
            "address": None,
            "area": "Bab El Louk",
            "governorate": "Cairo",
            "maps_url": None,
            "opening_hours": [],
            "branches": [],
            "sources": [
                {
                    "origin": "listed",
                    "url": None,
                    "checked_on": None,
                    "fields": ["area", "governorate"],
                }
            ],
        },
        "listing_count": 1,
        "in_stock_count": 1,
        "last_verified_at": "2026-06-01T12:00:00Z",
        "domains": [{"domain": "electronics", "count": 1}],
        "top_categories": [],
    }


async def test_listing_count_covers_only_active_listings(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier, status=ListingStatus.ACTIVE)
    await make_listing(db, supplier=supplier, status=ListingStatus.ACTIVE)
    await make_listing(db, supplier=supplier, status=ListingStatus.ARCHIVED)
    await make_listing(db, supplier=supplier, status=ListingStatus.HIDDEN)
    await make_listing(db, supplier=supplier, status=ListingStatus.PENDING_REVIEW)

    body = (await client.get("/suppliers/shop-a")).json()

    assert body["listing_count"] == 2


async def test_listing_count_ignores_other_suppliers(client, db):
    shop_a = await make_supplier(db, slug="shop-a")
    shop_c = await make_supplier(db, slug="shop-c")
    await make_listing(db, supplier=shop_a)
    await make_listing(db, supplier=shop_c)
    await make_listing(db, supplier=shop_c)

    assert (await client.get("/suppliers/shop-a")).json()["listing_count"] == 1
    assert (await client.get("/suppliers/shop-c")).json()["listing_count"] == 2


async def test_unknown_slug_is_404(client):
    response = await client.get("/suppliers/nobody")

    assert response.status_code == 404
    assert response.json()["detail"] == "supplier not found"


async def test_unknown_slug_is_404_on_the_listings_route_too(client):
    response = await client.get("/suppliers/nobody/listings")

    assert response.status_code == 404
    assert response.json()["detail"] == "supplier not found"


async def test_listings_are_in_stock_first_then_freshest(client, db):
    """What a buyer can actually get leads the page, however recently the rest
    was checked."""
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(
        db,
        supplier=supplier,
        title_en="sold out, fresh",
        stock_signal=StockSignal.OUT_OF_STOCK,
        last_verified_at=BASE_TIME + timedelta(days=5),
    )
    await make_listing(db, supplier=supplier, title_en="in stock, old", last_verified_at=BASE_TIME)
    await make_listing(
        db,
        supplier=supplier,
        title_en="in stock, new",
        last_verified_at=BASE_TIME + timedelta(days=1),
    )
    await make_listing(
        db,
        supplier=supplier,
        title_en="unknown",
        stock_signal=StockSignal.UNKNOWN,
        last_verified_at=BASE_TIME + timedelta(days=3),
    )

    body = (await client.get("/suppliers/shop-a/listings")).json()

    assert [item["title_en"] for item in body["items"]] == [
        "in stock, new",
        "in stock, old",
        "sold out, fresh",
        "unknown",
    ]


async def test_in_stock_narrows_the_listings_and_the_total(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier, title_en="here")
    await make_listing(
        db, supplier=supplier, title_en="sold out", stock_signal=StockSignal.OUT_OF_STOCK
    )
    await make_listing(db, supplier=supplier, title_en="low", stock_signal=StockSignal.LOW_STOCK)

    body = (await client.get("/suppliers/shop-a/listings?in_stock=true")).json()

    assert [item["title_en"] for item in body["items"]] == ["here"]
    assert body["total"] == 1


async def test_paging_is_stable_when_listings_tie(client, db):
    """Same stock, same timestamp: without a final tie-breaker the database may
    order them differently per query, and offset paging repeats or skips rows."""
    supplier = await make_supplier(db, slug="shop-a")
    for index in range(6):
        await make_listing(db, supplier=supplier, title_en=f"item-{index}")

    pages = [
        (await client.get(f"/suppliers/shop-a/listings?limit=2&offset={offset}")).json()
        for offset in (0, 2, 4)
    ]

    seen = [item["title_en"] for page in pages for item in page["items"]]
    assert sorted(seen) == [f"item-{index}" for index in range(6)]


async def test_listings_are_freshest_first(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier, title_en="oldest", last_verified_at=BASE_TIME)
    await make_listing(
        db, supplier=supplier, title_en="newest", last_verified_at=BASE_TIME + timedelta(days=2)
    )
    await make_listing(
        db, supplier=supplier, title_en="middle", last_verified_at=BASE_TIME + timedelta(days=1)
    )

    body = (await client.get("/suppliers/shop-a/listings")).json()

    assert [item["title_en"] for item in body["items"]] == ["newest", "middle", "oldest"]


async def test_listings_exclude_everything_that_is_not_active(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier, title_en="live", status=ListingStatus.ACTIVE)
    await make_listing(db, supplier=supplier, title_en="gone", status=ListingStatus.ARCHIVED)
    await make_listing(db, supplier=supplier, title_en="hidden", status=ListingStatus.HIDDEN)
    await make_listing(
        db, supplier=supplier, title_en="unreviewed", status=ListingStatus.PENDING_REVIEW
    )

    body = (await client.get("/suppliers/shop-a/listings")).json()

    assert [item["title_en"] for item in body["items"]] == ["live"]
    assert body["total"] == 1


async def test_items_carry_the_nested_supplier_and_category(client, db):
    supplier = await make_supplier(db, slug="shop-a", name="Shop A")
    await make_listing(db, supplier=supplier)

    (item,) = (await client.get("/suppliers/shop-a/listings")).json()["items"]

    assert item["supplier"]["slug"] == "shop-a"
    assert item["supplier"]["name"] == "Shop A"
    assert item["category"] is None


async def test_total_is_the_whole_result_set_not_the_page(client, db):
    """The frontend pages off `total`; if it were the page size, load-more would
    stop after the first page."""
    supplier = await make_supplier(db, slug="shop-a")
    for index in range(5):
        await make_listing(db, supplier=supplier, title_en=f"item-{index}")

    body = (await client.get("/suppliers/shop-a/listings?limit=2")).json()

    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


async def test_offset_walks_the_result_set_without_gaps_or_repeats(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    for index in range(5):
        await make_listing(
            db,
            supplier=supplier,
            title_en=f"item-{index}",
            last_verified_at=BASE_TIME + timedelta(days=index),
        )

    first = (await client.get("/suppliers/shop-a/listings?limit=2&offset=0")).json()
    second = (await client.get("/suppliers/shop-a/listings?limit=2&offset=2")).json()
    third = (await client.get("/suppliers/shop-a/listings?limit=2&offset=4")).json()

    seen = [item["title_en"] for page in (first, second, third) for item in page["items"]]
    assert seen == ["item-4", "item-3", "item-2", "item-1", "item-0"]
    assert second["offset"] == 2


async def test_an_offset_past_the_end_returns_an_empty_page(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier)

    body = (await client.get("/suppliers/shop-a/listings?offset=50")).json()

    assert body["items"] == []
    assert body["total"] == 1


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=-1", "offset=-1", "limit=abc"])
async def test_out_of_range_paging_is_rejected(client, db, query):
    """The cap exists so a crawler cannot ask for the whole catalogue in one call."""
    await make_supplier(db, slug="shop-a")

    response = await client.get(f"/suppliers/shop-a/listings?{query}")

    assert response.status_code == 422


async def test_paging_defaults(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier)

    body = (await client.get("/suppliers/shop-a/listings")).json()

    assert body["limit"] == 24
    assert body["offset"] == 0


# --- the richer profile -------------------------------------------------------


async def test_profile_counts_in_stock_and_reports_the_latest_check(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier, last_verified_at=BASE_TIME)
    await make_listing(
        db,
        supplier=supplier,
        stock_signal=StockSignal.OUT_OF_STOCK,
        last_verified_at=BASE_TIME + timedelta(days=3),
    )
    # Archived and newer still: it must not make the shop look fresher than it is.
    await make_listing(
        db,
        supplier=supplier,
        status=ListingStatus.ARCHIVED,
        last_verified_at=BASE_TIME + timedelta(days=9),
    )

    body = (await client.get("/suppliers/shop-a")).json()

    assert body["listing_count"] == 2
    assert body["in_stock_count"] == 1
    assert body["last_verified_at"] == "2026-06-04T12:00:00Z"


async def test_a_shop_with_no_active_listings_reports_zeros_not_an_error(client, db):
    await make_supplier(db, slug="shop-a")

    body = (await client.get("/suppliers/shop-a")).json()

    assert body["listing_count"] == 0
    assert body["in_stock_count"] == 0
    assert body["last_verified_at"] is None
    assert body["domains"] == []
    assert body["top_categories"] == []


async def test_domains_come_from_the_listings_not_the_supplier(client, db):
    """A shop can span verticals; Supplier.domain is only a fallback."""
    supplier = await make_supplier(db, slug="shop-a", domain="electronics")
    drills = await make_category(db, slug="drills", domain="tools")
    for _ in range(3):
        await make_listing(db, supplier=supplier, category=drills)
    await make_listing(db, supplier=supplier)
    await make_listing(db, supplier=supplier, category=drills, status=ListingStatus.ARCHIVED)

    body = (await client.get("/suppliers/shop-a")).json()

    assert body["domains"] == [
        {"domain": "tools", "count": 3},
        {"domain": "electronics", "count": 1},
    ]


async def test_top_categories_are_the_biggest_eight_by_active_listings(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    other = await make_supplier(db, slug="shop-b")
    categories = [
        await make_category(db, slug=f"cat-{index}", name_en=f"Cat {index}") for index in range(10)
    ]
    # cat-i gets i+1 listings, so cat-9 is biggest and cat-0, cat-1 fall off.
    for index, category in enumerate(categories):
        for _ in range(index + 1):
            await make_listing(db, supplier=supplier, category=category)
    # Neither archived listings nor another shop's count toward it.
    for _ in range(20):
        await make_listing(
            db, supplier=supplier, category=categories[0], status=ListingStatus.ARCHIVED
        )
        await make_listing(db, supplier=other, category=categories[1])
    # Uncategorized listings are not a category.
    for _ in range(20):
        await make_listing(db, supplier=supplier)

    top = (await client.get("/suppliers/shop-a")).json()["top_categories"]

    assert [c["ref"] for c in top] == [f"electronics:cat-{index}" for index in range(9, 1, -1)]
    assert top[0] == {"ref": "electronics:cat-9", "name_en": "Cat 9", "name_ar": None, "count": 10}


async def test_top_categories_name_the_category_by_ref(client, db):
    """Slugs repeat across domains, so the shop page links categories by ref."""
    supplier = await make_supplier(db, slug="shop-a")
    tools = await make_category(db, slug="measurement", domain="tools", name_en="Tools M")
    electronics = await make_category(db, slug="measurement", name_en="Electronics M")
    await make_listing(db, supplier=supplier, category=tools)
    await make_listing(db, supplier=supplier, category=tools)
    await make_listing(db, supplier=supplier, category=electronics)

    top = (await client.get("/suppliers/shop-a")).json()["top_categories"]

    assert [(c["ref"], c["count"]) for c in top] == [
        ("tools:measurement", 2),
        ("electronics:measurement", 1),
    ]


# --- every shop ---------------------------------------------------------------


async def test_lists_every_supplier_biggest_first(client, db):
    small = await make_supplier(db, slug="shop-a", name="Shop A", website_url="https://a.test")
    big = await make_supplier(db, slug="shop-b", name="Shop B", name_ar="Shop B (ar)")
    await make_supplier(db, slug="shop-c", name="Shop C")
    await make_listing(db, supplier=small)
    for day in range(3):
        await make_listing(db, supplier=big, last_verified_at=BASE_TIME + timedelta(days=day))
    await make_listing(db, supplier=big, stock_signal=StockSignal.OUT_OF_STOCK)

    body = (await client.get("/suppliers")).json()

    assert [row["slug"] for row in body] == ["shop-b", "shop-a", "shop-c"]
    assert body[0] == {
        "slug": "shop-b",
        "name": "Shop B",
        "name_ar": "Shop B (ar)",
        "website_url": None,
        "listing_count": 4,
        "in_stock_count": 3,
        "last_verified_at": "2026-06-03T12:00:00Z",
        "domains": [{"domain": "electronics", "count": 4}],
    }
    assert body[1]["website_url"] == "https://a.test"
    # A shop the crawler lost entirely is still listed, with zeros, not dropped.
    assert body[2] == {
        "slug": "shop-c",
        "name": "Shop C",
        "name_ar": None,
        "website_url": None,
        "listing_count": 0,
        "in_stock_count": 0,
        "last_verified_at": None,
        "domains": [],
    }


async def test_the_list_counts_only_active_listings(client, db):
    supplier = await make_supplier(db, slug="shop-a")
    await make_listing(db, supplier=supplier)
    await make_listing(db, supplier=supplier, status=ListingStatus.ARCHIVED)
    await make_listing(db, supplier=supplier, status=ListingStatus.HIDDEN)

    (row,) = (await client.get("/suppliers")).json()

    assert row["listing_count"] == 1
    assert row["in_stock_count"] == 1


async def test_the_list_keeps_each_shops_domains_apart(client, db):
    shop_a = await make_supplier(db, slug="shop-a")
    shop_b = await make_supplier(db, slug="shop-b")
    drills = await make_category(db, slug="drills", domain="tools")
    await make_listing(db, supplier=shop_a, category=drills)
    await make_listing(db, supplier=shop_b)
    await make_listing(db, supplier=shop_b)

    body = {row["slug"]: row["domains"] for row in (await client.get("/suppliers")).json()}

    assert body == {
        "shop-a": [{"domain": "tools", "count": 1}],
        "shop-b": [{"domain": "electronics", "count": 2}],
    }


async def test_an_empty_directory_is_an_empty_list(client):
    assert (await client.get("/suppliers")).json() == []
