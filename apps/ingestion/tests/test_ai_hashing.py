"""A listing's content hash moves with what a judge could read, and with nothing else (P5)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from makhzan_schemas.ai.hashing import listing_hash
from makhzan_schemas.ai.policy import ACTIVE, KEV_REVISION, MODELS, POLICIES, thresholds
from makhzan_schemas.ai.prompt import listing_row, pplx_payload, record


def _listing(**changes):
    base = dict(
        id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
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


def _shown(listing, category="Relays") -> str:
    """What pplx (the full description) is shown of the listing as LISTING A."""
    rec = record(listing_row(listing, category))
    return pplx_payload({"listing_a": rec, "listing_b": rec})["state"].split("[LISTING B]")[0]


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
    specs = {"Voltage": "5V", "Channels": "1"}
    changed = [
        _listing(title_en="Example Relay Module 12V"),
        _listing(title_ar="وحدة مرحل أخرى"),
        _listing(brand="Otherbrand"),
        _listing(attributes={"specs": specs, "mfr_part_number": "MFR-2"}),
        _listing(
            attributes={"specs": {"Voltage": "12V", "Channels": "1"}, "mfr_part_number": "MFR-1"}
        ),
        _listing(description_en="Another description."),
    ]
    for listing in changed:
        assert listing_hash(listing, "Relays") != before
    assert listing_hash(_listing(), "Modules") != before
    # The rules' identifier reaches the prompt only when the shop states none.
    no_code = {"specs": specs}
    assert listing_hash(_listing(attributes=no_code, part_number="ER-2"), "Relays") != (
        listing_hash(_listing(attributes=no_code), "Relays")
    )


def test_it_moves_exactly_when_what_the_judge_is_shown_moves():
    base = _listing()
    same_text = [
        # Markup and whitespace in the description: the prompt collapses them.
        _listing(description_en="<p>A synthetic</p>\n\n relay   module."),
        # The rules' identifier behind the shop's stated code: never shown.
        _listing(part_number="ER-2"),
    ]
    for listing in same_text:
        assert _shown(listing) == _shown(base)
        assert listing_hash(listing, "Relays") == listing_hash(base, "Relays")
    shown_differently = [
        # The title is shown as written, so is its spacing.
        _listing(title_en="Example  Relay Module 5V"),
        # Specs are shown in the shop's order.
        _listing(
            attributes={"specs": {"Channels": "1", "Voltage": "5V"}, "mfr_part_number": "MFR-1"}
        ),
    ]
    for listing in shown_differently:
        assert _shown(listing) != _shown(base)
        assert listing_hash(listing, "Relays") != listing_hash(base, "Relays")


def test_policy_p1_is_the_owners_safest_operating_point():
    assert POLICIES == {"p1": {"kev": 0.80, "pplx": 0.95}}
    assert ACTIVE == "p1" and thresholds() == {"kev": 0.80, "pplx": 0.95}
    assert KEV_REVISION == "6cfce5c2fa4b4bd64026336ab649c5ca78857d52"
    assert MODELS["kev"].model_version.startswith("kev-4b@6cfce5c2fa4b")
    assert MODELS["pplx"].weights_revision.startswith("d06fb3f2d97e")
