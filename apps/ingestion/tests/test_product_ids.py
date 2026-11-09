"""Product ids are permanent (docs/decisions/0004-stable-product-ids.md).

A product's id is a URL people share and search engines index, and projects
and price history will reference it. A regroup decides which offers belong
together; it never deletes a product or gives it a new id. It merges (the
absorbed id redirects to the survivor), splits (the core keeps the id),
empties (the page says "no longer listed") and revives, and records each in
`product_events`.

Most tests drive the real grouping. Where a test needs a rule change, it swaps
`_group_listings` for a table of title → key: the identity step is what is
under test, and the grouping heuristics have their own tests.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from makhzan_schemas import grouping
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, ProductEventKind, SourceType
from makhzan_schemas.grouping import plan_identity, rebuild_products
from makhzan_schemas.models import Listing, Product, ProductEvent, ProductRedirect, Supplier
from sqlalchemy import select, update


T0 = datetime(2026, 1, 1, tzinfo=UTC)


async def _supplier(slug: str) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    async with SessionLocal() as session:
        session.add(supplier)
        await session.commit()
    return supplier


async def _listing(
    supplier: Supplier,
    title: str,
    part_number: str | None = "SG90",
    *,
    price: int = 100,
    seen: datetime | None = None,
    external_id: str | None = None,
) -> uuid.UUID:
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        source=supplier.slug,
        source_type=SourceType.SCRAPED,
        external_id=external_id or str(uuid.uuid4()),
        title_en=title,
        # What normalisation extracts from the title; grouping keys on it.
        part_number=part_number,
        price=price,
        images=[],
        attributes={},
        first_seen_at=seen or T0,
    )
    async with SessionLocal() as session:
        session.add(listing)
        await session.commit()
    return listing.id


async def _rebuild() -> dict:
    async with SessionLocal() as session:
        return await rebuild_products(session)


async def _product_of(listing_id: uuid.UUID) -> uuid.UUID | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Listing.product_id).where(Listing.id == listing_id))


async def _product(product_id: uuid.UUID) -> Product:
    async with SessionLocal() as session:
        return await session.get(Product, product_id)


async def _products() -> dict[uuid.UUID, Product]:
    async with SessionLocal() as session:
        return {p.id: p for p in (await session.execute(select(Product))).scalars()}


async def _events() -> list[tuple[ProductEventKind, uuid.UUID, uuid.UUID | None]]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(ProductEvent))).scalars().all()
    return sorted(((e.kind, e.product_id, e.other_id) for e in rows), key=str)


async def _set_status(listing_id: uuid.UUID, status: ListingStatus) -> None:
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == listing_id).values(status=status))
        await session.commit()


def _rules(monkeypatch, table: dict[str, str]) -> None:
    """Group by a fixed title → key table instead of the real heuristics."""

    def group(listings):
        groups: dict[str, list[Listing]] = {}
        for listing in listings:
            groups.setdefault(table[listing.title_en], []).append(listing)
        return groups

    monkeypatch.setattr(grouping, "_group_listings", group)


# --- ids survive what used to replace them ---------------------------------


async def test_an_id_survives_a_second_shop_selling_the_product():
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    await _rebuild()
    alone = await _product_of(a)
    key_alone = (await _product(alone)).group_key

    b = await _listing(shop_b, "SG90 Micro Servo Motor 9g Tower Pro")
    stats = await _rebuild()

    product = await _product(alone)
    assert product.group_key != key_alone, "the test needs the group key to change"
    assert await _product_of(a) == alone
    assert await _product_of(b) == alone
    assert (product.offer_count, product.supplier_count) == (2, 2)
    assert stats["kept"] == 1 and stats["created"] == 0
    assert await _events() == []


async def test_an_id_survives_the_listing_that_named_its_key_going_away():
    shop_a, shop_b, shop_c = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    # shop-a sorts first, so its title seeds the key's words.
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    b = await _listing(shop_b, "SG90 Servo Motor 9g Tower Pro")
    c = await _listing(shop_c, "SG90 Servo Motor 9g Tower Pro Blue")
    await _rebuild()
    shared = await _product_of(b)
    assert await _product_of(a) == shared == await _product_of(c)
    key_before = (await _product(shared)).group_key

    await _set_status(a, ListingStatus.ARCHIVED)
    await _rebuild()

    assert (await _product(shared)).group_key != key_before, "the key must have changed"
    assert await _product_of(b) == shared
    assert await _product_of(c) == shared
    assert (await _product(shared)).merged_into is None
    assert await _events() == []


async def test_an_id_survives_a_rule_change_that_only_renames_keys(monkeypatch):
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    b = await _listing(shop_b, "SG90 Micro Servo Motor 9g Tower Pro")
    c = await _listing(shop_b, "MG996R Metal Gear Servo", "MG996R")
    await _rebuild()
    before = {x: await _product_of(x) for x in (a, b, c)}

    # A new rule that keys every group differently but agrees on membership:
    # the August 2026 fix re-keyed nearly every shared product this way.
    real = grouping._group_listings
    monkeypatch.setattr(
        grouping,
        "_group_listings",
        lambda listings: {f"v2|{k}": v for k, v in real(listings).items()},
    )
    stats = await _rebuild()

    assert {x: await _product_of(x) for x in (a, b, c)} == before
    assert all(p.group_key.startswith("v2|") for p in (await _products()).values())
    assert (stats["kept"], stats["created"], stats["merged"], stats["split"]) == (2, 0, 0, 0)
    assert await _events() == []


# --- merge -------------------------------------------------------------------


async def test_a_merge_keeps_the_product_with_more_offers_and_redirects_the_other(monkeypatch):
    shops = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    _rules(monkeypatch, {"Servo C": "y"})
    c = await _listing(shops[2], "Servo C")
    await _rebuild()
    older = await _product_of(c)  # older, but with one offer

    _rules(monkeypatch, {"Servo A": "x", "Servo B": "x", "Servo C": "y"})
    a = await _listing(shops[0], "Servo A")
    b = await _listing(shops[1], "Servo B")
    await _rebuild()
    larger = await _product_of(a)
    assert larger != older

    # A rule change decides all three are one product.
    _rules(monkeypatch, {"Servo A": "z", "Servo B": "z", "Servo C": "z"})
    stats = await _rebuild()

    assert {await _product_of(x) for x in (a, b, c)} == {larger}
    absorbed = await _product(older)
    assert absorbed is not None, "a merged product is never deleted"
    assert absorbed.merged_into == larger
    assert absorbed.merged_at is not None
    assert (absorbed.offer_count, absorbed.in_stock) == (0, False)
    assert (await _product(larger)).offer_count == 3
    assert stats["merged"] == 1
    assert await _events() == [(ProductEventKind.MERGE, older, larger)]


async def test_a_merge_of_equals_keeps_the_older_product(monkeypatch):
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    _rules(monkeypatch, {"Servo A": "x"})
    a = await _listing(shop_a, "Servo A")
    await _rebuild()
    first = await _product_of(a)

    _rules(monkeypatch, {"Servo A": "x", "Servo B": "y"})
    b = await _listing(shop_b, "Servo B")
    await _rebuild()
    second = await _product_of(b)
    async with SessionLocal() as session:
        # Created in the same second is plausible; make the order unambiguous.
        await session.execute(update(Product).where(Product.id == first).values(created_at=T0))
        await session.commit()

    _rules(monkeypatch, {"Servo A": "z", "Servo B": "z"})
    await _rebuild()

    assert await _product_of(b) == first
    assert (await _product(second)).merged_into == first


async def test_a_merge_repoints_every_redirect_so_each_stays_one_hop(monkeypatch):
    shops = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    _rules(monkeypatch, {"A": "a", "B": "b", "C": "c"})
    a = await _listing(shops[0], "A")
    b = await _listing(shops[1], "B")
    c = await _listing(shops[2], "C")
    await _rebuild()
    pa, pb, pc = [await _product_of(x) for x in (a, b, c)]
    # An id deleted before ids were permanent, leading to B.
    legacy = uuid.uuid4()
    async with SessionLocal() as session:
        session.add(ProductRedirect(old_id=legacy, new_id=pb))
        await session.commit()

    _rules(monkeypatch, {"A": "a", "B": "bc", "C": "bc"})
    await _rebuild()
    survivor = await _product_of(b)
    gone = pc if survivor == pb else pb

    # Two more offers already on A's product, so that it outweighs B+C's two...
    extra = [await _listing(shops[i], "A", external_id=f"a{i}") for i in (1, 2)]
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id.in_(extra)).values(product_id=pa))
        await session.commit()
    # ...and then everything is one product: the survivor of the first merge is
    # absorbed in turn.
    _rules(monkeypatch, {"A": "abc", "B": "abc", "C": "abc"})
    await _rebuild()

    products = await _products()
    assert await _product_of(b) == pa
    assert products[survivor].merged_into == pa
    assert products[gone].merged_into == pa, "the earlier merge now leads straight to A"
    async with SessionLocal() as session:
        assert (
            await session.scalar(
                select(ProductRedirect.new_id).where(ProductRedirect.old_id == legacy)
            )
            == pa
        )


async def test_a_reverted_rule_undoes_its_merge_and_gives_the_id_back(monkeypatch):
    """A rule tried and reverted, or an offer gone for a while and back, must
    not leave a product under a new id with its old one redirecting elsewhere."""
    shops = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    _rules(monkeypatch, {"A": "x", "B": "x", "C": "y"})
    a, b, c = [await _listing(shop, t) for shop, t in zip(shops, "ABC")]
    await _rebuild()
    x, y = await _product_of(a), await _product_of(c)

    _rules(monkeypatch, {"A": "xy", "B": "xy", "C": "xy"})
    await _rebuild()
    assert (await _product(y)).merged_into == x

    _rules(monkeypatch, {"A": "x", "B": "x", "C": "y"})
    stats = await _rebuild()

    assert await _product_of(c) == y
    assert (await _product_of(a), await _product_of(b)) == (x, x)
    restored = await _product(y)
    assert (restored.merged_into, restored.merged_at) == (None, None)
    assert restored.offer_count == 1
    assert (stats["created"], stats["unmerged"]) == (0, 1)
    assert await _events() == sorted(
        [
            (ProductEventKind.MERGE, y, x),
            (ProductEventKind.REVIVED, y, x),
            (ProductEventKind.SPLIT, x, y),
        ],
        key=str,
    )


# --- split -------------------------------------------------------------------


async def test_a_split_leaves_the_core_with_the_id(monkeypatch):
    shops = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    _rules(monkeypatch, {"Servo A": "x", "Servo B": "x", "Servo C": "x"})
    # A is the earliest seen, but the core is where most offers go.
    a = await _listing(shops[0], "Servo A", seen=T0)
    b = await _listing(shops[1], "Servo B", seen=T0 + timedelta(days=1))
    c = await _listing(shops[2], "Servo C", seen=T0 + timedelta(days=2))
    await _rebuild()
    original = await _product_of(a)

    _rules(monkeypatch, {"Servo A": "x1", "Servo B": "x2", "Servo C": "x2"})
    stats = await _rebuild()

    assert await _product_of(b) == original
    assert await _product_of(c) == original
    split_off = await _product_of(a)
    assert split_off not in (None, original)
    assert (await _product(original)).offer_count == 2
    assert stats["split"] == 1 and stats["created"] == 1
    assert await _events() == [(ProductEventKind.SPLIT, original, split_off)]


async def test_a_tied_split_leaves_the_id_with_the_earliest_seen_listing(monkeypatch):
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    _rules(monkeypatch, {"Servo A": "x", "Servo B": "x"})
    # Seen first despite sorting second by source.
    b = await _listing(shop_b, "Servo B", seen=T0)
    a = await _listing(shop_a, "Servo A", seen=T0 + timedelta(days=3))
    await _rebuild()
    original = await _product_of(a)

    _rules(monkeypatch, {"Servo A": "x1", "Servo B": "x2"})
    await _rebuild()

    assert await _product_of(b) == original
    assert await _product_of(a) != original


async def test_split_off_offers_join_the_product_whose_core_they_meet(monkeypatch):
    shops = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c", "shop-d")]
    _rules(monkeypatch, {"A": "p", "B": "p", "C": "p", "D": "q"})
    a, b, c, d = [await _listing(shop, title) for shop, title in zip(shops, "ABCD")]
    await _rebuild()
    p, q = await _product_of(a), await _product_of(d)

    # C now belongs with D: it leaves P for Q, and no product is created.
    _rules(monkeypatch, {"A": "p", "B": "p", "C": "q", "D": "q"})
    stats = await _rebuild()

    assert await _product_of(c) == q
    assert (await _product_of(a), await _product_of(b)) == (p, p)
    assert stats["created"] == 0
    assert await _events() == [(ProductEventKind.SPLIT, p, q)]


# --- emptied and revived -----------------------------------------------------


async def test_an_emptied_product_stays_no_longer_listed_and_revives_with_its_id():
    shop_a = await _supplier("shop-a")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g", price=85)
    await _rebuild()
    product_id = await _product_of(a)

    await _set_status(a, ListingStatus.ARCHIVED)
    stats = await _rebuild()

    emptied = await _product(product_id)
    assert emptied is not None, "a product whose offers are all gone is not deleted"
    assert emptied.delisted_at is not None
    assert (emptied.offer_count, emptied.supplier_count, emptied.in_stock) == (0, 0, False)
    # What the "no longer listed" page shows: the title and the last price seen.
    assert emptied.title_en == "SG90 Micro Servo Motor 9g"
    assert float(emptied.min_price) == 85
    assert await _product_of(a) == product_id, "the archived offer keeps its product"
    assert stats["emptied"] == 1

    # Rebuilding again changes nothing: it is emptied once.
    assert (await _rebuild())["emptied"] == 0

    await _set_status(a, ListingStatus.ACTIVE)
    stats = await _rebuild()

    assert await _product_of(a) == product_id
    revived = await _product(product_id)
    assert revived.delisted_at is None
    assert revived.offer_count == 1
    assert stats["revived"] == 1
    assert await _events() == [
        (ProductEventKind.EMPTIED, product_id, None),
        (ProductEventKind.REVIVED, product_id, None),
    ]


# --- determinism and migration -----------------------------------------------


async def test_rebuilding_twice_changes_nothing(monkeypatch):
    shops = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    _rules(monkeypatch, {"A": "x", "B": "x", "C": "y"})
    ids = [await _listing(shop, t) for shop, t in zip(shops, "ABC")]
    await _rebuild()
    _rules(monkeypatch, {"A": "x1", "B": "x2", "C": "x2"})
    await _rebuild()
    after_first = {x: await _product_of(x) for x in ids}
    events = await _events()

    stats = await _rebuild()

    assert {x: await _product_of(x) for x in ids} == after_first
    assert await _events() == events
    assert (stats["created"], stats["merged"], stats["split"], stats["emptied"]) == (0, 0, 0, 0)


def _fake_listing(name: str, seen_days: int) -> Listing:
    return Listing(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        source=f"shop-{name}",
        external_id=name,
        first_seen_at=T0 + timedelta(days=seen_days),
    )


def test_the_identity_plan_does_not_depend_on_input_order():
    """Two identical regroups decide identically, whatever order rows arrive in."""
    listings = {n: _fake_listing(n, i % 3) for i, n in enumerate("abcdefgh")}
    p, q, r = (uuid.uuid5(uuid.NAMESPACE_DNS, f"product-{n}") for n in "pqr")
    current = {
        listings["a"].id: p,
        listings["b"].id: p,
        listings["c"].id: q,
        listings["d"].id: q,
        listings["e"].id: r,
        listings["f"].id: None,
        listings["g"].id: p,
        listings["h"].id: r,
    }
    created = {p: T0, q: T0, r: T0 + timedelta(days=1)}
    groups = {"g1": ["a", "c"], "g2": ["b", "d", "e"], "g3": ["f", "g", "h"]}

    plans = []
    rng = random.Random(7)
    for _ in range(6):
        keys = list(groups)
        rng.shuffle(keys)
        shuffled = {}
        for key in keys:
            members = [listings[n] for n in groups[key]]
            rng.shuffle(members)
            shuffled[key] = members
        plan = plan_identity(shuffled, current, created, set())
        plans.append((plan.assigned, plan.merges, plan.splits, plan.emptied))

    assert all(plan == plans[0] for plan in plans)


async def test_the_first_regroup_after_the_migration_keeps_every_existing_id():
    """Rows as the previous release left them: products keyed by group key,
    listings pointing at them, one redirect from an id it deleted. The first
    regroup under permanent ids must not move a single one."""
    shop_a, shop_b, shop_c = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    b = await _listing(shop_b, "SG90 Micro Servo Motor 9g Tower Pro")
    c = await _listing(shop_c, "MG996R Metal Gear Servo", "MG996R")
    async with SessionLocal() as session:
        listings = (await session.execute(select(Listing))).scalars().all()
        groups = grouping._group_listings(listings)
        legacy_target = None
        for key, items in groups.items():
            product = Product(id=uuid.uuid4(), group_key=key, title_en=items[0].title_en)
            session.add(product)
            await session.flush()
            legacy_target = legacy_target or product.id
            for listing in items:
                listing.product_id = product.id
        legacy = uuid.uuid4()
        session.add(ProductRedirect(old_id=legacy, new_id=legacy_target))
        await session.commit()
    before = {x: await _product_of(x) for x in (a, b, c)}
    # A listing ingested since that release's last regroup has no product yet;
    # it joins the one its group already is.
    d = await _listing(await _supplier("shop-d"), "SG90 Micro Servo Motor 9g Blue")

    stats = await _rebuild()

    assert {x: await _product_of(x) for x in (a, b, c)} == before
    assert await _product_of(d) == before[a]
    assert (stats["kept"], stats["merged"], stats["split"], stats["emptied"]) == (2, 0, 0, 0)
    assert await _events() == []
    async with SessionLocal() as session:
        assert (
            await session.scalar(
                select(ProductRedirect.new_id).where(ProductRedirect.old_id == legacy)
            )
            == legacy_target
        )


async def test_events_record_what_happened_and_why(monkeypatch):
    shops = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    _rules(monkeypatch, {"A": "x", "B": "x", "C": "y"})
    a, b, c = [await _listing(shop, t) for shop, t in zip(shops, "ABC")]
    await _rebuild()
    x, y = await _product_of(a), await _product_of(c)

    _rules(monkeypatch, {"A": "xy", "B": "xy", "C": "xy"})
    await _rebuild()

    async with SessionLocal() as session:
        (event,) = (await session.execute(select(ProductEvent))).scalars().all()
    assert event.kind == ProductEventKind.MERGE
    assert (event.product_id, event.other_id) == (y, x)
    assert event.detail == {"group_key": "xy", "offers_before": 1, "survivor_offers_before": 2}
    assert event.created_at is not None


async def test_a_dry_run_reports_and_keeps_nothing(monkeypatch):
    shop_a = await _supplier("shop-a")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")

    async with SessionLocal() as session:
        stats = await rebuild_products(session, dry_run=True)

    assert stats["created"] == 1
    assert await _products() == {}
    assert await _product_of(a) is None
