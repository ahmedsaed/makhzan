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


# --- convergence and competing pairs (second review) -------------------------


def _store(listings, groups, ai):
    """What a regroup writes: each listing's product (one id per group key,
    stable across regroups) and how it got there."""
    rules = _group_listings(listings, {m.id: m.product_id for m in listings})
    via = grouping._attribute(groups, rules, ai)
    for key, members in groups.items():
        product = uuid.uuid5(uuid.NAMESPACE_URL, key)
        for member in members:
            member.product_id = product
            member.matched_via = via[member.id][0]


def _churn_case(m_shop):
    a = _mem("HCSR04 Ultrasonic Sensor Module", "shop-a", "HCSR04")
    b = _mem("HCSR04 Ultrasonic Sensor Module 3.3V", "shop-b", "HCSR04")
    r = _mem("HCSR04 Ultrasonic Sensor Module 5V", "shop-r", "HCSR04")
    r2 = _mem("HCSR04 Ultrasonic Sensor Module 5V", "shop-s", "HCSR04")
    m = _mem("Distance ranging board", m_shop)  # AI-joined to a
    return [a, b, r, m, r2], _ai((a, m))


@pytest.mark.parametrize("m_shop", ["shop-0", "shop-z"])
def test_regrouping_with_ai_members_converges_after_one_rebuild(m_shop):
    # An AI-joined listing contradicts nobody, so in pass 1 it would seed its
    # product and evict the rules core; it is kept out of incumbency, and the
    # regroup is a fixed point whichever side of the natural order it sorts.
    listings, ai = _churn_case(m_shop)
    rules = _shape(_group_listings(listings))
    first = _group_listings(listings, None, None, ai)
    _store(listings, first, ai)
    seen = [_shape(first)]
    for _ in range(4):
        again = _group_listings(listings, None, None, ai)
        _store(listings, again, ai)
        seen.append(_shape(again))
    assert all(shape == seen[0] for shape in seen), seen
    # And no rules merge was split: every rules group sits inside one group.
    final = list(seen[0].values())
    for members in rules.values():
        assert any(set(members) <= set(group) for group in final)
    a, m = listings[0], listings[3]
    assert _together(first, a, m)


def test_competing_pairs_go_by_strength_not_by_decision_id():
    x = _mem("Electrolytic capacitor", "shop-x")
    m = _mem("Cap 10uF radial", "shop-m")
    n = _mem("Cap 22uF radial", "shop-n")  # m and n conflict: x can join one
    xm, xn = pair(x.id, m.id), pair(x.id, n.id)

    def decisions(ids):
        return AiSame(
            frozenset({xm, xn}), {xm: ids[0], xn: ids[1]}, frozenset(),
            {xm: (0.99, 0.9), xn: (0.97, 0.95)},
        )  # fmt: skip

    first = _group_listings([x, m, n], None, None, decisions((1, 2)))
    assert _together(first, x, m)  # x-m is the stronger decision
    _store([x, m, n], first, decisions((1, 2)))
    # x-m re-scored: a new standing row, a new id, the same strength.
    again = _group_listings([x, m, n], None, None, decisions((3, 2)))
    assert _shape(again) == _shape(first)


def test_the_stronger_pair_wins_whichever_decision_is_older():
    x = _mem("Electrolytic capacitor", "shop-x")
    m = _mem("Cap 10uF radial", "shop-m")
    n = _mem("Cap 22uF radial", "shop-n")
    xm, xn = pair(x.id, m.id), pair(x.id, n.id)
    for ids in ((1, 2), (2, 1)):
        ai = AiSame(
            frozenset({xm, xn}), {xm: ids[0], xn: ids[1]}, frozenset(),
            {xm: (0.96, 0.9), xn: (0.99, 0.81)},
        )  # fmt: skip
        assert _together(_group_listings([x, m, n], None, None, ai), x, n)


async def test_a_live_regroup_is_a_fixed_point_with_ai_members_on_both_sides():
    shops = {s: await _supplier(s) for s in ("shop-0", "shop-a", "shop-b", "shop-r", "shop-z")}
    a = await _listing(shops["shop-a"], "HCSR04 Ultrasonic Sensor Module", "HCSR04")
    await _listing(shops["shop-b"], "HCSR04 Ultrasonic Sensor Module 3.3V", "HCSR04")
    await _listing(shops["shop-r"], "HCSR04 Ultrasonic Sensor Module 5V", "HCSR04")
    early = await _listing(shops["shop-0"], "Distance ranging board")
    late = await _listing(shops["shop-z"], "Sonar module board")
    await _rebuild()
    await _same(a, early)
    await _same(early, late)
    await _mode("live")
    await _rebuild()
    for _ in range(3):
        stats = await _rebuild()
        assert (stats["created"], stats["merged"], stats["split"]) == (0, 0, 0)
    ra, re_, rl = await _rows(a, early, late)
    assert ra.product_id == re_.product_id == rl.product_id
    assert (re_.matched_via, rl.matched_via) == ("ai", "ai")


def test_a_pair_with_no_known_strength_sorts_last():
    x = _mem("Electrolytic capacitor", "shop-x")
    m = _mem("Cap 10uF radial", "shop-m")
    n = _mem("Cap 22uF radial", "shop-n")
    xm, xn = pair(x.id, m.id), pair(x.id, n.id)
    # x-m has no rank: it must not outrank x-n, however weak x-n is.
    ai = AiSame(frozenset({xm, xn}), {xm: 1, xn: 2}, frozenset(), {xn: (0.01,)})
    assert _together(_group_listings([x, m, n], None, None, ai), x, n)


# --- what a live regroup found of each decision (ai_decisions.effect) -------


async def _decision(x, y, *, outcome="same", kev=0.9, pplx=0.97, state="standing") -> int:
    a, b = pair(x, y)
    row = AiDecision(
        pipeline="match",
        listing_a=a,
        listing_b=b,
        outcome=outcome,
        decided_by="pplx",
        scores={
            "kev": {"model": "kev", "ab": kev, "ba": kev, "min": kev},
            "pplx": {"model": "pplx", "ab": pplx, "ba": pplx, "min": pplx},
        },
        policy_version="p1",
        content_sha256_a=b"\0" * 32,
        content_sha256_b=b"\0" * 32,
        state=state,
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _effects() -> dict[int, tuple[str | None, str | None, datetime | None]]:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(
                AiDecision.id, AiDecision.effect, AiDecision.blocked_reason, AiDecision.checked_at
            )
        )
        return {i: (effect, reason, at) for i, effect, reason, at in rows}


async def _set(listing_id, **values) -> None:
    async with SessionLocal() as session:
        row = await session.get(Listing, listing_id)
        for key, value in values.items():
            setattr(row, key, value)
        await session.commit()


async def test_a_live_regroup_writes_each_same_decisions_effect():
    from makhzan_schemas.enums import ListingStatus
    from makhzan_schemas.models import GroupingOverride

    shop_a, shop_b, shop_c = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    # In effect by AI: titles the rules keep apart.
    ai_a = await _listing(shop_a, "Example ultrasonic ranging sensor")
    ai_b = await _listing(shop_b, "Distance meter board, sonar")
    # In effect already by the rules: one identifier, identical titles.
    rules_a = await _listing(shop_a, "Example gear motor XQ130", "XQ130")
    rules_b = await _listing(shop_b, "Example gear motor XQ130", "XQ130")
    # Blocked by the AI phase: values (5 V against 12 V).
    v_a = await _listing(shop_a, "Example relay board 5V")
    v_b = await _listing(shop_b, "Switching module 12V")
    # Blocked by the AI phase: a Kev confident no with a rules-merged member.
    k_x = await _listing(shop_a, "Example rotary knob encoder")
    k_y = await _listing(shop_b, "Example servo tester ZT48", "ZT48")
    k_z = await _listing(shop_c, "Example servo tester ZT48", "ZT48")
    # Blocked before the phase: one shop's two listings.
    s_a = await _listing(shop_c, "Example tilt switch")
    s_b = await _listing(shop_c, "Ball vibration sensor")
    # Not mutual best: n_x's stronger match in shop B is n_y, so n_x / n_w is not read.
    n_x = await _listing(shop_c, "Example infrared receiver")
    n_y = await _listing(shop_b, "IR sensor head")
    n_w = await _listing(shop_b, "Remote control eye")
    # Inactive: an archived listing, and one outside the served departments.
    gone_a = await _listing(shop_a, "Example buzzer active")
    gone_b = await _listing(shop_b, "Beeper module")
    dom_a = await _listing(shop_a, "Example spanner set")
    dom_b = await _listing(shop_b, "Wrench kit")
    # Overridden: a person ruled the pair apart.
    o_a = await _listing(shop_a, "Example joystick module")
    o_b = await _listing(shop_b, "Thumb stick board")
    await _rebuild()
    await _set(gone_b, status=ListingStatus.ARCHIVED)
    await _set(dom_b, domain="tools")
    async with SessionLocal() as session:
        lo, hi = pair(o_a, o_b)
        session.add(
            GroupingOverride(
                listing_a=lo,
                listing_b=hi,
                kind=rulings.NEVER,
                source="manual",
                note="test",
                created_by="test",
            )
        )
        await session.commit()

    ids = {
        "ai": await _decision(ai_a, ai_b),
        "rules": await _decision(rules_a, rules_b),
        "values": await _decision(v_a, v_b),
        "kev": await _decision(k_x, k_y),
        "shop": await _decision(s_a, s_b),
        "best": await _decision(n_x, n_y, pplx=0.99),
        "second": await _decision(n_x, n_w, pplx=0.95),
        "gone": await _decision(gone_a, gone_b),
        "domain": await _decision(dom_a, dom_b),
        "ruled": await _decision(o_a, o_b),
        "stale": await _decision(ai_a, rules_b, state="stale"),
    }
    no = await _decision(k_x, k_z, outcome="not_same", kev=0.01)
    await _mode("live")
    stats = await _rebuild()
    found = await _effects()
    want = {
        "ai": ("in_effect", None),
        "rules": ("in_effect", None),
        "values": ("blocked", "values"),
        "kev": ("blocked", "Kev floor"),
        "shop": ("blocked", "same shop"),
        "best": ("in_effect", None),
        "second": ("blocked", "not mutual best"),
        "gone": ("inactive", None),
        "domain": ("inactive", None),
        "ruled": ("overridden", None),
        "stale": ("inactive", None),
    }
    assert {name: found[i][:2] for name, i in ids.items()} == want
    assert all(found[i][2] is not None for i in ids.values())
    # A "not same" decision has no effect to record.
    assert found[no] == (None, None, None)
    assert stats["ai_effects"] == {"in_effect": 3, "blocked": 4, "inactive": 2, "overridden": 1}


async def test_a_dry_run_or_an_off_regroup_writes_no_effect():
    a, b = await _two_products()
    decision = await _decision(a, b)
    await _rebuild()  # mode off
    assert (await _effects())[decision] == (None, None, None)
    await _rebuild(dry_run=True, ai_preview=True)
    assert (await _effects())[decision] == (None, None, None)
    await _mode("live")
    stats = await _rebuild(dry_run=True)
    assert "ai_effects" not in stats and stats["merged"] == 1
    assert (await _effects())[decision] == (None, None, None)
    await _rebuild()
    assert (await _effects())[decision][:2] == ("in_effect", None)


def test_the_ai_phase_names_the_veto_it_refused_and_groups_as_without_it():
    x = _mem("Example relay board 5V", "shop-a")
    y = _mem("Switching module 12V", "shop-b")
    u = _mem("Example ultrasonic ranging sensor", "shop-a")
    v = _mem("Distance meter board, sonar", "shop-b")
    listings = [x, y, u, v]
    ai = _ai((x, y), (u, v))
    refused: dict = {}
    with_refused = _group_listings(listings, None, Overrides(), ai, refused)
    assert _shape(with_refused) == _shape(_group_listings(listings, None, Overrides(), ai))
    assert refused == {pair(x.id, y.id): "values"}
    assert _together(with_refused, u, v)
