"""The domain seam.

Phase 1 of the domain generalization: electronics moved behind a profile with no
behaviour change. These tests pin the two things that would silently break —
electronics resolving exactly as before, and a listing taking its domain from its
category rather than from its supplier.

The supplier-level domain is only a fallback. Keying off it would put gaskets and
microcontrollers in the same taxonomy the first time a marketplace spans
verticals, which is precisely the case that motivated this work.
"""

from __future__ import annotations

import pytest
from makhzan_schemas.contracts import RawItem
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.domains import DEFAULT_DOMAIN, PROFILES, DomainProfile, get_profile
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import Category, Listing
from sqlalchemy import select
from worker.pipeline import run_source
from worker.sources.base import Page, SourceAdapter, SupplierInfo

TEST_DOMAIN = "testvertical"


@pytest.fixture
def other_domain():
    """A second vertical, registered for the duration of one test."""
    profile = DomainProfile(
        slug=TEST_DOMAIN,
        name_en="Test Vertical",
        name_ar="قطاع اختباري",
        taxonomy=[("widgets", "Widgets", "ودجات", None), ("tools", "Tools", "أدوات", None)],
        category_rules=[("widgets", ["widget"]), ("tools", ["spanner"])],
    )
    PROFILES[TEST_DOMAIN] = profile
    yield profile
    PROFILES.pop(TEST_DOMAIN, None)


class OneItemAdapter(SourceAdapter):
    source_type = SourceType.SCRAPED
    polite_delay = 0

    def __init__(self, source_id, domain, title):
        self.source_id = source_id
        self.supplier = SupplierInfo(slug=source_id, name=source_id, domain=domain)
        self._title = title

    async def fetch_page(self, partition: str, page: int) -> Page:
        return Page(
            [
                RawItem(
                    source=self.source_id,
                    external_id="x1",
                    title=self._title,
                    price_text="10 EGP",
                    availability_text="In stock",
                )
            ],
            has_more=False,
        )


async def _only_listing(source_id):
    async with SessionLocal() as s:
        return (await s.execute(select(Listing).where(Listing.source == source_id))).scalar_one()


def test_electronics_is_the_default_domain():
    assert DEFAULT_DOMAIN == "electronics"
    assert get_profile(None).slug == "electronics"
    assert get_profile("nonsense-vertical").slug == "electronics"


def test_electronics_profile_still_resolves_known_categories():
    """Verbatim extraction: these mappings must not drift."""
    electronics = get_profile("electronics")
    assert electronics.resolve_category_slug(None, "10k ohm resistor") == "resistors"
    assert electronics.resolve_category_slug(None, "ESP32 DevKit board") == "dev-boards"
    assert electronics.resolve_category_slug(["Capacitors"], "unrelated") == "capacitors"
    # "led" must not fire inside "assembled"
    assert electronics.resolve_category_slug(None, "assembled enclosure") != "leds"


def test_electronics_ranks_its_identifier_first():
    assert get_profile("electronics").search_attributes[0] == "part_number"


async def test_listing_takes_domain_from_its_category(other_domain):
    """A category is authoritative: its domain wins, not the supplier's."""
    await run_source("t-widget", OneItemAdapter("t-widget", TEST_DOMAIN, "Blue Widget 5mm"))

    listing = await _only_listing("t-widget")
    assert listing.domain == TEST_DOMAIN
    async with SessionLocal() as s:
        category = (
            await s.execute(select(Category).where(Category.id == listing.category_id))
        ).scalar_one()
    assert (category.domain, category.slug) == (TEST_DOMAIN, "widgets")


async def test_uncategorized_listing_falls_back_to_supplier_domain(other_domain):
    """With nothing to inherit from, the supplier default applies."""
    await run_source("t-unknown", OneItemAdapter("t-unknown", TEST_DOMAIN, "Nothing matches this"))

    listing = await _only_listing("t-unknown")
    assert listing.category_id is None
    assert listing.domain == TEST_DOMAIN


async def test_same_slug_can_exist_in_two_domains(other_domain):
    """Slugs are unique per domain: electronics 'tools' and the test vertical's coexist."""
    await run_source("t-spanner", OneItemAdapter("t-spanner", TEST_DOMAIN, "Ratchet spanner"))

    async with SessionLocal() as s:
        rows = (await s.execute(select(Category).where(Category.slug == "tools"))).scalars().all()
    assert {c.domain for c in rows} == {"electronics", TEST_DOMAIN}
