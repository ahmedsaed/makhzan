"""A source with `listed = false` is crawled and stored, but shown nowhere public.

Its listings may still point at a product they offered before the source was
hidden (an archived listing does the same), so every endpoint that reads a
product's offers has to leave them out, not only the regroup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from factories import make_listing, make_product, make_source, make_supplier
from makhzan_schemas.models import IngestionRun, PriceObservation
from makhzan_schemas.enums import IngestionStatus, SourceType, StockSignal


async def _two_shops(db):
    """Shop A listed, shop B hidden; one product both offered."""
    shown = await make_supplier(db, slug="shop-a", name="Shop A")
    hidden = await make_supplier(db, slug="shop-b", name="Shop B")
    await make_source(db, supplier=shown)
    await make_source(db, supplier=hidden, listed=False)
    product = await make_product(db, offer_count=1, supplier_count=1)
    a = await make_listing(db, supplier=shown, product=product, price="10.00")
    b = await make_listing(db, supplier=hidden, product=product, price="5.00")
    return product, a, b


async def test_a_hidden_shop_is_not_in_the_shop_list_and_has_no_page(client, db):
    await _two_shops(db)

    shops = (await client.get("/suppliers")).json()
    assert [s["slug"] for s in shops] == ["shop-a"]
    assert (await client.get("/suppliers/shop-b")).status_code == 404
    assert (await client.get("/suppliers/shop-b/listings")).status_code == 404
    assert (await client.get("/stats")).json()["suppliers"] == 1


async def test_a_hidden_listing_is_never_an_offer(client, db):
    product, a, b = await _two_shops(db)

    body = (await client.get(f"/products/{product.id}")).json()
    assert [o["id"] for o in body["offers"]] == [str(a.id)]

    assert (await client.get(f"/listings/{b.id}")).status_code == 404
    assert (await client.get(f"/listings/{b.id}/history")).status_code == 404
    assert (await client.get(f"/listings/{a.id}")).status_code == 200


async def test_a_product_history_leaves_hidden_offers_out_even_when_withdrawn(client, db):
    product, a, b = await _two_shops(db)
    for listing in (a, b):
        db.add(
            PriceObservation(
                listing_id=listing.id,
                price=listing.price,
                currency="EGP",
                stock_signal=StockSignal.IN_STOCK,
                in_stock=True,
                observed_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
    await db.commit()

    history = (await client.get(f"/products/{product.id}/history")).json()
    assert [o["listing_id"] for o in history["offers"]] == [str(a.id)]

    product.delisted_at = datetime.now(UTC)
    await db.commit()
    history = (await client.get(f"/products/{product.id}/history")).json()
    assert str(b.id) not in [o["listing_id"] for o in history["offers"]]


async def test_a_product_only_a_hidden_shop_offers_is_not_in_the_sitemap(client, db):
    hidden = await make_supplier(db, slug="shop-b")
    await make_source(db, supplier=hidden, listed=False)
    product = await make_product(db)
    await make_listing(db, supplier=hidden, product=product)

    body = (await client.get("/sitemap/products")).json()
    assert body["items"] == [] and body["total"] == 0


async def test_a_shop_with_a_listed_and_a_hidden_source_shows_only_the_listed_ones(client, db):
    shop = await make_supplier(db, slug="shop-a")
    await make_source(db, supplier=shop)
    await make_source(db, supplier=shop, source_id="shop-a-extra", listed=False)
    await make_listing(db, supplier=shop)
    extra = await make_listing(db, supplier=shop)
    extra.source = "shop-a-extra"
    await db.commit()

    profile = (await client.get("/suppliers/shop-a")).json()
    assert profile["listing_count"] == 1
    rows = (await client.get("/suppliers/shop-a/listings")).json()
    assert rows["total"] == 1 and rows["items"][0]["id"] != str(extra.id)


async def test_a_shop_no_source_names_still_shows(client, db):
    """No `sources` row (a test row, a source being retired): listed, as before."""
    await make_supplier(db, slug="shop-a")
    assert (await client.get("/suppliers/shop-a")).status_code == 200


async def test_how_we_crawl_still_names_a_hidden_shop(client, db):
    """We do crawl it, and /how-we-crawl is the public record of whom we crawl."""
    hidden = await make_supplier(db, slug="shop-b", name="Shop B")
    await make_source(db, supplier=hidden, listed=False)
    started = datetime.now(UTC) - timedelta(hours=2)
    db.add(
        IngestionRun(
            source="shop-b",
            source_type=SourceType.SCRAPED,
            status=IngestionStatus.SUCCESS,
            started_at=started,
            finished_at=started + timedelta(minutes=5),
            stats={},
        )
    )
    await db.commit()

    shops = (await client.get("/crawler/activity")).json()["shops"]
    assert [s["name"] for s in shops] == ["Shop B"]
