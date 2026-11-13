"""Identifier rules for every department, the family guard and the fallbacks.

The examples are the ones the November 2026 measurement read off the
production catalogue (titles as the shops wrote them). Each rule is tested for
what it must read and, as importantly, what it must not: an identifier is
evidence, and a wrong one is only stopped by the vetoes downstream.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.domains import PROFILES, get_profile
from makhzan_schemas.enums import SourceType
from makhzan_schemas.grouping import _group_listings, assign_identifiers, rebuild_products
from makhzan_schemas.identifiers import (
    bearing_designation,
    fold_identifier,
    hyphenated_model_code,
    model_code,
    o_ring_size,
    oil_seal_size,
    stated_identifiers,
)
from makhzan_schemas.models import Listing, Supplier
from makhzan_schemas.values import is_scale_word, value_tokens, values_conflict
from sqlalchemy import select

from worker.normalize import _first_identifier

ELECTRONICS = get_profile("electronics")
TOOLS = get_profile("tools")
CHEMICALS = get_profile("chemicals")
SEALS = get_profile("seals-bearings")

_SHOPS: dict[str, uuid.UUID] = {}


def _listing(title, shop, domain="electronics", price=100, attributes=None):
    return Listing(
        id=uuid.uuid4(),
        supplier_id=_SHOPS.setdefault(shop, uuid.uuid4()),
        source=shop,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        domain=domain,
        title_en=title,
        part_number=None,
        price=Decimal(price) if price is not None else None,
        images=[],
        attributes=attributes or {},
    )


def _keys(title, profile=ELECTRONICS):
    found = profile.title_identifier(title)
    return found.key if found else None


def _merged(listings):
    """Assign identifiers as a regroup does, then group: the multi-listing groups."""
    assign_identifiers(listings)
    return [items for items in _group_listings(listings).values() if len(items) > 1]


# --------------------------------------------------------------------------- #
# Folding
# --------------------------------------------------------------------------- #


def test_folding_ignores_case_and_separators_between_letters():
    assert fold_identifier("DT-830") == fold_identifier("dt830") == fold_identifier("DT 830")
    assert fold_identifier("HC-SR04") == fold_identifier("HCSR04")


def test_folding_keeps_a_separator_between_digits():
    """There it separates numbers: AMS1117-3.3 is not AMS1117-33, and bearing
    6205-2RS is not a 62052."""
    assert fold_identifier("AMS1117-3.3") != fold_identifier("AMS1117-33")
    assert fold_identifier("6205-2RS") != fold_identifier("62052RS")


# --------------------------------------------------------------------------- #
# Electronics: hobby-market model codes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "title, code",
    [
        ("goot® CP-2515 Solder Wicker Width 2.5mm Length 1.5m", "CP2515"),
        ("Digital Voltmeter / Multimeter ( DT-830 )", "DT830"),
        ("DT-9205E Digital Multimeter", "DT9205E"),
        ("Pocket Oscilloscope DSO-153", "DSO153"),
        ("TB-1505 Fixed Barrier Terminal Block (15A-600V) 5pin", "TB1505"),
        ("RELIFE RL-084 Phone Repair Tool", "RL084"),
        ("KY-032 Obstacle Avoidance Sensor", "KY032"),
        ("HLK-10M24 AC-DC Module 220vac to 24VDC 10W HI LINK", "HLK10M24"),
        ("OSEPP LS-00051 Breadboard", "LS00051"),
        ("WAGO LT-223-6 Panel Mount Wire Connector 6 In 6 Out", "LT223-6"),
    ],
)
def test_hyphenated_model_codes_are_read(title, code):
    assert _keys(title) == code


def test_a_hyphenated_code_meets_the_same_code_written_without_one():
    """The MPN rule reads "DT830B"; the new rule reads "DT-830B": one key."""
    assert _keys("DT830B Multimeter") == _keys("Multimeter DT-830B") == "DT830B"


def test_the_mpn_rule_still_wins():
    assert ELECTRONICS.extract_identifier("LM358 Dual Op-Amp DIP-8") == "LM358"
    assert ELECTRONICS.extract_identifier("ESP32-WROOM-32 Module") == "ESP32-WROOM-32"


@pytest.mark.parametrize(
    "title",
    [
        # Measurement vocabulary: a scale and its reading, never a product.
        "Flexible Tinned Copper Silicone Wire AWG-16 (Black-1m)",
        "Stepper Motor (NEMA-17) 42mm",
        "Stepper Motor (NEMA-42) 110mm",
        "2SK1507 N-Channel MOSFET Transistor 600V 9A TO-220",
        # The tail is a value: the label of a reading.
        "Mini Heat Gun HG-2000W",
        # References: what the listing fits or comes with.
        "Extruder Kit Metal Grey for Creality CR-10",
        "Digital Logic Kit with ZY-204 Breadboard",
        # A word and a count, not a code.
        "Breadboard Jumper Wires Pack-40",
    ],
)
def test_readings_references_and_words_are_not_model_codes(title):
    assert hyphenated_model_code(title) is None


def test_scale_words_are_measurement_vocabulary():
    for word in ("AWG", "NEMA", "IP", "M", "DN", "PN", "PH", "P", "HSS", "SS", "DIN", "TO"):
        assert is_scale_word(word)
    for maker_code in ("DT", "CR", "RL", "TB", "KY", "ASR", "SW"):
        assert not is_scale_word(maker_code)


# --------------------------------------------------------------------------- #
# The family guard
# --------------------------------------------------------------------------- #


def test_a_code_one_shop_uses_for_several_products_is_a_family():
    """FC-40 male, female and angled from one shop: the code names a range, so
    nobody's FC-40 is grouped on it."""
    listings = [
        _listing("IDC FC-40 Male Angle Connector for PCB 40 pin", "shop-a"),
        _listing("IDC FC-40 Female Connector for Flat Cable 40 pin", "shop-a"),
        _listing("FC-40 Female IDC Connector with Strain Relief, 2.54mm Pitch", "shop-b"),
    ]
    assert _merged(listings) == []
    assert all(listing.part_number is None for listing in listings)


def test_the_same_title_listed_twice_is_a_duplicate_not_a_family():
    listings = [
        _listing("TB-2512 Fixed Barrier Terminal Block (25A-600V) 12pin", "shop-a"),
        _listing("TB-2512 Fixed Barrier Terminal Block (25A-600V) 12pin", "shop-a"),
        _listing("TB-2512 - 12 Pin Fixed Barrier Terminal Block (25A-600V)", "shop-b"),
    ]
    assign_identifiers(listings)
    assert {listing.part_number for listing in listings} == {"TB-2512"}


def test_a_code_with_one_title_per_shop_merges_across_shops():
    listings = [
        _listing("WAGO LT-223-4 Panel Mount Wire Connector 4 In 4 Out", "shop-a", price=45),
        _listing("WAGO 4 in 4 out WAGO LT-223-4 Universal Compact Wire Connector", "shop-b"),
    ]
    assert len(_merged(listings)) == 1


def test_cr10_never_merges_a_printer_with_its_parts():
    """CR-10 is a printer that spare parts are named after. A part "for CR-10" is
    a reference; a shop selling several CR-10 parts proves the code is a family.
    No list names it."""
    listings = [
        _listing("CR-10 Smart Pro 3D Printer 300×300×400mm", "printer-shop", price=25000),
        _listing("CR-10 Extruder Hotend Kit Round Red 24V", "parts-shop", price=600),
        _listing("CR-10 all metal extruder improved version", "parts-shop", price=450),
        _listing("Hot Bed Leveling Springs for Creality CR-10", "other-shop", price=50),
    ]
    assert _merged(listings) == []


def test_awg_and_nema_never_group():
    listings = [
        _listing("Flexible Tinned Copper Silicone Wire AWG-16 (Red-1m)", "shop-a"),
        _listing("Wire AWG-16 (Red-1m)", "shop-b"),
        _listing("Stepper Motor (NEMA-17) 17HS4401", "shop-a"),
        _listing("Stepper Motor Holder (NEMA-17) CNC 42mm", "shop-b"),
    ]
    assign_identifiers(listings)
    assert [listing.part_number for listing in listings[:2]] == [None, None]
    assert all("NEMA" not in (listing.part_number or "") for listing in listings[2:])


def test_a_family_code_falls_through_to_what_the_shop_states():
    listings = [
        _listing("HW-357 Charger (Type-C)", "shop-a", attributes={"mfr_part_number": "HW357C"}),
        _listing("HW-357 Charger (micro)", "shop-a", attributes={"mfr_part_number": "HW357M"}),
    ]
    assign_identifiers(listings)
    assert [listing.part_number for listing in listings] == ["HW357C", "HW357M"]


# --------------------------------------------------------------------------- #
# Every veto still applies
# --------------------------------------------------------------------------- #


def test_one_shop_never_merges_with_itself_even_on_a_designation():
    listings = [
        _listing("6205-2RS Deep Groove Ball Bearing", "marketplace", "seals-bearings"),
        _listing("SKF 6205-2RS Bearing", "marketplace", "seals-bearings"),
    ]
    assign_identifiers(listings)
    assert listings[0].part_number == listings[1].part_number == "6205-2RS"
    assert _merged(listings) == []


def test_different_values_under_one_code_do_not_merge():
    """SMA A500 gel 200 ml and A500 with a 400 ml activator: one code, two products."""
    listings = [
        _listing("SMA A500 Quick Adhesive Multi Purpose Gel 200ml", "shop-a", "chemicals", 90),
        _listing("SMA A500 Instant Adhesive with Activator 400mL", "shop-b", "chemicals", 120),
    ]
    assign_identifiers(listings)
    assert listings[0].part_number == listings[1].part_number == "A500"
    assert _merged(listings) == []


def test_volume_is_a_value():
    assert values_conflict(value_tokens("WD-40 Spray 100ml"), value_tokens("WD-40 Spray 330 mL"))
    assert not values_conflict(value_tokens("Glue 50ml"), value_tokens("Glue 50 ML"))


def test_titles_that_disagree_do_not_merge_on_a_shared_code():
    """YTH-109 is a wire stripper at one shop and a flush-cut plier at another."""
    listings = [
        _listing("Wire Stripper and Cutter YTH109", "shop-a", "tools"),
        _listing("YTH-109 Mini Flush Cut Plier 5 Inch", "shop-b", "tools"),
    ]
    assert _merged(listings) == []


def test_matching_stays_within_a_department():
    listings = [
        _listing("TNI-U TU-501 Cutting Pliers", "shop-a", "tools"),
        _listing("TNI-U TU-501 Cutting Pliers", "shop-b", "electronics"),
    ]
    assert _merged(listings) == []


# --------------------------------------------------------------------------- #
# Seals and bearings: designations
# --------------------------------------------------------------------------- #


def test_bearing_suffixes_make_different_products():
    open_, shielded, sealed = (
        bearing_designation("6205 Deep Groove Ball Bearing"),
        bearing_designation("6205-ZZ Deep Groove Ball Bearing"),
        bearing_designation("6205-2RS Deep Groove Ball Bearing"),
    )
    assert [open_.value, shielded.value, sealed.value] == ["6205", "6205-ZZ", "6205-2RS"]
    assert len({open_.key, shielded.key, sealed.key}) == 3
    assert bearing_designation("6205 Z Bearing").key != shielded.key
    assert bearing_designation("6205-RS Bearing").key != sealed.key


def test_each_makers_seal_spelling_folds_to_one():
    keys = {
        bearing_designation(f"{code} Bearing").key
        for code in ("6205-2RS", "6205-2RS1", "6205 2RSR", "6205DDU", "6205LLU", "6205-2RSH")
    }
    assert keys == {fold_identifier("6205-2RS")}
    assert bearing_designation("6205-2Z Bearing").key == bearing_designation("6205ZZ Bearing").key


def test_clearance_and_design_suffixes_are_kept():
    assert bearing_designation("6205-2RS C3 Bearing").value == "6205-2RS-C3"
    assert bearing_designation("24134 MBW33C3 Spherical Roller Bearing").value == "24134MBW33-C3"
    assert bearing_designation("UCHA203 Pillow Block Bearing Unit").value == "UCHA203"
    assert bearing_designation("697 ZZ Deep Groove Ball Bearing").value == "697-ZZ"
    assert bearing_designation("Ball Bearing 608zz 8x22x7mm").value == "608-ZZ"


def test_a_bearing_is_only_read_from_a_bearing_title():
    assert bearing_designation("Steel Pipe 6205 Fitting") is None
    assert bearing_designation("V-groove Wheel with 625ZZ Bearings") is None  # a part it has
    assert bearing_designation("Bearing Puller M10 Thread") is None


def test_o_ring_size_is_its_identity():
    assert o_ring_size("O-Ring297x4").value == "O-RING 297X4"
    assert o_ring_size("O-Ring 10.0 x 2").key == o_ring_size("o ring NBR 10x2.0").key
    assert o_ring_size("O-Ring10.5x2").key != o_ring_size("O-Ring105x2").key
    assert o_ring_size("O-ring Set 225 Piece Amtech") is None


def test_oil_seal_dimensions_and_profile():
    assert oil_seal_size("Oil seal A15x6x4").value == "OIL SEAL A 15X6X4"
    assert oil_seal_size("Oil seal AS15x6x4").key != oil_seal_size("Oil seal A15x6x4").key
    assert oil_seal_size("Oil Seal 85x60x8 mm (FKM + SS304 + PTFE)").value == "OIL SEAL 85X60X8"
    assert oil_seal_size("Oil seal A-DUO365x325x20").value == "OIL SEAL ADUO 365X325X20"
    assert oil_seal_size("Oil seal 20x35") is None


def test_seals_profile_tries_bearing_then_o_ring_then_oil_seal():
    assert SEALS.extract_identifier("6202-2RS Deep Groove Ball Bearing") == "6202-2RS"
    assert SEALS.extract_identifier("O-Ring44x3.5") == "O-RING 44X3.5"
    assert SEALS.extract_identifier("Oil seal AS52x25x7") == "OIL SEAL AS 52X25X7"
    assert SEALS.extract_identifier("Graphite Gland Packing 10mm") is None


# --------------------------------------------------------------------------- #
# Tools and chemicals: letter-led catalogue codes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "title, code",
    [
        ("Modular Monoblock Set with 12 Drawers ASR-6014", "ASR6014"),
        ("TNI-U Wire Cutter – TU501 Side Snips", "TU501"),
        ('5 inch Wire Cutter "TNI-U TU-501"', "TU501"),
        ("M&R Screwdriver Set 5pcs MR-818", "MR818"),
        ("STEARNEL SDL-8611 Hot Air Gun 1800W", "SDL8611"),
        ('Ceta Form Triangular File 10", Fine, Model J58-210', "J58-210"),
        ("Standard Cutting Pliers 180 Mm, Ceta Form, Model E06-43-0180", "E06-43-0180"),
    ],
)
def test_tools_catalogue_codes_are_read(title, code):
    assert _keys(title, TOOLS) == code


@pytest.mark.parametrize(
    "title",
    [
        "Screwdriver Set 6-in-1",
        "Pipe Wrench 5 inch",
        "Phillips Screwdriver No.2",
        "Socket Set 6Piece",
        "Total Test Pencil 3x140mm",
        "Hex Bolt M8x20",
        "Drill Bit HSS-10",
        "Wire Stripper for AWG-16",
        "Phillips Bit PH2 50mm",
    ],
)
def test_tools_sizes_and_readings_are_not_codes(title):
    assert model_code(title) is None


def test_a_value_glued_to_a_code_is_cut_off():
    assert model_code("Rust Remover WD40-330ml").value == "WD40"
    assert model_code("Pattex MDF Kit 50 ml-200 ml") is None


@pytest.mark.parametrize(
    "title, code",
    [
        ("AMRO Super Glue GP999 20gr", "GP999"),
        ("RELIFE 50ML CP-0001 Transparent High Elasticity Adhesive", "CP0001"),
        ("Md-50 Silicone Spray Oil Lubricant Aerosol – 400 Ml", "MD50"),
    ],
)
def test_chemicals_product_codes_are_read(title, code):
    assert _keys(title, CHEMICALS) == code


def test_departments_without_rules_read_nothing():
    """Codes there are family-level (EZC250H at 100 A and 250 A) or sizes; the
    seam is `identifier_rules` on their profile, empty for now."""
    for slug in ("electrical", "piping", "timber", "machinery", "welding", "safety"):
        profile = PROFILES[slug]
        assert profile.identifier_rules == ()
        assert profile.extract_identifier("Schneider EZC250H 3P 100A") is None
        assert profile.identifier_candidates("x", {"mfr_part_number": "EZC250H"}) == []


# --------------------------------------------------------------------------- #
# What a shop states: fallbacks only
# --------------------------------------------------------------------------- #


def test_the_title_wins_over_what_the_shop_states():
    found = ELECTRONICS.identifier_candidates(
        "DT-830 Multimeter", {"mfr_part_number": "XYZ123", "specs": {"Model": "XM-830"}}
    )
    assert [c.value for c in found] == ["DT-830", "XYZ123", "XM-830"]


def test_mfr_part_number_then_model_when_the_title_names_nothing():
    attrs = {"mfr_part_number": "CR0603JA0121G", "specs": {"Model": "R0603"}}
    assert _first_identifier("electronics", "Chip Resistor SMD 120Ω 0603", attrs) == (
        "CR0603JA0121G"
    )
    model_only = {"specs": {"Model Number": "JR-L007", "Color": "black"}}
    assert _first_identifier("electronics", "Power Bank 10000mAh", model_only) == "JR-L007"


def test_stated_codes_that_are_sizes_or_readings_are_refused():
    assert stated_identifiers({"specs": {"Model": "18650"}}) == []
    assert stated_identifiers({"mfr_part_number": "AWG-16"}) == []
    assert stated_identifiers({"specs": {"Supported Models": "CR-10"}}) == []
    assert stated_identifiers({"specs": {"Model": "Standard edition"}}) == []


def test_seals_do_not_use_shop_stated_codes():
    assert SEALS.identifier_candidates("Gland Packing", {"mfr_part_number": "GP-100"}) == []


def test_shop_stated_codes_merge_across_shops_and_are_family_checked():
    listings = [
        _listing("Linear Bearing Block SCS12UU (Closed – 12mm Dia)", "shop-a", price=130),
        _listing(
            "Linear Motion Ball Bearing Slide Block – 12mm",
            "shop-b",
            price=60,
            attributes={"specs": {"Model": "SCS12UU"}},
        ),
    ]
    assert len(_merged(listings)) == 1
    stated = stated_identifiers({"specs": {"Model": "SCS12UU"}})
    assert stated[0].family_checked


# --------------------------------------------------------------------------- #
# A regroup re-reads identifiers; a dry run keeps nothing
# --------------------------------------------------------------------------- #


async def _stored(title: str, shop: Supplier) -> uuid.UUID:
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=shop.id,
        source=shop.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        domain="electronics",
        title_en=title,
        part_number=None,  # read under the old rules: nothing
        price=Decimal(60),
        images=[],
        attributes={},
    )
    async with SessionLocal() as session:
        session.add(listing)
        await session.commit()
    return listing.id


async def test_a_regroup_reads_new_identifiers_without_a_recrawl():
    shops = []
    async with SessionLocal() as session:
        for slug in ("wick-a", "wick-b"):
            shop = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
            session.add(shop)
            shops.append(shop)
        await session.commit()
    first = await _stored("goot CP-2515 Solder Wick 2.5mm 1.5m", shops[0])
    second = await _stored("Solder Wick CP-2515 goot (2.5mm, 1.5m)", shops[1])

    async with SessionLocal() as session:
        dry = await rebuild_products(session, dry_run=True, reidentify=True)
    assert dry["reidentified"] == 2 and dry["multi_supplier"] == 1
    async with SessionLocal() as session:
        stored = await session.scalar(select(Listing.part_number).where(Listing.id == first))
    assert stored is None, "a dry run keeps nothing"

    async with SessionLocal() as session:
        await rebuild_products(session, reidentify=True)
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Listing.part_number, Listing.product_id).where(
                    Listing.id.in_([first, second])
                )
            )
        ).all()
    assert {row.part_number for row in rows} == {"CP-2515"}
    assert len({row.product_id for row in rows}) == 1


# --------------------------------------------------------------------------- #
# Review fixes (November 2026)
# --------------------------------------------------------------------------- #


def test_shop_spellings_of_grams_are_values():
    """ "XG-50 Solder Paste 42Gm" and "35gm" were merged: "gm" was not a unit."""
    assert values_conflict(value_tokens("XG-50 Solder Paste 42Gm"), value_tokens("XG-50 35gm"))
    for spelling in ("20g", "20 gr", "20grm", "20 gms", "20gm"):
        assert value_tokens(spelling) == {"mass": frozenset({Decimal(20)})}
    assert value_tokens("2 kgs")["mass"] == frozenset({Decimal(2000)})
    assert value_tokens("100 mls")["volume"] == frozenset({Decimal(100)})


def test_ranges_with_one_floor_and_far_ceilings_conflict():
    """An SSR switching 5-60 VDC is not one switching 5-200 VDC."""
    a = value_tokens("SSR-40DD Solid State Relay (3-32Vdc / 5-60Vdc)")
    b = value_tokens("Solid State Relay SSR-40 DD 3V~32VDC to 5V~200VDC")
    assert values_conflict(a, b)
    # Envelopes described loosely stay compatible, as does silence.
    assert not values_conflict(value_tokens("Buck 9-42V"), value_tokens("Buck 8-40V"))
    assert not values_conflict(a, value_tokens("SSR-40DD Solid State Relay"))
    # Two values that are not one dimension are not a range.
    assert value_tokens("DC Power Supply 30V-5A") == {
        "volt": frozenset({Decimal(30)}),
        "amp": frozenset({Decimal(5)}),
    }


def test_a_fixed_value_still_conflicts_with_a_range_written_with_both_units():
    assert values_conflict(
        value_tokens("LM2596 (+5V, 3A) Step-Down Regulator"),
        value_tokens("Step-Down Regulator with Display LM2596 3.2V-35V 3A"),
    )


@pytest.mark.parametrize(
    "title",
    [
        'Pipe Wrench12" Hardwell',
        'Hand File10"',
        'Total Bolt Cutter14"',
        "Total Chuck Key13 Mm",
        "Bosch Gop Accessories Universal Set13 Pcs For Multi-tool",
        "Drill bit SDS Plus10*450",
        "Circumference Rule, ø 20-300mm, Circ.60-950mm Vogel",
        'Claber Flexyfort Green d.5/8" mt.30',
        "Drill Bit HSS-10 Cobalt",
    ],
)
def test_tools_words_and_sizes_glued_to_numbers_are_not_codes(title):
    assert model_code(title) is None


def test_the_best_code_in_a_title_wins_not_the_first():
    assert model_code("Power Organizer Box-13 11 ASR-2064").value == "ASR-2064"
    assert model_code("Wheel Nut Wrench17×19×21×22 Mm, Ceta Form, N23-011").value == "N23-011"


def test_a_closing_quote_is_not_an_inch_mark():
    assert model_code('5 inch Wire Cutter "TNI-U TU-501"').value == "TU-501"
    assert model_code("Delta Organizer 5” ASR-5050").value == "ASR-5050"


def test_sw_is_a_code_and_p_is_a_grit():
    """SW-420 is a sensor, not a wrench size. "P" stays a scale: most P-numbers
    in tools titles are sanding grits (P80, P120), at the cost of P-led codes."""
    assert hyphenated_model_code("Vibration Sensor Blue SW-420 20mA 12V").value == "SW-420"
    assert model_code("10 x P120 grit circular sanding sheets (125mm diameter)") is None
    assert model_code("150cm Spirit Level – Ceta Form, Model P22-150") is None


def test_separators_between_digits_are_one_hyphen():
    assert fold_identifier("J58 210") == fold_identifier("J58-210") == fold_identifier("j58_210")
    assert fold_identifier("AMS1117 3.3") == fold_identifier("AMS1117-3.3")


def test_electronics_reads_a_bearing_only_when_it_states_its_seal():
    assert ELECTRONICS.extract_identifier("Ball Bearing 624ZZ 4X13X5MM") == "624-ZZ"
    assert ELECTRONICS.extract_identifier("775 Motor with Ball Bearing") is None
    assert ELECTRONICS.extract_identifier("2020 Bearing Wheel for V-slot") is None
    assert SEALS.extract_identifier("6321 Deep Groove Ball Bearing") == "6321"


def test_sizes_of_one_product_are_not_a_family():
    """One shop's 2 mm and 3 mm wick is one product in two sizes: the value veto
    keeps the sizes apart, and the code stays usable."""
    listings = [
        _listing("RELIFE RL-3020 Soldering Wick 2mm", "shop-a"),
        _listing("RELIFE RL-3020 Soldering Wick 3mm", "shop-a"),
        _listing("RELIFE RL-3020 Soldering Wick 3mm", "shop-b"),
    ]
    assign_identifiers(listings)
    assert {listing.part_number for listing in listings} == {"RL-3020"}
    merged = _merged(listings)
    assert len(merged) == 1
    assert {listing.title_en for listing in merged[0]} == {"RELIFE RL-3020 Soldering Wick 3mm"}


def test_a_title_that_only_adds_words_is_not_another_product():
    listings = [
        _listing("TNI-U Wire Cutter – TU501 Side Snips for Electronics", "shop-a", "tools"),
        _listing('5 inch Wire Cutter "TNI-U TU-501"', "shop-a", "tools"),
    ]
    assign_identifiers(listings)
    assert {listing.part_number for listing in listings} == {"TU501", "TU-501"}


def test_regrouping_twice_changes_nothing_the_second_time():
    listings = [
        _listing("IDC FC-40 Male Connector", "shop-a"),
        _listing("IDC FC-40 Female Connector", "shop-a"),
        _listing("WAGO LT-223-4 Connector", "shop-b", attributes={"specs": {"Model": "LT-223-4"}}),
        _listing("Chip Resistor 0603", "shop-c", attributes={"mfr_part_number": "CR0603JA0121G"}),
    ]
    assert assign_identifiers(listings) > 0
    assert assign_identifiers(listings) == 0


def test_an_adapter_supplied_part_number_is_kept():
    listing = _listing(
        "ESP32 DevKit V1 Development Board",
        "shop-a",
        attributes={"adapter_part_number": "ESP32-WROOM-32"},
    )
    assign_identifiers([listing])
    assert listing.part_number == "ESP32-WROOM-32"
