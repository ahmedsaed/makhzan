"""/sitemap/products — every product page, keyset-paged by id, for the sitemap.

What matters: a page is listed only while it would render (an active offer),
paging by `after` visits every product exactly once, and `changed_at` is the
content-change date, not the last recheck.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from makhzan_schemas.enums import ListingStatus

from factories import make_listing, make_product, make_supplier

CHANGED = datetime(2026, 3, 4, 5, 6, tzinfo=UTC)


async def _offered(db, supplier, **kwargs):
    product = await make_product(db, **kwargs)
    await make_listing(db, supplier=supplier, product=product)
    return product


async def test_lists_id_title_and_content_change_date(client, db):
    shop = await make_supplier(db, slug="shop-a")
    product = await _offered(
        db,
        shop,
        title_en="SG90 Micro Servo",
        content_changed_at=CHANGED,
        last_verified_at=datetime(2026, 11, 1, tzinfo=UTC),
    )

    body = (await client.get("/sitemap/products")).json()

    assert body == {
        "items": [
            {
                "id": str(product.id),
                "title_en": "SG90 Micro Servo",
                "title_ar": None,
                "part_number": None,
                "changed_at": "2026-03-04T05:06:00Z",
            }
        ],
        "next": None,
        "total": 1,
    }


async def test_leaves_out_products_without_an_active_offer(client, db):
    """The product page 404s without offers; an archived offer is a withdrawn one."""
    shop = await make_supplier(db, slug="shop-a")
    listed = await _offered(db, shop)
    await make_product(db)  # no offers at all
    withdrawn = await make_product(db)
    await make_listing(db, supplier=shop, product=withdrawn, status=ListingStatus.ARCHIVED)

    body = (await client.get("/sitemap/products")).json()

    assert [item["id"] for item in body["items"]] == [str(listed.id)]
    assert body["total"] == 1


async def test_a_product_with_several_offers_is_listed_once(client, db):
    shop_a = await make_supplier(db, slug="shop-a")
    shop_b = await make_supplier(db, slug="shop-b")
    product = await _offered(db, shop_a)
    await make_listing(db, supplier=shop_b, product=product)

    body = (await client.get("/sitemap/products")).json()

    assert [item["id"] for item in body["items"]] == [str(product.id)]
    assert body["total"] == 1


async def test_pages_by_id_and_visits_every_product_once(client, db):
    shop = await make_supplier(db, slug="shop-a")
    ids = sorted([str((await _offered(db, shop)).id) for _ in range(5)])

    seen, after, pages = [], None, 0
    while True:
        url = "/sitemap/products?limit=2" + (f"&after={after}" if after else "")
        body = (await client.get(url)).json()
        pages += 1
        # Only the first page counts the whole; later pages are a cursor away.
        assert body["total"] == (5 if pages == 1 else None)
        seen += [item["id"] for item in body["items"]]
        after = body["next"]
        if after is None:
            break

    assert seen == ids
    assert pages == 3


async def test_a_full_last_page_is_followed_by_an_empty_one(client, db):
    """`next` is set whenever a page is full: the caller cannot know it was the last."""
    shop = await make_supplier(db, slug="shop-a")
    ids = sorted([str((await _offered(db, shop)).id) for _ in range(2)])

    first = (await client.get("/sitemap/products?limit=2")).json()
    assert first["next"] == ids[-1]
    rest = (await client.get(f"/sitemap/products?limit=2&after={first['next']}")).json()
    assert rest == {"items": [], "next": None, "total": None}


async def test_limit_is_capped_at_one_sitemap(client):
    assert (await client.get("/sitemap/products?limit=50000")).status_code == 200
    assert (await client.get("/sitemap/products?limit=50001")).status_code == 422
    assert (await client.get("/sitemap/products?limit=0")).status_code == 422


async def test_a_malformed_cursor_is_rejected(client):
    assert (await client.get("/sitemap/products?after=nope")).status_code == 422
    unknown = uuid.uuid4()
    assert (await client.get(f"/sitemap/products?after={unknown}")).status_code == 200


async def test_does_not_shadow_the_product_routes(client, db):
    shop = await make_supplier(db, slug="shop-a")
    product = await _offered(db, shop)
    assert (await client.get(f"/products/{product.id}")).status_code == 200
