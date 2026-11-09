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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from makhzan_schemas.contracts import NormalizedListing
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import (
    IngestionStatus,
    ListingStatus,
    ReviewReason,
    SourceType,
    StockSignal,
)
from makhzan_schemas.models import (
    IngestionRun,
    Listing,
    PriceObservation,
    ReviewQueueItem,
    Source,
    SourceCursor,
    Supplier,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from worker.categorize import category_slug_for, seed_categories
from worker.details import apply_details, carry_details, run_details
from worker.http import CycleFetcher, RequestLog, logging_requests, set_host_pace
from worker.normalize import REVIEW_THRESHOLD, not_a_product
from worker.sources.base import CONTACT_PART, SourceAdapter, SupplierInfo


async def _upsert_listing(
    session: AsyncSession,
    adapter: SourceAdapter,
    supplier_id: uuid.UUID,
    norm: NormalizedListing,
    *,
    record_history: bool = True,
) -> tuple[Listing, bool]:
    """Insert or update a listing by (source, external_id). Returns (row, created).

    Records a price observation when the listing is new or its price or stock
    moved (`_record_changes`), unless `record_history` is off, as in a `limit=` run.
    """
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
    attributes = norm.attributes
    if norm.stock_signal == StockSignal.OUT_OF_STOCK:
        attributes = _without_stock_counts(attributes)
    if existing is not None:
        # The card has none of what a product page gave (one request each, read
        # rarely), so it is carried over from the stored row and laid back on
        # top — or this sweep would wipe it. See worker/details.py.
        attributes = carry_details(existing.attributes, attributes)
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
        attributes=attributes,
        source_url=norm.source_url,
        confidence=norm.confidence,
        status=ListingStatus.ACTIVE,
        last_verified_at=now,
        last_seen_at=now,
    )
    fields = apply_details(fields)

    if existing:
        for key, value in fields.items():
            setattr(existing, key, value)
        if record_history:
            await _record_changes(session, [existing], now)
        return existing, False

    listing = Listing(
        supplier_id=supplier_id,
        source=norm.source,
        source_type=adapter.source_type,
        external_id=norm.external_id,
        **fields,
    )
    session.add(listing)
    if record_history:
        await _record_changes(session, [listing], now, new=True)
    return listing, True


def _cents(price) -> Decimal | None:
    """A price as `price_observations` stores it (Numeric(12, 2)), for comparing."""
    return None if price is None else Decimal(str(price)).quantize(Decimal("0.01"))


async def _record_changes(
    session: AsyncSession, listings: list[Listing], now: datetime, *, new: bool = False
) -> int:
    """Add a `PriceObservation` for each listing whose price or stock changed.

    Compared against the listing's latest observation, not the values the update
    just overwrote: a `limit=` run updates listings without recording, and its
    change must still be recorded by the next real run rather than lost. A listing
    with no observation yet (new, or archived before history began) gets its
    first. A recheck that changes nothing writes nothing. Returns rows added.
    """
    latest: dict = {}
    if not new:
        ids = [listing.id for listing in listings]
        rows = await session.execute(
            select(
                PriceObservation.listing_id,
                PriceObservation.price,
                PriceObservation.currency,
                PriceObservation.stock_signal,
            )
            .where(PriceObservation.listing_id.in_(ids))
            .order_by(PriceObservation.listing_id, PriceObservation.observed_at.desc())
            .distinct(PriceObservation.listing_id)
        )
        latest = {row[0]: tuple(row[1:]) for row in rows}
    added = 0
    for listing in listings:
        current = (_cents(listing.price), listing.currency, listing.stock_signal)
        if latest.get(listing.id) == current:
            continue
        session.add(
            PriceObservation(
                listing=listing,
                observed_at=now,
                price=current[0],
                currency=listing.currency,
                stock_signal=listing.stock_signal,
                in_stock=listing.stock_signal == StockSignal.IN_STOCK,
            )
        )
        added += 1
    return added


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
    *,
    record_history: bool = True,
) -> str | None:
    """Normalize and upsert one item, or route it to review. Raises on bad items.

    Returns why the item was skipped as not a product, if it was. A skipped
    entry is never upserted, so one already stored stops being verified and is
    archived when the cycle completes — the same path as stock the shop dropped.
    """
    default_domain = adapter.supplier.domain

    # Resolve the category first when the source is authoritative: the crosswalk
    # reads the raw item, so the item's domain is known before normalization.
    # That matters because identifier extraction is per-domain — a marketplace
    # spanning verticals would otherwise run an electronics part through its
    # supplier default's profile and silently extract no part number.
    # A mapping is a fact and inference is a guess, so try the crosswalk first
    # whatever kind of source this is. Resolving it before normalization also
    # means identifier extraction runs under the item's own domain.
    source_categories = adapter.source_categories(raw)
    if observed is not None:
        observed.update(source_categories)
    skip = not_a_product(raw.title, source_categories)
    if skip:
        return skip
    mapped = adapter.category_for(raw)
    domain = mapped[0] if mapped else default_domain
    slug = mapped[1] if mapped else None
    norm = adapter.normalize(raw, domain)
    if token := adapter.change_token(raw):
        # Free: read off the list page. The details stage compares it with the
        # one stored when the product page was last read.
        norm.attributes = {**(norm.attributes or {}), "change_token": token}

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
        return None

    listing, created = await _upsert_listing(
        session, adapter, supplier_id, norm, record_history=record_history
    )

    knows = adapter.knows_category(raw)
    if (
        slug is None
        and not adapter.authoritative_categories
        and (knows or listing.category_id is None)
    ):
        # Only sources whose categories are a tag cloud get to guess. For a
        # source whose taxonomy covers its catalogue, a miss stays a miss. And
        # a pass that carries no category signal guesses only for a listing
        # that has no category yet: replacing one with a guess erases it as
        # surely as clearing it would ("Raspberry Red PLA+" infers as a dev
        # board, and its Wix type gallery has already said it is filament).
        slug = category_slug_for(norm.attributes, norm.title_en or norm.title_ar, domain)

    cat = cat_index.get((domain, slug)) if slug else None
    if cat is not None:
        # The category is authoritative for domain; the supplier default only
        # applies while a listing is uncategorized.
        listing.category_id = cat.id
        listing.domain = cat.domain
    elif knows:
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
    return None


def _without_stock_counts(attributes: dict) -> dict:
    """A listing's attributes once it is out of stock: no count says otherwise.

    A stored "68 in stock", or a variant still marked in stock with its own
    count, would contradict the badge; neither is true of a product the shop
    says it has none of.
    """
    if not isinstance(attributes, dict):
        return attributes
    out = {k: v for k, v in attributes.items() if k != "stock_quantity"}
    variants = out.get("variants")
    if isinstance(variants, list):
        out["variants"] = [
            {**{k: x for k, x in v.items() if k != "stock_quantity"}, "in_stock": False}
            if isinstance(v, dict)
            else v
            for v in variants
        ]
    return out


async def _mark_out_of_stock(
    session: AsyncSession,
    supplier_id: uuid.UUID,
    external_ids: list[str],
    *,
    record_history: bool = True,
) -> int:
    """Keep listings the source says it still sells but has out of stock.

    For a shop whose catalogue feed leaves out-of-stock products out, a second
    route still lists them by id. Without this they would go unseen for the
    cycle and be archived as if discontinued. That route carries no price or
    details, so what was stored stays as last read, and so does
    `last_verified_at`: the site shows it as when the price was checked, and it
    was not. Only `last_seen_at` moves, which is what archiving reads. Any stock
    count is dropped, since the shop has just said there is none. One the cycle
    had archived is restored, since the shop has just said it exists; one hidden
    or awaiting review is left alone. Returns how many listings were kept.

    The flip to out of stock is a stock change, so it is recorded as one (at the
    stored price, which is the last one read), unless `record_history` is off.
    """
    listings = (
        (
            await session.execute(
                select(Listing).where(
                    Listing.supplier_id == supplier_id,
                    Listing.external_id.in_(set(external_ids)),
                    Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.ARCHIVED]),
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    for listing in listings:
        listing.stock_signal = StockSignal.OUT_OF_STOCK
        listing.status = ListingStatus.ACTIVE
        listing.last_seen_at = now
        listing.attributes = _without_stock_counts(listing.attributes)
    if record_history and listings:
        await _record_changes(session, list(listings), now)
    return len(listings)


#: Refetch a source's reference data at least this often, even mid-cycle: a cycle
#: that never completes (a source failing every day) must not pin it forever.
#: Above the longest real cycle (about four weeks for the slowest shop), so in a
#: healthy sweep the data is refreshed once a cycle, when the next one starts.
CYCLE_DATA_MAX_AGE = timedelta(days=45)


def _when(entry: dict, key: str) -> datetime | None:
    try:
        return datetime.fromisoformat(entry[key])
    except (KeyError, TypeError, ValueError):
        return None


async def _load_cycle_data(
    session: AsyncSession,
    adapter: SourceAdapter,
    supplier_id: uuid.UUID,
    *,
    ephemeral: bool,
    errors: list[str],
) -> Counter:
    """Hand the adapter its per-cycle reference data, fetching what is due.

    A part is due when it has never been tried, when a new cycle is starting —
    no partition of this source has a cycle in flight — or when its last try is
    older than `CYCLE_DATA_MAX_AGE`. So a cycle spread over weeks of daily runs
    pays for it once, at its first run, and every later run reads the copy on
    the source's row.

    A part that fails is reported and marked tried (`attempted_at`), keeping its
    previous copy: the sweep goes on without the new one, and the next try is at
    the next cycle. Retrying every run would re-fetch a many-page part from its
    first page every day, failing in the same place; and a part that stopped
    partway is never stored, since a partial variations list would hide variants.

    An ephemeral (`limit=`) run fetches nothing and stores nothing: like its
    cursors, the source's state is not its to change, and a quick test run must
    not cost a shop a cycle's worth of extra requests. It reads what is stored.
    Returns the requests made, by part.
    """
    parts = adapter.cycle_data_parts()
    if not parts:
        return Counter()
    source = (
        await session.execute(select(Source).where(Source.source_id == adapter.source_id))
    ).scalar_one_or_none()
    stored: dict = dict((source.cycle_data if source else None) or {})

    now = datetime.now(timezone.utc)
    in_flight = (
        await session.execute(
            select(func.count())
            .select_from(SourceCursor)
            .where(
                SourceCursor.source == adapter.source_id,
                SourceCursor.cycle_started_at.is_not(None),
            )
        )
    ).scalar_one()

    def due(part: str) -> bool:
        if ephemeral:
            return False
        entry = stored.get(part)
        if not isinstance(entry, dict):
            return True
        tries = [t for t in (_when(entry, "fetched_at"), _when(entry, "attempted_at")) if t]
        if not tries:
            return True
        return not in_flight or now - max(tries) > CYCLE_DATA_MAX_AGE

    fetcher = CycleFetcher(lambda: _pace(adapter))
    changed = False
    for part in [p for p in parts if due(p)]:
        changed = True
        try:
            data = await adapter.fetch_cycle_part(fetcher, part)
        except Exception as exc:  # noqa: BLE001 — reference data must not stop the sweep
            errors.append(f"cycle data {part}: {type(exc).__name__}: {exc}")
            previous = stored.get(part) if isinstance(stored.get(part), dict) else {}
            stored[part] = {**previous, "attempted_at": datetime.now(timezone.utc).isoformat()}
            continue
        stored[part] = {"fetched_at": datetime.now(timezone.utc).isoformat(), "data": data}
        if part == CONTACT_PART and data:
            supplier = await session.get(Supplier, supplier_id)
            if supplier is not None:
                supplier.contact = data

    adapter.use_cycle_data(
        {part: entry.get("data") for part, entry in stored.items() if isinstance(entry, dict)},
        fetched_at={
            part: entry["fetched_at"]
            for part, entry in stored.items()
            if isinstance(entry, dict) and entry.get("fetched_at")
        },
    )
    if changed and source is not None:
        source.cycle_data = stored
    if fetcher.requests:
        # The next request to this host is a product page: it waits its turn too.
        await asyncio.sleep(await _pace(adapter))
    return fetcher.requests


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
    not_products: Counter | None = None,
    tally: Counter | None = None,
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

        if tally is not None:
            tally["pages"] += 1
        try:
            result = await adapter.fetch_page(partition, page)
        except Exception as exc:  # noqa: BLE001 — a dead host must not discard the run
            errors.append(f"{partition or 'default'} p{page}: {exc}")
            return True
        pages_this_run += 1

        if result.out_of_stock_ids:
            marked = await _mark_out_of_stock(
                session, supplier_id, result.out_of_stock_ids, record_history=not ephemeral
            )
            if tally is not None:
                tally["out_of_stock_kept"] += marked
                tally["out_of_stock_unknown"] += len(set(result.out_of_stock_ids)) - marked

        for raw in result.items:
            if limit is not None and run.items_seen >= limit:
                break
            run.items_seen += 1
            try:
                skipped = await _ingest_item(
                    session,
                    run,
                    adapter,
                    supplier_id,
                    cat_index,
                    raw,
                    observed,
                    record_history=not ephemeral,  # a `limit=` run leaves no history
                )
                if skipped and not_products is not None:
                    not_products[f"{raw.title} ({skipped})"] += 1
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
    """Seconds to wait before this source's next request (see `robots.polite_pause`)."""
    from worker.robots import polite_pause

    return await polite_pause(adapter.base_url, adapter.polite_delay)


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
            # Seen, not verified: a listing kept alive by id alone was not
            # re-priced, but the shop still says it sells it.
            Listing.last_seen_at < cycle_started,
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
    """Shared body for whole-source and single-partition runs.

    Every request the run sends — cycle data, every partition's pages, whatever
    the adapter fetches to build a page — is logged with when it went out, so
    the run's `stats.pacing` is the pace the shop actually saw.
    """
    with logging_requests() as log:
        return await _logged_run(source_id, adapter, partitions, limit=limit, log=log)


async def _logged_run(
    source_id: str,
    adapter: SourceAdapter,
    partitions: list[str],
    *,
    limit: int | None,
    log: RequestLog,
) -> IngestionRun:
    errors: list[str] = []
    # The least gap between any two requests to this host, retries and
    # robots.txt included (worker.http.take_turn); Crawl-Delay is a floor on it.
    set_host_pace(adapter.base_url, adapter.polite_delay)

    async with SessionLocal() as session:
        run = IngestionRun(source=source_id, source_type=adapter.source_type)
        session.add(run)
        supplier_id = await _get_or_create_supplier(session, adapter.supplier, adapter.source_type)
        cat_index = await seed_categories(session)  # idempotent
        await session.flush()

        if limit is None:
            # Bounded dev runs always sweep what they were asked for.
            partitions = await _partitions_for_this_run(session, adapter, partitions)

        # Before any page: the adapter reads it while turning pages into listings.
        cycle_requests = await _load_cycle_data(
            session, adapter, supplier_id, ephemeral=limit is not None, errors=errors
        )
        # Durable before the sweep: a run that dies on page 1 still keeps it, and
        # a part that failed stays marked as tried.
        await session.commit()

        fetch_failed = False
        observed: Counter = Counter()
        resumed: list[bool] = []
        not_products: Counter = Counter()
        tally: Counter = Counter()
        for i, partition in enumerate(partitions):
            if limit is not None and run.items_seen >= limit:
                break
            if i:
                # Partitions share one host. The pause between pages ends at a
                # partition's last page, so without this the next partition's
                # first request went out at once: for a source of many two-page
                # categories, half of its requests were unpaced.
                await asyncio.sleep(await _pace(adapter))
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
                not_products=not_products,
                tally=tally,
            )
            fetch_failed = fetch_failed or failed

        archived, cycle = 0, {}
        if limit is None:
            archived, cycle = await _finish_cycle_if_swept(session, adapter, supplier_id)

        details_requests: Counter = Counter()
        details: dict = {}
        if limit is None:
            # After the sweep and its archiving, so only listings the shop still
            # sells are read. A `limit=` run is a quick test: it never costs a
            # shop product-page requests.
            await session.commit()
            details_requests, details = await run_details(
                session,
                adapter,
                errors=errors,
                pace=lambda: _pace(adapter),
                already_sent=bool(tally["pages"] or cycle_requests),
            )

        stats: dict = {}
        if errors:
            stats["errors"] = errors
        if archived:
            stats["archived"] = archived
        if cycle:
            stats["cycle"] = cycle
        if not_products:
            # Named, so a wrongly skipped real product is visible in the run.
            stats["not_products"] = dict(not_products.most_common(25))
        # Every request this run made to the source's host: its pages, and the
        # reference data fetched once a cycle, by part, and whatever else the
        # adapter asked for while building its pages.
        requests: Counter = Counter({"pages": tally["pages"]})
        requests.update(cycle_requests)
        requests.update(adapter.extra_requests())
        requests.update(details_requests)
        if details:
            stats["details"] = details
        requests.update({"robots": sum(log.robots.values())})
        if any(requests.values()):
            stats["requests"] = {k: v for k, v in requests.items() if v}
        # What the shop's server saw: requests sent (a retry is one more) and the
        # gaps between them, which is what /how-we-crawl publishes. `requests`
        # above counts by purpose, and a page refused before sending (robots.txt,
        # a host still backing off) is in it but not here.
        stats["pacing"] = log.pacing()
        if report := adapter.run_report():
            stats["source_report"] = report
        if tally["out_of_stock_kept"] or tally["out_of_stock_unknown"]:
            # Kept as out of stock rather than archived; "unknown" ones were
            # never stored, and a route with no price or photo creates nothing.
            stats["out_of_stock_unlisted"] = {
                "kept": tally["out_of_stock_kept"],
                "unknown": tally["out_of_stock_unknown"],
            }
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
    grouping.rebuild_products + indexer.reindex_all (worker.regroup / cron).
    """
    return await _run(source_id, adapter, adapter.partitions(), limit=limit)


async def run_partition(
    source_id: str, adapter: SourceAdapter, partition: str, *, limit: int | None = None
) -> IngestionRun:
    """Run a single partition — the unit of work for distributing a source."""
    return await _run(source_id, adapter, [partition], limit=limit)
