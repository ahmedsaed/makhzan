"""/suppliers/{slug} and /suppliers/{slug}/listings — the supplier profile page.

Both endpoints are scoped to ACTIVE listings. That is the load-bearing part: a
sweep archives listings it no longer sees, and a profile page that kept showing
them would advertise stock the supplier has withdrawn.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from factories import BASE_TIME, make_listing, make_supplier
from makhzan_schemas.enums import ListingStatus


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
        "listing_count": 1,
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
