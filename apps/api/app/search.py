"""Search reader side — queries the Meilisearch product index.

Uses the shared index name/attribute config from makhzan_schemas.search so the
reader and writer stay in agreement.
"""

from __future__ import annotations

import os

import meilisearch
from makhzan_schemas.search import (
    FACET_ATTRIBUTES,
    INDEX_NAME,
    SEARCHABLE_ATTRIBUTES,
    TEXT_SEARCH_ATTRIBUTES,
    looks_like_identifier,
)

_client: meilisearch.Client | None = None


def get_client() -> meilisearch.Client:
    global _client
    if _client is None:
        _client = meilisearch.Client(
            os.getenv("MEILI_URL", "http://localhost:7700"),
            os.getenv("MEILI_MASTER_KEY") or None,
        )
    return _client


def search_products(
    query: str,
    *,
    category: str | None = None,
    domain: str | None = None,
    in_stock: bool = False,
    min_price: float | None = None,
    max_price: float | None = None,
    min_suppliers: int | None = None,
    shop: str | None = None,
    sort: str | None = None,
    limit: int = 24,
    offset: int = 0,
    facets: bool = False,
) -> dict:
    """Search products. Sync (Meilisearch client is sync) — call via run_in_threadpool."""
    filters: list[str] = []
    if category:
        # A ref ("tools:measurement") names one category exactly. A bare slug is
        # accepted for older links, but matches that slug in every domain — which
        # is ambiguous, because slugs are only unique within a domain.
        field = "category_ref" if ":" in category else "category_slug"
        filters.append(f'{field} = "{category}"')
    if domain:
        # Scopes results to one vertical. Deliberately opt-in: search is
        # cross-domain by default, because someone searching "multimeter" should
        # see electronics and tools together and let ranking decide the order.
        # Only browse — which names a vertical explicitly — passes this.
        filters.append(f'domain = "{domain}"')
    if in_stock:
        filters.append("in_stock = true")
    # Price filters/sort act on the product's cheapest offer (min_price).
    if min_price is not None:
        filters.append(f"min_price >= {min_price}")
    if max_price is not None:
        filters.append(f"min_price <= {max_price}")
    if min_suppliers is not None:
        # "Sold by more than one supplier" is makhzan's whole proposition, and a
        # supplier's own site cannot show it. Filtered in the index rather than
        # over a page of results, so paging stays correct.
        filters.append(f"supplier_count >= {min_suppliers}")
    if shop:
        # Search within one shop. supplier_slugs is an array, and `=` on an array
        # matches when any element equals — so a product several shops sell is
        # found from each of their pages, with its cross-shop aggregates intact.
        filters.append(f'supplier_slugs = "{shop}"')

    opts: dict = {"limit": limit, "offset": offset}
    # part_number ranks first index-wide, which is what you want for "LM358" and
    # wrong for "digital caliper" — and now that a whole vertical (tools) carries
    # no part numbers at all, letting it rank first for word queries would be
    # actively unhelpful. Meilisearch cannot reorder attributes per query, so
    # narrow which ones are searched instead.
    opts["attributesToSearchOn"] = (
        list(SEARCHABLE_ATTRIBUTES) if looks_like_identifier(query) else TEXT_SEARCH_ATTRIBUTES
    )
    if filters:
        opts["filter"] = filters
    if facets:
        # Counts for the browse rail. Meilisearch computes these over the whole
        # matching set, not the returned page, which is what makes them useful.
        opts["facets"] = list(FACET_ATTRIBUTES)
    if sort:
        opts["sort"] = [sort.replace("price:", "min_price:")]

    return get_client().index(INDEX_NAME).search(query, opts)
