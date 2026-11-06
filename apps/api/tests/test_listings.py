"""/listings/{id} — the hand-off page to the supplier.

This is the endpoint a buyer lands on before leaving for the supplier's site, so
the supplier block and the source URL are the payload, not decoration.
"""

from __future__ import annotations

import uuid

from factories import BASE_TIME, make_category, make_listing, make_product, make_supplier
from makhzan_schemas.enums import ListingStatus, StockSignal


async def test_returns_the_listing_with_its_supplier_and_category(client, db):
    supplier = await make_supplier(
        db,
        slug="shop-a",
        name="Shop A",
        name_ar="متجر أ",
        area="Bab El Louk",
        governorate="Cairo",
        website_url="https://shop-a.test",
    )
    category = await make_category(db, slug="op-amps", name_en="Op-Amps", name_ar="مضخمات")
    listing = await make_listing(
        db,
        supplier=supplier,
        category=category,
        title_en="LM358 Dual Op-Amp",
        title_ar="إل إم ٣٥٨",
        part_number="LM358",
        brand="TI",
        price="12.50",
        unit="piece",
        images=["https://shop-a.test/lm358.jpg"],
        source_url="https://shop-a.test/p/lm358",
    )

    body = (await client.get(f"/listings/{listing.id}")).json()

    assert body["id"] == str(listing.id)
    assert body["title_en"] == "LM358 Dual Op-Amp"
    assert body["title_ar"] == "إل إم ٣٥٨"
    assert body["part_number"] == "LM358"
    assert body["brand"] == "TI"
    assert body["price"] == 12.50
    assert body["currency"] == "EGP"
    assert body["unit"] == "piece"
    assert body["stock_signal"] == StockSignal.IN_STOCK
    assert body["status"] == ListingStatus.ACTIVE
    assert body["images"] == ["https://shop-a.test/lm358.jpg"]
    assert body["source_url"] == "https://shop-a.test/p/lm358"
    assert body["supplier"] == {
        "id": str(supplier.id),
        "slug": "shop-a",
        "name": "Shop A",
        "name_ar": "متجر أ",
        "area": "Bab El Louk",
        "governorate": "Cairo",
        "website_url": "https://shop-a.test",
    }
    # Exact, so that widening the nested category contract stays a deliberate,
    # visible change.
    assert body["category"] == {
        "ref": "electronics:op-amps",
        "domain": "electronics",
        "slug": "op-amps",
        "name_en": "Op-Amps",
        "name_ar": "مضخمات",
    }


async def test_price_is_serialized_as_a_number_not_a_decimal_string(client, db):
    """The column is Numeric; the contract is float. A string here would make the
    frontend's price formatting and comparisons silently wrong."""
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier, price="1234.56")

    body = (await client.get(f"/listings/{listing.id}")).json()

    assert body["price"] == 1234.56
    assert isinstance(body["price"], float)


async def test_an_uncategorized_listing_still_resolves(client, db):
    """Thousands of listings are uncategorized; the detail page must not need one."""
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier, category=None, price=None)

    body = (await client.get(f"/listings/{listing.id}")).json()

    assert body["category"] is None
    assert body["price"] is None


async def test_last_verified_at_is_returned(client, db):
    """Freshness is the whole trust story for a directory — it has to reach the UI."""
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier)

    body = (await client.get(f"/listings/{listing.id}")).json()

    assert body["last_verified_at"].startswith(BASE_TIME.strftime("%Y-%m-%dT%H:%M:%S"))


async def test_the_listing_names_the_product_it_is_an_offer_of(client, db):
    """The way back up to the comparison. Without it the page can only send a
    buyer to one supplier, which is what the supplier's own site already does."""
    supplier = await make_supplier(db)
    product = await make_product(db)
    listing = await make_listing(db, supplier=supplier, product=product)

    body = (await client.get(f"/listings/{listing.id}")).json()

    assert body["product_id"] == str(product.id)


async def test_an_ungrouped_listing_has_no_product(client, db):
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier, product=None)

    assert (await client.get(f"/listings/{listing.id}")).json()["product_id"] is None


async def test_unknown_id_is_404(client):
    response = await client.get(f"/listings/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "listing not found"


async def test_a_malformed_id_is_rejected_before_the_query(client):
    response = await client.get("/listings/not-a-uuid")

    assert response.status_code == 422


async def test_the_nested_category_can_be_turned_into_a_browse_link(client, db):
    """The detail page links "browse this category". Built from the bare slug that
    link filters across every domain using that slug, so the payload has to carry
    the domain and the ref it implies."""
    supplier = await make_supplier(db)
    tools = await make_category(db, slug="measurement", domain="tools", name_en="Measuring Tools")
    listing = await make_listing(db, supplier=supplier, category=tools)

    category = (await client.get(f"/listings/{listing.id}")).json()["category"]

    assert category["domain"] == "tools"
    assert category["ref"] == "tools:measurement"
    assert category["ref"] != f"electronics:{category['slug']}"
