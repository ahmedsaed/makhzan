"""reindex_all — the product documents it writes, with Meilisearch faked.

What is pinned here is `supplier_slugs`, which powers "search within this shop".
It is not a Product column but is gathered from the product's listings, so a
mistake shows up only as a shop page quietly missing or keeping products.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType
from makhzan_schemas.models import Category, Listing, Product, Supplier
from makhzan_schemas.search import FILTERABLE_ATTRIBUTES

from worker.indexer import reindex_all


class _Task:
    task_uid = 0


class FakeIndex:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.settings: dict = {}

    def update_settings(self, settings: dict) -> _Task:
        self.settings = settings
        return _Task()

    def delete_all_documents(self) -> _Task:
        self.documents = []
        return _Task()

    def add_documents(self, docs: list[dict]) -> _Task:
        self.documents.extend(docs)
        return _Task()


class FakeClient:
    def __init__(self) -> None:
        self.products = FakeIndex()

    def create_index(self, name: str, options: dict) -> _Task:
        return _Task()

    def wait_for_task(self, uid: int) -> None:
        pass

    def index(self, name: str) -> FakeIndex:
        return self.products


def _supplier(slug: str) -> Supplier:
    return Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)


def _listing(supplier: Supplier, product: Product, status=ListingStatus.ACTIVE) -> Listing:
    return Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        product_id=product.id,
        source=supplier.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        title_en="LM358 Op-Amp",
        status=status,
        images=[],
        attributes={},
    )


async def _reindex() -> dict[str, dict]:
    client = FakeClient()
    async with SessionLocal() as session:
        await reindex_all(session, client)
    return {doc["title_en"]: doc for doc in client.products.documents}


async def _seed(*rows) -> None:
    async with SessionLocal() as session:
        session.add_all([r for r in rows if not isinstance(r, Listing)])
        await session.flush()
        session.add_all([r for r in rows if isinstance(r, Listing)])
        await session.commit()


async def test_documents_name_every_shop_with_an_active_offer():
    shop_a, shop_b, shop_c = _supplier("shop-a"), _supplier("shop-b"), _supplier("shop-c")
    shared = Product(id=uuid.uuid4(), group_key="mpn:lm358", title_en="shared")
    single = Product(id=uuid.uuid4(), group_key="single:x", title_en="single")
    await _seed(
        shop_a,
        shop_b,
        shop_c,
        shared,
        single,
        _listing(shop_b, shared),
        _listing(shop_a, shared),
        # Two offers from one shop name it once.
        _listing(shop_a, shared),
        _listing(shop_c, single),
    )

    docs = await _reindex()

    assert docs["shared"]["supplier_slugs"] == ["shop-a", "shop-b"]
    assert docs["single"]["supplier_slugs"] == ["shop-c"]


async def test_an_archived_offer_does_not_keep_a_product_in_a_shop():
    """A sweep archives what a shop dropped; its search must drop it too."""
    live, gone = _supplier("shop-a"), _supplier("shop-b")
    product = Product(id=uuid.uuid4(), group_key="mpn:ne555", title_en="ne555")
    await _seed(
        live,
        gone,
        product,
        _listing(live, product),
        _listing(gone, product, status=ListingStatus.ARCHIVED),
    )

    docs = await _reindex()

    assert docs["ne555"]["supplier_slugs"] == ["shop-a"]


async def test_a_product_without_listings_has_an_empty_list():
    """Empty, not missing: a filter on a missing attribute and on an empty one
    both match nothing, but a document shape that varies is a trap for readers."""
    await _seed(Product(id=uuid.uuid4(), group_key="single:orphan", title_en="orphan"))

    docs = await _reindex()

    assert docs["orphan"]["supplier_slugs"] == []


async def test_supplier_slugs_is_filterable():
    """The shop filter is silently empty unless the index lists it as filterable."""
    client = FakeClient()
    async with SessionLocal() as session:
        await reindex_all(session, client)

    assert "supplier_slugs" in FILTERABLE_ATTRIBUTES
    assert "supplier_slugs" in client.products.settings["filterableAttributes"]


async def test_documents_carry_their_category_and_every_ancestor():
    """A group page filters on the group's ref, but products are filed on
    leaves: without the ancestors in the document a group could never narrow."""
    top = Category(id=uuid.uuid4(), domain="electronics", slug="passives", name_en="Passives")
    mid = Category(
        id=uuid.uuid4(),
        domain="electronics",
        slug="resistors",
        name_en="Resistors",
        parent_id=top.id,
    )
    leaf = Category(
        id=uuid.uuid4(),
        domain="electronics",
        slug="smd-resistors",
        name_en="SMD resistors",
        parent_id=mid.id,
    )
    filed = Product(id=uuid.uuid4(), group_key="single:r", title_en="filed", category_id=leaf.id)
    loose = Product(id=uuid.uuid4(), group_key="single:l", title_en="loose")
    async with SessionLocal() as session:
        session.add(top)
        await session.flush()
        session.add(mid)
        await session.flush()
        session.add(leaf)
        await session.flush()
        session.add_all([filed, loose])
        await session.commit()

    docs = await _reindex()

    assert docs["filed"]["category_ref"] == "electronics:smd-resistors"
    assert docs["filed"]["category_refs"] == [
        "electronics:smd-resistors",
        "electronics:resistors",
        "electronics:passives",
    ]
    assert docs["loose"]["category_refs"] == []


async def test_category_refs_is_filterable():
    client = FakeClient()
    async with SessionLocal() as session:
        await reindex_all(session, client)

    assert "category_refs" in client.products.settings["filterableAttributes"]


async def test_last_verified_at_is_filterable():
    """The stale filter (rule C2b) is a range on the newest check. A filter on an
    attribute the index does not list is a Meilisearch error, so a deploy whose
    index settings predate this breaks search until it is reindexed."""
    client = FakeClient()
    async with SessionLocal() as session:
        await reindex_all(session, client)

    assert "last_verified_at" in FILTERABLE_ATTRIBUTES
    assert "last_verified_at" in client.products.settings["filterableAttributes"]


async def test_only_listed_products_are_indexed():
    """Ids are permanent: a merged-away product only redirects and a withdrawn
    one says "no longer listed". Neither is something search should offer."""
    shop = _supplier("shop-a")
    listed = Product(id=uuid.uuid4(), group_key="single:a", title_en="listed")
    withdrawn = Product(
        id=uuid.uuid4(), group_key="single:b", title_en="withdrawn", delisted_at=datetime.now(UTC)
    )
    merged = Product(
        id=uuid.uuid4(), group_key="single:c", title_en="merged", merged_into=listed.id
    )
    await _seed(shop, listed, withdrawn, _listing(shop, listed))
    await _seed(merged)

    docs = await _reindex()
    assert set(docs) == {"listed"}
    # The stale filter ranges over this; a listed product always carries the key.
    assert "last_verified_at" in docs["listed"]
