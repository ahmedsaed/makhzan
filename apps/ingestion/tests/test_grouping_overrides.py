"""Grouping overrides: a person's ruling outranks the rules.

A never_merge pair is one more veto between two listings; a must_merge pair
admits two listings to one product without title agreement or a shared
identifier, every veto still applying unless forced, and the same shop never
merging at all. The regroup is the only writer, every product a ruling changes
cites it in `product_events`, and accepting a grouping report writes the
rulings it stands for.

The shops here are fictional.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from makhzan_schemas import overrides as rulings
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ProductEventKind, SourceType
from makhzan_schemas.grouping import _group_listings, rebuild_products
from makhzan_schemas.models import GroupingOverride, Listing, ProductEvent, Report, Supplier
from makhzan_schemas.overrides import Overrides, load_overrides, pair
from sqlalchemy import select

from worker import overrides as overrides_cli
from worker import reports as reports_cli

T0 = datetime(2026, 1, 1, tzinfo=UTC)

#: The pair every AI judge calls the same, and which is not: the -PU is the
#: older, non-picoPower die. In the live catalogue the two read different
#: identifiers (ATMEGA328 / ATMEGA328P), so the rules keep them apart already;
#: here both state "ATMEGA328" and the same description, so the rules alone
#: would merge them and only the ruling can keep them apart.
ATMEGA_PU = "ATMEGA328-PU 8bit AVR Microcontroller, 20MHz, 32 kB Flash, 28-Pin PDIP"
ATMEGA_P = "ATMega328P 8bit AVR Microcontroller, 20MHz, 32 kB Flash, 28-Pin PDIP"


# --- the rules, in memory ---------------------------------------------------

_SUPPLIERS: dict[str, uuid.UUID] = {}


def _mem(title, source, part_number=None, price=180):
    return Listing(
        id=uuid.uuid4(),
        supplier_id=_SUPPLIERS.setdefault(source, uuid.uuid4()),
        source=source,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        domain="electronics",
        title_en=title,
        part_number=part_number,
        price=Decimal(str(price)),
        images=[],
        attributes={},
    )


def _together(groups, *listings) -> bool:
    return any(all(x in members for x in listings) for members in groups.values())


def _never(*pairs) -> Overrides:
    return Overrides(never=frozenset(pair(a.id, b.id) for a, b in pairs))


def _must(*pairs, forced=False) -> Overrides:
    must = frozenset(pair(a.id, b.id) for a, b in pairs)
    return Overrides(must=must, forced=must if forced else frozenset())


def test_never_merge_keeps_apart_what_the_rules_would_merge():
    a = _mem(ATMEGA_PU, "shop-a", "ATMEGA328")
    b = _mem(ATMEGA_P, "shop-b", "ATMEGA328")
    assert _together(_group_listings([a, b]), a, b)
    assert not _together(_group_listings([a, b], None, _never((a, b))), a, b)


def test_never_merge_is_checked_against_every_member():
    """A third listing that agrees with both cannot chain the pair together."""
    a = _mem("SG90 Micro Servo 9g", "shop-a", "SG90")
    b = _mem("SG90 Micro Servo 9g", "shop-b", "SG90")
    c = _mem("SG90 Micro Servo 9g", "shop-c", "SG90")
    groups = _group_listings([a, b, c], None, _never((a, b)))
    assert not _together(groups, a, b)
    assert _together(groups, a, c) or _together(groups, b, c)


def test_must_merge_admits_without_a_shared_identifier_or_title():
    a = _mem("ATMEGA328 AVR Microcontroller", "shop-a", "ATMEGA328")
    b = _mem("Arduino brain chip, DIP", "shop-b", None)
    assert not _together(_group_listings([a, b]), a, b)
    assert _together(_group_listings([a, b], None, _must((a, b))), a, b)


def test_must_merge_does_not_let_two_codes_merge_on_their_titles():
    """Joining two identifiers' groups for one ruling admits that pair only:
    the rest of each group still needs its own identifier to merge."""
    a = _mem("ESP32 WROOM", "shop-a", "ESP32")
    b = _mem("ESP8266 NodeMCU", "shop-b", "ESP8266")
    c = _mem("ESP32 Development Board WiFi", "shop-c", "ESP32")
    d = _mem("ESP8266 Development Board WiFi", "shop-d", "ESP8266")
    ruled = _group_listings([a, b, c, d], None, _must((a, b)))
    assert _together(ruled, a, b)
    # c and d agree on every word, but read different codes: no ruling joins them.
    assert not _together(ruled, c, d)


def test_what_matches_a_ruled_pair_joins_it():
    """Sameness is transitive: a listing the rules put with one side of a
    must_merge is in the product the ruling made."""
    a = _mem("ESP32 Development Board WiFi", "shop-a", "ESP32")
    b = _mem("ESP8266 Development Board WiFi", "shop-b", "ESP8266")
    c = _mem("ESP32 Development Board WiFi", "shop-c", "ESP32")
    plain = _group_listings([a, b, c])
    ruled = _group_listings([a, b, c], None, _must((a, b)))
    assert _together(plain, a, c) and not _together(plain, a, b)
    assert _together(ruled, a, b, c)


def test_unforced_must_merge_still_obeys_the_vetoes():
    a = _mem("ESP32 Development Board 30 pin", "shop-a", "ESP32")
    b = _mem("ESP32 Development Board 38 pin", "shop-b", "ESP32")
    assert not _together(_group_listings([a, b], None, _must((a, b))), a, b)
    assert _together(_group_listings([a, b], None, _must((a, b), forced=True)), a, b)


def test_a_forced_pair_drags_no_third_listing_past_a_veto():
    a = _mem("ESP32 Development Board 30 pin", "shop-a", "ESP32")
    b = _mem("ESP32 Development Board 38 pin", "shop-b", "ESP32")
    c = _mem("ESP32 Development Board 38 pin", "shop-c", "ESP32")
    groups = _group_listings([a, b, c], None, _must((a, b), forced=True))
    assert _together(groups, a, b)
    assert not _together(groups, a, c)


def test_forced_must_merge_is_past_the_price_veto_too():
    a = _mem("Relay Module 5V 1 Channel", "shop-a", "SRD05VDC", price=40)
    b = _mem("Relay Module 5V 1 Channel", "shop-b", "SRD05VDC", price=900)
    assert not _together(_group_listings([a, b], None, _must((a, b))), a, b)
    assert _together(_group_listings([a, b], None, _must((a, b), forced=True)), a, b)


def test_the_same_shop_never_merges_even_when_forced():
    a = _mem("SG90 Micro Servo 9g", "shop-a", "SG90")
    b = _mem("SG90 Micro Servo 9g blue", "shop-a", "SG90")
    assert not _together(_group_listings([a, b], None, _must((a, b), forced=True)), a, b)


def test_a_ruling_that_changes_nothing_changes_no_key():
    """A listing left alone by a must_merge the vetoes refuse keeps the key it
    had without the ruling, and so does every group nobody ruled on."""
    a = _mem("ESP32 Development Board 30 pin", "shop-a", "ESP32")
    b = _mem("Relay board 38 pin", "shop-b", None)
    c = _mem("SG90 Micro Servo 9g", "shop-c", "SG90")
    d = _mem("SG90 Micro Servo 9g", "shop-d", "SG90")
    plain = _group_listings([a, b, c, d])
    ruled = _group_listings([a, b, c, d], None, _must((a, b)))
    assert {k: {x.id for x in v} for k, v in plain.items()} == {
        k: {x.id for x in v} for k, v in ruled.items()
    }


def test_the_loaded_set_answers_in_either_order():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = [
        GroupingOverride(id=1, listing_a=min(a, b), listing_b=max(a, b), kind=rulings.NEVER),
        GroupingOverride(
            id=2, listing_a=min(a, c), listing_b=max(a, c), kind=rulings.MUST, forced=True
        ),
    ]
    loaded = Overrides.of(rows)
    assert loaded.kind(b, a) == loaded.kind(a, b) == rulings.NEVER
    assert loaded.kind(c, a) == rulings.MUST and loaded.is_forced(c, a)
    assert loaded.kind(b, c) is None
    assert loaded.ids[pair(c, a)] == 2


# --- the regroup, against the database --------------------------------------


async def _supplier(slug: str) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    async with SessionLocal() as session:
        session.add(supplier)
        await session.commit()
    return supplier


async def _listing(
    supplier: Supplier, title: str, part_number: str | None, *, price=180, seen=T0
) -> uuid.UUID:
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


async def _rebuild() -> dict:
    async with SessionLocal() as session:
        return await rebuild_products(session)


async def _product_of(listing_id: uuid.UUID) -> uuid.UUID | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Listing.product_id).where(Listing.id == listing_id))


async def _events() -> list[ProductEvent]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(ProductEvent).order_by(ProductEvent.created_at)))


async def _add(a, b, kind, **kw) -> GroupingOverride:
    async with SessionLocal() as session:
        added = await rulings.add(session, a, b, kind, created_by="test", note="test", **kw)
        await session.commit()
        return added.row


async def test_the_atmega_pair_splits_under_a_ruling_and_rejoins_without_it():
    a = await _listing(await _supplier("shop-a"), ATMEGA_PU, "ATMEGA328")
    b = await _listing(await _supplier("shop-b"), ATMEGA_P, "ATMEGA328")
    await _rebuild()
    merged = await _product_of(a)
    assert merged == await _product_of(b)

    ruling = await _add(a, b, rulings.NEVER)
    stats = await _rebuild()
    assert await _product_of(a) != await _product_of(b)
    assert stats["split"] == 1
    # The product keeps its id on the earliest-seen side, and the split cites
    # the ruling that made it.
    (split,) = [e for e in await _events() if e.kind == ProductEventKind.SPLIT]
    assert split.product_id == merged
    assert split.detail["overrides"] == [ruling.id]

    async with SessionLocal() as session:
        await rulings.remove(session, ruling.id)
        await session.commit()
    stats = await _rebuild()
    assert await _product_of(a) == await _product_of(b) == merged
    assert stats["merged"] == 1


async def test_a_ruling_survives_every_later_rebuild():
    a = await _listing(await _supplier("shop-a"), ATMEGA_PU, "ATMEGA328")
    b = await _listing(await _supplier("shop-b"), ATMEGA_P, "ATMEGA328")
    await _add(a, b, rulings.NEVER)
    await _rebuild()
    apart = (await _product_of(a), await _product_of(b))
    assert apart[0] != apart[1]
    before = len(await _events())
    for _ in range(2):
        stats = await _rebuild()
        assert (await _product_of(a), await _product_of(b)) == apart
        assert (stats["created"], stats["merged"], stats["split"]) == (0, 0, 0)
    assert len(await _events()) == before


async def test_must_merge_joins_two_products_and_the_merge_cites_it():
    a = await _listing(await _supplier("shop-a"), "ATMEGA328 AVR Microcontroller", "ATMEGA328")
    b = await _listing(
        await _supplier("shop-b"), "Arduino brain chip, DIP", None, seen=T0 + timedelta(days=1)
    )
    await _rebuild()
    pa, pb = await _product_of(a), await _product_of(b)
    assert pa != pb

    ruling = await _add(a, b, rulings.MUST)
    stats = await _rebuild()
    assert stats["merged"] == 1
    # Equals created in one regroup: which id survives is the plan's tie-break,
    # not this test's business.
    survivor = await _product_of(a)
    assert survivor == await _product_of(b) and survivor in (pa, pb)
    (merge,) = [e for e in await _events() if e.kind == ProductEventKind.MERGE]
    assert {merge.product_id, merge.other_id} == {pa, pb} and merge.other_id == survivor
    assert merge.detail["overrides"] == [ruling.id]

    # And it holds: the next rebuild changes nothing.
    stats = await _rebuild()
    assert (stats["merged"], stats["split"], stats["created"]) == (0, 0, 0)
    assert await _product_of(a) == await _product_of(b)


async def test_unforced_must_merge_is_refused_by_a_veto_and_forced_is_not():
    a = await _listing(await _supplier("shop-a"), "ESP32 Development Board 30 pin", "ESP32")
    b = await _listing(await _supplier("shop-b"), "ESP32 Development Board 38 pin", "ESP32")
    await _add(a, b, rulings.MUST)
    await _rebuild()
    assert await _product_of(a) != await _product_of(b)

    async with SessionLocal() as session:
        row = await session.scalar(select(GroupingOverride))
        row.forced = True
        await session.commit()
    await _rebuild()
    assert await _product_of(a) == await _product_of(b)


async def test_the_same_shop_stays_apart_whatever_the_ruling():
    shop = await _supplier("shop-a")
    a = await _listing(shop, "SG90 Micro Servo 9g", "SG90")
    b = await _listing(shop, "SG90 Micro Servo 9g blue", "SG90")
    await _add(a, b, rulings.MUST, forced=True)
    await _rebuild()
    assert await _product_of(a) != await _product_of(b)


async def test_no_ruling_writes_no_override_into_events():
    a = await _listing(await _supplier("shop-a"), "SG90 Micro Servo 9g", "SG90")
    b = await _listing(await _supplier("shop-b"), "MG996R Servo", "MG996R")
    await _rebuild()
    await _add(a, b, rulings.NEVER)  # two products already: nothing to change
    await _rebuild()
    assert all("overrides" not in e.detail for e in await _events())


# --- rulings from reports, and by hand -------------------------------------


async def _report(reason: str, product: list, other: list | None = None) -> int:
    def snap(ids, ticked=()):
        return {"listings": [{"id": str(i), "title": "x", "ticked": i in ticked} for i in ids]}

    snapshot = {"product": snap(product[0], product[1] if len(product) > 1 else ())}
    snapshot["other_product"] = snap(other) if other else None
    async with SessionLocal() as session:
        report = Report(
            product_id=uuid.uuid4(),
            reason=reason,
            snapshot=snapshot,
            created_at=datetime.now(UTC),
        )
        session.add(report)
        await session.commit()
        return report.id


async def _overrides() -> list[GroupingOverride]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(GroupingOverride).order_by(GroupingOverride.id)))


async def test_accepting_offers_not_same_keeps_each_ticked_offer_from_each_unticked(capsys):
    shops = [await _supplier(f"shop-{c}") for c in "abcd"]
    a, b, c, d = [await _listing(s, "SG90 Micro Servo 9g", "SG90") for s in shops]
    report_id = await _report("offers_not_same", [[a, b, c, d], {a, b}])

    assert await reports_cli.run(["accept", str(report_id), "--by", "owner"]) == 0
    rows = await _overrides()
    expected = {pair(x, y) for x in (a, b) for y in (c, d)}
    assert {(r.listing_a, r.listing_b) for r in rows} == expected
    assert {(r.kind, r.source, r.report_id, r.created_by) for r in rows} == {
        (rulings.NEVER, "report", report_id, "owner")
    }
    assert "applies at the next regroup" in capsys.readouterr().out

    # Accepting again adds nothing; rejecting withdraws what it made.
    assert await reports_cli.run(["accept", str(report_id)]) == 0
    assert len(await _overrides()) == 4
    assert await reports_cli.run(["reject", str(report_id)]) == 0
    assert await _overrides() == []


async def test_accepting_same_as_other_joins_one_listing_of_each(capsys):
    shops = [await _supplier(f"shop-{c}") for c in "abcd"]
    a = await _listing(shops[0], "Chip A", None, seen=T0 + timedelta(days=2))
    b = await _listing(shops[1], "Chip A again", None, seen=T0)  # earliest of its product
    c = await _listing(shops[2], "Chip B", None, seen=T0 + timedelta(days=1))
    d = await _listing(shops[3], "Chip B again", None, seen=T0 + timedelta(days=3))
    report_id = await _report("same_as_other", [[a, b]], [c, d])

    assert await reports_cli.run(["accept", str(report_id)]) == 0
    (row,) = await _overrides()
    assert (row.listing_a, row.listing_b) == pair(b, c)
    assert (row.kind, row.forced, row.report_id) == (rulings.MUST, False, report_id)


async def test_other_reasons_make_no_ruling():
    a = await _listing(await _supplier("shop-a"), "SG90 Micro Servo 9g", "SG90")
    report_id = await _report("wrong_category", [[a]])
    assert await reports_cli.run(["accept", str(report_id)]) == 0
    assert await _overrides() == []


async def test_a_conflicting_ruling_is_refused_not_overwritten(capsys):
    a = await _listing(await _supplier("shop-a"), "SG90 Micro Servo 9g", "SG90")
    b = await _listing(await _supplier("shop-b"), "SG90 Micro Servo 9g", "SG90")
    await _add(a, b, rulings.NEVER)
    code = await overrides_cli.run(
        ["add", str(a), str(b), "--kind", "must", "--note", "same part", "--by", "owner"]
    )
    assert code == 1
    assert "NOT recorded" in capsys.readouterr().out
    (row,) = await _overrides()
    assert row.kind == rulings.NEVER


async def test_overrides_by_hand(capsys):
    a = await _listing(await _supplier("shop-a"), ATMEGA_PU, "ATMEGA328")
    b = await _listing(await _supplier("shop-b"), ATMEGA_P, "ATMEGA328")
    args = ["add", str(b), str(a), "--kind", "never", "--note", "-PU is not picoPower"]
    assert await overrides_cli.run([*args, "--by", "owner"]) == 0
    (row,) = await _overrides()
    assert (row.listing_a, row.listing_b) == pair(a, b)
    assert (row.source, row.note, row.created_by) == ("manual", "-PU is not picoPower", "owner")

    capsys.readouterr()
    assert await overrides_cli.run(["list"]) == 0
    out = capsys.readouterr().out
    assert f"#{row.id} never_merge  manual" in out and ATMEGA_P in out

    async with SessionLocal() as session:
        assert (await load_overrides(session)).kind(a, b) == rulings.NEVER

    assert await overrides_cli.run(["remove", str(row.id)]) == 0
    assert await _overrides() == []
    assert await overrides_cli.run(["remove", "999"]) == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["add", str(uuid.uuid4()), str(uuid.uuid4()), "--kind", "never"],  # no note
        ["add", str(uuid.uuid4()), str(uuid.uuid4()), "--kind", "never", "--forced", "--note", "x"],
        ["add", "not-an-id", str(uuid.uuid4()), "--kind", "must", "--note", "x"],
    ],
)
async def test_a_manual_override_needs_a_note_and_sense(argv):
    with pytest.raises(SystemExit):
        await overrides_cli.run(argv)
