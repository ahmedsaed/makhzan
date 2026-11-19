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
from makhzan_schemas.domains import DEFAULT_DOMAIN, get_profile
from makhzan_schemas.models import Product
from makhzan_schemas.search import (
    DISPLAYED_ATTRIBUTES,
    IDENTIFIER_ATTRIBUTES,
    MEMBER_ATTRIBUTES,
    SEARCHABLE_ATTRIBUTES,
    TEXT_SEARCH_ATTRIBUTES,
    MemberText,
    build_product_document,
    looks_like_identifier,
    member_fields,
)


def test_part_numbers_are_excluded_from_text_search():
    """The members' codes follow the product's: searched only for identifiers."""
    assert IDENTIFIER_ATTRIBUTES == ["part_number", "member_part_numbers"]
    for attr in IDENTIFIER_ATTRIBUTES:
        assert attr in SEARCHABLE_ATTRIBUTES
        assert attr not in TEXT_SEARCH_ATTRIBUTES
    assert TEXT_SEARCH_ATTRIBUTES == [
        "title_en",
        "title_ar",
        "member_titles_en",
        "member_titles_ar",
        "brand",
        "member_brands",
    ]


def test_searchable_attribute_order():
    """The product's own title ranks first, then the members' titles, then the
    brands; the members' codes last. Earlier ranks higher, index-wide."""
    assert SEARCHABLE_ATTRIBUTES == [
        "part_number",
        "title_en",
        "title_ar",
        "member_titles_en",
        "member_titles_ar",
        "brand",
        "member_brands",
        "member_part_numbers",
    ]
    # The product's own attributes keep the default profile's order.
    own = [a for a in SEARCHABLE_ATTRIBUTES if a not in MEMBER_ATTRIBUTES]
    assert own == list(get_profile(DEFAULT_DOMAIN).search_attributes)


def test_hits_retrieve_every_document_field_but_the_member_arrays():
    """`attributesToRetrieve` names what to keep, so a field added to the
    document and not here would vanish from every search result."""
    doc = build_product_document(Product(title_en="x"), None, None)
    assert set(DISPLAYED_ATTRIBUTES) == set(doc) - set(MEMBER_ATTRIBUTES)
    assert set(MEMBER_ATTRIBUTES) <= set(doc)


def test_member_fields_are_distinct_and_sorted():
    """One per spelling, whatever order the listings come in, so a rebuild of an
    unchanged product writes an identical document."""
    members = [
        MemberText("Relay  Module 5V", None, "Songle", ("SRD-05VDC", None, "srd-05vdc")),
        MemberText("relay module 5v", "ريلاي", None, (None, "SRD05")),
        MemberText("", "  ", "", ()),
    ]
    fields = member_fields(members)
    assert fields == member_fields(reversed(members))
    assert fields == {
        "member_titles_en": ["Relay Module 5V"],
        "member_titles_ar": ["ريلاي"],
        "member_brands": ["Songle"],
        "member_part_numbers": ["SRD-05VDC", "SRD05"],
    }
    assert member_fields([]) == {attr: [] for attr in MEMBER_ATTRIBUTES}


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
