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
import math
import os
import time
import uuid
from collections import Counter
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from makhzan_schemas.contracts import NormalizedListing
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.domains.crosswalks import fold_names, normalize_category_name
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
from sqlalchemy import Integer, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from worker.categorize import category_slug_for, seed_categories
from worker.details import apply_details, carry_details, run_details
from worker.http import (
    CycleFetcher,
    HostBackingOff,
    RequestLog,
    current_request_log,
    host_of,
    logging_requests,
    set_host_pace,
)
from worker.identity import Identity, identity_for, using_identity
from worker.normalize import REVIEW_THRESHOLD, not_a_product
from worker.sources.base import CONTACT_PART, SourceAdapter, SupplierInfo

#: How long one source's job may take before arq cancels it (worker.main).
JOB_TIMEOUT = int(os.getenv("REFRESH_TIMEOUT_SECONDS", str(6 * 3600)))

#: The share of `JOB_TIMEOUT` a run may spend before it stops starting pages.
#: Whatever slows a host down — its Crawl-delay, a Retry-After, the error
#: slowdown in worker/http.py — the run ends itself cleanly first (cursors
#: kept, stats written) instead of being cancelled mid-page by arq. This is
#: the bound on the slowdown multiplier: it can stretch a run, never past this.
RUN_TIME_SHARE = 0.85

#: Monotonic clock for the run's time budget (patched in tests).
_clock = time.monotonic


def _refused_by_own_host(exc: Exception, adapter: SourceAdapter) -> bool:
    """Whether `exc` says the source's host will not be read today, whatever the page.

    Its robots.txt cannot be read (`RobotsUnavailable`), or it asked for a
    longer wait than the crawler waits out (`HostBackingOff`). Every later page
    and partition would fail the same way without sending anything, so the run
    stops instead of logging one identical error per partition and sleeping the
    pace between them.
    """
    from worker.robots import RobotsUnavailable

    if not adapter.base_url or not isinstance(exc, RobotsUnavailable | HostBackingOff):
        return False
    return exc.host == host_of(adapter.base_url)


def _refused_unsent(exc: Exception, log: RequestLog | None, before: int | None) -> bool:
    """A page refused before any request for it went out: not a page sent."""
    from worker.robots import DisallowedByRobots, RobotsUnavailable

    if not isinstance(exc, RobotsUnavailable | DisallowedByRobots | HostBackingOff):
        return False
    return before is None or _requests_logged(log) == before


def _requests_logged(log: RequestLog | None) -> int | None:
    """Requests the run has sent to any host, robots.txt excluded (None outside a run)."""
    if log is None:
        return None
    return sum(len(times) for times in log.times.values()) - sum(log.robots.values())


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


#: When the run in progress in this task started, if any (`_logged_run`): a
#: listing whose `last_checked_at` is at or after it was already counted.
_RUN_STARTED: ContextVar[datetime | None] = ContextVar("run_started", default=None)


def _count_check(listing: Listing, now: datetime, *, changed: bool) -> None:
    """Add one read to the listing's check log (`checks`, `changes`, first/last checked).

    The input to a per-listing change-rate estimate (the scheduling plan's T7):
    n reads and X changes seen over the n - 1 intervals between them. Done
    beside the history row, so it counts exactly the reads that record history
    — never a `limit=` run's. A stock-only read (out of stock by id) counts:
    it would see a stock change, though never a price one.

    - The first counted read is never a change, whatever the latest
      observation says: a listing stored before the log existed compares
      against a row weeks old, and that change belongs to no measured interval.
    - At most one counted read per listing per run. The Odoo shop reads a
      product in each leaf it is filed under and again in its /shop pass,
      minutes apart, and those reads would crowd the intervals. A later read
      in the same run still counts a change it finds, unless the run's read
      already did (`changes` never exceeds `checks - 1`), and leaves
      `last_checked_at` where the run's first read put it.
    """
    if listing.first_checked_at is None:
        changed = False
    started = _RUN_STARTED.get()
    if started is not None and listing.last_checked_at is not None:
        if listing.last_checked_at >= started:
            if changed and (listing.changes or 0) < (listing.checks or 0) - 1:
                listing.changes = (listing.changes or 0) + 1
            return
    listing.checks = (listing.checks or 0) + 1
    if changed:
        listing.changes = (listing.changes or 0) + 1
    if listing.first_checked_at is None:
        listing.first_checked_at = now
    listing.last_checked_at = now


async def _record_changes(
    session: AsyncSession,
    listings: list[Listing],
    now: datetime,
    *,
    new: bool = False,
    via: str = "sweep",
) -> int:
    """Add a `PriceObservation` for each listing whose price or stock changed.

    Compared against the listing's latest observation, not the values the update
    just overwrote: a `limit=` run updates listings without recording, and its
    change must still be recorded by the next real run rather than lost. A listing
    with no observation yet (new, or archived before history began) gets its
    first. A recheck that changes nothing writes nothing. Returns rows added.

    Each listing's read is also counted in its check log (`_count_check`): a
    change is the price, currency or stock differing from the latest row — not
    a first row, and not a return from archiving at the same values. `via`
    names the kind of read on the rows written (`PriceObservation.via`).

    Every listing passed here was just seen by its source, so it is available:
    one whose latest row is its archiving (`available` false) gets a row on
    coming back even at the same price and stock, which is what dates the gap.
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
                PriceObservation.available,
            )
            .where(PriceObservation.listing_id.in_(ids))
            .order_by(PriceObservation.listing_id, PriceObservation.observed_at.desc())
            .distinct(PriceObservation.listing_id)
        )
        latest = {row[0]: tuple(row[1:]) for row in rows}
    added = 0
    for listing in listings:
        current = (_cents(listing.price), listing.currency, listing.stock_signal, True)
        previous = latest.get(listing.id)
        prev_checked_at = listing.last_checked_at  # before this read moves it
        _count_check(listing, now, changed=previous is not None and previous[:3] != current[:3])
        if previous == current:
            continue
        session.add(
            PriceObservation(
                listing=listing,
                observed_at=now,
                price=current[0],
                currency=listing.currency,
                stock_signal=listing.stock_signal,
                in_stock=listing.stock_signal == StockSignal.IN_STOCK,
                available=True,
                via=via,
                prev_checked_at=prev_checked_at,
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
        source_type=source_type,
        # The listed contact details, area and governorate among them. After
        # this, `worker.sources.sync` keeps them in step with sources.toml.
        **info.contact_columns(),
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
    categories: Counter | None = None,
) -> str | None:
    """Normalize and upsert one item, or route it to review. Raises on bad items.

    Returns why the item was skipped as not a product, if it was. A skipped
    entry is never upserted, so one already stored stops being verified and is
    archived when the cycle completes — the same path as stock the shop dropped.

    `categories` counts how this item changed a stored listing's category
    (`_count_category_change`).
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
    stored_category = listing.category_id

    knows = adapter.knows_category(raw)
    if knows and mapped is None and adapter.authoritative_categories:
        # Browsed by category, under one the crosswalk does not map. A product
        # can sit in two categories, one mapped and one not, and then whichever
        # partition happened to be swept last decided: the unmapped one cleared
        # what the mapped one had just set (servos such as the SG90 and MG996R
        # lost theirs this way). Only a mapped category is in a position to
        # say; an unmapped one leaves the listing's category as it is.
        knows = False
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
    elif knows or listing.category_id is None:
        # This sweep was in a position to know, and there is no category: clear
        # whatever was there, so a supplier dropping a category is visible.
        # (One with no category yet just gets the supplier's default domain.)
        listing.category_id = None
        listing.domain = default_domain
    # Otherwise this pass carries no category signal — leave the existing one
    # alone rather than erasing what a category partition established.
    if categories is not None and not created:
        _count_category_change(categories, stored_category, listing.category_id)
    if created:
        run.items_created += 1
    else:
        run.items_updated += 1
    return None


def _count_category_change(categories: Counter, before, after) -> None:
    """Count a stored listing's category being set, moved or cleared by this read.

    `stats.categories`, for judging how often a sweep that carries a category
    changes one (decision D4 of the scheduling plan: could the Odoo shop's leaf
    categories be swept every Nth cycle, with the whole-shop pass alone keeping
    price and stock?). Counted on our category (`category_id`), not the shop's
    own name for it: two leaves the crosswalk maps alike are no move, while a
    product filed in two leaves mapped differently flips here each time, which
    is exactly the churn an Nth-cycle sweep would leave standing longer.
    """
    if before == after:
        return
    if before is None:
        categories["set"] += 1
    elif after is None:
        categories["cleared"] += 1
    else:
        categories["moved"] += 1


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
    halt: list[str] | None = None,
) -> Counter:
    """Hand the adapter its per-cycle reference data, fetching what is due.

    A refusal by the source's own host (`_refused_by_own_host`) stops the
    fetching and is appended to `halt`, so the run sweeps nothing today.

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
            if halt is not None and _refused_by_own_host(exc, adapter):
                # Not stamped as attempted: nothing was asked of the shop, so
                # the next run tries again rather than waiting out the delay.
                halt.append(str(exc))
                break
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
    checkpoint: Callable[[], None] | None = None,
    run_page_budget: int | None = None,
    deadline: float | None = None,
    halt: list[str] | None = None,
    categories: Counter | None = None,
) -> bool:
    """Sweep one partition from its cursor, committing after every page.

    `categories` counts category changes to stored listings (`_ingest_item`).

    `run_page_budget` caps the pages of the whole run (`tally["pages"]`), across
    partitions: the adaptive budget of a source with `target_cycle_days`.

    `checkpoint` puts what the run has sent so far on its row before each
    commit, so a run cut off mid-sweep still says how many requests it made.

    `deadline` (`_clock` time) stops it before the next page once the run's time
    budget is spent; `halt` receives the reason when the source's own host
    refuses the run (see `_refused_by_own_host`), so the caller stops too.

    Only pages that sent a request are counted in `tally["pages"]`: a page
    refused before anything went out (robots.txt, a host backing off) is not
    a request, and counting it inflated `stats.requests` and the cycle size
    the `target_cycle_days` budget plans from.

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
        if cursor.exhausted:
            # Finished this cycle: its next_page is back at 1, and sweeping it
            # again would re-read the whole partition before the cycle closes.
            return False
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
        if run_page_budget is not None and tally is not None and tally["pages"] >= run_page_budget:
            return False  # the run's adaptive budget is spent
        if deadline is not None and _clock() >= deadline:
            return False  # the run's time budget is spent; the cursor resumes here

        log = current_request_log()
        before = _requests_logged(log)
        try:
            result = await adapter.fetch_page(partition, page)
        except Exception as exc:  # noqa: BLE001 — a dead host must not discard the run
            if tally is not None and not _refused_unsent(exc, log, before):
                tally["pages"] += 1  # it reached the host, whatever came back
            errors.append(f"{partition or 'default'} p{page}: {exc}")
            if halt is not None and _refused_by_own_host(exc, adapter):
                halt.append(str(exc))
            return True
        if tally is not None:
            tally["pages"] += 1
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
                    categories=None if ephemeral else categories,
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
            if checkpoint is not None:
                checkpoint()
            await session.commit()

        if not result.has_more:
            return False
        page += 1
        await asyncio.sleep(await _pace(adapter))


def _requests_sent(
    tally: Counter,
    cycle_requests: Counter,
    adapter: SourceAdapter,
    log: RequestLog,
    details_requests: Counter,
) -> dict[str, int]:
    """`stats.requests`: every request this run made to the source's host, by purpose.

    Its pages, the reference data fetched once a cycle (by part), whatever else
    the adapter asked for while building its pages, product-page details and
    robots.txt. Zero counts are left out.
    """
    requests: Counter = Counter({"pages": tally["pages"]})
    requests.update(cycle_requests)
    requests.update(adapter.extra_requests())
    requests.update(details_requests)
    requests.update({"robots": sum(log.robots.values())})
    return {k: v for k, v in requests.items() if v}


async def _pace(adapter: SourceAdapter) -> float:
    """Seconds to wait before this source's next request (see `robots.polite_pause`)."""
    from worker.robots import polite_pause

    return await polite_pause(adapter.base_url, adapter.polite_delay)


#: Archive candidates offered to the source for confirmation in one run, the
#: most recently seen first. A cycle missing more than this is not the drift of
#: a multi-day sweep but a shop that changed: the rest archive as they always did.
CONFIRM_MAX_CANDIDATES = 500

#: The shortest a held archive waits before archiving as before, whatever the
#: cycle length: a source swept in one sitting still gets a day's retries.
CONFIRM_MIN_WAIT = timedelta(days=1)


class Confirmer:
    """Asks the source about a cycle's archive candidates before they are archived (T4).

    A multi-day sweep by page offset can skip a listing: one that leaves an
    already-read page shifts the rest back a slot, and one that moves to a stock
    partition already swept is never reached. The cycle then archives it,
    though the shop still sells it. So the candidates — active, not seen since
    the cycle began — are first offered to `SourceAdapter.confirm_listed`:

      - returned with a price: upserted (seen and verified), and kept;
      - still listed without a price: `last_seen_at` only, and kept;
      - asked and absent: archived, as before;
      - not asked (over a cap, held for a page there was no room to read) or
        the asking failed: nothing more is archived, and the cycle stays open
        with every cursor exhausted, so the next run asks again.

    The wait is capped at one cycle (`target_cycle_days`, else as long as the
    cycle took, at least `CONFIRM_MIN_WAIT`) from when the sweep finished; after
    it the cycle archives as it always has. Confirmation only ever *prevents* an
    archive: a listing's absence from it is never the reason for one beyond
    what the cycle already established.
    """

    def __init__(
        self,
        session: AsyncSession,
        run: IngestionRun,
        adapter: SourceAdapter,
        supplier_id: uuid.UUID,
        cat_index: dict,
        *,
        errors: list[str],
        already_sent: Callable[[], bool],
        may_send: Callable[[], str | None],
    ) -> None:
        self.session, self.run, self.adapter = session, run, adapter
        self.supplier_id, self.cat_index, self.errors = supplier_id, cat_index, errors
        self._already_sent = already_sent
        #: Why no request may go out now (the host refused the run, its time
        #: budget is spent), or None.
        self._may_send = may_send
        self.requests: Counter = Counter()
        self.report: dict = {}

    async def __call__(
        self, candidates: list[Listing], *, overdue: bool
    ) -> tuple[list[uuid.UUID], bool]:
        """(ids to archive, whether to hold the cycle open for the next run)."""
        everything = [row.id for row in candidates]
        offered = candidates[:CONFIRM_MAX_CANDIDATES]
        beyond = [row.id for row in candidates[CONFIRM_MAX_CANDIDATES:]]
        report = self.report
        report.update(candidates=len(candidates), offered=len(offered))
        if overdue:
            report["overdue"] = True

        refused = self._may_send()
        if refused:
            report["failed"] = refused[:200]
            return (everything, False) if overdue else ([], True)

        fetcher = CycleFetcher(lambda: _pace(self.adapter), retries=1)
        if self._already_sent():
            await asyncio.sleep(await _pace(self.adapter))
        try:
            answer = await self.adapter.confirm_listed(offered, fetcher)
        except Exception as exc:  # noqa: BLE001 — a failed check must not archive
            self.requests.update(fetcher.requests)
            message = f"{type(exc).__name__}: {exc}"[:200]
            self.errors.append(f"confirm before archiving: {message}")
            report["failed"] = message
            return (everything, False) if overdue else ([], True)
        self.requests.update(fetcher.requests)
        if answer is None:
            # No cheap way to ask this source: archive as it always has.
            self.report = {}
            return everything, False
        report.update(answer.notes)

        returned: set[str] = set()
        for raw in answer.items:
            returned.add(str(raw.external_id))
            try:
                await _ingest_item(
                    self.session, self.run, self.adapter, self.supplier_id, self.cat_index, raw
                )
            except Exception as exc:  # noqa: BLE001 — one bad item must not stop the rest
                self.run.items_failed += 1
                self.errors.append(f"confirm {raw.external_id}: {exc}")
        kept = returned | answer.seen
        by_external = {str(row.external_id): row for row in offered}
        now = datetime.now(timezone.utc)
        for external_id in kept:
            # The source just listed it. An upsert already said so; a listing
            # routed to review, or seen without a price, is said so here.
            if (row := by_external.get(external_id)) is not None:
                row.last_seen_at = now
        absent = [
            row.id
            for external_id, row in by_external.items()
            if external_id in answer.absent and external_id not in kept
        ]
        unasked = [
            row.id
            for external_id, row in by_external.items()
            if external_id not in kept and external_id not in answer.absent
        ]
        report.update(kept=len(kept & set(by_external)), absent=len(absent))
        if unasked and not overdue:
            report["held"] = len(unasked)
            # The confirmed absences go now; the cycle waits on the rest.
            return absent, True
        return absent + unasked + beyond, False


async def _finish_cycle_if_swept(
    session: AsyncSession,
    adapter: SourceAdapter,
    supplier_id: uuid.UUID,
    *,
    run: IngestionRun | None = None,
    pages_this_run: int = 0,
    confirm: Confirmer | None = None,
) -> tuple[int, dict]:
    """Archive vanished listings, but only once every partition has been swept.

    Archiving keys off the start of the whole *cycle*, not of this run: a sweep
    may span several runs, and retiring everything a single partial run failed
    to reach would delete most of the catalog.

    With `confirm`, the candidates are first put to the source (`Confirmer`);
    it may hold the cycle open, cursors exhausted, for the next run to finish.
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

    vanished = [
        Listing.supplier_id == supplier_id,
        Listing.status == ListingStatus.ACTIVE,
        # Seen, not verified: a listing kept alive by id alone was not
        # re-priced, but the shop still says it sells it.
        Listing.last_seen_at < cycle_started,
    ]
    if confirm is not None:
        candidates = (
            (
                await session.execute(
                    select(Listing)
                    .where(*vanished)
                    .order_by(Listing.last_seen_at.desc(), Listing.id)
                )
            )
            .scalars()
            .all()
        )
        if candidates:
            # When the sweep finished: no cursor is touched while a cycle is held.
            swept_at = max(c.updated_at for c in cursors)
            if adapter.target_cycle_days:
                wait = timedelta(days=adapter.target_cycle_days)
            else:
                wait = max(CONFIRM_MIN_WAIT, swept_at - cycle_started)
            overdue = datetime.now(timezone.utc) - swept_at > wait
            ids, hold = await confirm(list(candidates), overdue=overdue)
            # Only these, and only if still unseen: a confirmed one moved on.
            vanished.append(Listing.id.in_(ids))
            archived = await _archive(session, vanished) if ids else 0
            if hold:
                return archived, {}
        else:
            archived = 0
    else:
        archived = await _archive(session, vanished)
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
        # Every page the cycle read, across its runs: the size the next cycle's
        # adaptive budget (`target_cycle_days`) is planned from.
        "cycle_pages": pages_this_run
        + await _cycle_pages_since(
            session, adapter.source_id, cycle_started, exclude=run.id if run else None
        ),
    }
    return archived, cycle


async def _archive(session: AsyncSession, where: list) -> int:
    """Archive the listings matching `where`, dating the gap in their history."""
    archived = (
        await session.execute(
            update(Listing)
            .where(*where)
            .values(status=ListingStatus.ARCHIVED)
            .returning(Listing.id, Listing.price, Listing.currency, Listing.stock_signal)
        )
    ).all()
    if archived:
        # History marks the gap: from now until the listing is seen again it is
        # not offered at all, whatever its last price and stock were.
        now = datetime.now(timezone.utc)
        await session.execute(
            insert(PriceObservation),
            [
                {
                    "listing_id": listing_id,
                    "observed_at": now,
                    "price": _cents(price),
                    "currency": currency,
                    "stock_signal": stock_signal,
                    "in_stock": False,
                    "available": False,
                }
                for listing_id, price, currency, stock_signal in archived
            ],
        )
    return len(archived)


async def _cycle_pages_since(
    session: AsyncSession, source_id: str, since: datetime, *, exclude: uuid.UUID | None = None
) -> int:
    """Pages read by this source's runs of the cycle that started at `since`.

    A run belongs to the cycle when it was still going at `since` or later:
    the previous cycle closed inside a run that finished before this cycle's
    first cursor was stamped. `limit=` test runs are left out, and so is
    `exclude` (the run asking, which counts its own). Read from
    `stats.requests.pages`, which every run keeps current page by page.
    """
    pages = IngestionRun.stats["requests"]["pages"].astext.cast(Integer)
    query = select(func.coalesce(func.sum(pages), 0)).where(
        IngestionRun.source == source_id,
        or_(IngestionRun.finished_at.is_(None), IngestionRun.finished_at >= since),
        ~IngestionRun.stats.has_key("limit"),
    )
    if exclude is not None:
        query = query.where(IngestionRun.id != exclude)
    return int((await session.execute(query)).scalar_one())


#: The adaptive budget never drops below this share of a day's even split of
#: the last cycle: a cycle running ahead of schedule still makes steady progress.
BUDGET_FLOOR_SHARE = 0.5


async def _page_budget(session: AsyncSession, adapter: SourceAdapter) -> dict:
    """This run's page budget, for a source with `target_cycle_days` (else {}).

    Planned from the last completed cycle's size (`stats.cycle.cycle_pages`):
    the pages it is still owed, spread over the days the target leaves, one run
    a day. So a shop that grows gets more pages a run and its cycle stays near
    the target, instead of stretching with the catalogue under a fixed cap.
    `max_pages_per_run`, when set, is a hard ceiling on the run's total (a
    stricter reading than its usual per-partition one): the budget never asks
    a shop for more than the owner approved, and `ceiling_limited` says when it
    would have. A floor of half a day's even share keeps a cycle that is ahead
    moving. With no completed cycle yet, the ceiling alone applies.
    """
    target = adapter.target_cycle_days
    if not target:
        return {}
    ceiling = adapter.max_pages_per_run or None
    out: dict = {"target_cycle_days": target, "ceiling": ceiling}

    previous = (
        await session.execute(
            select(IngestionRun.stats["cycle"]["cycle_pages"].astext.cast(Integer))
            .where(
                IngestionRun.source == adapter.source_id,
                IngestionRun.stats["cycle"].has_key("cycle_pages"),
            )
            .order_by(IngestionRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not previous:
        out.update(pages=ceiling, basis="no completed cycle with a page count yet")
        return out

    starts = (
        (
            await session.execute(
                select(SourceCursor.cycle_started_at).where(
                    SourceCursor.source == adapter.source_id,
                    SourceCursor.cycle_started_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    started = min(starts) if starts else now
    elapsed_days = (now - started).total_seconds() / 86400
    read = await _cycle_pages_since(session, adapter.source_id, started) if starts else 0
    remaining_pages = max(0, previous - read)
    # Daily runs left before the target, this one included: a run 2.5 days in
    # of 7 has 5 (at 2.5, 3.5 ... 6.5). Rounded first, so seconds of drift in
    # when the cron fires do not buy a run.
    remaining_days = max(1, math.ceil(round(target - elapsed_days, 3)))

    planned = math.ceil(remaining_pages / remaining_days)
    floor = max(1, math.ceil(BUDGET_FLOOR_SHARE * previous / target))
    pages = max(planned, floor)
    limited = ceiling is not None and pages > ceiling
    if limited:
        pages = ceiling
    out.update(
        pages=pages,
        planned=planned,
        ceiling_limited=limited,
        previous_cycle_pages=previous,
        cycle_pages_read=read,
        # Runs are daily: the days so far plus a run per budget of what is left.
        projected_cycle_days=round(elapsed_days + math.ceil(remaining_pages / pages), 1),
    )
    return out


#: Unmapped names kept per run. Status unions a cycle's runs, so this only has
#: to hold one run's slice; 15 was hit on every run of the biggest source.
UNMAPPED_STORED = 100


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

    A clean check is recorded too (`unmapped` empty; `unused` empty when the
    run was complete, absent when it could not say), and None means "not
    checked" — no crosswalk, or nothing observed — so status can tell the two
    apart. A clean result speaks only for the names this run saw: on a paced
    source that is one slice, and status unions the cycle's runs.
    """
    if not adapter.categories or not observed:
        return None

    # Compared folded, as the lookup is (`crosswalks.normalize_category_name`):
    # exact strings reported "LED" and "Raspberry Pi" as unmapped while every
    # listing under them was being mapped.
    mapped = fold_names(adapter.categories)
    known = mapped | fold_names(adapter.ignored_categories)
    unmapped = {
        name: n for name, n in observed.items() if normalize_category_name(name) not in known
    }
    # Biggest first — a rename of a busy category matters more than a new
    # one-product corner. Capped to keep the row small; `unmapped_count` and
    # `unmapped_listings` cover every name, so status can say what the cap hid.
    drift: dict = {
        "observed": len(observed),
        "unmapped": dict(Counter(unmapped).most_common(UNMAPPED_STORED)),
        "unmapped_count": len(unmapped),
        "unmapped_listings": sum(unmapped.values()),
    }
    if complete:
        seen = fold_names(observed)
        unused = sorted(
            name for name in adapter.categories if normalize_category_name(name) not in seen
        )
        # Present (even empty) only when this run could speak for retirements,
        # so status can tell "none retired" from "not in a position to know".
        drift["unused"] = unused[:25]
        drift["unused_count"] = len(unused)
    return drift


async def _last_source_report(session: AsyncSession, source_id: str) -> dict:
    """`stats.source_report` of the source's newest finished, full (not `limit=`) run."""
    report = (
        await session.execute(
            select(IngestionRun.stats["source_report"])
            .where(
                IngestionRun.source == source_id,
                IngestionRun.finished_at.is_not(None),
                IngestionRun.stats.has_key("source_report"),
                ~IngestionRun.stats.has_key("limit"),
            )
            .order_by(IngestionRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return report if isinstance(report, dict) else {}


async def _partitions_for_this_run(
    session: AsyncSession, adapter: SourceAdapter, partitions: list[str]
) -> list[str]:
    """Take this run's slice of the work, skipping what the cycle already covered.

    A source can be swept over several days rather than in one sitting: each run
    takes `max_partitions_per_run` of the partitions still outstanding, and the
    cycle closes when the last of them is done. That spreads a large catalogue
    into a steady trickle instead of a daily spike, without touching freshness —
    the cycle length is what sets how often a product is re-checked.

    A partition already finished this cycle is skipped whatever the caps. It
    used to be skipped only under `max_partitions_per_run`: without it every
    run took every partition, and one exhausted earlier in the cycle (its
    cursor back at page 1) was read again from the start, so a shop paced by
    `max_pages_per_run` alone re-read its 49 out-of-stock pages 90 times a
    cycle while the big partition crept forward.
    """
    budget = adapter.max_partitions_per_run
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
    return outstanding[:budget] if budget else outstanding


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
    the run's `stats.pacing` is the pace the shop actually saw — and sent as
    the source's identity (`identity` in its config, worker/identity.py), which
    every client the run makes reads, so no request goes out as anything else.
    """
    identity = identity_for(adapter.identity)
    # Reads before this were earlier runs': a listing's first read in this run
    # is a check, its later ones are not (`_count_check`).
    started = _RUN_STARTED.set(datetime.now(timezone.utc))
    try:
        with logging_requests() as log, using_identity(identity):
            return await _logged_run(
                source_id, adapter, partitions, limit=limit, log=log, identity=identity
            )
    finally:
        _RUN_STARTED.reset(started)


async def _logged_run(
    source_id: str,
    adapter: SourceAdapter,
    partitions: list[str],
    *,
    limit: int | None,
    log: RequestLog,
    identity: Identity,
) -> IngestionRun:
    errors: list[str] = []
    # The least gap between any two requests to this host, retries and
    # robots.txt included (worker.http.take_turn); Crawl-Delay is a floor on it.
    set_host_pace(adapter.base_url, adapter.polite_delay)
    # No page is started after this: the run ends itself before arq cancels it.
    deadline = _clock() + JOB_TIMEOUT * RUN_TIME_SHARE
    #: Why the run stopped early, if it did: its own host refused it.
    halt: list[str] = []

    async with SessionLocal() as session:
        run = IngestionRun(source=source_id, source_type=adapter.source_type)
        session.add(run)
        supplier_id = await _get_or_create_supplier(session, adapter.supplier, adapter.source_type)
        cat_index = await seed_categories(session)  # idempotent
        await session.flush()

        budget: dict = {}
        if limit is None:
            # Bounded dev runs always sweep what they were asked for.
            partitions = await _partitions_for_this_run(session, adapter, partitions)
            budget = await _page_budget(session, adapter)
            # What the last full run left for this one to finish (a short page
            # whose verdict is the next page). A `limit=` run neither reads it
            # nor, being left out here, hands anything on.
            adapter.resume_from(await _last_source_report(session, source_id))
        run_page_budget = budget.get("pages")

        # Before any page: the adapter reads it while turning pages into listings.
        cycle_requests = await _load_cycle_data(
            session, adapter, supplier_id, ephemeral=limit is not None, errors=errors, halt=halt
        )
        fetch_failed = False
        observed: Counter = Counter()
        resumed: list[bool] = []
        not_products: Counter = Counter()
        tally: Counter = Counter()
        #: How this run's reads changed stored listings' categories (`stats.categories`).
        categories: Counter = Counter()
        #: Requests outside the sweep and the details stage (confirmation), by label.
        sent_extra: Counter = Counter()

        def checkpoint(more: Counter | None = None) -> None:
            """Put what the run has sent so far on its row, for the next commit.

            Called before every per-page commit. The full stats are written only
            when the run ends, and a run cut off before that (a deploy recreates
            the worker) used to be left with none: /how-we-crawl then published
            its week as "at least N". This keeps the two published figures,
            `requests` and `pacing`, current to the last page; they cost one
            small JSONB update in a commit that happens anyway.
            """
            sent = _requests_sent(
                tally, cycle_requests, adapter, log, (more or Counter()) + sent_extra
            )
            stats = dict(run.stats or {})
            if sent:
                stats["requests"] = sent
            stats["pacing"] = log.pacing()
            stats["identity"] = identity.describe()
            if log.robots_state:
                stats["robots"] = dict(log.robots_state)
            if validators := log.validator_stats():
                stats["validators"] = validators
            # The names seen so far, so a run cut off mid-sweep (its cursors
            # already advanced past these pages) still reports them. Never
            # `unused`: only the finished run can know it saw everything.
            if limit is None and (drift := _crosswalk_drift(adapter, observed, complete=False)):
                stats["crosswalk"] = drift
            if limit is None and tally["pages"]:
                stats["categories"] = {k: categories[k] for k in ("set", "moved", "cleared")}
            run.stats = stats

        # Durable before the sweep: a run that dies on page 1 still keeps it, and
        # a part that failed stays marked as tried.
        checkpoint()
        await session.commit()
        stopped: str | None = None
        if halt:
            fetch_failed, stopped = True, f"refused by its host: {halt[0]}"
            partitions = []
        for i, partition in enumerate(partitions):
            if limit is not None and run.items_seen >= limit:
                break
            if run_page_budget is not None and tally["pages"] >= run_page_budget:
                break
            if _clock() >= deadline:
                stopped = "time budget spent; the cursors resume next run"
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
                checkpoint=checkpoint,
                run_page_budget=run_page_budget,
                deadline=deadline,
                halt=halt,
                categories=categories,
            )
            fetch_failed = fetch_failed or failed
            if halt:
                # Every later partition would be refused the same way, sending
                # nothing: one error, not one per partition, and no idle pauses.
                stopped = f"refused by its host: {halt[0]}"
                break

        archived, cycle = 0, {}
        confirm: Confirmer | None = None
        if limit is None:
            # Never on a `limit=` run: it archives nothing, so has nothing to ask.
            if type(adapter).confirm_listed is not SourceAdapter.confirm_listed:
                confirm = Confirmer(
                    session,
                    run,
                    adapter,
                    supplier_id,
                    cat_index,
                    errors=errors,
                    already_sent=lambda: bool(tally["pages"] or cycle_requests),
                    may_send=lambda: (
                        f"refused by its host: {halt[0]}"
                        if halt
                        else ("time budget spent" if _clock() >= deadline else None)
                    ),
                )
            archived, cycle = await _finish_cycle_if_swept(
                session,
                adapter,
                supplier_id,
                run=run,
                pages_this_run=tally["pages"],
                confirm=confirm,
            )
        if confirm is not None and confirm.requests:
            sent_extra.update(confirm.requests)
            checkpoint()

        details_requests: Counter = Counter()
        details: dict = {}
        if limit is None and not fetch_failed and _clock() < deadline:
            # After the sweep and its archiving, so only listings the shop still
            # sells are read. A `limit=` run is a quick test: it never costs a
            # shop product-page requests. Nor does a run whose sweep failed: a
            # host refusing list pages is not asked for product pages.
            await session.commit()
            try:
                details_requests, details = await run_details(
                    session,
                    adapter,
                    errors=errors,
                    pace=lambda: _pace(adapter),
                    already_sent=bool(tally["pages"] or cycle_requests or sent_extra),
                    checkpoint=checkpoint,
                )
            except Exception as exc:  # noqa: BLE001 — the sweep's stats must survive
                # Whatever went wrong reading details, the run's own record
                # (requests, pacing, archiving) is what /how-we-crawl publishes.
                await session.rollback()
                errors.append(f"details: {exc}")

        stats: dict = {}
        if errors:
            stats["errors"] = errors
        # Who the run said it was, and what robots.txt said, for `make status`.
        # Never on /how-we-crawl.
        stats["identity"] = identity.describe()
        if log.robots_state:
            stats["robots"] = dict(log.robots_state)
        if stopped:
            stats["stopped"] = stopped
        if limit is not None:
            # A test run: its pages are not part of any cycle (`_cycle_pages_since`).
            stats["limit"] = limit
        if budget:
            stats["budget"] = budget
        if archived:
            stats["archived"] = archived
        if cycle:
            stats["cycle"] = cycle
        if not_products:
            # Named, so a wrongly skipped real product is visible in the run.
            stats["not_products"] = dict(not_products.most_common(25))
        if details:
            stats["details"] = details
        if requests := _requests_sent(
            tally, cycle_requests, adapter, log, details_requests + sent_extra
        ):
            stats["requests"] = requests
        if confirm is not None and confirm.report:
            # What the cycle's archive candidates turned out to be (T4, T12).
            # For `make status`; never on /how-we-crawl.
            stats["archive_confirm"] = confirm.report
        # What the shop's server saw: requests sent (a retry is one more) and the
        # gaps between them, which is what /how-we-crawl publishes. `requests`
        # above counts by purpose; a page refused before sending (robots.txt, a
        # host still backing off) is in neither.
        stats["pacing"] = log.pacing()
        if report := adapter.run_report():
            stats["source_report"] = report
        if validators := log.validator_stats():
            # How many answers carried ETag / Last-Modified, per host (T11:
            # measure before building conditional requests). Counts only, and
            # never in `stats.pacing`, which /how-we-crawl publishes.
            stats["validators"] = validators
        if limit is None and tally["pages"]:
            # Recorded even when nothing changed: a zero here is a measurement,
            # its absence (older runs, `limit=` runs) is not.
            stats["categories"] = {k: categories[k] for k in ("set", "moved", "cleared")}
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
        # Recorded only for a real sweep: a `limit=` test run is ephemeral and
        # must not speak for the catalogue (a clean result would read as a
        # check), and a run its host stopped before any page saw nothing.
        if drift is not None and limit is None and not (stopped and not tally["pages"]):
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
