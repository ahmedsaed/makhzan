"""Pipeline behaviour that protects a catalog from being lost or wrongly retired.

These cover the guarantees that make a sweep survivable: work already fetched is
committed, a failure resumes where it stopped instead of restarting at page 1,
and listings are only archived once the whole catalog has genuinely been seen.
"""

from __future__ import annotations

import pytest
from makhzan_schemas.contracts import RawItem
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus, ListingStatus, SourceType
from makhzan_schemas.models import Listing, SourceCursor, Supplier
from sqlalchemy import select
from worker.normalize import not_a_product
from worker.pipeline import run_source
from worker.sources.base import Page, SourceAdapter, SupplierInfo

SRC = "test-source"


class StubAdapter(SourceAdapter):
    """A source with scripted pages, optionally failing on a chosen page."""

    source_id = SRC
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug=SRC, name="Test Shop")
    polite_delay = 0

    def __init__(self, pages=None, fail_on_page=None, parts=None):
        self.pages = pages if pages is not None else {1: ["a1", "a2"], 2: ["b1", "b2"], 3: ["c1"]}
        self.fail_on_page = fail_on_page
        self._parts = parts
        self.fetched: list[tuple[str, int]] = []

    def partitions(self):
        return self._parts if self._parts is not None else super().partitions()

    async def fetch_page(self, partition: str, page: int) -> Page:
        self.fetched.append((partition, page))
        if self.fail_on_page is not None and page == self.fail_on_page:
            raise RuntimeError(f"simulated fetch failure on page {page}")
        ids = self.pages.get(page, [])
        return Page(
            [
                RawItem(
                    source=SRC,
                    external_id=i,
                    title=f"Item {i}",
                    price_text="10 EGP",
                    availability_text="In stock",
                )
                for i in ids
            ],
            has_more=page < max(self.pages),
        )


async def _listings():
    async with SessionLocal() as s:
        supplier = (
            await s.execute(select(Supplier).where(Supplier.slug == SRC))
        ).scalar_one_or_none()
        if supplier is None:
            return []
        return (
            (await s.execute(select(Listing).where(Listing.supplier_id == supplier.id)))
            .scalars()
            .all()
        )


async def _cursors():
    async with SessionLocal() as s:
        rows = (
            (await s.execute(select(SourceCursor).where(SourceCursor.source == SRC)))
            .scalars()
            .all()
        )
        return {c.partition_key: (c.next_page, c.exhausted) for c in rows}


@pytest.mark.asyncio
async def test_failed_fetch_keeps_earlier_pages():
    """A mid-sweep failure must not discard pages already fetched."""
    run = await run_source(SRC, StubAdapter(fail_on_page=2))

    assert run.status == IngestionStatus.PARTIAL
    assert len(await _listings()) == 2, "page 1 must survive the page 2 failure"
    assert run.stats.get("errors"), "the failure should be recorded on the run"


@pytest.mark.asyncio
async def test_failed_fetch_parks_cursor_on_failing_page():
    """The cursor stays on the page that failed so the next run retries it."""
    await run_source(SRC, StubAdapter(fail_on_page=2))
    assert await _cursors() == {"": (2, False)}


@pytest.mark.asyncio
async def test_next_run_resumes_instead_of_restarting():
    """The whole point: page 1 is not refetched, and the tail is reachable."""
    await run_source(SRC, StubAdapter(fail_on_page=2))

    second = StubAdapter()
    run = await run_source(SRC, second)

    assert second.fetched[0] == ("", 2), "must resume on the failed page"
    assert ("", 1) not in second.fetched, "must not refetch page 1"
    assert run.status == IngestionStatus.SUCCESS
    assert len(await _listings()) == 5
    assert await _cursors() == {"": (1, False)}, "cursor resets after a full sweep"


@pytest.mark.asyncio
async def test_partial_run_archives_nothing():
    """Archiving everything a failed run never reached would delete the catalog."""
    await run_source(SRC, StubAdapter())  # full sweep: 5 listings
    run = await run_source(SRC, StubAdapter(pages={1: ["a1"]}, fail_on_page=1))

    assert run.status == IngestionStatus.PARTIAL
    assert not run.stats.get("archived")
    assert all(listing.status == ListingStatus.ACTIVE for listing in await _listings())


@pytest.mark.asyncio
async def test_complete_sweep_archives_vanished_listings():
    """Once the whole catalog is seen, items that disappeared are retired."""
    await run_source(SRC, StubAdapter())
    run = await run_source(SRC, StubAdapter(pages={1: ["a1", "a2"]}))

    assert run.stats.get("archived") == 3
    active = [x for x in await _listings() if x.status == ListingStatus.ACTIVE]
    assert len(active) == 2


@pytest.mark.asyncio
async def test_archiving_waits_for_every_partition():
    """A source is only fully swept when all of its partitions are."""

    class OnePartitionFails(StubAdapter):
        async def fetch_page(self, partition: str, page: int) -> Page:
            if partition == "p2":
                raise RuntimeError("simulated fetch failure")
            return await super().fetch_page(partition, page)

    run = await run_source(SRC, OnePartitionFails(pages={1: ["a1"]}, parts=["p1", "p2"]))

    assert run.status == IngestionStatus.PARTIAL
    assert not run.stats.get("archived"), "p2 was never swept, so nothing may be retired"
    assert (await _cursors())["p1"][1] is True
    assert (await _cursors())["p2"][1] is False


@pytest.mark.asyncio
async def test_limit_runs_leave_cursors_untouched():
    """Bounded dev runs must not disturb a real sweep's resume point."""
    await run_source(SRC, StubAdapter(fail_on_page=2))  # parks cursor at page 2
    before = await _cursors()

    await run_source(SRC, StubAdapter(), limit=1)

    assert await _cursors() == before, "a limited run must not move the cursor"


@pytest.mark.asyncio
async def test_partition_budget_spreads_a_sweep_across_runs():
    """A big catalogue is swept over several days rather than in one sitting."""

    class Budgeted(StubAdapter):
        max_partitions_per_run = 2

        def partitions(self):
            return ["a", "b", "c", "d"]

    first = Budgeted(pages={1: ["x"]})
    await run_source(SRC, first)
    assert {p for p, _page in first.fetched} == {"a", "b"}, "first run takes its slice"
    assert (await _cursors()).keys() == {"a", "b"}

    second = Budgeted(pages={1: ["x"]})
    await run_source(SRC, second)
    assert {p for p, _page in second.fetched} == {"c", "d"}, "next run continues, not restarts"


@pytest.mark.asyncio
async def test_cycle_only_closes_once_every_partition_is_swept():
    """Archiving must wait for the whole catalogue, however many runs that takes."""

    class Budgeted(StubAdapter):
        max_partitions_per_run = 2

        def partitions(self):
            return ["a", "b", "c", "d"]

    first = await run_source(SRC, Budgeted(pages={1: ["x"]}))
    assert not first.stats.get("cycle"), "half the partitions is not a cycle"

    second = await run_source(SRC, Budgeted(pages={1: ["x"]}))
    assert second.stats.get("cycle"), "the run that finishes the last partition closes it"


@pytest.mark.asyncio
async def test_limited_runs_ignore_the_partition_budget():
    """Bounded dev runs sweep what they were asked for."""

    class Budgeted(StubAdapter):
        max_partitions_per_run = 1

        def partitions(self):
            return ["a", "b", "c"]

    adapter = Budgeted(pages={1: ["x"]})
    await run_source(SRC, adapter, limit=99)
    assert {p for p, _page in adapter.fetched} == {"a", "b", "c"}


# --------------------------------------------------------------------------- #
# A sweep that carries no category must not erase one
# --------------------------------------------------------------------------- #


class CategoryAdapter(StubAdapter):
    """Browsed by category, plus a whole-catalogue pass that carries none.

    The shape of an Odoo shop: 'cat-*' partitions know the category exactly, and
    the '' partition exists only so products filed under nothing are still seen.
    """

    authoritative_categories = True

    def __init__(self, parts, crosswalk):
        super().__init__(pages={1: ["a1"]}, parts=parts)
        self.categories = crosswalk

    async def fetch_page(self, partition, page):
        self.fetched.append((partition, page))
        if page > 1:
            return Page([], has_more=False)
        return Page(
            [
                RawItem(
                    source=SRC,
                    external_id="a1",
                    title="Widget",
                    price_text="10 EGP",
                    availability_text="In stock",
                    raw={"category": partition or None},
                )
            ],
            has_more=False,
        )

    def source_categories(self, raw):
        # What the sweep actually saw — the input to drift detection.
        category = (raw.raw or {}).get("category")
        return [category] if category else []

    def category_for(self, raw):
        return self.categories.get((raw.raw or {}).get("category"))

    def knows_category(self, raw):
        return bool((raw.raw or {}).get("category"))


async def _seed_taxonomy():
    """The pipeline resolves (domain, slug) against the Category table."""
    from makhzan_schemas.models import Category

    async with SessionLocal() as s:
        s.add(Category(domain="electronics", slug="resistors", name_en="Resistors", path="/r"))
        await s.commit()


async def _category_slug_of(external_id="a1"):
    from makhzan_schemas.models import Category

    async with SessionLocal() as s:
        listing = (
            await s.execute(select(Listing).where(Listing.external_id == external_id))
        ).scalar_one()
        if listing.category_id is None:
            return None
        cat = (
            await s.execute(select(Category).where(Category.id == listing.category_id))
        ).scalar_one()
        return cat.slug


async def test_the_whole_shop_pass_does_not_erase_a_category(_clean_tables):
    """The reason this rule exists: a shop can file products under no category,
    so the category sweep alone would archive them — but the /shop pass that keeps them
    alive carries no category, and must not clear what the category pass set."""
    await _seed_taxonomy()
    crosswalk = {"cat-resistors": ("electronics", "resistors")}

    await run_source(SRC, CategoryAdapter(["cat-resistors"], crosswalk))
    assert await _category_slug_of() == "resistors"

    # Now the whole-catalogue pass sees the same product with no category.
    await run_source(SRC, CategoryAdapter([""], crosswalk))
    assert await _category_slug_of() == "resistors", "the category survived a sweep that had none"


async def test_an_authoritative_miss_still_clears_the_category(_clean_tables):
    """The other half: a sweep that *does* browse by category and finds the item
    under one we do not map has genuinely uncategorized it. That must show."""
    await _seed_taxonomy()
    crosswalk = {"cat-resistors": ("electronics", "resistors")}

    await run_source(SRC, CategoryAdapter(["cat-resistors"], crosswalk))
    assert await _category_slug_of() == "resistors"

    await run_source(SRC, CategoryAdapter(["cat-unmapped"], crosswalk))
    assert await _category_slug_of() is None


# --------------------------------------------------------------------------- #
# Crosswalk drift on a paced source
# --------------------------------------------------------------------------- #


class PacedCategoryAdapter(CategoryAdapter):
    """Browsed by category and swept a slice at a time, the way the big
    category-partitioned sources are."""

    def __init__(self, parts, crosswalk, budget):
        super().__init__(parts, crosswalk)
        self.max_partitions_per_run = budget


async def test_unused_is_not_reported_when_a_run_swept_only_its_slice(_clean_tables):
    """The run that closes a 171-partition cycle may have visited 25 of them.
    The other 146 categories are not retired — they were swept days ago, and
    calling them unused buries the renames the report exists to surface."""
    await _seed_taxonomy()
    crosswalk = {f"cat-{i}": ("electronics", "resistors") for i in range(4)}
    parts = list(crosswalk)

    stats = {}
    for _ in range(len(parts)):
        run = await run_source(SRC, PacedCategoryAdapter(parts, crosswalk, budget=1))
        stats = run.stats or {}

    # The last run closed the cycle...
    assert stats.get("cycle"), "expected the cycle to close"
    # ...having seen one category, so it cannot speak for the other three.
    assert "unused" not in stats.get("crosswalk", {})


async def test_unused_is_reported_when_one_run_swept_everything(_clean_tables):
    """The case the report is actually for: a full sweep that never saw a
    category the crosswalk still maps."""
    await _seed_taxonomy()
    crosswalk = {
        "cat-resistors": ("electronics", "resistors"),
        "cat-retired": ("electronics", "resistors"),
    }

    run = await run_source(SRC, CategoryAdapter(["cat-resistors"], crosswalk))

    assert run.stats["crosswalk"]["unused"] == ["cat-retired"]


# --------------------------------------------------------------------------- #
# Authoritative categories, across verticals
# --------------------------------------------------------------------------- #

MARKETPLACE = SupplierInfo(slug="marketplace", name="Marketplace", domain="tools")
MARKETPLACE_CROSSWALK = {
    "tape-measures": ("tools", "tape-rules"),
    "12pt-sockets": ("tools", "sockets-drivers"),
    # A marketplace spans verticals: this one maps into electronics.
    "zener-diodes": ("electronics", "diodes"),
}


class MarketplaceAdapter(SourceAdapter):
    """Browsed by category, spanning verticals, serving one product from one category."""

    source_id = "marketplace"
    source_type = SourceType.SCRAPED
    supplier = MARKETPLACE
    polite_delay = 0
    authoritative_categories = True
    categories = MARKETPLACE_CROSSWALK

    def __init__(self, category, title):
        self._category, self._title = category, title

    def partitions(self):
        # Only this stub's category, which may deliberately be one the crosswalk
        # does not cover.
        return [self._category]

    def category_for(self, raw):
        return self.categories.get((raw.raw or {}).get("category"))

    async def fetch_page(self, partition, page):
        if page > 1:
            return Page([], has_more=False)
        item = RawItem(
            source="marketplace",
            external_id="x1",
            title=self._title,
            price_text="325 EGP",
            availability_text="In stock",
            raw={"category": self._category},
        )
        return Page([item], has_more=False)


async def _marketplace_listing():
    async with SessionLocal() as s:
        return (
            await s.execute(select(Listing).where(Listing.source == "marketplace"))
        ).scalar_one()


async def test_category_comes_from_the_crosswalk_not_the_title():
    """'12pt socket' would match the electronics 'connectors' keyword rule."""
    from makhzan_schemas.models import Category

    await run_source("marketplace", MarketplaceAdapter("12pt-sockets", "12pt Socket Set 10mm"))

    listing = await _marketplace_listing()
    async with SessionLocal() as s:
        category = (
            await s.execute(select(Category).where(Category.id == listing.category_id))
        ).scalar_one()

    assert (category.domain, category.slug) == ("tools", "sockets-drivers")
    assert listing.domain == "tools"


async def test_item_is_normalized_with_its_own_domain_not_the_suppliers():
    """A marketplace's electronics part must be read by the electronics profile.

    Identifier extraction is per-domain and the tools profile has none, so
    normalizing against the supplier default would silently drop the part number
    and stop the listing grouping with the same part from other suppliers.
    """
    await run_source(
        "marketplace", MarketplaceAdapter("zener-diodes", "1N4007 Rectifier Diode 1A 1000V")
    )

    listing = await _marketplace_listing()
    assert listing.domain == "electronics", "category domain wins over supplier default"
    assert listing.part_number == "1N4007", "electronics extractor must have been used"


async def test_tools_item_gets_no_identifier():
    """The same adapter, a tools category: no extractor, so no part number."""
    await run_source("marketplace", MarketplaceAdapter("tape-measures", "LM358 Tape Measure 5m"))

    listing = await _marketplace_listing()
    assert listing.domain == "tools"
    assert listing.part_number is None


async def test_unmapped_category_stays_uncategorized():
    """A crosswalk miss must not fall back to guessing from the title."""
    await run_source("marketplace", MarketplaceAdapter("not-in-crosswalk", "Resistor 10k"))

    listing = await _marketplace_listing()
    assert listing.category_id is None, "must not infer a category for an unmapped source category"
    assert listing.domain == "tools"


# --------------------------------------------------------------------------- #
# Catalogue entries that are not products
# --------------------------------------------------------------------------- #


class ShopWithJunk(StubAdapter):
    """A shop whose feed carries a placeholder, a delivery fee and a service
    beside real stock, as real ones do."""

    def __init__(self, titles):
        super().__init__(pages={1: list(titles)})
        self.titles = titles

    def source_categories(self, raw):
        return list((raw.raw or {}).get("categories") or [])

    async def fetch_page(self, partition: str, page: int) -> Page:
        return Page(
            [
                RawItem(
                    source=SRC,
                    external_id=key,
                    title=title,
                    price_text="10 EGP",
                    raw={"categories": cats},
                )
                for key, (title, cats) in self.titles.items()
            ],
            has_more=False,
        )


@pytest.mark.asyncio
async def test_entries_that_are_not_products_are_never_stored():
    run = await run_source(
        SRC,
        ShopWithJunk(
            {
                "1": ("Arduino Uno R3", ["Boards"]),
                "2": ("point1", []),
                "3": ("Local Delivery", []),
                "4": ("3D Printing Service", ["Services"]),
                "5": ("Disc Brake Pad & Caliper Service Tool Kit", ["Tools"]),
            }
        ),
    )
    titles = {x.title_en for x in await _listings()}
    assert titles == {"Arduino Uno R3", "Disc Brake Pad & Caliper Service Tool Kit"}
    # Named on the run, so a real product skipped by mistake is visible.
    assert set(run.stats["not_products"]) == {
        "point1 (placeholder title)",
        "Local Delivery (delivery fee)",
        "3D Printing Service (filed as a service)",
    }
    assert run.items_seen == 5 and run.items_created == 2


@pytest.mark.asyncio
async def test_a_stored_non_product_is_archived_by_the_next_complete_cycle():
    """No hand cleanup: one stored before the rule existed stops being verified,
    and a completed cycle retires it like stock the shop dropped."""
    async with SessionLocal() as s:
        supplier = Supplier(slug=SRC, name="Test Shop", source_type=SourceType.SCRAPED)
        s.add(supplier)
        await s.flush()
        s.add(
            Listing(
                supplier_id=supplier.id,
                source=SRC,
                source_type=SourceType.SCRAPED,
                external_id="2",
                title_en="Point",
                currency="EGP",
                images=[],
                attributes={},
                status=ListingStatus.ACTIVE,
                confidence=1.0,
            )
        )
        await s.commit()

    run = await run_source(SRC, ShopWithJunk({"1": ("Arduino Uno R3", []), "2": ("Point", [])}))

    assert run.stats.get("archived") == 1
    statuses = {x.title_en: x.status for x in await _listings()}
    assert statuses == {"Arduino Uno R3": ListingStatus.ACTIVE, "Point": ListingStatus.ARCHIVED}


@pytest.mark.parametrize(
    ("title", "categories"),
    [
        # Real products whose titles carry the same words.
        ("Chesterton Lubri-Cup S Automatic Delivery System for Greases", []),
        ("Manual Tire Inflation Service, 12 Bar", []),
        ("O-Ring Service Kit NBR-70 (30 Sizes)", ['Kits "Packages"']),
        ("Item Counter Module 4-Digit", []),
        ("Test Hook Clips (2 pcs)", []),
        ("Laser Pointer 5mW", []),
    ],
)
def test_the_non_product_rules_are_narrow(title, categories):
    """A false positive is a real product silently dropped, so the whole title
    has to be the placeholder or the fee."""
    assert not_a_product(title, categories) is None


@pytest.mark.parametrize(
    ("title", "categories"),
    [("Item", ["Services"]), ("point1", []), ("Point", []), ("Shipping Fee", []), ("Test", [])],
)
def test_placeholders_and_fees_are_not_products(title, categories):
    assert not_a_product(title, categories)
