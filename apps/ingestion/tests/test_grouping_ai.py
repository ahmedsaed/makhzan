"""The regroup and AI "same" decisions.

An AI "same" pair acts last: once the rules and the rulings have formed every
cluster, it may join two whole clusters. Every one of today's vetoes still
applies against every member, a person's ruling wins, and a Kev confident no
between any two members blocks the join (P14) but never splits what the rules
merged; the outcome does not depend on placement order. Decisions are read
only in `live` mode, or in a dry run's preview; with none, grouping is exactly
what it was. The shops and listings here are fictional.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from makhzan_schemas import grouping
from makhzan_schemas import overrides as rulings
from makhzan_schemas.ai.decisions import AiSame
from makhzan_schemas.ai.mode import set_ai_mode
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ProductEventKind, SourceType
from makhzan_schemas.grouping import _group_listings, rebuild_products
from makhzan_schemas.matching import matched_by
from makhzan_schemas.models import AiDecision, Listing, ProductEvent, Supplier
from makhzan_schemas.overrides import Overrides, pair
from sqlalchemy import select

T0 = datetime(2026, 1, 1, tzinfo=UTC)

# --- in memory --------------------------------------------------------------

_SHOPS: dict[str, uuid.UUID] = {}


def _mem(title, source, part_number=None, price=180, product=None, external_id=None):
    return Listing(
        id=uuid.uuid4(),
        supplier_id=_SHOPS.setdefault(source, uuid.uuid4()),
        source=source,
        source_type=SourceType.SCRAPED,
        external_id=external_id or str(uuid.uuid4()),
        domain="electronics",
        title_en=title,
        part_number=part_number,
        price=Decimal(str(price)),
        images=[],
        attributes={},
        product_id=product,
    )


def _ai(*pairs, no=()) -> AiSame:
    keys = [pair(a.id, b.id) for a, b in pairs]
    return AiSame(
        frozenset(keys),
        {k: i + 1 for i, k in enumerate(keys)},
        frozenset(pair(a.id, b.id) for a, b in no),
    )


def _together(groups, *listings) -> bool:
    return any(all(x in members for x in listings) for members in groups.values())


def _shape(groups) -> dict:
    return {key: sorted(str(m.id) for m in members) for key, members in groups.items()}


def test_an_ai_pair_joins_two_listings_the_rules_keep_apart():
    a = _mem("Example ultrasonic ranging sensor", "shop-a")
    b = _mem("Distance meter board, sonar", "shop-b")
    assert not _together(_group_listings([a, b]), a, b)
    assert _together(_group_listings([a, b], None, None, _ai((a, b))), a, b)


def test_an_ai_pair_across_two_identifiers_joins_only_its_own_listings():
    a = _mem("ABC123 example timer chip", "shop-a", "ABC123")
    b = _mem("XYZ789 example timer chip", "shop-b", "XYZ789")
    c = _mem("XYZ789 example timer chip", "shop-c", "XYZ789")
    groups = _group_listings([a, b, c], None, None, _ai((a, b)))
    assert _together(groups, a, b, c)  # c joins b on its title, within its own key
    d = _mem("ABC123 example timer chip", "shop-d", "ABC123")
    e = _mem("XYZ789 example timer chip", "shop-e", "XYZ789")
    groups = _group_listings([a, d, e], None, None, _ai((a, b)))
    # Without the pair inside the group, titles never join two keys.
    assert not _together(groups, d, e)


@pytest.mark.parametrize(
    "first, second",
    [
        # The value veto: 10 uF against 22 uF.
        (("Example capacitor 10uF", 100), ("Example capacitor 22uF", 100)),
        # The price veto, at today's 4x.
        (("Example relay board", 10), ("Example relay module board", 100)),
    ],
)
def test_todays_vetoes_still_apply_to_an_ai_pair(first, second):
    a = _mem(first[0], "shop-a", price=first[1])
    b = _mem(second[0], "shop-b", price=second[1])
    assert not _together(_group_listings([a, b], None, None, _ai((a, b))), a, b)


def test_one_shops_two_listings_never_merge_on_an_ai_pair():
    a = _mem("Example sensor", "shop-a")
    b = _mem("Example sensor board", "shop-a")
    assert not _together(_group_listings([a, b], None, None, _ai((a, b))), a, b)


def test_a_persons_never_merge_beats_an_ai_pair():
    a = _mem("Example sensor", "shop-a")
    b = _mem("Sonar board", "shop-b")
    never = Overrides(never=frozenset({pair(a.id, b.id)}))
    assert not _together(_group_listings([a, b], None, never, _ai((a, b))), a, b)


def _rules_pair():
    a = _mem("HCSR04 Ultrasonic Sensor Module", "shop-a", "HCSR04")
    b = _mem("HCSR04 Ultrasonic Sensor Module", "shop-b", "HCSR04")
    return a, b


def test_a_kev_no_with_any_member_blocks_an_ai_join():
    a, b = _rules_pair()
    x = _mem("Distance ranging board", "shop-c")
    assert _together(_group_listings([a, b, x], None, None, _ai((x, a))), a, b, x)
    blocked = _group_listings([a, b, x], None, None, _ai((x, a), no=[(x, b)]))
    assert _together(blocked, a, b) and not _together(blocked, a, x)


def test_a_kev_no_never_splits_what_the_rules_merged():
    a, b = _rules_pair()
    x = _mem("Distance ranging board", "shop-c")
    groups = _group_listings([a, b, x], None, None, _ai((x, a), no=[(a, b)]))
    assert _together(groups, a, b, x)
    # And a rules join with a Kev no inside it, with an AI pair elsewhere.
    c = _mem("HCSR04 Ultrasonic Sensor Module", "shop-d", "HCSR04")
    groups = _group_listings([a, b, c, x], None, None, _ai((x, a), no=[(c, x), (c, a)]))
    assert _together(groups, a, b, c)


@pytest.mark.parametrize("x_shop", ["shop-0", "shop-z"])
def test_the_group_check_does_not_depend_on_which_shop_sorts_first(x_shop):
    # X's AI pair is with M; its Kev no is with N, M's rules partner. Whether
    # X sorts before or after them, from scratch, X stays out.
    m = _mem("HCSR04 Ultrasonic Sensor Module", "shop-m", "HCSR04")
    n = _mem("HCSR04 Ultrasonic Sensor Module", "shop-n", "HCSR04")
    x = _mem("Distance ranging board", x_shop)
    groups = _group_listings([m, n, x], None, None, _ai((x, m), no=[(x, n)]))
    assert _together(groups, m, n) and not _together(groups, m, x)


@pytest.mark.parametrize("x_shop", ["shop-0", "shop-z"])
def test_from_scratch_and_incremental_agree(x_shop):
    m = _mem("HCSR04 Ultrasonic Sensor Module", "shop-m", "HCSR04")
    n = _mem("HCSR04 Ultrasonic Sensor Module", "shop-n", "HCSR04")
    x = _mem("Distance ranging board", x_shop)
    y = _mem("Sonar distance board", "shop-y")
    listings = [m, n, x, y]
    for ai in (_ai((x, m), (y, x)), _ai((x, m), (y, x), no=[(x, n)]), _ai((y, n), no=[(y, m)])):
        scratch = _group_listings(listings, None, None, ai)
        # Store what the first regroup decided, then regroup again from it.
        for key, members in scratch.items():
            product = uuid.uuid5(uuid.NAMESPACE_URL, key)
            for member in members:
                member.product_id = product
        incremental = _group_listings(listings, None, None, ai)
        assert _shape(incremental) == _shape(scratch)
        # And from products the rules alone made.
        for member in listings:
            member.product_id = None
        rules_first = {k: v for k, v in _group_listings(listings).items()}
        for key, members in rules_first.items():
            for member in members:
                member.product_id = uuid.uuid5(uuid.NAMESPACE_URL, "rules" + key)
        assert _shape(_group_listings(listings, None, None, ai)) == _shape(scratch)
        for member in listings:
            member.product_id = None


@pytest.mark.parametrize("x_shop", ["shop-0", "shop-z"])
def test_a_kev_no_that_arrives_after_an_ai_merge_undoes_only_that_merge(x_shop):
    product = uuid.uuid4()
    m = _mem("HCSR04 Ultrasonic Sensor Module", "shop-m", "HCSR04", product=product)
    n = _mem("HCSR04 Ultrasonic Sensor Module", "shop-n", "HCSR04", product=product)
    x = _mem("Distance ranging board", x_shop, product=product)  # joined by AI earlier
    groups = _group_listings([m, n, x], None, None, _ai((x, m), no=[(x, n)]))
    assert _together(groups, m, n) and not _together(groups, m, x)
    # Without the no, the AI-joined product stands.
    assert _together(_group_listings([m, n, x], None, None, _ai((x, m))), m, n, x)


def test_an_existing_product_wins_over_an_ai_pair_that_contradicts_it():
    product = uuid.uuid4()
    a = _mem("HCSR04 Ultrasonic Sensor Module", "shop-a", "HCSR04", product=product)
    b = _mem("HCSR04 Ultrasonic Sensor Module", "shop-b", "HCSR04", product=product)
    x = _mem("Distance ranging board", "shop-b")  # b's own shop
    groups = _group_listings([a, b, x], None, None, _ai((x, a)))
    assert _together(groups, a, b) and not _together(groups, a, x)


def test_with_no_ai_pair_grouping_is_byte_for_byte_what_it_was():
    product = uuid.uuid4()
    listings = [
        _mem("ESP32 Development Board 30 pin", "shop-a", "ESP32", 300, product),
        _mem("ESP32 Development Board 30 pin", "shop-b", "ESP32", 320, product),
        _mem("ESP32 Development Board 38 pin", "shop-c", "ESP32", 330),
        _mem("Bracket for SG90 servo", "shop-a", "SG90", 20),
        _mem("SG90 Micro Servo 9g", "shop-b", "SG90", 60),
        _mem("SG90 servo motor", "shop-c", "SG90", 65),
        _mem("Plain resistor pack", "shop-d"),
    ]
    never = Overrides(never=frozenset({pair(listings[4].id, listings[5].id)}))
    for overrides in (None, never):
        want = _shape(_group_listings(listings, None, overrides))
        # An empty set, or Kev "no" pairs alone, change nothing at all.
        for ai in (AiSame(), _ai(no=[(listings[0], listings[2])])):
            assert _shape(_group_listings(listings, None, overrides, ai)) == want


def test_attribution_names_the_core_rules_and_the_rest_ai():
    a, b = _rules_pair()
    x = _mem("Distance ranging board", "shop-c")
    y = _mem("Sonar distance board", "shop-d")
    ai = _ai((x, a), (y, x))
    groups = _group_listings([a, b, x, y], None, None, ai)
    rules = _group_listings([a, b, x, y])
    got = grouping._attribute(groups, rules, ai)
    assert got[a.id] == got[b.id] == ("rules", None)
    assert got[x.id] == ("ai", ai.ids[pair(x.id, a.id)])
    assert got[y.id] == ("ai", ai.ids[pair(y.id, x.id)])  # reached through x


# --- the regroup, against the database --------------------------------------


async def _supplier(slug: str) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    async with SessionLocal() as session:
        session.add(supplier)
        await session.commit()
    return supplier


async def _listing(supplier, title, part_number=None, *, price=180, seen=T0) -> uuid.UUID:
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        source=supplier.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        title_en=title,
        part_number=part_number,
        price=price,
        images=[],
        attributes={},
        first_seen_at=seen,
    )
    async with SessionLocal() as session:
        session.add(listing)
        await session.commit()
    return listing.id


async def _same(x, y) -> int:
    a, b = pair(x, y)
    row = AiDecision(
        pipeline="match",
        listing_a=a,
        listing_b=b,
        outcome="same",
        decided_by="pplx",
        scores={
            "kev": {"model": "kev", "ab": 0.9, "ba": 0.9, "min": 0.9},
            "pplx": {"model": "pplx", "ab": 0.98, "ba": 0.97, "min": 0.97},
        },
        policy_version="p1",
        content_sha256_a=b"\0" * 32,
        content_sha256_b=b"\0" * 32,
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _mode(mode: str) -> None:
    async with SessionLocal() as session:
        await set_ai_mode(session, mode)
        await session.commit()


async def _rebuild(**kw) -> dict:
    async with SessionLocal() as session:
        return await rebuild_products(session, **kw)


async def _rows(*ids) -> list[Listing]:
    async with SessionLocal() as session:
        found = {r.id: r for r in await session.scalars(select(Listing).where(Listing.id.in_(ids)))}
    return [found[i] for i in ids]


async def _events() -> list[ProductEvent]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(ProductEvent).order_by(ProductEvent.id)))


async def _two_products():
    a = await _listing(await _supplier("shop-a"), "Example ultrasonic ranging sensor")
    b = await _listing(
        await _supplier("shop-b"), "Distance meter board, sonar", seen=T0 + timedelta(days=1)
    )
    await _rebuild()
    return a, b


async def test_a_live_same_decision_merges_cites_itself_and_marks_the_listing_ai():
    a, b = await _two_products()
    ra, rb = await _rows(a, b)
    assert ra.product_id != rb.product_id
    # NULL reads as "rules": the regroup does not write it to say so.
    assert (ra.matched_via, rb.matched_via) == (None, None)
    assert matched_by([ra, rb]) == {a: "rules", b: "rules"}
    decision = await _same(a, b)
    await _mode("live")
    stats = await _rebuild()
    assert (stats["merged"], stats["ai_pairs"], stats["ai_admitted"]) == (1, 1, 1)
    ra2, rb2 = await _rows(a, b)
    assert ra2.product_id == rb2.product_id
    assert ra2.product_id in {ra.product_id, rb.product_id}  # an existing id survives
    assert (ra2.matched_via, ra2.matched_ai_decision_id) == (None, None)  # reads as rules
    assert (rb2.matched_via, rb2.matched_ai_decision_id) == ("ai", decision)
    assert matched_by([ra2, rb2]) == {a: "rules", b: "ai"}
    (merge,) = [e for e in await _events() if e.kind == ProductEventKind.MERGE]
    assert merge.detail["ai_decisions"] == [decision]
    # One rebuild converges: the next changes nothing and cites nothing more.
    before = len(await _events())
    stats = await _rebuild()
    assert (stats["created"], stats["merged"], stats["split"]) == (0, 0, 0)
    assert len(await _events()) == before


async def test_going_back_to_off_undoes_every_ai_merge():
    a, b = await _two_products()
    await _same(a, b)
    await _mode("live")
    await _rebuild()
    await _mode("off")
    stats = await _rebuild()
    ra, rb = await _rows(a, b)
    assert ra.product_id != rb.product_id and stats["split"] == 1
    assert (rb.matched_via, rb.matched_ai_decision_id) == ("rules", None)


async def test_decisions_are_ignored_unless_live():
    a, b = await _two_products()
    await _same(a, b)
    stats = await _rebuild()  # mode: off by default
    assert stats["merged"] == 0 and "ai_pairs" not in stats
    await _mode("live")
    assert (await _rebuild())["merged"] == 1


async def test_the_preview_reads_decisions_while_off_in_a_dry_run_only():
    a, b = await _two_products()
    await _same(a, b)
    stats = await _rebuild(dry_run=True, ai_preview=True)
    assert (stats["merged"], stats["ai_mode"], stats["ai_admitted"]) == (1, "preview", 1)
    ra, rb = await _rows(a, b)
    assert ra.product_id != rb.product_id  # rolled back
    with pytest.raises(ValueError):
        await _rebuild(ai_preview=True)


async def test_a_rebuild_with_no_decisions_is_identical_in_every_mode(monkeypatch):
    shop_a, shop_b, shop_c = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    for shop in (shop_a, shop_b):
        await _listing(shop, "HCSR04 Ultrasonic Sensor Module", "HCSR04")
        await _listing(shop, "ESP32 Development Board 30 pin", "ESP32", price=300)
    await _listing(shop_c, "ESP32 Development Board 38 pin", "ESP32", price=310)
    await _listing(shop_c, "Bracket for HCSR04", "HCSR04", price=15)
    async with SessionLocal() as session:
        ids = list(await session.scalars(select(Listing.id)))
        await rulings.add(session, ids[0], ids[1], rulings.NEVER, created_by="t", note="t")
        await session.commit()

    seen = []
    original = grouping.plan_identity

    def spy(groups, *args, **kwargs):
        seen.append(_shape(groups))
        return original(groups, *args, **kwargs)

    monkeypatch.setattr(grouping, "plan_identity", spy)
    results = []
    for mode in ("off", "live"):
        await _mode(mode)
        stats = await _rebuild(dry_run=True)
        results.append({k: v for k, v in stats.items() if k != "ai_mode"})
    assert seen[0] == seen[1]
    assert results[0] == results[1]


async def test_the_api_offer_answer_follows_the_column():
    a, b = await _two_products()
    await _same(a, b)
    await _mode("live")
    await _rebuild()
    assert matched_by(await _rows(a, b)) == {a: "rules", b: "ai"}


async def test_the_largest_ai_product_counts_only_products_ai_joined():
    a, b = await _two_products()
    big = [await _supplier(f"shop-{c}") for c in "pqrs"]
    for shop in big:  # a four-offer product the rules alone made
        await _listing(shop, "HCSR04 Ultrasonic Sensor Module", "HCSR04")
    await _rebuild()
    await _same(a, b)
    stats = await _rebuild(dry_run=True, ai_preview=True)
    assert stats["ai_largest"] == 2
