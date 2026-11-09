"""Search endpoint — the primary consumer-facing surface. Returns products."""

from __future__ import annotations

from app.search import search_products
from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from makhzan_schemas.freshness import STALE_AFTER_DAYS
from makhzan_schemas.search import looks_like_identifier

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(
    q: str = Query("", description="Query text — part number, name (EN/AR), brand"),
    category: str | None = Query(
        None, description="Filter by category ref (domain:slug); a bare slug is ambiguous"
    ),
    domain: str | None = Query(
        None, description="Scope to one vertical, e.g. tools. Omit to search across all of them"
    ),
    in_stock: bool = Query(False, description="Only products with an in-stock offer"),
    fresh: bool = Query(
        False,
        description=(
            f"Only products with an offer checked within the last {STALE_AFTER_DAYS} days. "
            "Off by default, like in_stock: the site asks for it explicitly"
        ),
    ),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    min_suppliers: int | None = Query(
        None, ge=1, le=50, description="Only products offered by at least this many suppliers"
    ),
    shop: str | None = Query(
        None,
        # A slug, and nothing else: the value is interpolated into a Meilisearch
        # filter expression, so the pattern is what keeps a quote out of it.
        pattern="^[A-Za-z0-9_-]+$",
        max_length=120,
        description="Only products with an offer from this supplier (slug)",
    ),
    facets: bool = Query(False, description="Include per-domain and per-category counts"),
    sort: str | None = Query(
        None,
        pattern="^(price|last_verified_at|supplier_count):(asc|desc)$",
        description="e.g. price:asc, supplier_count:desc",
    ),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    result = await run_in_threadpool(
        search_products,
        q,
        category=category,
        domain=domain,
        in_stock=in_stock,
        fresh=fresh,
        min_price=min_price,
        max_price=max_price,
        min_suppliers=min_suppliers,
        shop=shop,
        sort=sort,
        limit=limit,
        offset=offset,
        facets=facets,
    )
    body = {
        "query": q,
        # Why the ordering changed. The reader narrows attributesToSearchOn for
        # identifier-shaped queries, and a UI that cannot say so leaves the user
        # guessing. Reported from the shared contract rather than re-derived by
        # the caller — two notions of "looks like a part number" would drift.
        "identifier_query": looks_like_identifier(q),
        "total": result.get("estimatedTotalHits"),
        "limit": limit,
        "offset": offset,
        "hits": result.get("hits", []),
    }
    if facets:
        # Absent rather than empty when not asked for, so a caller can tell
        # "no facets requested" from "nothing matched".
        body["facets"] = result.get("facetDistribution", {})
    return body
