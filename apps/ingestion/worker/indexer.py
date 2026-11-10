"""Search indexer (writer side).

Pushes Listings into Meilisearch. The index is a rebuildable projection of the
`listings` table — `reindex_all` can recreate it from scratch, and the pipeline
indexes incrementally as it ingests.
"""

from __future__ import annotations

import os
from collections import defaultdict

import meilisearch
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Category, Listing, Product, Supplier
from makhzan_schemas.search import (
    FILTERABLE_ATTRIBUTES,
    INDEX_NAME,
    SEARCHABLE_ATTRIBUTES,
    SORTABLE_ATTRIBUTES,
    build_product_document,
    category_ref,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def get_client() -> meilisearch.Client:
    return meilisearch.Client(
        os.getenv("MEILI_URL", "http://localhost:7700"),
        os.getenv("MEILI_MASTER_KEY") or None,
    )


#: Where a full reindex is built before it is swapped in, so search never
#: serves a half-filled index.
STAGING_INDEX_NAME = f"{INDEX_NAME}_staging"


def ensure_index(client: meilisearch.Client, name: str = INDEX_NAME) -> None:
    """Create the index (if absent) and apply its attribute configuration."""
    try:
        task = client.create_index(name, {"primaryKey": "id"})
        client.wait_for_task(task.task_uid)
    except meilisearch.errors.MeilisearchApiError:
        pass  # already exists
    index = client.index(name)
    task = index.update_settings(
        {
            "searchableAttributes": SEARCHABLE_ATTRIBUTES,
            "filterableAttributes": FILTERABLE_ATTRIBUTES,
            "sortableAttributes": SORTABLE_ATTRIBUTES,
            # Default cap is 1000; raise it so result counts stay accurate at volume.
            "pagination": {"maxTotalHits": 50000},
        }
    )
    client.wait_for_task(task.task_uid)


def index_documents(
    client: meilisearch.Client,
    docs: list[dict],
    *,
    wait: bool = False,
    batch_size: int = 1000,
    index_name: str = INDEX_NAME,
) -> None:
    """Add documents to the index, in batches to keep request payloads sane at volume."""
    if not docs:
        return
    index = client.index(index_name)
    for start in range(0, len(docs), batch_size):
        task = index.add_documents(docs[start : start + batch_size])
        if wait:
            client.wait_for_task(task.task_uid)


def delete_documents(client: meilisearch.Client, ids: list[str], *, wait: bool = False) -> None:
    """Remove documents from the index (e.g. listings archived because a supplier dropped them)."""
    if not ids:
        return
    task = client.index(INDEX_NAME).delete_documents(ids)
    if wait:
        client.wait_for_task(task.task_uid)


def ancestry(category_id, tree: dict) -> list[str]:
    """The refs of a category and every ancestor above it, leaf first.

    `tree` maps a category id to its (ref, parent id). Stops at a cycle rather
    than looping: a corrupt parent pointer must not hang a reindex.
    """
    refs: list[str] = []
    seen: set = set()
    current = category_id
    while current is not None and current in tree and current not in seen:
        seen.add(current)
        ref, current = tree[current]
        if ref:
            refs.append(ref)
    return refs


async def reindex_all(session: AsyncSession, client: meilisearch.Client) -> int:
    """Rebuild the whole product index from Postgres (full replace).

    Built into a staging index, then swapped in atomically: search keeps
    answering from the old index the whole time, and a product that stopped
    being listed doesn't linger. (Emptying the live index and refilling it left
    search blank for the length of a reindex, which with one rebuild per
    source finishing happens several times a day.) Listed products only: a
    merged-away id only redirects, and a withdrawn product keeps its page (ids
    are permanent, docs/decisions/0004-stable-product-ids.md) but nothing to
    buy, so search never shows it.
    """
    ensure_index(client)
    _drop_index(client, STAGING_INDEX_NAME)
    ensure_index(client, STAGING_INDEX_NAME)
    rows = (
        await session.execute(
            select(Product, Category)
            .outerjoin(Category, Category.id == Product.category_id)
            .where(Product.is_listed())
        )
    ).all()
    # The whole tree, so each document can carry its category's ancestors and a
    # group page can filter on the group. A few hundred rows; one query.
    tree = {
        cat.id: (category_ref(cat.domain, cat.slug), cat.parent_id)
        for cat in (await session.execute(select(Category))).scalars()
    }
    # Which shops sell each product. Active listings only, matching how the
    # product's own aggregates are computed: an archived offer must not keep a
    # product in a shop's search after the shop dropped it.
    shops: dict = defaultdict(set)
    for product_id, slug in (
        await session.execute(
            select(Listing.product_id, Supplier.slug)
            .join(Supplier, Supplier.id == Listing.supplier_id)
            .where(Listing.status == ListingStatus.ACTIVE, Listing.product_id.is_not(None))
            .distinct()
        )
    ).all():
        shops[product_id].add(slug)
    # The shop each photo comes from, for the badge on it: the handful of
    # shops, looked up once rather than joined into every product row.
    photo_shops = {
        shop.id: {"slug": shop.slug, "name": shop.name}
        for shop in (await session.execute(select(Supplier))).scalars()
    }
    docs = [
        build_product_document(
            product,
            cat.slug if cat else None,
            cat.name_en if cat else None,
            cat.domain if cat else None,
            list(shops.get(product.id, ())),
            ancestry(cat.id, tree) if cat else [],
            photo_shops.get(product.image_supplier_id),
        )
        for product, cat in rows
    ]
    index_documents(client, docs, wait=True, index_name=STAGING_INDEX_NAME)
    swap = client.swap_indexes([{"indexes": [INDEX_NAME, STAGING_INDEX_NAME]}])
    client.wait_for_task(swap.task_uid)
    # The staging name now holds the previous index.
    _drop_index(client, STAGING_INDEX_NAME)
    return len(docs)


def _drop_index(client: meilisearch.Client, name: str) -> None:
    try:
        task = client.delete_index(name)
        client.wait_for_task(task.task_uid)
    except meilisearch.errors.MeilisearchApiError:
        pass  # not there
