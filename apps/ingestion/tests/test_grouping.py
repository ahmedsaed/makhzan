"""Cross-supplier product grouping.

An extracted identifier is evidence, not proof. It comes from a title, so it also
matches titles that merely reference the part — "bracket for SG90", "robot arm
kit with 4x SG90" — and merging those puts a mounting bracket inside a servo.

Two listings sharing an identifier are therefore only merged when something else
agrees: their titles describe the same thing, or their prices sit in the same
band. Either alone suffices, because suppliers word the same part very
differently while a bracket and the servo it fits agree on neither.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from makhzan_schemas.enums import SourceType
from makhzan_schemas.grouping import _group_listings
from makhzan_schemas.models import Listing


def _listing(title, price, part_number, source="s1", domain="electronics"):
    return Listing(
        id=uuid.uuid4(),
        supplier_id=uuid.uuid4(),
        source=source,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
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
