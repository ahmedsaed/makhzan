"""Recording every category a product is listed under, and filing it under one
(worker/categories_seen.py).

A shop browsed by category partitions shows a product filed under several
categories once per partition. It used to keep whichever partition was swept
last; it now keeps the one the owner's rule chooses from every name seen this
cycle and the last (the rule itself: test_category_rule.py). These tests pin
that the memberships are recorded per cycle, that sweeps do not erase them,
that the category no longer depends on sweep order, and that a source that
does not record them is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from makhzan_schemas.ai.prompt import listing_row
from makhzan_schemas.contracts import RawItem
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus, SourceType
from makhzan_schemas.models import Category, IngestionRun, Listing, Source
from sqlalchemy import select
from worker.categories_seen import KEY, collect, format_report, record
from worker.pipeline import run_source
from worker.sources.base import Page, SourceAdapter, SupplierInfo

SRC = "test-shop"

#: A fictional shop's crosswalk: two leaves, one name ignored on purpose.
CROSSWALK = {
    "cat-resistors": ("electronics", "resistors"),
    "cat-passives": ("electronics", "resistors"),
    "cat-capacitors": ("electronics", "capacitors"),
}


class PartitionedShop(SourceAdapter):
    """Browsed by category, plus a whole-shop pass ('') that carries none.

    `listed` says which products each partition shows; every product is
    listed by the whole-shop pass.
    """

    source_id = SRC
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug=SRC, name="Test Shop")
    polite_delay = 0
    authoritative_categories = True
    records_categories_seen = True

    def __init__(self, parts, listed=None, max_partitions_per_run=None):
        self._parts = parts
        self.listed = listed or {}
        self.categories = CROSSWALK
        if max_partitions_per_run is not None:
            self.max_partitions_per_run = max_partitions_per_run

    def partitions(self):
        return self._parts

    async def fetch_page(self, partition, page):
        ids = self.listed.get(partition, ["p1"]) if partition else ["p1", "p2"]
        return Page(
            [
                RawItem(
                    source=SRC,
                    external_id=i,
                    title=f"Widget {i}",
                    price_text="10 EGP",
                    availability_text="In stock",
                    raw={"category": partition or None},
                )
                for i in ids
            ],
            has_more=False,
        )

    def source_categories(self, raw):
        category = (raw.raw or {}).get("category")
        return [category] if category else []

    def category_for(self, raw):
        return self.categories.get((raw.raw or {}).get("category"))

    def knows_category(self, raw):
        return bool((raw.raw or {}).get("category"))


async def _seed_taxonomy():
    async with SessionLocal() as s:
        s.add(Category(domain="electronics", slug="resistors", name_en="Resistors", path="/r"))
        s.add(Category(domain="electronics", slug="capacitors", name_en="Capacitors", path="/c"))
        await s.commit()


async def _listing(external_id="p1") -> Listing:
    async with SessionLocal() as s:
        return (
            await s.execute(select(Listing).where(Listing.external_id == external_id))
        ).scalar_one()


async def _slug_of(external_id="p1"):
    listing = await _listing(external_id)
    if listing.category_id is None:
        return None
    async with SessionLocal() as s:
        return await s.scalar(select(Category.slug).where(Category.id == listing.category_id))


async def _cycles() -> list[str]:
    """Every completed cycle's start, oldest first."""
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(IngestionRun.stats["cycle"]["cycle_started_at"].astext)
                .where(IngestionRun.source == SRC, IngestionRun.stats.has_key("cycle"))
                .order_by(IngestionRun.started_at)
            )
        ).all()
    return [r[0] for r in rows]


def _same(stamp_a: str, stamp_b: str) -> bool:
    return datetime.fromisoformat(stamp_a) == datetime.fromisoformat(stamp_b)


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #


async def test_memberships_accumulate_across_partitions_within_a_cycle():
    """Unmapped names are recorded too, and the whole-shop pass adds none. The
    key is the cycle's start exactly as the completing run stamps it."""
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop(["", "cat-resistors", "cat-unmapped", "cat-capacitors"]))

    seen = (await _listing()).attributes[KEY]
    (cycle,) = await _cycles()
    ((stamp, names),) = seen.items()
    assert _same(stamp, cycle)
    assert names == ["cat-resistors", "cat-unmapped", "cat-capacitors"]
    # Listed only by the whole-shop pass: nothing to record.
    assert KEY not in (await _listing("p2")).attributes


async def test_a_cycle_spanning_runs_keeps_one_key_and_survives_other_sweeps():
    """The carry-over: each run's upsert rebuilds attributes from the card, so a
    sweep of another partition, and the whole-shop pass, must keep what earlier
    partitions recorded."""
    await _seed_taxonomy()
    parts = ["cat-resistors", "cat-capacitors", ""]
    for _ in parts:
        await run_source(SRC, PartitionedShop(parts, max_partitions_per_run=1))

    seen = (await _listing()).attributes[KEY]
    (cycle,) = await _cycles()
    assert len(seen) == 1
    ((stamp, names),) = seen.items()
    assert _same(stamp, cycle)
    assert names == ["cat-resistors", "cat-capacitors"]


async def test_the_previous_cycle_is_kept_and_older_ones_dropped():
    await _seed_taxonomy()
    for part in ("cat-resistors", "cat-capacitors", "cat-unmapped"):
        await run_source(SRC, PartitionedShop([part]))

    seen = (await _listing()).attributes[KEY]
    cycles = await _cycles()
    assert len(cycles) == 3
    assert [_same(a, b) for a, b in zip(seen, cycles[1:], strict=True)] == [True, True]
    assert list(seen.values()) == [["cat-capacitors"], ["cat-unmapped"]]


async def test_the_whole_shop_pass_records_nothing_and_erases_nothing():
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop([""]))
    assert KEY not in (await _listing()).attributes

    # Within one cycle: the category partition records, the whole-shop pass
    # after it (a later run) keeps it.
    shop = PartitionedShop(["cat-resistors", ""], max_partitions_per_run=1)
    await run_source(SRC, shop)
    before = (await _listing()).attributes[KEY]
    await run_source(SRC, shop)
    assert (await _listing()).attributes[KEY] == before
    assert list(before.values()) == [["cat-resistors"]]


async def test_a_limit_run_records_nothing():
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop(["cat-resistors"]), limit=5)
    assert KEY not in (await _listing()).attributes


async def test_an_adapter_that_does_not_opt_in_records_nothing():
    class TagShop(PartitionedShop):
        records_categories_seen = False

    await _seed_taxonomy()
    await run_source(SRC, TagShop(["cat-resistors"]))
    assert KEY not in (await _listing()).attributes


def test_record_keeps_order_drops_duplicates_and_the_oldest_cycles():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stamps = [(t0 + timedelta(days=7 * i)).isoformat() for i in range(3)]
    attrs = record({"specs": {"a": "1"}}, stamps[0], ["x"])
    attrs = record(attrs, stamps[1], ["y", "x"])
    attrs = record(attrs, stamps[1], ["y", "z"])
    assert attrs[KEY] == {stamps[0]: ["x"], stamps[1]: ["y", "x", "z"]}
    attrs = record(attrs, stamps[2], ["w"])
    assert attrs[KEY] == {stamps[1]: ["y", "x", "z"], stamps[2]: ["w"]}
    assert attrs["specs"] == {"a": "1"}


# --------------------------------------------------------------------------- #
# The category
# --------------------------------------------------------------------------- #


async def _moves() -> list[int]:
    """`stats.categories` moved + cleared, per run, oldest first."""
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(IngestionRun.stats["categories"])
                .where(IngestionRun.source == SRC)
                .order_by(IngestionRun.started_at)
            )
        ).all()
    return [(r[0] or {}).get("moved", 0) + (r[0] or {}).get("cleared", 0) for r in rows]


async def test_the_category_no_longer_depends_on_sweep_order():
    """Pins the owner's rule where this test used to pin "the last mapped
    partition swept wins" (changed on purpose, 2026-11-23). Two mapped leaves
    and no `prefer`: the first ref alphabetically, in either order, and an
    unmapped partition after them changes nothing."""
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop(["cat-resistors", "cat-capacitors"]))
    assert await _slug_of() == "capacitors"
    await run_source(SRC, PartitionedShop(["cat-capacitors", "cat-resistors", "cat-unmapped"]))
    assert await _slug_of() == "capacitors"
    await run_source(SRC, PartitionedShop(["cat-unmapped", ""]))
    assert await _slug_of() == "capacitors"


async def test_prefer_outranks_the_ref():
    await _seed_taxonomy()
    shop = PartitionedShop(["cat-capacitors", "cat-resistors"])
    shop.preferred_categories = ("cat-resistors",)
    await run_source(SRC, shop)
    assert await _slug_of() == "resistors"


async def test_stable_across_cycles_runs_and_orders():
    """Once a cycle has seen both categories, later cycles split over runs,
    each in another order, never move the category, mid-cycle included: no
    flip to re-queue AI scores."""
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop(["cat-resistors", "cat-capacitors", ""]))
    assert await _slug_of() == "capacitors"
    orders = [
        ["cat-capacitors", "cat-unmapped", "cat-resistors", ""],
        ["", "cat-unmapped", "cat-resistors", "cat-capacitors"],
        ["cat-unmapped", "cat-capacitors", "", "cat-resistors"],
        ["cat-resistors", "", "cat-unmapped", "cat-capacitors"],
    ]
    for order in orders:
        for _ in order:
            await run_source(SRC, PartitionedShop(order, max_partitions_per_run=1))
            assert await _slug_of() == "capacitors"
    assert len(await _cycles()) == 1 + len(orders)
    assert sum((await _moves())[1:]) == 0


async def test_the_old_rule_flipped_where_the_new_one_does_not():
    """The same cycles on a source that does not record: the last mapped
    partition swept decides, so the category moves mid-cycle."""

    class Unrecorded(PartitionedShop):
        records_categories_seen = False

    await _seed_taxonomy()
    for order in (["cat-resistors", "cat-capacitors"], ["cat-capacitors", "cat-resistors"]):
        for _ in order:
            await run_source(SRC, Unrecorded(order, max_partitions_per_run=1))
    assert await _slug_of() == "resistors"
    assert sum(await _moves()) == 2


async def test_a_removed_category_drops_out_once_absent_from_both_cycles():
    """Filed under capacitors (alphabetically ahead) while the shop lists it
    under both; the shop then drops it from capacitors. The cycle after still
    has the last one's sighting, so nothing moves mid-cycle; the next one, with
    capacitors in neither kept cycle, files it under resistors."""
    await _seed_taxonomy()
    both = {"cat-resistors": ["p1"], "cat-capacitors": ["p1"]}
    gone = {"cat-resistors": ["p1"], "cat-capacitors": []}
    parts = ["cat-resistors", "cat-capacitors"]
    await run_source(SRC, PartitionedShop(parts, listed=both))
    assert await _slug_of() == "capacitors"
    await run_source(SRC, PartitionedShop(parts, listed=gone))
    assert await _slug_of() == "capacitors"
    await run_source(SRC, PartitionedShop(parts, listed=gone))
    assert await _slug_of() == "resistors"


async def test_an_unmapped_only_sighting_leaves_a_mapped_category_alone():
    """The authoritative miss rule still holds once the mapped sighting has
    left both kept cycles, and the listing is never inferred."""
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop(["cat-resistors"]))
    for _ in range(3):
        await run_source(SRC, PartitionedShop(["cat-unmapped"]))
    listing = await _listing()
    assert "cat-resistors" not in str(listing.attributes[KEY])
    assert await _slug_of() == "resistors"


async def test_never_inferred_on_an_authoritative_source():
    """A listing only ever under unmapped names stays uncategorized, even with
    a title the keyword rules would read."""

    class Titled(PartitionedShop):
        async def fetch_page(self, partition, page):
            result = await super().fetch_page(partition, page)
            for item in result.items:
                item.title = "10k ohm resistor 1/4W"
            return result

    await _seed_taxonomy()
    await run_source(SRC, Titled(["cat-unmapped", "cat-brand-x"]))
    assert await _slug_of() is None


async def test_the_whole_shop_pass_never_clears_the_chosen_category():
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop(["cat-resistors", "cat-capacitors"]))
    for _ in range(3):
        await run_source(SRC, PartitionedShop([""]))
    assert await _slug_of() == "capacitors"


async def test_a_limit_run_files_by_the_stored_set_too():
    """A `limit=` run records nothing, but reads what is recorded: sweeping one
    partition alone does not move the category."""
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop(["cat-capacitors", "cat-resistors"]))
    await run_source(SRC, PartitionedShop(["cat-resistors"]), limit=5)
    assert await _slug_of() == "capacitors"


async def test_a_source_that_does_not_record_still_takes_the_last_mapped_partition():
    """Byte for byte as before for every other source: the later partition
    wins, in either order; an unmapped one clears nothing."""

    class TagShop(PartitionedShop):
        records_categories_seen = False

    await _seed_taxonomy()
    await run_source(SRC, TagShop(["cat-resistors", "cat-capacitors"]))
    assert await _slug_of() == "capacitors"
    await run_source(SRC, TagShop(["cat-capacitors", "cat-resistors", "cat-unmapped"]))
    assert await _slug_of() == "resistors"
    await run_source(SRC, TagShop(["cat-unmapped", ""]))
    assert await _slug_of() == "resistors"


async def test_the_ai_view_of_a_listing_ignores_the_memberships():
    """`listing_row` is what the AI content hash and prompt are built from."""
    await _seed_taxonomy()
    await run_source(SRC, PartitionedShop(["cat-resistors", "cat-capacitors"]))
    listing = await _listing()
    assert KEY in listing.attributes
    without = SimpleNamespace(
        **{
            c: getattr(listing, c)
            for c in ("id", "title_en", "title_ar", "brand", "part_number", "description_en")
        },
        attributes={k: v for k, v in listing.attributes.items() if k != KEY},
    )
    assert listing_row(listing, "Resistors") == listing_row(without, "Resistors")


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


async def _seed_source(tmp_path, monkeypatch):
    (tmp_path / "test-shop.toml").write_text(
        'ignore = ["cat-brand-x"]\n[categories]\n'
        + "".join(f'"{k}" = "{d}:{s}"\n' for k, (d, s) in CROSSWALK.items())
    )
    monkeypatch.setenv("MAKHZAN_CROSSWALKS", str(tmp_path))
    async with SessionLocal() as s:
        s.add(
            Source(
                source_id=SRC,
                adapter="odoo",
                base_url="https://shop.test",
                supplier={"slug": SRC, "name": "Test Shop"},
                config={"crosswalk": "test-shop"},
            )
        )
        await s.commit()


async def _report(**kwargs) -> list[str]:
    async with SessionLocal() as s:
        return format_report(await collect(s, SRC), **kwargs)


async def test_the_report_lists_multi_category_products_of_the_last_completed_cycle(
    tmp_path, monkeypatch
):
    await _seed_taxonomy()
    await _seed_source(tmp_path, monkeypatch)
    listed = {
        "cat-resistors": ["p1", "p2", "p3"],
        "cat-capacitors": ["p1"],
        "cat-passives": ["p2"],
        "cat-brand-x": ["p2", "p3"],
        "cat-unmapped": ["p3"],
    }
    await run_source(SRC, PartitionedShop(list(listed), listed=listed))
    # A cycle in flight sweeps one partition: it must not show.
    await run_source(
        SRC, PartitionedShop([*listed, "cat-new"], listed=listed, max_partitions_per_run=1)
    )

    lines = await _report()
    text = "\n".join(lines)
    print(text)
    assert lines[0] == f"CATEGORIES SEEN: {SRC}"
    assert (
        "3 listings seen under a category in that cycle; 3 under two or more; "
        "1 of those under two or more distinct mapped leaves" in text
    )
    # p2 and p3 both sit in resistors + the brand tag: the commonest pair.
    assert "    2  cat-brand-x  +  cat-resistors" in text
    conflicts, rest = text.split("at most one mapped leaf")
    assert "p1  Widget p1" in conflicts and "p2" not in conflicts.split("leaves (1):")[1]
    # p1 sits in capacitors and resistors: the rule files it under capacitors
    # (no `prefer`, the first ref), and the report says so.
    assert "stored today: electronics:capacitors" in conflicts
    assert "rule picks:   electronics:capacitors" in conflicts
    conflicts, rest = " ".join(conflicts.split()), " ".join(rest.split())
    assert "cat-capacitors -> electronics:capacitors" in conflicts
    assert "cat-brand-x -> ignored" in rest
    assert "cat-unmapped -> unmapped" in rest
    assert "cat-passives -> electronics:resistors" in rest

    only = "\n".join(await _report(conflicts_only=True))
    assert "p1  Widget p1" in only and "p3  Widget p3" not in only


async def test_the_report_says_plainly_when_no_cycle_has_completed(tmp_path, monkeypatch):
    await _seed_source(tmp_path, monkeypatch)
    await run_source(
        SRC, PartitionedShop(["cat-resistors", "cat-capacitors"], max_partitions_per_run=1)
    )
    text = "\n".join(await _report())
    assert "No completed cycle recorded for this source yet" in text
    assert "1 listings carry memberships so far" in text


async def test_the_report_says_when_the_last_cycle_predates_recording(tmp_path, monkeypatch):
    await _seed_source(tmp_path, monkeypatch)
    async with SessionLocal() as s:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        s.add(
            IngestionRun(
                source=SRC,
                source_type=SourceType.SCRAPED,
                status=IngestionStatus.SUCCESS,
                stats={
                    "cycle": {
                        "cycle_started_at": started.isoformat(),
                        "cycle_completed_at": (started + timedelta(days=7)).isoformat(),
                    }
                },
            )
        )
        await s.commit()
    text = "\n".join(await _report())
    assert "ran before categories were recorded" in text


async def test_the_report_flags_a_cycle_that_began_before_recording(tmp_path, monkeypatch):
    """Deployed mid-cycle: the runs before it swept partitions and recorded
    nothing, so the first completed cycle's memberships are partial."""
    await _seed_taxonomy()
    await _seed_source(tmp_path, monkeypatch)

    class BeforeRecording(PartitionedShop):
        records_categories_seen = False

    parts = ["cat-resistors", "cat-capacitors"]
    await run_source(SRC, BeforeRecording(parts, max_partitions_per_run=1))
    await run_source(SRC, PartitionedShop(parts, max_partitions_per_run=1))
    assert len(await _cycles()) == 1

    text = "\n".join(await _report())
    assert "PARTIAL: 1 run(s) of that cycle swept pages before categories were recorded" in text

    # The next cycle, recorded throughout, is whole.
    for _ in parts:
        await run_source(SRC, PartitionedShop(parts, max_partitions_per_run=1))
    assert "PARTIAL" not in "\n".join(await _report())
