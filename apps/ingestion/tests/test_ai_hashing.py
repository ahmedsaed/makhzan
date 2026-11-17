"""A listing's content hash moves with what a judge could read, and with nothing else (P5)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from makhzan_schemas.ai.hashing import content_fields, listing_hash
from makhzan_schemas.ai.policy import ACTIVE, KEV_REVISION, MODELS, POLICIES, thresholds


def _listing(**changes):
    base = dict(
        id=uuid.uuid4(),
        title_en="Example Relay Module 5V",
        title_ar="وحدة مرحل",
        brand="Examplebrand",
        part_number="ER-1",
        description_en="A synthetic relay module.",
        price=Decimal("120.00"),
        stock_signal="in_stock",
        images=["https://example.invalid/a.jpg"],
        attributes={"specs": {"Voltage": "5V", "Channels": "1"}, "mfr_part_number": "MFR-1"},
    )
    base.update(changes)
    return SimpleNamespace(**base)


def test_price_stock_photos_and_other_attributes_leave_the_hash_alone():
    before = listing_hash(_listing(), "Relays")
    attributes = {
        "specs": {"Voltage": "5V", "Channels": "1"},
        "mfr_part_number": "MFR-1",
        "details_fetched_at": "2026-11-01",
        "options": {"Colour": ["red"]},
    }
    after = _listing(
        price=Decimal("95.00"), stock_signal="out_of_stock", images=[], attributes=attributes
    )
    assert listing_hash(after, "Relays") == before


def test_every_field_that_reaches_a_prompt_moves_it():
    before = listing_hash(_listing(), "Relays")
    changed = [
        _listing(title_en="Example Relay Module 12V"),
        _listing(title_ar="وحدة مرحل أخرى"),
        _listing(brand="Otherbrand"),
        _listing(part_number="ER-2"),
        _listing(attributes={"specs": {"Voltage": "5V", "Channels": "1"}, "mfr_part_number": "X"}),
        _listing(
            attributes={"specs": {"Voltage": "12V", "Channels": "1"}, "mfr_part_number": "MFR-1"}
        ),
        _listing(description_en="Another description."),
    ]
    for listing in changed:
        assert listing_hash(listing, "Relays") != before
    assert listing_hash(_listing(), "Modules") != before


def test_it_is_deterministic_over_key_order_and_whitespace():
    a = _listing(
        title_en="Example  Relay\tModule 5V ",
        attributes={"mfr_part_number": "MFR-1", "specs": {"Channels": "1", "Voltage": " 5V"}},
        description_en="A synthetic\n\nrelay   module.",
    )
    assert listing_hash(a, " Relays ") == listing_hash(_listing(), "Relays")


def test_empty_counts_as_absent():
    a = content_fields(
        title_en="T", title_ar="", brand="  ", part_number=None, mfr_part_number=None,
        category=None, specs={}, description="",
    )  # fmt: skip
    b = content_fields(
        title_en="T", title_ar=None, brand=None, part_number=None, mfr_part_number=None,
        category=None, specs="not a table", description=None,
    )  # fmt: skip
    assert a == b


def test_policy_p1_is_the_owners_safest_operating_point():
    assert POLICIES == {"p1": {"kev": 0.80, "pplx": 0.95}}
    assert ACTIVE == "p1" and thresholds() == {"kev": 0.80, "pplx": 0.95}
    assert KEV_REVISION == "6cfce5c2fa4b4bd64026336ab649c5ca78857d52"
    assert MODELS["kev"].model_version.startswith("kev-4b@6cfce5c2fa4b")
    assert MODELS["pplx"].weights_revision.startswith("d06fb3f2d97e")
