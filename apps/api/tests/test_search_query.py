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

from datetime import UTC, datetime, timedelta

import pytest
from app.search import search_products
from makhzan_schemas.freshness import STALE_AFTER_DAYS, fresh_since
from makhzan_schemas.search import (
    FACET_ATTRIBUTES,
    FILTERABLE_ATTRIBUTES,
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

    assert filters_of(meili) == ['category_refs = "tools:measurement"']


async def test_a_category_ref_matches_the_category_and_everything_beneath_it(meili):
    """Products are filed on leaves. `category_refs` carries a product's leaf and
    every ancestor, so filtering on a group's ref narrows to its children's
    products; filtering `category_ref` (the leaf alone) would match nothing."""
    search_products("", category="electronics:passives")

    assert filters_of(meili) == ['category_refs = "electronics:passives"']
    assert "category_refs" in FILTERABLE_ATTRIBUTES


async def test_a_quote_in_a_category_cannot_break_the_filter(meili):
    """The value comes straight from a URL; it is escaped, not interpolated raw."""
    search_products("", category='tools:a"b')

    assert filters_of(meili) == ['category_refs = "tools:a\\"b"']


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

    assert filters_of(meili) == ['category_refs = "tools:measurement"', 'domain = "tools"']


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
        'category_refs = "electronics:resistors"',
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


async def test_a_shop_filters_on_the_array_of_shops_selling_the_product(meili):
    """Not supplier_name: that is one representative shop, and a product three
    shops sell would vanish from the other two's search."""
    search_products("", shop="shop-a")

    assert filters_of(meili) == ['supplier_slugs = "shop-a"']


async def test_a_shop_combines_with_other_filters_and_facets(meili):
    """The shop page's search keeps its rail: facets count within the shop."""
    search_products("resistor", shop="shop-a", in_stock=True, facets=True)

    assert filters_of(meili) == ["in_stock = true", 'supplier_slugs = "shop-a"']
    assert opts_of(meili)["facets"] == FACET_ATTRIBUTES


async def test_no_shop_filter_by_default(meili):
    search_products("resistor")

    assert "filter" not in opts_of(meili)


async def test_the_shop_attribute_is_filterable_in_the_contract(meili):
    """A filter on an attribute the index does not list as filterable is an error
    at query time; this keeps reader and writer agreeing on the name."""
    from makhzan_schemas.search import FILTERABLE_ATTRIBUTES

    assert "supplier_slugs" in FILTERABLE_ATTRIBUTES


# --------------------------------------------------------------------------- #
# Freshness (rule C2b): stale products are hidden unless asked for


async def test_fresh_filters_on_the_newest_check_of_any_offer(meili, monkeypatch):
    monkeypatch.setattr("app.search.fresh_since", lambda: 1_700_000_000)

    search_products("LM358", fresh=True)

    assert filters_of(meili) == ["last_verified_at > 1700000000"]
    # Without this the filter is a Meilisearch error, i.e. a broken search page.
    assert "last_verified_at" in FILTERABLE_ATTRIBUTES


async def test_no_freshness_filter_unless_asked_for(meili):
    """The API's default is everything, like in_stock: the site sends it."""
    search_products("LM358")

    assert "filter" not in opts_of(meili)


async def test_fresh_combines_with_in_stock_and_facets(meili, monkeypatch):
    """The site counts what each default hides by running the same search with
    one filter dropped, so the two must compose and still bring the stock facet."""
    monkeypatch.setattr("app.search.fresh_since", lambda: 42)

    search_products("", in_stock=True, fresh=True, shop="shop-a", facets=True)

    opts = opts_of(meili)
    assert opts["filter"] == [
        "in_stock = true",
        "last_verified_at > 42",
        'supplier_slugs = "shop-a"',
    ]
    assert "in_stock" in opts["facets"]


def test_stale_means_the_warn_tier_more_than_45_whole_days():
    """The web warns from day 46 (whole days, rounded down); the filter must cut
    at the same instant, or a row could be hidden that reads "45 days"."""
    now = datetime(2026, 11, 9, 12, tzinfo=UTC)
    cutoff = fresh_since(now)

    assert STALE_AFTER_DAYS == 45
    almost = now - timedelta(days=45, hours=23)
    over = now - timedelta(days=46)
    assert int(almost.timestamp()) > cutoff  # "45 days ago": fresh
    assert not int(over.timestamp()) > cutoff  # "46 days ago": stale
