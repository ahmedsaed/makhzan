"""reindex_all — the product documents it writes, with Meilisearch faked.

What is pinned here is what is gathered from the product's listings rather than
read off the Product row: `supplier_slugs`, which powers "search within this
shop", and the `member_*` arrays, which make every active listing's wording
searchable whichever listing the product's own title came from. A mistake in
either shows up only as a product quietly missing from results.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType
from makhzan_schemas.models import Category, Listing, Product, Supplier
from makhzan_schemas.search import (
    FILTERABLE_ATTRIBUTES,
    MEMBER_ATTRIBUTES,
    SEARCHABLE_ATTRIBUTES,
    build_product_document,
)

from worker.indexer import TASK_TIMEOUT_MS, ensure_index, index_documents, reindex_all


class _Task:
    task_uid = 0


class FakeIndex:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.settings: dict = {}

    def get_searchable_attributes(self) -> list[str]:
        return self.settings.get("searchableAttributes", ["*"])

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
    """Named indexes, with Meilisearch's create, delete and atomic swap."""

    def __init__(self) -> None:
        self.indexes: dict[str, FakeIndex] = {}
        #: The live index's documents at the moment of each swap request.
        self.live_at_swap: list[int] = []
        #: The timeout of every wait for a task.
        self.wait_timeouts: list[int] = []

    @property
    def products(self) -> FakeIndex:
        return self.indexes.setdefault("products", FakeIndex())

    def create_index(self, name: str, options: dict) -> _Task:
        self.indexes.setdefault(name, FakeIndex())
        return _Task()

    def delete_index(self, name: str) -> _Task:
        self.indexes.pop(name, None)
        return _Task()

    def swap_indexes(self, pairs: list[dict]) -> _Task:
        for pair in pairs:
            a, b = pair["indexes"]
            self.live_at_swap.append(len(self.indexes.get("products", FakeIndex()).documents))
            self.indexes[a], self.indexes[b] = self.indexes[b], self.indexes[a]
        return _Task()

    def wait_for_task(self, uid: int, timeout_in_ms: int = 5000) -> None:
        self.wait_timeouts.append(timeout_in_ms)

    def index(self, name: str) -> FakeIndex:
        return self.indexes.setdefault(name, FakeIndex())


def _supplier(slug: str) -> Supplier:
    return Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)


def _listing(
    supplier: Supplier, product: Product, status=ListingStatus.ACTIVE, **fields
) -> Listing:
    return Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        product_id=product.id,
        source=supplier.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        status=status,
        images=[],
        **{"title_en": "LM358 Op-Amp", "attributes": {}, **fields},
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


async def test_a_reindex_never_empties_the_live_index():
    """Built in a staging index and swapped in: search keeps answering from the
    old documents the whole time, then sees the new ones at once."""
    client = FakeClient()
    client.products.documents = [{"id": "old-1"}, {"id": "old-2"}]
    async with SessionLocal() as session:
        await reindex_all(session, client)
    assert client.live_at_swap == [2], "the live index still held the old documents"
    assert "products_staging" not in client.indexes, "the old index is dropped after the swap"
    assert all(doc["id"] not in {"old-1", "old-2"} for doc in client.products.documents)


async def test_documents_name_the_shop_each_photo_comes_from():
    """For the badge on a result's photo: the photo's own shop, slug and name,
    which need not be a shop the card names (`supplier_name`)."""
    shop_a, shop_b = _supplier("shop-a"), _supplier("shop-b")
    shop_b.name = "Shop B"
    pictured = Product(
        id=uuid.uuid4(),
        group_key="mpn:sg90",
        title_en="pictured",
        image="https://shop-b.test/sg90.jpg",
        image_supplier_id=shop_b.id,
        supplier_name="shop-a",
    )
    unknown = Product(
        id=uuid.uuid4(),
        group_key="single:u",
        title_en="unknown",
        image="https://shop-a.test/u.jpg",
    )
    bare = Product(id=uuid.uuid4(), group_key="single:b", title_en="bare")
    await _seed(
        shop_a,
        shop_b,
        pictured,
        unknown,
        bare,
        _listing(shop_a, pictured),
        _listing(shop_b, pictured),
        _listing(shop_a, unknown),
        _listing(shop_a, bare),
    )

    docs = await _reindex()

    assert docs["pictured"]["image_shop"] == {"slug": "shop-b", "name": "Shop B"}
    # Not rebuilt since the column was added: no badge rather than a guess.
    assert docs["unknown"]["image_shop"] is None
    assert docs["bare"]["image_shop"] is None


async def test_documents_name_the_shop_whose_offer_sets_the_lowest_price():
    shop_a, shop_b = _supplier("shop-a"), _supplier("shop-b")
    shop_b.name = "Shop B"
    priced = Product(
        id=uuid.uuid4(),
        group_key="mpn:esp32",
        title_en="priced",
        min_price=320,
        max_price=340,
        min_price_supplier_id=shop_b.id,
        min_price_option="Without headers",
    )
    unpriced = Product(id=uuid.uuid4(), group_key="single:u", title_en="unpriced")
    await _seed(
        shop_a,
        shop_b,
        priced,
        unpriced,
        _listing(shop_a, priced),
        _listing(shop_b, priced),
        _listing(shop_a, unpriced),
    )

    docs = await _reindex()

    assert docs["priced"]["min_price_shop"] == {"slug": "shop-b", "name": "Shop B"}
    assert docs["priced"]["min_price_option"] == "Without headers"
    assert docs["unpriced"]["min_price_shop"] is None
    assert docs["unpriced"]["price_on_request"] is None
    assert docs["unpriced"]["on_request_count"] == 0


async def test_documents_hold_every_active_listings_text():
    """Search never depends on grouping: the product's own title is one
    listing's, but every member's titles, brands and codes are searchable."""
    shop_a, shop_b, shop_c = _supplier("shop-a"), _supplier("shop-b"), _supplier("shop-c")
    product = Product(
        id=uuid.uuid4(),
        group_key="mpn:lm358",
        part_number="LM358",
        title_en="LM358 Dual Op-Amp",
        brand="Texas Instruments",
    )
    await _seed(
        shop_a,
        shop_b,
        shop_c,
        product,
        _listing(
            shop_a,
            product,
            title_en="LM358 Dual Op-Amp",
            brand="Texas Instruments",
            part_number="LM358",
        ),
        _listing(
            shop_b,
            product,
            title_en="Dual operational amplifier DIP-8",
            title_ar="مكبر عمليات مزدوج",
            brand="ST",
            part_number="LM358N",
            attributes={"mfr_part_number": "LM358P", "details": {"description": "long text"}},
        ),
        _listing(
            shop_c,
            product,
            # Case and spacing aside, the same title and brand: listed once.
            title_en="lm358  dual op-amp",
            brand="texas instruments",
            part_number="LM358",
            attributes={"adapter_part_number": "LM358DR"},
        ),
    )

    doc = (await _reindex())["LM358 Dual Op-Amp"]

    assert doc["member_titles_en"] == ["Dual operational amplifier DIP-8", "LM358 Dual Op-Amp"]
    assert doc["member_titles_ar"] == ["مكبر عمليات مزدوج"]
    assert doc["member_brands"] == ["ST", "Texas Instruments"]
    assert doc["member_part_numbers"] == ["LM358", "LM358DR", "LM358N", "LM358P"]


async def test_an_inactive_listings_text_is_not_searchable():
    """An archived offer is gone from the shop, and a hidden or pending one is
    not shown: none of them may keep a product findable by its wording."""
    shop = _supplier("shop-a")
    product = Product(id=uuid.uuid4(), group_key="single:relay", title_en="5V Relay Module")
    await _seed(
        shop,
        product,
        _listing(shop, product, title_en="5V Relay Module", brand="Songle"),
        *(
            _listing(
                shop,
                product,
                status=status,
                title_en=f"{status.value} wording",
                title_ar="نص",
                brand=f"{status.value} brand",
                part_number="SRD-05VDC",
                attributes={"mfr_part_number": "X1", "adapter_part_number": "X2"},
            )
            for status in (
                ListingStatus.ARCHIVED,
                ListingStatus.HIDDEN,
                ListingStatus.PENDING_REVIEW,
            )
        ),
    )

    doc = (await _reindex())["5V Relay Module"]

    assert doc["member_titles_en"] == ["5V Relay Module"]
    assert doc["member_titles_ar"] == []
    assert doc["member_brands"] == ["Songle"]
    assert doc["member_part_numbers"] == []


async def test_member_text_does_not_depend_on_the_representative():
    """The representative changes with stock and price; what a query can find
    must not change with it."""
    shop_a, shop_b = _supplier("shop-a"), _supplier("shop-b")
    product = Product(id=uuid.uuid4(), group_key="single:fan", title_en="12V Fan 80mm")
    await _seed(
        shop_a,
        shop_b,
        product,
        _listing(shop_a, product, title_en="12V Fan 80mm"),
        _listing(shop_b, product, title_en="Cooling fan 8cm 12 volt"),
    )
    before = (await _reindex())["12V Fan 80mm"]

    async with SessionLocal() as session:
        stored = await session.get(Product, product.id)
        stored.title_en = "Cooling fan 8cm 12 volt"
        await session.commit()
    after = (await _reindex())["Cooling fan 8cm 12 volt"]

    for attr in MEMBER_ATTRIBUTES:
        assert after[attr] == before[attr]
    assert before["member_titles_en"] == ["12V Fan 80mm", "Cooling fan 8cm 12 volt"]


async def test_a_single_listing_product_is_its_old_document_plus_the_member_fields():
    shop = _supplier("shop-a")
    product = Product(
        id=uuid.uuid4(),
        group_key="mpn:ne555",
        part_number="NE555",
        title_en="NE555 Timer",
        title_ar="مؤقت",
        brand="TI",
    )
    await _seed(
        shop,
        product,
        _listing(
            shop, product, title_en="NE555 Timer", title_ar="مؤقت", brand="TI", part_number="NE555"
        ),
    )

    doc = (await _reindex())["NE555 Timer"]
    async with SessionLocal() as session:
        stored = await session.get(Product, product.id)
        old = build_product_document(stored, None, None, supplier_slugs=["shop-a"])

    assert set(doc) == set(old)
    assert {k: v for k, v in doc.items() if k not in MEMBER_ATTRIBUTES} == {
        k: v for k, v in old.items() if k not in MEMBER_ATTRIBUTES
    }
    assert doc["member_titles_en"] == ["NE555 Timer"]
    assert doc["member_titles_ar"] == ["مؤقت"]
    assert doc["member_brands"] == ["TI"]
    assert doc["member_part_numbers"] == ["NE555"]


async def test_the_index_searches_the_member_fields_in_order():
    """Settings are applied by the reindex; an attribute not listed here is
    stored but never searched."""
    client = FakeClient()
    async with SessionLocal() as session:
        await reindex_all(session, client)

    assert client.products.settings["searchableAttributes"] == SEARCHABLE_ATTRIBUTES
    for attr in MEMBER_ATTRIBUTES:
        assert attr in SEARCHABLE_ATTRIBUTES


async def test_every_wait_on_meilisearch_is_generous():
    """The client's default wait is 5 s, and changing searchableAttributes
    re-tokenises every document: on the live catalogue a timeout there would
    fail the deploy's migrate step."""
    shop = _supplier("shop-a")
    product = Product(id=uuid.uuid4(), group_key="single:a", title_en="a")
    await _seed(shop, product, _listing(shop, product))
    client = FakeClient()
    async with SessionLocal() as session:
        await reindex_all(session, client)
    index_documents(client, [{"id": "x"}], wait=True)

    assert TASK_TIMEOUT_MS >= 300_000
    assert client.wait_timeouts
    assert set(client.wait_timeouts) == {TASK_TIMEOUT_MS}


def test_ensure_index_says_whether_the_searchable_attributes_changed():
    """So the deploy knows the indexed documents lack what the new attributes
    search, and queues a reindex (worker.ensure_index)."""
    client = FakeClient()
    assert ensure_index(client) is True, "a new index has none of ours"
    assert ensure_index(client) is False, "applying the same settings again changes nothing"
    client.products.settings["searchableAttributes"] = ["part_number", "title_en", "brand"]
    assert ensure_index(client) is True, "an index from before the member arrays"
    assert client.wait_timeouts and set(client.wait_timeouts) == {TASK_TIMEOUT_MS}
