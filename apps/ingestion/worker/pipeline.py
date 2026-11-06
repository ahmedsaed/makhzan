"""Ingestion pipeline: fetch -> normalize -> upsert / review, per source.

Orchestrates one adapter run, recording an IngestionRun audit row. A single bad
item is logged and skipped; it never aborts the whole run.

Work is organised as partitions (independently pageable slices of a catalog) and
progress is durable per page: after every page the pipeline commits and advances
a SourceCursor. A run that dies at page 40 of 43 therefore keeps 39 pages, and
the next run resumes at 40 rather than restarting at 1 — which is what stops a
rate-limited host from making the tail of its catalog permanently unreachable.

Because a sweep can span several runs, archiving is deferred until every
partition has been swept, and keys off the start of the cycle rather than of the
individual run.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import datetime, timezone

from makhzan_schemas.contracts import NormalizedListing
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus, ListingStatus, ReviewReason, SourceType
from makhzan_schemas.models import (
    IngestionRun,
    Listing,
    ReviewQueueItem,
    SourceCursor,
    Supplier,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from worker.categorize import category_slug_for, seed_categories
from worker.normalize import REVIEW_THRESHOLD
from worker.sources.base import SourceAdapter, SupplierInfo


async def _upsert_listing(
    session: AsyncSession,
    adapter: SourceAdapter,
    supplier_id: uuid.UUID,
    norm: NormalizedListing,
) -> tuple[Listing, bool]:
    """Insert or update a listing by (source, external_id). Returns (row, created)."""
    existing = None
    if norm.external_id:
        # Look up by (supplier_id, external_id) — backed by the unique index
        # uq_listing_supplier_external, so this stays O(log N) at volume.
        existing = (
            await session.execute(
                select(Listing).where(
                    Listing.supplier_id == supplier_id,
                    Listing.external_id == norm.external_id,
                )
            )
        ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    fields = dict(
        title_en=norm.title_en,
        title_ar=norm.title_ar,
        description_en=norm.description_en,
        description_ar=norm.description_ar,
        part_number=norm.part_number,
        brand=norm.brand,
        price=norm.price,
        currency=norm.currency,
        unit=norm.unit,
        stock_signal=norm.stock_signal,
        images=norm.images,
        attributes=norm.attributes,
        source_url=norm.source_url,
        confidence=norm.confidence,
        status=ListingStatus.ACTIVE,
        last_verified_at=now,
    )

    if existing:
        for key, value in fields.items():
            setattr(existing, key, value)
        return existing, False

    listing = Listing(
        supplier_id=supplier_id,
        source=norm.source,
        source_type=adapter.source_type,
        external_id=norm.external_id,
        **fields,
    )
    session.add(listing)
    return listing, True


async def _get_or_create_supplier(
    session: AsyncSession, info: SupplierInfo, source_type: SourceType
) -> uuid.UUID:
    """Look up the Supplier for this adapter by slug, creating it if new."""
    supplier = (
        await session.execute(select(Supplier).where(Supplier.slug == info.slug))
    ).scalar_one_or_none()
    if supplier is not None:
        return supplier.id

    supplier = Supplier(
        slug=info.slug,
        name=info.name,
        domain=info.domain,
        name_ar=info.name_ar,
        website_url=info.website_url,
        area=info.area,
        governorate=info.governorate,
        source_type=source_type,
    )
    session.add(supplier)
    await session.flush()
    return supplier.id


async def _get_cursor(session: AsyncSession, source_id: str, partition: str) -> SourceCursor:
    """Load this partition's resume point, creating it on first sight."""
    cursor = (
        await session.execute(
            select(SourceCursor).where(
                SourceCursor.source == source_id,
                SourceCursor.partition_key == partition,
            )
        )
    ).scalar_one_or_none()
    if cursor is None:
        cursor = SourceCursor(source=source_id, partition_key=partition)
        session.add(cursor)
        await session.flush()
    return cursor


async def _ingest_item(
    session: AsyncSession,
    run: IngestionRun,
    adapter: SourceAdapter,
    supplier_id: uuid.UUID,
    cat_index: dict,
    raw,
    observed: Counter | None = None,
) -> None:
    """Normalize and upsert one item, or route it to review. Raises on bad items."""
    default_domain = adapter.supplier.domain

    # Resolve the category first when the source is authoritative: the crosswalk
    # reads the raw item, so the item's domain is known before normalization.
    # That matters because identifier extraction is per-domain — a marketplace
    # spanning verticals would otherwise run an electronics part through its
    # supplier default's profile and silently extract no part number.
    # A mapping is a fact and inference is a guess, so try the crosswalk first
    # whatever kind of source this is. Resolving it before normalization also
    # means identifier extraction runs under the item's own domain.
    if observed is not None:
        observed.update(adapter.source_categories(raw))
    mapped = adapter.category_for(raw)
    domain = mapped[0] if mapped else default_domain
    slug = mapped[1] if mapped else None
    norm = adapter.normalize(raw, domain)

    if norm.confidence < REVIEW_THRESHOLD or norm.review_reasons:
        session.add(
            ReviewQueueItem(
                ingestion_run_id=run.id,
                source=run.source,
                reason=(
                    norm.review_reasons[0] if norm.review_reasons else ReviewReason.LOW_CONFIDENCE
                ),
                confidence=norm.confidence,
                raw_payload=raw.model_dump(mode="json"),
                proposed=norm.model_dump(mode="json"),
            )
        )
        run.items_for_review += 1
        return

    listing, created = await _upsert_listing(session, adapter, supplier_id, norm)

    if slug is None and not adapter.authoritative_categories:
        # Only sources whose categories are a tag cloud get to guess. For a
        # source whose taxonomy covers its catalogue, a miss stays a miss.
        slug = category_slug_for(norm.attributes, norm.title_en or norm.title_ar, domain)

    cat = cat_index.get((domain, slug)) if slug else None
    if cat is not None:
        # The category is authoritative for domain; the supplier default only
        # applies while a listing is uncategorized.
        listing.category_id = cat.id
        listing.domain = cat.domain
    elif adapter.knows_category(raw):
        # This sweep was in a position to know, and there is no category: clear
        # whatever was there, so a supplier dropping a category is visible.
        listing.category_id = None
        listing.domain = default_domain
    # Otherwise this pass carries no category signal — leave the existing one
    # alone rather than erasing what a category partition established.
    if created:
        run.items_created += 1
    else:
        run.items_updated += 1


async def _sweep_partition(
    session: AsyncSession,
    run: IngestionRun,
    adapter: SourceAdapter,
    supplier_id: uuid.UUID,
    cat_index: dict,
    partition: str,
    *,
    limit: int | None,
    errors: list[str],
    observed: Counter | None = None,
    resumed: list[bool] | None = None,
) -> bool:
    """Sweep one partition from its cursor, committing after every page.

    Returns True if the fetch failed. The cursor is left pointing at the page
    that failed, so the next run retries exactly there instead of restarting at
    page 1 — without that, a host that rate-limits mid-catalog would make the
    tail permanently unreachable.
    """
    ephemeral = limit is not None  # dev/testing runs leave cursors untouched
    cursor = None
    page = 1
    if not ephemeral:
        cursor = await _get_cursor(session, adapter.source_id, partition)
        if cursor.cycle_started_at is None:
            cursor.cycle_started_at = datetime.now(timezone.utc)
        page = cursor.next_page
        if page > 1 and resumed is not None:
            # Picking up mid-partition means this run did not see the pages
            # before it, so its observed-category set is incomplete.
            resumed.append(True)

    pages_this_run = 0
    while True:
        if limit is not None and run.items_seen >= limit:
            return False
        if adapter.max_pages_per_run and pages_this_run >= adapter.max_pages_per_run:
            return False  # budget spent; the cursor resumes here next run

        try:
            result = await adapter.fetch_page(partition, page)
        except Exception as exc:  # noqa: BLE001 — a dead host must not discard the run
            errors.append(f"{partition or 'default'} p{page}: {exc}")
            return True
        pages_this_run += 1

        for raw in result.items:
            if limit is not None and run.items_seen >= limit:
                break
            run.items_seen += 1
            try:
                await _ingest_item(session, run, adapter, supplier_id, cat_index, raw, observed)
            except Exception as exc:  # noqa: BLE001 — one bad item must not kill the run
                run.items_failed += 1
                errors.append(str(exc))

        if not ephemeral:
            # Checkpoint: everything up to and including this page is durable.
            cursor.next_page = page + 1
            if not result.has_more:
                cursor.exhausted = True
                cursor.next_page = 1
            await session.commit()

        if not result.has_more:
            return False
        page += 1
        await asyncio.sleep(await _pace(adapter))


async def _pace(adapter: SourceAdapter) -> float:
    """Seconds to wait before the next page of this source.

    `Crawl-Delay` is a floor, never a ceiling: a host asking for 20 seconds gets
    20 even though the default is 15, and a host asking for 1 still gets the full
    polite delay. One supplier does ask for 20, so this was a real if small
    breach — the crawler was reading them faster than they had asked in writing.
    """
    if not adapter.base_url:
        return adapter.polite_delay
    from worker.robots import ROBOTS
    from worker.http import BROWSER_HEADERS

    requested = await ROBOTS.crawl_delay(adapter.base_url, BROWSER_HEADERS["User-Agent"])
    return max(adapter.polite_delay, requested or 0.0)


async def _finish_cycle_if_swept(
    session: AsyncSession, adapter: SourceAdapter, supplier_id: uuid.UUID
) -> tuple[int, dict]:
    """Archive vanished listings, but only once every partition has been swept.

    Archiving keys off the start of the whole *cycle*, not of this run: a sweep
    may span several runs, and retiring everything a single partial run failed
    to reach would delete most of the catalog.
    """
    cursors = (
        (
            await session.execute(
                select(SourceCursor).where(SourceCursor.source == adapter.source_id)
            )
        )
        .scalars()
        .all()
    )
    expected = set(adapter.partitions())
    swept = {c.partition_key for c in cursors if c.exhausted}
    if not expected <= swept:
        return 0, {}

    starts = [c.cycle_started_at for c in cursors if c.cycle_started_at is not None]
    cycle_started = min(starts) if starts else datetime.now(timezone.utc)

    result = await session.execute(
        update(Listing)
        .where(
            Listing.supplier_id == supplier_id,
            Listing.status == ListingStatus.ACTIVE,
            Listing.last_verified_at < cycle_started,
        )
        .values(status=ListingStatus.ARCHIVED)
    )
    for cursor in cursors:
        cursor.exhausted = False
        cursor.next_page = 1
        cursor.cycle_started_at = None

    # Completing a cycle resets the cursors, which erases the only evidence it
    # happened. Stamp the run so cycle health stays inspectable afterwards —
    # otherwise you can only ever see the cycle in flight and never judge whether
    # it is behaving normally.
    finished = datetime.now(timezone.utc)
    cycle = {
        "cycle_started_at": cycle_started.isoformat(),
        "cycle_completed_at": finished.isoformat(),
        "cycle_seconds": round((finished - cycle_started).total_seconds()),
        "cycle_partitions": len(expected),
    }
    return result.rowcount or 0, cycle


def _crosswalk_drift(adapter: SourceAdapter, observed: Counter, *, complete: bool) -> dict | None:
    """Compare the categories a sweep actually saw against the crosswalk.

    A crosswalk is a snapshot of a supplier's taxonomy. When they rename, add or
    retire a category the mapping silently stops matching and listings quietly
    lose their category — indistinguishable from the supplier discontinuing
    stock. This records both sides of the difference so the change is visible.

    `unused` is only meaningful when this run swept the whole catalogue from the
    start. A run that *resumed* mid-partition finishes the cycle without having
    seen the earlier pages, so a category missing from its observations proves
    nothing — reporting it would cry wolf on every recovery from a failure. The
    same is true of a paced source, where the run that closes the cycle has only
    visited its own slice of the partitions; see the caller.
    """
    if not adapter.categories or not observed:
        return None

    unmapped = {name: n for name, n in observed.items() if name not in adapter.categories}
    drift: dict = {"observed": len(observed)}
    if unmapped:
        # Biggest first — a rename of a busy category matters more than a new
        # one-product corner.
        drift["unmapped"] = dict(Counter(unmapped).most_common(15))
        drift["unmapped_listings"] = sum(unmapped.values())
    if complete:
        unused = sorted(set(adapter.categories) - set(observed))
        if unused:
            drift["unused"] = unused[:25]
            drift["unused_count"] = len(unused)
    return drift if len(drift) > 1 else None


async def _partitions_for_this_run(
    session: AsyncSession, adapter: SourceAdapter, partitions: list[str]
) -> list[str]:
    """Take this run's slice of the work, skipping what the cycle already covered.

    A source can be swept over several days rather than in one sitting: each run
    takes `max_partitions_per_run` of the partitions still outstanding, and the
    cycle closes when the last of them is done. That spreads a large catalogue
    into a steady trickle instead of a daily spike, without touching freshness —
    the cycle length is what sets how often a product is re-checked.
    """
    budget = adapter.max_partitions_per_run
    if not budget:
        return partitions
    rows = (
        (
            await session.execute(
                select(SourceCursor).where(SourceCursor.source == adapter.source_id)
            )
        )
        .scalars()
        .all()
    )
    done = {c.partition_key for c in rows if c.exhausted}
    outstanding = [p for p in partitions if p not in done]
    return outstanding[:budget]


async def _run(
    source_id: str,
    adapter: SourceAdapter,
    partitions: list[str],
    *,
    limit: int | None,
) -> IngestionRun:
    """Shared body for whole-source and single-partition runs."""
    errors: list[str] = []

    async with SessionLocal() as session:
        run = IngestionRun(source=source_id, source_type=adapter.source_type)
        session.add(run)
        supplier_id = await _get_or_create_supplier(session, adapter.supplier, adapter.source_type)
        cat_index = await seed_categories(session)  # idempotent
        await session.flush()

        if limit is None:
            # Bounded dev runs always sweep what they were asked for.
            partitions = await _partitions_for_this_run(session, adapter, partitions)

        fetch_failed = False
        observed: Counter = Counter()
        resumed: list[bool] = []
        for partition in partitions:
            failed = await _sweep_partition(
                session,
                run,
                adapter,
                supplier_id,
                cat_index,
                partition,
                limit=limit,
                errors=errors,
                observed=observed,
                resumed=resumed,
            )
            fetch_failed = fetch_failed or failed

        archived, cycle = 0, {}
        if limit is None:
            archived, cycle = await _finish_cycle_if_swept(session, adapter, supplier_id)

        stats: dict = {}
        if errors:
            stats["errors"] = errors
        if archived:
            stats["archived"] = archived
        if cycle:
            stats["cycle"] = cycle
        # "Never matched" only means "retired" when this run swept the whole
        # catalogue itself. Two ways it might not have: it resumed mid-partition
        # (so it never saw the earlier pages), or — for a paced source — it only
        # took its slice of the partitions. The run that happens to close a cycle
        # of 171 partitions may have visited 25 of them, and the other 146 are
        # not retired, merely swept days ago.
        swept_every_partition = len(partitions) == len(adapter.partitions())
        drift = _crosswalk_drift(
            adapter,
            observed,
            complete=bool(cycle) and not resumed and swept_every_partition,
        )
        if drift:
            stats["crosswalk"] = drift
        run.stats = stats

        run.status = (
            IngestionStatus.PARTIAL
            if (fetch_failed or run.items_failed)
            else IngestionStatus.SUCCESS
        )
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        return run


async def run_source(
    source_id: str, adapter: SourceAdapter, *, limit: int | None = None
) -> IngestionRun:
    """Run every partition of one adapter. `limit` caps items (dev/testing).

    Writes listings only; the product search index is rebuilt separately via
    grouping.rebuild_products + indexer.reindex_all (backfill / cron).
    """
    return await _run(source_id, adapter, adapter.partitions(), limit=limit)


async def run_partition(
    source_id: str, adapter: SourceAdapter, partition: str, *, limit: int | None = None
) -> IngestionRun:
    """Run a single partition — the unit of work for distributing a source."""
    return await _run(source_id, adapter, [partition], limit=limit)
