"""Cross-supplier product grouping.

An extracted identifier is evidence, not proof. It comes from a title, so it also
matches titles that merely reference the part — "bracket for SG90", "robot arm
kit with 4x SG90" — and merging those puts a mounting bracket inside a servo.

Two listings sharing an identifier are therefore only merged when their titles
agree that they are the same thing, and nothing vetoes it: the same shop, a
different value of the same unit, a different form, or a price gap of 10x or more.

The shops in these tests are fictional; the titles are real ones that were
merged wrongly.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from makhzan_schemas.enums import SourceType
from makhzan_schemas.grouping import _group_listings
from makhzan_schemas.models import Listing
from makhzan_schemas.values import value_tokens, values_conflict

#: One supplier id per fictional shop, so listings from the same `source` share it.
_SUPPLIERS: dict[str, uuid.UUID] = {}


def _listing(title, price, part_number, source=None, domain="electronics", external_id=None):
    # Without a named shop, each listing is its own supplier: most tests here are
    # about two shops' titles, not one shop's catalogue.
    supplier_id = _SUPPLIERS.setdefault(source, uuid.uuid4()) if source else uuid.uuid4()
    return Listing(
        id=uuid.uuid4(),
        supplier_id=supplier_id,
        source=source or "s1",
        source_type=SourceType.SCRAPED,
        external_id=external_id or str(uuid.uuid4()),
        domain=domain,
        title_en=title,
        part_number=part_number,
        price=Decimal(str(price)) if price is not None else None,
        images=[],
        attributes={},
    )


def _group_count(listings):
    return len(_group_listings(listings))


def test_price_alone_no_longer_merges():
    """The regression that made this rule change.

    "ESP32" is a family prefix, not a part, and within a family everything costs
    about the same — so price agreed with everything. An MP3 player, a battery
    shield and a dev board ended up as one product with 22 offers spanning 99 to
    850 EGP. Prices being similar is not evidence that two things are the same.
    """
    groups = _group_listings(
        [
            _listing("ESP32 Development Board 30 pin", 260, "ESP32", source="a"),
            _listing("DFPlayer MP3 Mini Player for Arduino, ESP32", 495, "ESP32", source="b"),
        ]
    )
    assert len(groups) == 2, "a similar price is not evidence of being the same part"


def test_the_cost_of_that_rule_is_some_under_merging():
    """Documented, because it is a real loss and was chosen deliberately.

    Suppliers do word the same part very differently, and price used to bridge
    that. Without it these two LM358 listings become separate products. Under-
    merging shows fewer suppliers on a page; over-merging publishes a price range
    that is false and offers that are not the same item. The second is worse.
    """
    groups = _group_listings(
        [
            _listing("LM358 Dual Op Amp IC", 12, "LM358", source="a"),
            _listing("LM358N Op Amps, 1MHz, 3:32 V, 8-Pin PDIP", 15, "LM358", source="b"),
        ]
    )
    assert len(groups) == 2


def test_matching_titles_merge_across_a_normal_price_gap():
    groups = _group_listings(
        [
            _listing("NE555 Timer IC DIP-8", 12, "NE555", source="a"),
            _listing("NE555 Timer IC DIP-8", 45, "NE555", source="b"),
        ]
    )
    assert len(groups) == 1, "matching titles corroborate on their own"


def test_price_vetoes_an_implausible_gap_between_identical_titles():
    """Identical titles priced 15x apart are a pack and a single unit. Merging
    them publishes "from EGP 3" beside a 45 EGP item, which is false."""
    groups = _group_listings(
        [
            _listing("NE555 Timer IC DIP-8", 3, "NE555", source="a"),
            _listing("NE555 Timer IC DIP-8", 45, "NE555", source="b"),
        ]
    )
    assert len(groups) == 2


def test_accessory_referencing_a_part_does_not_merge_with_it():
    """The failure this guard exists for: 'bracket for SG90' is not an SG90."""
    groups = _group_listings(
        [
            _listing("SG90 Micro Servo Motor", 85, "SG90", source="a"),
            _listing("DIY Acrylic Robot Arm Kit with 4x SG90 Servos", 950, "SG90", source="b"),
        ]
    )
    assert len(groups) == 2, "different wording and price band means different products"


def test_pack_of_many_does_not_merge_with_a_single_unit():
    groups = _group_listings(
        [
            _listing("1N4007 General Purpose Rectifier Diode 1A", Decimal("0.45"), "1N4007"),
            _listing("1N4007 Through Hole Diode Pack of 1000", 350, "1N4007", source="b"),
        ]
    )
    assert len(groups) == 2


def test_corroboration_is_not_limited_to_known_families():
    """No hardcoded list: SG90 and CR10 were never on the old _AMBIGUOUS regex."""
    groups = _group_listings(
        [
            _listing("Ender3/CR10 Hotend Kit With Silicon Sock", 400, "CR10", source="a"),
            _listing("BLV Guide Rail Mod for Creality CR10 upgrade", 7500, "CR10", source="b"),
        ]
    )
    assert len(groups) == 2


def test_listings_without_an_identifier_stay_singletons():
    groups = _group_listings(
        [
            _listing("Some Unbranded Widget", 10, None, source="a"),
            _listing("Some Unbranded Widget", 10, None, source="b"),
        ]
    )
    assert len(groups) == 2, "no identifier means no merge, however similar"


def test_missing_prices_fall_back_to_titles():
    """A missing price is not evidence either way."""
    merged = _group_listings(
        [
            _listing("ESP8266 ESP-01 WiFi Module", None, "ESP-01", source="a"),
            _listing("ESP8266 ESP-01 WiFi Module", None, "ESP-01", source="b"),
        ]
    )
    assert len(merged) == 1

    split = _group_listings(
        [
            _listing("ESP-01 Programmer Adapter Board", None, "ESP-01", source="a"),
            _listing("ESP8266 ESP-01 WiFi Serial Transceiver", None, "ESP-01", source="b"),
        ]
    )
    assert len(split) == 2


def test_a_title_poor_listing_does_not_turn_its_cluster_into_a_magnet():
    """Half of the original bug.

    A candidate used to be compared only against the *first* member of a
    cluster. "ESP32 Development Board 30 pin" reduces to {pin} once the
    identifier and noise words are stripped, so a cluster seeded by it could
    never be matched on title by anything — leaving price as the only way in.
    Comparing against every member fixes that.
    """
    groups = _group_listings(
        [
            # Seeds the cluster and is nearly tokenless after stripping.
            _listing("ESP32 Development Board", 300, "ESP32", source="a"),
            _listing("ESP32 CAM Camera Module OV2640", 495, "ESP32", source="b"),
            # Matches the second member, not the first.
            _listing("ESP32 CAM Camera OV2640", 520, "ESP32", source="c"),
        ]
    )
    by_size = sorted((len(v) for v in groups.values()), reverse=True)
    assert by_size == [2, 1], "the two cameras belong together, the bare board apart"


def test_the_price_veto_measures_the_whole_cluster_not_its_first_member():
    """A band centred on one mid-priced member reached from 65 to 1040 EGP and
    swallowed the family. The span is what has to stay inside the ratio."""
    groups = _group_listings(
        [
            _listing("XL4015 Buck Converter Module", 100, "XL4015", source="a"),
            _listing("XL4015 Buck Converter Module", 300, "XL4015", source="b"),
            # Within 10x of b, but 12x of a — the cluster would span too far.
            _listing("XL4015 Buck Converter Module", 1200, "XL4015", source="c"),
        ]
    )
    assert len(groups) == 2


def _sizes(groups):
    return sorted((len(v) for v in groups.values()), reverse=True)


def _together(groups, *titles):
    """Whether every one of these titles landed in the same product."""
    homes = {key for key, items in groups.items() for item in items if item.title_en in set(titles)}
    return len(homes) == 1


# --------------------------------------------------------------------------- #
# A shop's two SKUs are two products
# --------------------------------------------------------------------------- #


def test_two_listings_from_one_shop_never_merge():
    """A shop lists two SKUs because they differ. Across the catalogue, 485
    products held two or more listings from one shop — 23 KSD301 thermal switches
    from 40 to 140 °C, thirteen trimpot values — and almost none were duplicates.
    Even word-for-word duplicates stay apart: that under-merge is honest."""
    groups = _group_listings(
        [
            _listing("WTH118 Potentiometer 1W", 25, "WTH118", source="volta"),
            _listing("WTH118 Potentiometer 1W", 25, "WTH118", source="volta"),
        ]
    )
    assert len(groups) == 2


def test_another_shop_joins_the_variant_it_matches_not_the_first_one():
    groups = _group_listings(
        [
            _listing("KSD301 Thermal Switch NC 140°C (10A, 250V)", 18, "KSD301", source="volta"),
            _listing("KSD301 Thermal Switch NC 40°C (10A, 250V)", 18, "KSD301", source="volta"),
            _listing("KSD301 Thermal Switch NC 40C 10A", 20, "KSD301", source="ohmic"),
        ]
    )
    assert _sizes(groups) == [2, 1]
    assert _together(
        groups,
        "KSD301 Thermal Switch NC 40°C (10A, 250V)",
        "KSD301 Thermal Switch NC 40C 10A",
    )


# --------------------------------------------------------------------------- #
# Values: a number next to a unit is what tells variants apart
# --------------------------------------------------------------------------- #


def test_thermal_switches_of_different_temperatures_do_not_merge():
    groups = _group_listings(
        [
            _listing("KSD301 Thermal Switch NC 40°C (10A, 250V)", 18, "KSD301", source="volta"),
            _listing("KSD301 Thermal Switch NC 120C (10A, 250V)", 18, "KSD301", source="ohmic"),
        ]
    )
    assert len(groups) == 2


def test_esp32_boards_with_30_and_38_pins_do_not_merge():
    """The `ESP32` product held 30- and 38-pin boards from three shops. The pin
    count was the only difference, and "30" and "38" were dropped as bare digits
    before titles were compared."""
    groups = _group_listings(
        [
            _listing("ESP32 Development Board 30-Pin with CP2102", 280, "ESP32", source="volta"),
            _listing("ESP32S ESP-WROOM-32 38-Pin CP2102", 290, "ESP32", source="ohmic"),
            _listing(
                "ESP32 Development Board 30 pin (WIFI - Bluetooth)", 260, "ESP32", source="pcb"
            ),
        ]
    )
    assert _together(
        groups,
        "ESP32 Development Board 30-Pin with CP2102",
        "ESP32 Development Board 30 pin (WIFI - Bluetooth)",
    )
    assert not _together(
        groups, "ESP32S ESP-WROOM-32 38-Pin CP2102", "ESP32 Development Board 30-Pin with CP2102"
    )


def test_180_degree_and_continuous_servos_do_not_merge():
    """MG996R 180° and 360° servos were one product across four shops.
    "Continuous rotation" states 360° without a digit."""
    groups = _group_listings(
        [
            _listing("MG996R Servo Motor 180° 11 kg.cm Metal Gears", 195, "MG996R", source="volta"),
            _listing("MG996R Servo Motor 360° 11 kg.cm Metal Gears", 210, "MG996R", source="ohmic"),
            _listing(
                "MG996R Servo Motor Tower Pro Continues Rotation (Full Metal Gear)",
                190,
                "MG996R",
                source="pcb",
            ),
            _listing(
                "MG996R High Torque Servo Motor (180° Rotation) (Full Metal Gear)",
                180,
                "MG996R",
                source="relay",
            ),
        ]
    )
    for items in groups.values():
        stated = {value_tokens(i.title_en).get("angle") for i in items} - {None}
        assert len(stated) <= 1, f"180° and 360° merged: {[i.title_en for i in items]}"


def test_optocoupler_boards_of_different_channel_counts_do_not_merge():
    groups = _group_listings(
        [
            _listing("PC817 Optocoupler Isolation Board 2 Channel", 40, "PC817", source="volta"),
            _listing("PC817 - 4 Channel Optocoupler Isolation Board", 60, "PC817", source="ohmic"),
            _listing("PC817 Optocoupler Isolation Module 2-Channel", 70, "PC817", source="pcb"),
        ]
    )
    assert _sizes(groups) == [2, 1]
    assert _together(
        groups,
        "PC817 Optocoupler Isolation Board 2 Channel",
        "PC817 Optocoupler Isolation Module 2-Channel",
    )


def test_drives_of_different_power_do_not_merge_and_units_are_compared_by_value():
    """0.75 to 11 kW drives were one product: the 3.65x spread stayed under the
    price veto. Power is compared as a value, so 0.75 kW and 750 W agree."""
    small = "Variable Speed Drive, ATV320, 0.75 KW, 380…500 V, 3 Phases"
    split = _group_listings(
        [
            _listing(small, 26886, "ATV320", source="volta"),
            _listing("Variable Speed Drive ATV320 - 11kW - 380...500V", 89034, "ATV320", "ohmic"),
        ]
    )
    assert len(split) == 2
    merged = _group_listings(
        [
            _listing(small, 26886, "ATV320", source="volta"),
            _listing("ATV320 Variable Speed Drive 750W 3 Phases", 27500, "ATV320", "ohmic"),
        ]
    )
    assert len(merged) == 1


def test_a_multipack_does_not_merge_with_a_single_unit():
    """Silence on quantity means one unit: "– 3Pcs" at 1,275 EGP sat beside
    single drivers at about 425."""
    groups = _group_listings(
        [
            _listing("TB6600 4A Stepper Motor Driver – 3Pcs", 1275, "TB6600", source="volta"),
            _listing("TB6600 Stepper Motor Driver 4A", 425, "TB6600", source="ohmic"),
        ]
    )
    assert len(groups) == 2


def test_a_value_only_one_title_states_does_not_split():
    """Silence is not a conflict — most shops do not repeat every rating."""
    groups = _group_listings(
        [
            _listing("TP4056 Lithium Battery Charger Module 1A", 20, "TP4056", source="volta"),
            _listing("TP4056 Lithium Battery Charger Module", 18, "TP4056", source="ohmic"),
        ]
    )
    assert len(groups) == 1


# --------------------------------------------------------------------------- #
# Form: a chip is not a module, and a bracket is not the sensor it holds
# --------------------------------------------------------------------------- #


def test_a_bare_chip_does_not_merge_with_its_module():
    """A TP4056 SOP-8 sat inside a six-shop charger-module product: "ic",
    "module" and "board" are all noise words, so the titles looked alike."""
    groups = _group_listings(
        [
            _listing("SMD IC TP4056 Battery Management SOP-8", 12, "TP4056", source="volta"),
            _listing("TP4056 Battery Charger Module With Protection", 22, "TP4056", "ohmic"),
            _listing("TP4056 SMD Battery charger IC", 15, "TP4056", source="pcb"),
        ]
    )
    assert _sizes(groups) == [2, 1]
    assert _together(
        groups, "SMD IC TP4056 Battery Management SOP-8", "TP4056 SMD Battery charger IC"
    )


def test_an_rtc_chip_does_not_merge_with_the_rtc_module():
    groups = _group_listings(
        [
            _listing("DS1302 Real Time Clock (RTC) IC DIP-8", 15, "DS1302", source="volta"),
            _listing("DS1302 RTC Real Time Clock Module", 40, "DS1302", source="ohmic"),
        ]
    )
    assert len(groups) == 2


def test_a_bracket_does_not_merge_with_the_part_it_holds():
    """A title that says nothing about form is usually the part itself, so an
    accessory conflicts even with silence. Half its words in common and 15
    against 40 EGP cleared both the title and the price checks."""
    bracket = "Ultrasonic Sensor Mounting Bracket For HC-SR04"
    another_bracket = "Ultrasonic Sensor Bracket HC-SR04"
    groups = _group_listings(
        [
            _listing(bracket, 15, "HC-SR04", source="volta"),
            _listing("Ultrasonic Sensor HC-SR04", 40, "HC-SR04", source="ohmic"),
            _listing(another_bracket, 11, "HC-SR04", source="pcb"),
        ]
    )
    assert _sizes(groups) == [2, 1]
    assert _together(groups, bracket, another_bracket)


@pytest.mark.parametrize(
    ("titled", "plain"),
    [
        # Both pairs are from the local catalogue, and were kept apart by "mount".
        ("D-SUB DB15 Female Right Angle PCB Mount", "Female DB15 Right Angle on PCB Solder Type"),
        ("WAGO NV-F15 Panel Mount Wire Connector 1 In 5 Out", "WAGO F15 Wire Connector 1 In 5 Out"),
        ("Toggle Switch E-TEN1322 Surface-Mount", "Toggle Switch E-TEN1322"),
        ("ESP-01 ESP8266 WiFi with adapter", "ESP-01 ESP8266 WiFi"),
    ],
)
def test_how_a_part_is_fitted_is_not_an_accessory(titled, plain):
    """ "PCB Mount" says how a connector is fitted, not that it is a mount."""
    mpn = {"DB15": "DB15", "F15": "F15", "TEN1322": "TEN1322", "ESP": "ESP8266"}
    part = next(v for k, v in mpn.items() if k in titled)
    groups = _group_listings([_listing(titled, 30, part), _listing(plain, 30, part)])
    assert len(groups) == 1


@pytest.mark.parametrize(
    "accessory", ["SG90 Servo Mount Bracket", "Servo Motor Mount SG90", "SG90 Servo Adapter"]
)
def test_a_mount_for_a_part_is_still_an_accessory(accessory):
    groups = _group_listings(
        [_listing(accessory, 20, "SG90"), _listing("SG90 Micro Servo Motor", 30, "SG90")]
    )
    assert len(groups) == 2


def test_a_makers_colours_and_a_resellers_spool_stay_apart():
    """A filament maker lists one product per colour; resellers list one per
    material, with colour as an option. Grouping is not taught that a reseller's
    spool is "any of" the maker's colours, so nothing merges: no identifier is
    read from these titles, and each listing stands alone. Titles are the
    shapes the real shops use, with the brand changed."""
    from makhzan_schemas.domains import get_profile

    profile = get_profile("electronics")
    maker = [
        "Acme Black PLA+ 3D printer filament",
        "Acme White PLA+ 3D printer filament",
        "Acme Black PETG HF 3D printer filament",
        "Acme PLA-CF 3D printer filament",
    ]
    resellers = [
        ("Acme PLA+ Filament 1.75mm 1Kg Roll for 3D Printer", "ohmic"),
        ("Acme Brand PLA+ 3D Printer Filament (1.75mm) - 1Kg Roll", "volta"),
        ("Acme PLA CF Filament 1.75mm (Carbon Fiber Reinforced, 1kg)", "ohmic"),
    ]
    listings = [_listing(t, 695, profile.extract_identifier(t), source="maker") for t in maker] + [
        _listing(t, 650, profile.extract_identifier(t), source=s) for t, s in resellers
    ]
    assert all(item.part_number is None for item in listings)
    assert _sizes(_group_listings(listings)) == [1] * len(listings)


def test_grouping_does_not_depend_on_the_order_listings_arrive_in():
    """External ids are unique only within a shop: two shops' "1" must still sort
    the same way every run, or the seed (and so the key) of a group drifts."""
    listings = [
        _listing("Ultrasonic Sensor HC-SR04 ranging", 40, "HC-SR04", source="b", external_id="1"),
        _listing("HC-SR04 Ultrasonic Sensor", 42, "HC-SR04", source="a", external_id="1"),
        _listing("Ultrasonic Sensor HC-SR04 sonar", 41, "HC-SR04", source="c", external_id="1"),
    ]
    keys = {tuple(sorted(_group_listings(order))) for order in (listings, listings[::-1])}
    assert len(keys) == 1


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #


def test_variants_with_colliding_signatures_get_keys_that_do_not_depend_on_siblings():
    """Variants worded alike apart from the value share a token signature. The
    collision is broken by the seed listing's own natural key, not by position,
    so a sibling appearing or vanishing does not rename the others."""

    def switch(celsius, external_id):
        title = f"KSD301 Thermal Switch NC {celsius}°C"
        return _listing(title, 18, "KSD301", source="volta", external_id=external_id)

    first, forty, ninety = switch(70, "1"), switch(40, "2"), switch(90, "3")

    def key_of(groups, listing):
        return next(k for k, items in groups.items() if listing in items)

    without = _group_listings([forty, ninety])
    with_sibling = _group_listings([first, forty, ninety])
    assert key_of(without, ninety) == key_of(with_sibling, ninety)
    assert len(with_sibling) == 3


# --------------------------------------------------------------------------- #
# Value tokens themselves
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("title", "dimension", "values"),
    [
        ("ESP32 Development Board 38pin", "pin", {38}),
        ("ESP32 Development Board 38-Pin", "pin", {38}),
        ("Terminal Block 2P", "pin", {2}),
        ("KSD301 Thermal Switch NC 100°C", "temperature", {100}),
        ("KSD301 Thermostat (90C Normally Close)", "temperature", {90}),
        ("Servo 360deg", "angle", {360}),
        ("Servo 180 Degree", "angle", {180}),
        ("Servo Continuous Rotation", "angle", {360}),
        ("Relay Module 4CH", "channel", {4}),
        ("Optocoupler Single Channel", "channel", {1}),
        ("Drive 0.75kW", "watt", {750}),
        ("Fan 12V", "volt", {12}),
        ("Battery (2 Pcs)", "quantity", {2}),
        ("Resistor pack of 10", "quantity", {10}),
        ("Linear Rail 1000mm", "length", {1000}),
        ("Gear Motor 12V 130RPM", "speed", {130}),
        ("Gear Motor 12V 170 RPM", "speed", {170}),
    ],
)
def test_value_tokens_are_read_from_titles(title, dimension, values):
    assert value_tokens(title)[dimension] == {Decimal(v) for v in values}


@pytest.mark.parametrize(
    "title",
    [
        # A number glued to letters before it is part of a part number.
        "MG996R Servo",
        "AMS1117 Regulator",
        # A range is an operating envelope, not a variant.
        "Stepper Driver 9-42V",
        "Drive 380…500 V",
        # A bare letter unit has to touch its number.
        "Arduino 4 c",
    ],
)
def test_what_is_not_a_value(title):
    """No single value; a range is kept apart, under "range:<dimension>"."""
    assert {k for k in value_tokens(title) if not k.startswith("range:")} == set()


def test_values_conflict_only_when_both_state_the_dimension():
    assert values_conflict(value_tokens("Fan 12V"), value_tokens("Fan 24V"))
    assert not values_conflict(value_tokens("Fan 12V"), value_tokens("Fan"))
    assert not values_conflict(value_tokens("Module 3.3V 5V"), value_tokens("Module 5V"))
    assert values_conflict(value_tokens("Driver 3Pcs"), value_tokens("Driver"))
    assert not values_conflict(value_tokens("Battery (1 pc)"), value_tokens("Battery"))


# --------------------------------------------------------------------------- #
# Incumbency: a settled product is not reshuffled by a newcomer sorted first
# --------------------------------------------------------------------------- #

_PRODUCT = uuid.uuid4()
#: The four shops already grouped as one 1N5817 product, two of them silent on
#: the voltage, and the marketplace's contradicting listing ("30V"; a 1N5817
#: is a 20 V part), whose source sorts ahead of all of them.
_SETTLED = [
    ("ampere", "1N5817 Schottky Diode 1A 20V DO-41"),
    ("makers", "1N5817 Schottky Barrier Diode"),
    ("most", "Schottky Diode 1N5817 1A 20V"),
    ("ram", "1N5817 Schottky Diode"),
]


def _diode(source, title, product_id=None):
    listing = _listing(title, 2, "1N5817", source=source)
    listing.product_id = product_id
    return listing


def _members_by_shop(groups):
    return sorted(sorted(i.source for i in items) for items in groups.values())


def test_from_scratch_a_stated_only_code_cannot_evict_a_title_that_names_it():
    """The marketplace's "1A 30V Schottky Barrier Diode" states 1N5817 beside
    its title. Sorting first, it used to seed the group on a first build and
    leave out a shop whose title names the 20 V part."""
    listings = [_diode(src, title) for src, title in _SETTLED]
    listings.append(_diode("aaa-marketplace", "1A 30V Schottky Barrier Diode"))
    assert _members_by_shop(_group_listings(listings)) == [
        ["aaa-marketplace"],
        sorted(src for src, _ in _SETTLED),
    ]


def test_a_stated_only_member_keeps_no_incumbency_against_titles_naming_the_part():
    """Day 1 the 30 V marketplace diode, stating 1N5817 beside its title, is
    grouped with two titles silent on voltage; day 2 two 20 V shops arrive.
    The silent titles join the 20 V shops, as they would from scratch."""
    day1 = [_diode(s, t) for s, t in _SETTLED if s in ("makers", "ram")]
    day1.append(_diode("aaa-marketplace", "1A 30V Schottky Barrier Diode"))
    (first,) = _group_listings(day1).values()
    product = uuid.uuid4()
    for listing in first:
        listing.product_id = product
    day2 = day1 + [_diode(s, t) for s, t in _SETTLED if s in ("ampere", "most")]
    assert _members_by_shop(_group_listings(day2)) == [
        ["aaa-marketplace"],
        sorted(src for src, _ in _SETTLED),
    ]


def test_a_contradicting_newcomer_does_not_break_a_settled_product():
    listings = [_diode(src, title, _PRODUCT) for src, title in _SETTLED]
    listings.append(_diode("aaa-marketplace", "1N5817 Schottky Diode 1A 30V"))
    assert _members_by_shop(_group_listings(listings)) == [
        ["aaa-marketplace"],
        ["ampere", "makers", "most", "ram"],
    ]


def test_on_a_first_build_the_plain_order_still_applies():
    """No product ids yet: the same listings are placed in (source, id) order, as
    before, so the early contradicting listing seeds and captures the silent."""
    listings = [_diode(src, title) for src, title in _SETTLED]
    listings.append(_diode("aaa-marketplace", "1N5817 Schottky Diode 1A 30V"))
    assert _members_by_shop(_group_listings(listings)) == [
        ["aaa-marketplace", "makers", "ram"],
        ["ampere", "most"],
    ]


def test_a_newcomer_that_agrees_joins_the_settled_product():
    listings = [_diode(src, title, _PRODUCT) for src, title in _SETTLED]
    listings.append(_diode("aaa-marketplace", "1N5817 Schottky Diode 1A 20V"))
    assert _members_by_shop(_group_listings(listings)) == [
        ["aaa-marketplace", "ampere", "makers", "most", "ram"],
    ]


def test_a_wrong_existing_merge_still_splits():
    """Incumbency is not immunity: members of one product that the vetoes now
    reject leave it."""
    product = uuid.uuid4()
    listings = [
        _diode("ampere", "1N5817 Schottky Diode 1A 20V", product),
        _diode("makers", "1N5817 Schottky Diode 1A 20V", product),
        _diode("most", "1N5817 Schottky Diode 1A 40V", product),
    ]
    groups = _group_listings(listings)
    assert _members_by_shop(groups) == [["ampere", "makers"], ["most"]]
    assert sum(len(items) for items in groups.values()) == len(listings), "each listing once"


def test_two_existing_products_the_rules_now_join_merge():
    first, second = uuid.uuid4(), uuid.uuid4()
    listings = [
        _diode("ampere", "1N5817 Schottky Diode 1A 20V", first),
        _diode("makers", "1N5817 Schottky Diode 20V", first),
        _diode("most", "1N5817 Schottky Diode 1A", second),
        _diode("ram", "1N5817 Schottky Diode", second),
    ]
    assert _members_by_shop(_group_listings(listings)) == [["ampere", "makers", "most", "ram"]]


def test_a_misfit_does_not_seed_the_product_it_sorts_first_in():
    """The member that contradicts the most others is evicted, not made the
    seed: the consistent majority keeps the product."""
    product = uuid.uuid4()
    listings = [
        _diode("aaa", "1N5817 Schottky Diode 1A 30V", product),
        _diode("bbb", "1N5817 Schottky Diode", product),
        _diode("ccc", "1N5817 Schottky Diode 1A 20V", product),
        _diode("ddd", "1N5817 Schottky Diode 20V 1A", product),
        _diode("eee", "1N5817 Schottky Diode", product),
    ]
    assert _members_by_shop(_group_listings(listings)) == [
        ["aaa"],
        ["bbb", "ccc", "ddd", "eee"],
    ]


def test_existing_products_do_not_merge_across_a_veto():
    # The same shop on both sides.
    first, second = uuid.uuid4(), uuid.uuid4()
    same_shop = [
        _diode("ampere", "1N5817 Schottky Diode", first),
        _diode("makers", "1N5817 Schottky Diode", first),
        _diode("ampere", "1N5817 Schottky Diode DO-41", second),
        _diode("ram", "1N5817 Schottky Diode", second),
    ]
    assert len(_group_listings(same_shop)) == 2
    # Two products that state different values.
    third, fourth = uuid.uuid4(), uuid.uuid4()
    values = [
        _diode("ampere", "1N5817 Schottky Diode 20V", third),
        _diode("makers", "1N5817 Schottky Diode 20V", third),
        _diode("most", "1N5817 Schottky Diode 40V", fourth),
        _diode("ram", "1N5817 Schottky Diode 40V", fourth),
    ]
    assert _members_by_shop(_group_listings(values)) == [["ampere", "makers"], ["most", "ram"]]


def test_incumbency_follows_products_through_merges():
    """`current` resolves a listing's product through `merged_into`. Here an
    absorbed product's two listings still carry its id and the survivor's one
    listing carries its own: unresolved, the survivor's listing is a newcomer
    and joins the contradicting marketplace listing it resembles more; resolved,
    the three are one product and the marketplace listing stands alone."""
    survivor, absorbed = uuid.uuid4(), uuid.uuid4()
    listings = [
        _diode("ampere", "1N5817 Schottky Diode 20V", absorbed),
        _diode("ram", "1N5817 Schottky Diode", absorbed),
        _diode("makers", "1N5817 Schottky Diode 1A", survivor),
        _diode("aaa-marketplace", "1N5817 Schottky Diode 1A 30V"),
    ]
    assert _members_by_shop(_group_listings(listings)) == [
        ["aaa-marketplace", "makers"],
        ["ampere", "ram"],
    ]
    current = {
        listing.id: (survivor if listing.product_id == absorbed else listing.product_id)
        for listing in listings
    }
    assert _members_by_shop(_group_listings(listings, current)) == [
        ["aaa-marketplace"],
        ["ampere", "makers", "ram"],
    ]


def test_clusters_left_apart_by_the_placing_order_merge_at_the_end():
    """A and B share no word, C shares words with both: placed in order, A
    seeds, B starts its own cluster, C joins A's. Nothing vetoes B joining
    them, so the last merge brings it in."""
    listings = [
        _listing("1N4148 alpha beta", 1, "1N4148", source="shop-a"),
        _listing("1N4148 gamma delta", 1, "1N4148", source="shop-b"),
        _listing("1N4148 alpha beta gamma delta", 1, "1N4148", source="shop-c"),
    ]
    assert _members_by_shop(_group_listings(listings)) == [["shop-a", "shop-b", "shop-c"]]


def test_an_incumbents_members_are_checked_against_each_other():
    """Each member of an existing product is added one at a time and checked
    against those already in: the 20 V and the 30 V listing both suit the
    silent one, but not each other."""
    product = uuid.uuid4()
    listings = [
        _diode("bbb", "1N5817 Schottky Diode", product),
        _diode("ccc", "1N5817 Schottky Diode 20V", product),
        _diode("ddd", "1N5817 Schottky Diode 30V", product),
    ]
    assert _members_by_shop(_group_listings(listings)) == [["bbb", "ccc"], ["ddd"]]


def test_group_keys_depend_only_on_membership():
    """The same groups reached from scratch or through incumbency carry the
    same keys."""
    listings = [_diode(src, title) for src, title in _SETTLED]
    listings.append(_diode("aaa-marketplace", "1N5817 Schottky Diode 1A 30V"))
    scratch = _group_listings(listings)
    for key, items in scratch.items():
        for listing in items:
            listing.product_id = uuid.uuid5(uuid.NAMESPACE_URL, key)
    again = _group_listings(listings)
    assert {k: {i.id for i in v} for k, v in again.items()} == {
        k: {i.id for i in v} for k, v in scratch.items()
    }


def test_a_second_grouping_from_the_first_changes_nothing():
    """Convergence: group from scratch, give each listing its group as a
    product, group again — the same groups."""
    listings = [_diode(src, title) for src, title in _SETTLED]
    listings.append(_diode("aaa-marketplace", "1N5817 Schottky Diode 1A 30V"))
    listings.append(_diode("zzz", "1N5817 Schottky Diode 1A 20V DO-41"))
    first = _group_listings(listings)
    for key, items in first.items():
        for listing in items:
            listing.product_id = uuid.uuid5(uuid.NAMESPACE_URL, key)
    second = _group_listings(listings)
    assert _members_by_shop(second) == _members_by_shop(first)


# --------------------------------------------------------------------------- #
# Relaxed vetoes: what owner-labelled pairs showed the vetoes blocking wrongly
# --------------------------------------------------------------------------- #
#
# Each pair below is two shops' listings of one product, judged so by the owner,
# that a veto kept apart. Several carry no identifier in the catalogue (so they
# are never compared today); they are given a code that is not in either title
# here, because what is under test is the veto, not identifier extraction.


def _fired(a, b, part_number, price_a=10, price_b=10):
    """Which vetoes keep two titles apart, read exactly as grouping reads them."""
    from makhzan_schemas.domains import get_profile
    from makhzan_schemas.grouping import _form, _forms_conflict, _span_ok, _without_identifier

    profile = get_profile("electronics")
    fired = set()
    va = value_tokens(_without_identifier(a, part_number))
    vb = value_tokens(_without_identifier(b, part_number))
    if values_conflict(va, vb):
        fired.add("values")
    form_a, form_b = _form(a, part_number), _form(b, part_number)
    if _forms_conflict(form_a, form_b, profile.accessory_forms):
        fired.add("form")
    prices = [Decimal(str(price_a))]
    if not _span_ok(prices, Decimal(str(price_b)), profile.merge_price_ratio):
        fired.add("price")
    return fired


@pytest.mark.parametrize(
    ("a", "price_a", "b", "price_b"),
    [
        ("Ceramic Capacitor 47PF – 50v (47PF)", "0.5", "Capacitors Ceramic 47pf. 50v (47)", 3),
        ("Ceramic Capacitor 220pF 50V", "0.5", "Capacitors Ceramic 220pf. 50v (221)", 3),
        (
            "Audio Plug - Miniature Jack Socket - 3.5mm Mono",
            "8.5",
            "Audio Plug 3.5mm Mono Miniature Jack Socket",
            1,
        ),
        ("TTP223 Capacitive Touch Sensor Red", 10, "Touch Switch Module TTP223", 50),
    ],
)
def test_a_price_gap_under_ten_times_is_not_a_veto(a, price_a, b, price_b):
    """Shops price one part very differently. At 4x, the price veto alone was
    wrong on about one pair in forty it fired on; these were among them."""
    assert _fired(a, b, "TESTCODE", price_a, price_b) == set()


def test_the_same_capacitor_at_six_times_the_price_merges():
    groups = _group_listings(
        [
            _listing("Ceramic Capacitor 220pF 50V", "0.5", "CC220", source="volta"),
            _listing("Capacitors Ceramic 220pf. 50v (221)", 3, "CC220", source="ohmic"),
        ]
    )
    assert len(groups) == 1


@pytest.mark.xfail(
    strict=True,
    reason="known remaining false veto: a branded sensor at 15x a generic one is the "
    "same product (brand alone does not make a different product), but 15x is past "
    "the 10x price veto and nothing else tells it from a pack",
)
def test_a_branded_sensor_far_above_a_generic_one_is_the_same_product():
    assert "price" not in _fired(
        "OSEPP HUMI-01 DHT11 Humidity & Temperature Sensor",
        "DHT11 Temperature And Humidity Sensor Module with LED",
        "DHT11",
        680,
        45,
    )


@pytest.mark.parametrize(
    ("a", "b", "part_number"),
    [
        # A USB-serial converter, called a "cable" and a "... to Serial Adapter".
        (
            "FTDI FT232RL USB to TTL Converter Module",
            "USB TO UART TTL FTDI 5V 3.3V FT232RL Download Cable To Serial Adapter Module "
            "For Arduino",
            "FT232RL",
        ),
        # The same case, two words for it.
        (
            "Clear Acrylic Case Enclosure for Arduino UNO",
            "Acrylic Casefor Arduino UNO Protective Shell",
            "TESTCODE",
        ),
        # A heat sink that comes with the driver is not what the listing is.
        (
            "TMC2208 Stepper Motor Driver Module with Heat Sink for 3D Printer Part",
            "TMC2208 V1.2 Stepper Motor Driver for 3D Printer",
            "TMC2208",
        ),
        # One battery holder, called a spacer and a holder.
        (
            "Battery Spacer ( 1 x 18650 ) imported",
            "18650 1×1 Spacer Single Battery 1 Cell Holder",
            "TESTCODE",
        ),
        # SMD is how the board's chip is mounted; it is still the board.
        ("Arduino Uno Rev3 SMD", "Arduino Board – Arduino UNO Rev3", "TESTCODE"),
        # "(Heat Sink)" glosses what the cooling block is.
        (
            "Aluminium Water Cooling Block Head 40x40x12mm (Heat Sink)",
            "Aluminum Water Cooling Block for Peltier 40x40mm",
            "TESTCODE",
        ),
        # A holder and a clip, each with a DC plug.
        (
            "Battery Holder 9V + Standard 2.1mm DC Male Plug",
            "9V Battery Clip with standard DC Male Plug",
            "TESTCODE",
        ),
        # A cover or shell that comes with the element.
        (
            "Piezo Buzzer Element with Aluminum Cover",
            "Piezoelectric Piezo Ceramic 15mm + Aluminum shell",
            "TESTCODE",
        ),
    ],
)
def test_form_words_that_do_not_say_what_the_listing_is_do_not_veto(a, b, part_number):
    assert _fired(a, b, part_number) == set()


def test_a_driver_with_a_heat_sink_merges_with_the_driver():
    groups = _group_listings(
        [
            _listing(
                "TMC2208 Stepper Motor Driver Module with Heat Sink for 3D Printer Part",
                200,
                "TMC2208",
                source="volta",
            ),
            _listing("TMC2208 V1.2 Stepper Motor Driver for 3D Printer", 290, "TMC2208", "ohmic"),
        ]
    )
    assert len(groups) == 1


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (
            "Energizer Alkaline AAA 1.5V Battery 2 PCS (Made in China)",
            "Energizer Alkaline AAA 1.5V Two Batteries",
        ),
        (
            "Energizer Alkaline AAA 1.5V Two Batteries",
            "Energizer 1.5V AAA Size Battery Alkaline (Pack of 2)",
        ),
        ("AAA Battery Pack of Two", "AAA Battery 2 Pieces"),
    ],
)
def test_a_count_spelled_out_is_the_same_pack(a, b):
    assert _fired(a, b, "TESTCODE") == set()


@pytest.mark.parametrize(
    ("title", "quantity"),
    [
        ("Energizer AAA Two Batteries", 2),
        ("Resistor Pack of Two", 2),
        ("Header Three Pcs", 3),
        ("Fuse twelve pieces", 12),
        ("Pair of Wheels", 2),
        ("Battery 2 Pieces", 2),
    ],
)
def test_counts_written_as_words_are_read(title, quantity):
    assert value_tokens(title)["quantity"] == {Decimal(quantity)}


@pytest.mark.parametrize("title", ["Relay One Channel", "Two Way Switch", "Three Phase Motor"])
def test_a_number_word_that_counts_something_else_is_not_a_pack(title):
    assert "quantity" not in value_tokens(title)


def test_a_counted_pack_still_does_not_merge_with_one_unit():
    assert "values" in _fired("AAA Battery Two Batteries", "AAA Battery", "TESTCODE")
    assert "values" in _fired("AAA Battery Pack of 4", "AAA Battery Two Pcs", "TESTCODE")


# The look-alikes the relaxed vetoes must still keep out.


def test_an_adapter_board_for_a_module_does_not_merge_with_the_module():
    """An adapter for a part is an accessory of it, even when called a module."""
    module = "ESP-01 ESP8266 Serial WIFI Wireless Transceiver Module"
    adapter = "ESP-01 Adapter Module"
    programmer = "USB to UART/ESP8266 Adapter Programmer for ESP-01 WiFi Modules with CH340G Chip"
    groups = _group_listings(
        [
            _listing(module, 90, "ESP-01", source="a"),
            _listing(adapter, 40, "ESP-01", source="b"),
            _listing(programmer, 65, "ESP-01", source="c"),
        ]
    )
    assert not _together(groups, module, adapter)
    assert not _together(groups, module, programmer)
    assert "form" in _fired(module, adapter, "ESP-01")
    assert "form" in _fired(module, programmer, "ESP-01")


def test_a_laptop_dc_jack_is_not_a_panel_jack_adapter():
    """Never compared — they read different identifiers — and, if they were,
    the panel jack's "adapter" is not the "to X adapter" of a converter."""
    from makhzan_schemas.domains import get_profile

    laptop = "DC Power Jack Female Socket Connector for Laptop 5.5mmx2.1mm"
    panel = "2.1×5.5mm 2.1mm Jack Adapter Female DC Power Plastic Socket Panel Mount for Box DC022B"
    profile = get_profile("electronics")
    listings = [
        _listing(laptop, "4.5", profile.extract_identifier(laptop), source="a"),
        _listing(panel, 7, profile.extract_identifier(panel), source="b"),
    ]
    assert len(_group_listings(listings)) == 2
    assert "form" in _fired(laptop, panel, "TESTCODE", "4.5", 7)


def test_a_different_regulator_family_reads_a_different_identifier():
    """A 78R12 is a low-dropout regulator, not an LM7812, and at 6x the price
    the price veto no longer says so. Identifiers do: they never share a group."""
    from makhzan_schemas.domains import get_profile

    profile = get_profile("electronics")
    titles = ["Voltage Regulator 78R12", "LM7812 Voltage Regulator Integrated Circuit Chip"]
    listings = [
        _listing(t, p, profile.extract_identifier(t), source=s)
        for t, p, s in zip(titles, (5, 30), ("a", "b"), strict=True)
    ]
    assert listings[0].part_number != listings[1].part_number
    assert len(_group_listings(listings)) == 2


@pytest.mark.parametrize(
    ("accessory", "part"),
    [
        ("HC-SR04 Ultrasonic Sensor Mounting Bracket with Screws", "HC-SR04 Ultrasonic Sensor"),
        ("18650 Battery Holder", "18650 Battery 3.7V"),
        ("18650 Battery Clip", "18650 Battery 3.7V"),
        ("Raspberry Pi 4 Case + Fan", "Raspberry Pi 4 Model B"),
        ("Heat Sink for TO-220", "LM7805 Regulator TO-220"),
    ],
)
def test_an_accessory_named_as_such_still_does_not_merge_with_its_part(accessory, part):
    assert "form" in _fired(accessory, part, "TESTCODE")


def test_gear_motors_of_different_speeds_do_not_merge():
    """A bracket used to keep these apart by accident (an accessory word); with
    "with Bracket" read as included, the speed is what tells them apart."""
    groups = _group_listings(
        [
            _listing(
                "GA25-370 DC Gear Motor with Encoder 12V 280RPM with Bracket", 475, "GA25-370"
            ),
            _listing("GA25-370 DC Gear Motor with Encoder 12V 130RPM 4.4kg.cm", 450, "GA25-370"),
        ]
    )
    assert len(groups) == 2
