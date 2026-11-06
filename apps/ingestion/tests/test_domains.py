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


@pytest.mark.parametrize(
    ("tags", "title", "expected"),
    [
        # A shop tag naming two leaves at once; the title decides.
        (["3D Printer Filament"], "PLA Filament 1.75mm 1Kg Roll for 3D Printer", "filament"),
        (["3D Printer Filament"], "Extrusion Nozzle for 3D Printer (0.4)", "printer-parts"),
        (
            ["3D Printer Filament"],
            "CREALITY Ender-3 V2 3D Printer 220 x 220 x 250mm",
            "printers-3d",
        ),
        # Something sold "for 3D Printer" is not a printer.
        (None, "Anodized Aluminum Heated Bed Plate For 3D Printer", "printer-parts"),
        (None, "ESUN PETG 3D Filament 1.75mm 1Kg Roll for 3D Printer", "filament"),
        # "resin" is a filament word, but not in front of "printer".
        (None, "ELEGOO Mars 5 Ultra 9K Resin 3D Printer", "printers-3d"),
        (None, "Standard Resin V2.0 405nm 1Kg", "filament"),
        (None, "Flashforge Adventurer 5M 3D Printer", "printers-3d"),
    ],
)
def test_filament_and_printer_parts_win_over_a_printer_they_fit(tags, title, expected):
    assert get_profile("electronics").resolve_category_slug(tags, title) == expected


@pytest.mark.parametrize(
    "title",
    ["Steel V-Slot Gantry Plate", "Linear Shaft Chrome Plated 8mm", "Plastic Gear Set 61PCS"],
)
def test_short_filament_names_are_whole_words(title):
    """As prefixes, "pla" and "abs" filed plates, plating and plastic as filament."""
    assert get_profile("electronics").resolve_category_slug(None, title) != "filament"


@pytest.mark.parametrize("title", ["PLA+ Filament 1.75mm", "eSUN ABS+ 1.75mm 1kg", "PLA 1kg"])
def test_short_filament_names_still_match_the_material(title):
    assert get_profile("electronics").resolve_category_slug(None, title) == "filament"


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
