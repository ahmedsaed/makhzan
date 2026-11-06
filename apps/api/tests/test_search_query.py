"""How search_products turns API arguments into a Meilisearch request.

Everything here is silent when wrong: a filter on the wrong attribute, or a sort
key the index does not know, produces a plausible-looking result set rather than
an error. The Meilisearch client is faked so these assert the request we build,
not what a live index happens to return.

Whether a given query *is* identifier-shaped is the search contract's business
and is tested in apps/ingestion/tests/test_search_contract.py; what is asserted
here is that the answer reaches `attributesToSearchOn`.
"""

from __future__ import annotations

import pytest
from app.search import search_products
from makhzan_schemas.search import (
    FACET_ATTRIBUTES,
    INDEX_NAME,
    SEARCHABLE_ATTRIBUTES,
    TEXT_SEARCH_ATTRIBUTES,
)


class FakeIndex:
    def __init__(self) -> None:
        self.searches: list[tuple[str, dict]] = []

    def search(self, query: str, opts: dict) -> dict:
        self.searches.append((query, opts))
        return {"hits": [], "estimatedTotalHits": 0}


class FakeClient:
    def __init__(self) -> None:
        self.index_names: list[str] = []
        self.indexes: dict[str, FakeIndex] = {}

    def index(self, name: str) -> FakeIndex:
        self.index_names.append(name)
        return self.indexes.setdefault(name, FakeIndex())


@pytest.fixture
def meili(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr("app.search.get_client", lambda: fake)
    return fake


def opts_of(meili: FakeClient) -> dict:
    (index,) = meili.indexes.values()
    (_, opts) = index.searches[-1]
    return opts


def filters_of(meili: FakeClient) -> list[str]:
    return opts_of(meili).get("filter", [])


async def test_searches_the_shared_product_index(meili):
    search_products("LM358")

    assert meili.index_names == [INDEX_NAME]
    assert meili.indexes[INDEX_NAME].searches[0][0] == "LM358"


async def test_no_filter_key_when_nothing_is_filtered(meili):
    """An empty filter list is not the same as no filter; send neither."""
    search_products("LM358")

    assert "filter" not in opts_of(meili)


async def test_a_category_ref_filters_on_the_domain_qualified_attribute(meili):
    search_products("", category="tools:measurement")

    assert filters_of(meili) == ['category_ref = "tools:measurement"']


async def test_a_bare_slug_still_works_but_filters_on_the_ambiguous_attribute(meili):
    """Kept for links that predate refs. It matches that slug in *every* domain,
    which is why new links must carry the ref."""
    search_products("", category="measurement")

    assert filters_of(meili) == ['category_slug = "measurement"']


async def test_a_domain_scopes_results_to_one_vertical(meili):
    search_products("multimeter", domain="tools")

    assert filters_of(meili) == ['domain = "tools"']


async def test_no_domain_filter_by_default(meili):
    """Search is cross-domain on purpose — domain is a facet, not a partition."""
    search_products("multimeter")

    assert "filter" not in opts_of(meili)


async def test_a_domain_and_a_category_can_be_combined(meili):
    """Redundant when the ref already implies the domain, but a browse UI that
    holds both in its URL state must not produce a contradictory filter."""
    search_products("", category="tools:measurement", domain="tools")

    assert filters_of(meili) == ['category_ref = "tools:measurement"', 'domain = "tools"']


async def test_in_stock_is_only_filtered_when_asked_for(meili):
    search_products("LM358", in_stock=True)
    assert filters_of(meili) == ["in_stock = true"]

    search_products("LM358", in_stock=False)
    assert "filter" not in opts_of(meili)


async def test_price_bounds_both_act_on_the_cheapest_offer(meili):
    """The document has no scalar price — min_price is the product's cheapest
    offer. A max bound on max_price would return products whose *dearest* offer
    fits the budget, which is not what the filter says."""
    search_products("", min_price=10, max_price=250)

    assert filters_of(meili) == ["min_price >= 10", "min_price <= 250"]


async def test_a_zero_lower_bound_is_a_filter_not_an_absent_one(meili):
    """0 is falsy; the check has to be against None or the bound disappears."""
    search_products("", min_price=0)

    assert filters_of(meili) == ["min_price >= 0"]


async def test_filters_combine(meili):
    search_products("", category="electronics:resistors", in_stock=True, max_price=99)

    assert filters_of(meili) == [
        'category_ref = "electronics:resistors"',
        "in_stock = true",
        "min_price <= 99",
    ]


async def test_the_api_price_sort_is_translated_to_the_indexed_attribute(meili):
    """The API says `price`; the index only has `min_price`. Passing `price:asc`
    straight through would be rejected by Meilisearch as unsortable."""
    search_products("", sort="price:asc")

    assert opts_of(meili)["sort"] == ["min_price:asc"]


@pytest.mark.parametrize(
    "sort", ["last_verified_at:desc", "supplier_count:desc", "supplier_count:asc"]
)
async def test_other_sorts_pass_through_unchanged(meili, sort):
    search_products("", sort=sort)

    assert opts_of(meili)["sort"] == [sort]


async def test_no_sort_key_when_unsorted(meili):
    """Absent means Meilisearch's relevance ranking, which is the default we want."""
    search_products("LM358")

    assert "sort" not in opts_of(meili)


async def test_an_identifier_query_searches_the_part_number_too(meili):
    search_products("LM358")

    assert opts_of(meili)["attributesToSearchOn"] == SEARCHABLE_ATTRIBUTES
    assert "part_number" in opts_of(meili)["attributesToSearchOn"]


async def test_a_word_query_does_not_search_the_part_number(meili):
    """part_number ranks first index-wide, so leaving it in would let a stray
    identifier match outrank real title hits — and a whole vertical (tools)
    carries no part numbers at all."""
    search_products("digital caliper")

    assert opts_of(meili)["attributesToSearchOn"] == TEXT_SEARCH_ATTRIBUTES
    assert "part_number" not in opts_of(meili)["attributesToSearchOn"]


async def test_an_empty_query_is_treated_as_a_word_query(meili):
    """Browse-by-category sends no query; it must not be routed as an identifier."""
    search_products("")

    assert opts_of(meili)["attributesToSearchOn"] == TEXT_SEARCH_ATTRIBUTES


async def test_paging_is_passed_to_the_index(meili):
    search_products("LM358", limit=50, offset=100)

    assert opts_of(meili)["limit"] == 50
    assert opts_of(meili)["offset"] == 100


async def test_min_suppliers_filters_in_the_index(meili):
    """ "Sold by more than one supplier" is the proposition no supplier's own site
    can make. Filtering it in the index rather than over a page keeps paging
    correct."""
    search_products("", min_suppliers=2)

    assert filters_of(meili) == ["supplier_count >= 2"]


async def test_facets_are_only_requested_when_asked_for(meili):
    """They cost Meilisearch real work, and most callers are a detail page."""
    search_products("LM358")
    assert "facets" not in opts_of(meili)

    search_products("LM358", facets=True)
    assert opts_of(meili)["facets"] == FACET_ATTRIBUTES


async def test_price_is_not_a_facet(meili):
    """min_price is a range. Faceting it returns one bucket per distinct price,
    which is a useless rail and a slow query."""
    search_products("", facets=True)

    assert "min_price" not in opts_of(meili)["facets"]
