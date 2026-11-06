"""Cross-supplier product grouping.

An extracted identifier is evidence, not proof. It comes from a title, so it also
matches titles that merely reference the part — "bracket for SG90", "robot arm
kit with 4x SG90" — and merging those puts a mounting bracket inside a servo.

Two listings sharing an identifier are therefore only merged when their titles
agree that they are the same thing, and nothing vetoes it: the same shop, a
different value of the same unit, a different form, or an implausible price gap.

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
            # Within 4x of b, but 9x of a — the cluster would span too far.
            _listing("XL4015 Buck Converter Module", 900, "XL4015", source="c"),
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
    assert value_tokens(title) == {}


def test_values_conflict_only_when_both_state_the_dimension():
    assert values_conflict(value_tokens("Fan 12V"), value_tokens("Fan 24V"))
    assert not values_conflict(value_tokens("Fan 12V"), value_tokens("Fan"))
    assert not values_conflict(value_tokens("Module 3.3V 5V"), value_tokens("Module 5V"))
    assert values_conflict(value_tokens("Driver 3Pcs"), value_tokens("Driver"))
    assert not values_conflict(value_tokens("Battery (1 pc)"), value_tokens("Battery"))
