"""Search ranking contract.

Meilisearch ranks by the index-wide order of `searchableAttributes`, so
part_number cannot be promoted per query. The reader instead narrows which
attributes are searched: identifier-shaped queries search everything and inherit
part_number's ranking, word queries skip it.

This matters more since the tools vertical landed — those listings carry no part
number at all, so letting an identifier match outrank title matches on a query
like "digital caliper" would bury the right results.
"""

from __future__ import annotations

import pytest
from makhzan_schemas.search import (
    SEARCHABLE_ATTRIBUTES,
    TEXT_SEARCH_ATTRIBUTES,
    looks_like_identifier,
)


def test_part_number_is_excluded_from_text_search():
    assert "part_number" in SEARCHABLE_ATTRIBUTES
    assert "part_number" not in TEXT_SEARCH_ATTRIBUTES
    assert TEXT_SEARCH_ATTRIBUTES == ["title_en", "title_ar", "brand"]


@pytest.mark.parametrize(
    "query", ["LM358", "NE555", "ESP32", "esp32", "7805", "ATMEGA328P", "IRFZ44N", "ESP32 CAM"]
)
def test_identifier_queries_are_detected(query):
    assert looks_like_identifier(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "digital caliper",
        "tape measure",
        "spirit level 60cm",
        "bosch drill",
        "resistor",
        "arduino board",
        "",
        "   ",
    ],
)
def test_word_queries_are_not_treated_as_identifiers(query):
    assert looks_like_identifier(query) is False


@pytest.mark.parametrize("query", ["DT-830", "dt830b", "ASR-6014", "TU-501", "608ZZ bearing"])
def test_every_departments_codes_are_identifier_queries(query):
    """Hyphenated hobby codes (electronics) and catalogue codes (tools) are read
    by their departments' rules, so they search the identifier first too."""
    assert looks_like_identifier(query) is True


@pytest.mark.parametrize("query", ["awg-16 wire", "nema-17 motor", 'pipe wrench12"', "m8 bolt"])
def test_measurements_are_not_identifier_queries(query):
    assert looks_like_identifier(query) is False


def test_long_phrases_are_never_identifiers():
    """A descriptive phrase can contain something identifier-shaped; it is still a phrase."""
    assert looks_like_identifier("cheap ESP32 development board kit") is False


def test_category_ref_is_domain_qualified():
    """Slugs repeat across domains, so a bare slug cannot identify a category."""
    from makhzan_schemas.search import category_ref

    assert category_ref("tools", "measurement") == "tools:measurement"
    assert category_ref("electronics", "measurement") == "electronics:measurement"
    assert category_ref("tools", "measurement") != category_ref("electronics", "measurement")


def test_category_ref_defaults_domain_and_handles_missing_slug():
    from makhzan_schemas.search import DEFAULT_DOMAIN, category_ref

    assert category_ref(None, "resistors") == f"{DEFAULT_DOMAIN}:resistors"
    assert category_ref("tools", None) is None
