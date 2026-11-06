"""/search — parameter validation and the response envelope.

The Meilisearch call itself is faked here: what this file pins down is the
contract between the HTTP layer and `search_products`. How that function turns
its arguments into Meilisearch options is covered in test_search_query.py.
"""

from __future__ import annotations

import pytest


class FakeSearch:
    """Stands in for app.search.search_products, recording how it was called."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.result: dict = {"estimatedTotalHits": 0, "hits": []}

    def __call__(self, query: str, **kwargs) -> dict:
        self.calls.append({"query": query, **kwargs})
        return self.result

    @property
    def call(self) -> dict:
        assert len(self.calls) == 1, f"expected exactly one search, got {len(self.calls)}"
        return self.calls[0]


@pytest.fixture
def backend(monkeypatch):
    fake = FakeSearch()
    monkeypatch.setattr("app.routers.search.search_products", fake)
    return fake


async def test_returns_hits_in_a_paging_envelope(client, backend):
    backend.result = {
        "estimatedTotalHits": 137,
        "hits": [{"id": "1", "title_en": "LM358"}, {"id": "2", "title_en": "LM358N"}],
    }

    body = (await client.get("/search?q=LM358&limit=2&offset=4")).json()

    assert body == {
        "query": "LM358",
        "identifier_query": True,
        "total": 137,
        "limit": 2,
        "offset": 4,
        "hits": [{"id": "1", "title_en": "LM358"}, {"id": "2", "title_en": "LM358N"}],
    }


async def test_a_result_without_the_optional_keys_does_not_break_the_envelope(client, backend):
    """Meilisearch omits estimatedTotalHits when the search is paginated by page;
    the envelope must degrade rather than raise."""
    backend.result = {}

    body = (await client.get("/search?q=LM358")).json()

    assert body["total"] is None
    assert body["hits"] == []


async def test_filters_are_forwarded_verbatim(client, backend):
    await client.get(
        "/search?q=multimeter&category=tools:measurement&domain=tools&in_stock=true"
        "&min_price=50&max_price=500&sort=price:asc&limit=10&offset=20"
    )

    assert backend.call == {
        "query": "multimeter",
        "category": "tools:measurement",
        "domain": "tools",
        "in_stock": True,
        "min_price": 50.0,
        "max_price": 500.0,
        "min_suppliers": None,
        "sort": "price:asc",
        "limit": 10,
        "offset": 20,
        "facets": False,
    }


async def test_defaults_when_nothing_is_supplied(client, backend):
    """An empty query is a legitimate request — it is how browse-by-category works."""
    response = await client.get("/search")

    assert response.status_code == 200
    assert backend.call == {
        "query": "",
        "category": None,
        "domain": None,
        "in_stock": False,
        "min_price": None,
        "max_price": None,
        "min_suppliers": None,
        "sort": None,
        "limit": 24,
        "offset": 0,
        "facets": False,
    }


@pytest.mark.parametrize(
    "sort",
    [
        "price:asc",
        "price:desc",
        "last_verified_at:asc",
        "last_verified_at:desc",
        "supplier_count:asc",
        "supplier_count:desc",
    ],
)
async def test_supported_sorts_are_accepted(client, backend, sort):
    assert (await client.get(f"/search?sort={sort}")).status_code == 200


@pytest.mark.parametrize(
    "sort",
    [
        "price",  # no direction
        "price:sideways",  # not a direction
        "name:asc",  # not a sortable attribute
        "min_price:asc",  # the index's name for it, not the API's
        "price:asc;drop",  # anything appended
        "PRICE:ASC",  # case matters
    ],
)
async def test_unsupported_sorts_are_rejected(client, backend, sort):
    """The pattern is the allow-list: it is what stops an arbitrary string from
    reaching Meilisearch's sort expression."""
    response = await client.get(f"/search?sort={sort}")

    assert response.status_code == 422
    assert backend.calls == []


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=-5",
        "offset=-1",
        "min_price=-1",
        "max_price=-1",
        "limit=abc",
        "min_price=cheap",
        "in_stock=maybe",
    ],
)
async def test_out_of_range_parameters_are_rejected(client, backend, query):
    response = await client.get(f"/search?{query}")

    assert response.status_code == 422
    assert backend.calls == []


async def test_the_boundaries_of_the_allowed_ranges_are_accepted(client, backend):
    response = await client.get("/search?limit=100&offset=0&min_price=0&max_price=0")

    assert response.status_code == 200
    assert backend.call["limit"] == 100
    assert backend.call["min_price"] == 0.0


async def test_search_is_cross_domain_unless_a_domain_is_named(client, backend):
    """Domain is a facet, not a partition: "multimeter" should return electronics
    and tools together. Only browse, which names a vertical, narrows it."""
    await client.get("/search?q=multimeter")

    assert backend.call["domain"] is None


async def test_facets_are_returned_only_when_requested(client, backend):
    """Absent rather than empty, so a caller can tell "not asked for" from
    "nothing matched"."""
    backend.result = {
        "estimatedTotalHits": 2,
        "hits": [],
        "facetDistribution": {"domain": {"electronics": 34, "tools": 2}},
    }

    plain = (await client.get("/search?q=LM358")).json()
    assert "facets" not in plain

    faceted = (await client.get("/search?q=LM358&facets=true")).json()
    assert faceted["facets"] == {"domain": {"electronics": 34, "tools": 2}}


async def test_facets_requested_but_absent_from_the_engine_is_an_empty_map(client, backend):
    backend.result = {"estimatedTotalHits": 0, "hits": []}

    body = (await client.get("/search?facets=true")).json()

    assert body["facets"] == {}


async def test_min_suppliers_is_forwarded(client, backend):
    await client.get("/search?min_suppliers=2&sort=supplier_count:desc")

    assert backend.call["min_suppliers"] == 2
    assert backend.call["sort"] == "supplier_count:desc"


@pytest.mark.parametrize("query", ["min_suppliers=0", "min_suppliers=51", "min_suppliers=many"])
async def test_out_of_range_min_suppliers_is_rejected(client, backend, query):
    assert (await client.get(f"/search?{query}")).status_code == 422
    assert backend.calls == []


@pytest.mark.parametrize(
    ("query", "expected"),
    [("LM358", True), ("ESP32", True), ("digital caliper", False), ("", False)],
)
async def test_the_response_says_whether_the_query_was_identifier_shaped(
    client, backend, query, expected
):
    """The reader narrows which attributes it searches for part-number queries.
    A UI that cannot say so leaves the user guessing why the order changed — and
    re-deriving it in the frontend would be a second, drifting definition."""
    body = (await client.get(f"/search?q={query}")).json()

    assert body["identifier_query"] is expected
