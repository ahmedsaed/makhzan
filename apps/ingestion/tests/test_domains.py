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


@pytest.mark.parametrize(
    ("tags", "title", "expected"),
    [
        (None, "OV7670 Camera Module", "cameras"),
        (None, "USB Webcam 1080p Full HD", "cameras"),
        # A camera that connects over Wi-Fi is a camera, not a wireless module.
        (None, "Outdoor Smart Wi-Fi Camera, Sound and Light", "cameras"),
        (None, "WIFI Endoscope 5.5mm Industrial", "cameras"),
        (["AI Machine Vision"], "Depth Kit with PoE, IP67", "cameras"),
        # A camera board is still a board.
        (None, "ESP32-CAM Development Board with OV2640 Camera", "dev-boards"),
        # A thermal camera is a test instrument; "thermal" alone said cooling.
        (None, "Infrared Rapid Thermal Camera", "measurement"),
    ],
)
def test_cameras_and_imaging(tags, title, expected):
    assert get_profile("electronics").resolve_category_slug(tags, title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Things merely *for* a camera keep the leaf they had before.
        ("Camera Battery LP-E6", "batteries"),
        ("Camera Battery Charger NP-F550", "batteries"),
        ("CCTV Camera Power Adapter 12V", "power-supplies"),
        ("IP Camera Power Supply", "power-supplies"),
        ("Pan Tilt Camera Mount for SG90 Servo", "servos"),
        ("Camera Tripod Screw", "mechanical"),
        ("Camera Slider Motorized", "motors"),
        ("Security Camera Cable BNC", None),
        ("Webcam Cover Slider", None),
        ("Camera Housing", None),
        ("Camera Flash Trigger", None),
        ("Machine Vision Light Ring", None),
    ],
)
def test_camera_accessories_are_not_cameras(title, expected):
    assert get_profile("electronics").resolve_category_slug(None, title) == expected


@pytest.mark.parametrize(
    "title",
    ["IP Camera 1080p PoE", "Car Dash Camera Full HD", "Dashcam with G-Sensor", "OV2640 Camera"],
)
def test_cameras_that_say_so_are_cameras(title):
    """A dash cam is a camera."""
    assert get_profile("electronics").resolve_category_slug(None, title) == "cameras"


def test_a_veto_lets_the_text_fall_through_to_later_rules(other_domain):
    """ "!word" in a rule's keywords stops that rule, not the search."""
    profile = DomainProfile(
        slug="vetotest",
        name_en="Veto",
        name_ar="فيتو",
        category_rules=[("widgets", ["widget", "!spare"]), ("parts", ["spare"])],
    )
    assert profile.resolve_category_slug(None, "Blue widget") == "widgets"
    assert profile.resolve_category_slug(None, "Widget spare spring") == "parts"


def test_a_mixed_security_camera_tag_does_not_file_its_contents_as_cameras():
    """One shop's "Security Camera" tag also holds an RFID card copier and
    barcode modules; only a title that says camera is a camera."""
    electronics = get_profile("electronics")
    assert electronics.resolve_category_slug(["Security Camera"], "RFID Card Copier") is None
    assert (
        electronics.resolve_category_slug(["Devices", "Security Camera"], "Indoor Wi-Fi Camera")
        == "cameras"
    )


@pytest.mark.parametrize(
    ("tags", "title"),
    [
        # Kits name their parts; the kit is what they are.
        (None, "Educational Solar Robot Kit 6 in 1"),
        (None, "Humanoid Robot Kit 17DOF with Servo Motors"),
        (None, "Kids Electric Circuit Kit - 56 Parts DIY STEM Toys"),
        (None, "DIY Wood Traffic Lights - Science Toy"),
        (None, "Digital Logic Design Kit - Faculty of Engineering"),
        (None, "Electronics Kit - Engineering Institute, Spring Term"),
        (["Project Kits"], "Smart City Kit"),
        # Ahead of the parts the kit names.
        (None, "Educational Robot Kit with LED Eyes"),
        # A starter or learning kit is a kit, whatever board it is built on.
        (None, "Arduino Starter Kit UNO R3"),
        (None, "Arduino Learning Kit 36 PCS"),
    ],
)
def test_educational_and_robot_kits(tags, title):
    assert get_profile("electronics").resolve_category_slug(tags, title) == "kits"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # A printer's board set, not a course box.
        ("3D Printer Electronics Kit", "printers-3d"),
        # "kit" alone is never enough.
        ("O-Ring Service Kit NBR-70 (30 Sizes)", None),
        ("Soldering Starter Kit 60W", "soldering"),
        # Neither "for kids" nor a bare "stem" makes a kit.
        ("Wired Headphones for Kids", None),
        ("Valve Stem Seal Set", None),
    ],
)
def test_kit_alone_does_not_make_a_teaching_kit(title, expected):
    assert get_profile("electronics").resolve_category_slug(None, title) == expected


def test_photography_is_its_own_department():
    """Studio lights and tripods are not electronics accessories. Filled by
    crosswalk only: inference runs under a supplier's default domain, and no
    supplier defaults to photography, so it carries no keyword rules."""
    photography = get_profile("photography")
    assert photography.slug == "photography"
    leaves = {slug for slug, _en, _ar, parent in photography.taxonomy if parent}
    assert leaves == {"photo-lights", "tripods", "camera-bags", "camera-accessories"}
    assert photography.category_rules == []
    electronics = {slug for slug, *_ in get_profile("electronics").taxonomy}
    assert {"cameras", "kits"} <= electronics


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
