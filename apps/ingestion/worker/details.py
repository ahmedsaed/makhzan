"""Product-page details, read slowly and only when something changed.

The list pages a source is swept by give title, price, stock and a photo. The
description, the spec sheet, datasheet links and the rest of the gallery are on
each product's own page: one request per product. Reading every page every
cycle would multiply what a shop receives several times over, so this stage
reads a fixed, small number of them a run (`DetailsSettings.per_run`), and a
page is read again only when there is a reason to think it changed.

**Which listings are due.** ACTIVE listings of the source, in this order:
  1. *changed*: the change token the list page gave (`attributes.change_token`)
     differs from the one stored when the page was last read
     (`attributes.details_token`);
  2. *never fetched*: the most important first (`importance`: in a product
     several suppliers offer, in stock), then newest, so the backfill reaches
     the listings a buyer compares and can buy before the rest (T10);
  3. *stale by age*: read more than `max_age_days` ago, oldest first. The
     safety net for an edit no token shows — a card hash (TOKEN_CARD_HASH)
     only sees what the card shows, so a description edited on its own is
     caught here and nowhere else. For such a source the age adapts per
     listing (`details_interval_days`), as Nutch's AdaptiveFetchSchedule does:
     a re-read that finds the page unchanged waits 1.4 times longer next
     time, one that finds it changed 0.8 times as long, within
     [`MIN_INTERVAL_DAYS`, `MAX_INTERVAL_DAYS`]. A shop's own last-write
     token (TOKEN_MODIFIED) already sees every edit, so its age stays fixed.
A listing whose last read failed waits out a backoff (`details_retry_at`) first.

**Where the details live.** What a page gave is kept whole under
`attributes.details`, beside `details_token`, `details_fetched_at` and the
failure keys. The list-page upsert rebuilds every column and every attribute
from the card on each sweep, so it carries those keys over from the stored row
and lays the details on top again (`apply_details`). Without that, the next
sweep would wipe a description that cost a request to read.

**Pacing.** Every request goes through `CycleFetcher` — `worker/http.py`'s
`take_turn` gate, robots.txt on the full URL, the host's pace with its
Crawl-delay as a floor, and its Retry-After — and is counted under
`stats.requests.details` and in `stats.pacing`. A host that says to back off
(`HostBackingOff`), a robots.txt that cannot be read (`RobotsUnavailable`), a
429/5xx that outlasted its retries, or a network failure ends the stage for the run and blames no listing. A `limit=` run never gets here.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
from makhzan_schemas.enums import ListingStatus, StockSignal
from makhzan_schemas.models import Listing, Product
from sqlalchemy import DateTime, Float, Interval, and_, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.http import CycleFetcher, HostBackingOff
from worker.normalize import clean_description, clean_text
from worker.robots import RobotsUnavailable
from worker.richtext import merge_specs
from worker.sources.base import TOKEN_CARD_HASH, DetailsSettings, SourceAdapter

log = logging.getLogger(__name__)

#: The label every details request is counted under in `stats.requests`.
LABEL = "details"

#: Attribute keys the details stage owns. The list-page upsert carries them over
#: from the stored row: it rebuilds attributes from the card, which has none of them.
DETAIL_KEYS = (
    "details",
    "details_token",
    "details_fetched_at",
    "details_failed_at",
    "details_failures",
    "details_retry_at",
    "details_interval_days",
)

#: The adaptive revisit interval of a card-hash source (T10), in days: grown
#: by `INTERVAL_GROW` on a re-read that found nothing new, shrunk by
#: `INTERVAL_SHRINK` on one that did, and kept within these bounds.
MIN_INTERVAL_DAYS = 30
MAX_INTERVAL_DAYS = 180
INTERVAL_GROW = 1.4
INTERVAL_SHRINK = 0.8

#: Importance weights for the never-fetched backfill (T8's starting weights):
#: w = 1 + 1·[in a product several suppliers offer] + 0.5·[in stock].
WEIGHT_MULTI_SUPPLIER = 1.0
WEIGHT_IN_STOCK = 0.5

#: After the n-th failure in a row, wait 2**(n-1) days before trying the page
#: again, up to this many. A broken page costs one request a month, not one a day.
MAX_BACKOFF_DAYS = 30

#: Reasons a listing is due, in the order the budget is spent on them.
REASONS = ("changed", "never_fetched", "stale")

_ARABIC = re.compile(r"[؀-ۿ]")

#: Status codes that say the host, not the page, is in trouble.
#: Answers that say "the host", not "this page": stop the stage for the run and
#: mark no listing failed. 403 included: a shop that blocks the crawler blocks
#: every page, and marking each one failed would back off real pages for weeks.
_HOST_TROUBLE = {403, 429, 500, 502, 503, 504}


# --------------------------------------------------------------------------- #
# Merging the details into a listing
# --------------------------------------------------------------------------- #


def carry_details(stored: object, fresh: dict) -> dict:
    """`fresh` attributes (from a card) with the stored row's details keys kept."""
    if not isinstance(stored, dict):
        return fresh
    kept = {key: stored[key] for key in DETAIL_KEYS if key in stored}
    return {**fresh, **kept} if kept else fresh


def _merge_links(first: object, more: object) -> list:
    out: list = [d for d in first if isinstance(d, dict)] if isinstance(first, list) else []
    seen = {d.get("url") for d in out}
    for doc in more if isinstance(more, list) else []:
        if isinstance(doc, dict) and doc.get("url") and doc["url"] not in seen:
            seen.add(doc["url"])
            out.append(doc)
    return out


def apply_details(fields: dict) -> dict:
    """Lay `attributes.details` over a listing's card-derived fields.

    `fields` holds `description_en`, `description_ar`, `brand`, `images` and
    `attributes` as the card gave them; the result is what the listing shows.
    The product page's description replaces the card's one-liner; its photos
    follow the card's; its specs, documents and videos add to the card's (a name
    or link the card already has keeps the card's); its brand and manufacturer
    part number fill a gap and never overwrite one. Idempotent, so applying it
    to fields that already carry the details changes nothing.
    """
    attributes = fields.get("attributes")
    details = attributes.get("details") if isinstance(attributes, dict) else None
    if not isinstance(details, dict) or not details:
        return fields
    out = dict(fields)
    attrs = dict(attributes)

    description = clean_description(details.get("description"))
    if description:
        if _ARABIC.search(description) and not re.search(r"[A-Za-z]{3}", description):
            out["description_ar"] = description
        else:
            out["description_en"] = description

    images = list(out.get("images") or [])
    for url in details.get("images") or []:
        if isinstance(url, str) and url and url not in images:
            images.append(url)
    out["images"] = images

    brand = clean_text(details.get("brand"))
    if brand and not out.get("brand"):
        out["brand"] = brand[:120]

    specs = details.get("specs")
    if isinstance(specs, dict) and specs:
        card = attrs.get("specs") if isinstance(attrs.get("specs"), dict) else {}
        attrs["specs"] = merge_specs(card, {str(k): str(v) for k, v in specs.items()})
    for key in ("documents", "videos"):
        if details.get(key):
            attrs[key] = _merge_links(attrs.get(key), details[key])
    for key, value in details.items():
        if key in {"description", "images", "brand", "specs", "documents", "videos"}:
            continue
        if value not in (None, "", [], {}):
            attrs.setdefault(key, value)
    out["attributes"] = attrs
    return out


def _apply_to_listing(listing: Listing, attributes: dict) -> None:
    fields = apply_details(
        {
            "description_en": listing.description_en,
            "description_ar": listing.description_ar,
            "brand": listing.brand,
            "images": listing.images,
            "attributes": attributes,
        }
    )
    for key, value in fields.items():
        setattr(listing, key, value)


# --------------------------------------------------------------------------- #
# The queue
# --------------------------------------------------------------------------- #


def importance():
    """A listing's weight for the never-fetched backfill (see the module doc)."""
    suppliers = select(Product.supplier_count).where(Product.id == Listing.product_id)
    return (
        1.0
        + case(
            (func.coalesce(suppliers.scalar_subquery(), 0) > 1, WEIGHT_MULTI_SUPPLIER), else_=0.0
        )
        + case((Listing.stock_signal == StockSignal.IN_STOCK, WEIGHT_IN_STOCK), else_=0.0)
    )


def _conditions(
    source_id: str, settings: DetailsSettings, now: datetime, *, adaptive: bool = False
) -> dict:
    a = Listing.attributes
    fetched = a["details_fetched_at"].astext
    retry = a["details_retry_at"].astext
    max_age = cast(literal(timedelta(days=settings.max_age_days)), Interval)
    if adaptive:
        # Per listing, once a re-read has set one; the setting until then.
        days = cast(a["details_interval_days"].astext, Float)
        max_age = func.coalesce(cast(literal(timedelta(days=1)), Interval) * days, max_age)
    eligible = and_(
        Listing.source == source_id,
        Listing.status == ListingStatus.ACTIVE,
        or_(retry.is_(None), cast(retry, DateTime(timezone=True)) <= now),
    )
    changed = and_(
        fetched.is_not(None),
        a["change_token"].astext.is_distinct_from(a["details_token"].astext),
    )
    never = fetched.is_(None)
    stale = and_(
        fetched.is_not(None),
        ~changed,
        cast(fetched, DateTime(timezone=True)) < literal(now) - max_age,
    )
    return {
        "eligible": eligible,
        "changed": changed,
        "never_fetched": never,
        "stale": stale,
        "fetched_order": cast(fetched, DateTime(timezone=True)).asc(),
    }


async def due_listings(
    session: AsyncSession,
    source_id: str,
    settings: DetailsSettings,
    *,
    now: datetime | None = None,
    adaptive: bool = False,
) -> list[tuple[Listing, str]]:
    """Up to `per_run` listings due for a details fetch, with why, in budget order.

    `adaptive` gives each listing its own age limit (a card-hash source, T10).
    """
    now = now or datetime.now(timezone.utc)
    c = _conditions(source_id, settings, now, adaptive=adaptive)
    orders = {
        "changed": (c["fetched_order"], Listing.id),
        "never_fetched": (importance().desc(), Listing.first_seen_at.desc(), Listing.id),
        "stale": (c["fetched_order"], Listing.id),
    }
    picked: list[tuple[Listing, str]] = []
    for reason in REASONS:
        room = settings.per_run - len(picked)
        if room <= 0:
            break
        rows = (
            (
                await session.execute(
                    select(Listing)
                    .where(c["eligible"], c[reason])
                    .order_by(*orders[reason])
                    .limit(room)
                )
            )
            .scalars()
            .all()
        )
        picked.extend((row, reason) for row in rows)
    return picked


async def queue_counts(
    session: AsyncSession,
    source_id: str,
    settings: DetailsSettings,
    *,
    now: datetime | None = None,
    adaptive: bool = False,
) -> dict[str, int]:
    """How many listings are due, by reason, and how many have details: for `make status`."""
    now = now or datetime.now(timezone.utc)
    c = _conditions(source_id, settings, now, adaptive=adaptive)
    retry = Listing.attributes["details_retry_at"].astext
    row = (
        await session.execute(
            select(
                func.count().filter(c["eligible"], c["changed"]),
                func.count().filter(c["eligible"], c["never_fetched"]),
                func.count().filter(c["eligible"], c["stale"]),
                func.count().filter(Listing.attributes["details_fetched_at"].astext.is_not(None)),
                func.count().filter(retry.is_not(None), cast(retry, DateTime(timezone=True)) > now),
            ).where(Listing.source == source_id, Listing.status == ListingStatus.ACTIVE)
        )
    ).one()
    changed, never, stale, fetched, backing_off = row
    return {
        "changed": changed,
        "never_fetched": never,
        "stale": stale,
        "fetched": fetched,
        "backing_off": backing_off,
    }


# --------------------------------------------------------------------------- #
# The stage
# --------------------------------------------------------------------------- #


def _host_trouble(exc: Exception) -> bool:
    if isinstance(exc, HostBackingOff | RobotsUnavailable | httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _HOST_TROUBLE


def _failed(attributes: dict, now: datetime) -> dict:
    failures = int(attributes.get("details_failures") or 0) + 1
    wait = timedelta(days=min(2 ** (failures - 1), MAX_BACKOFF_DAYS))
    return {
        **attributes,
        "details_failed_at": now.isoformat(),
        "details_failures": failures,
        "details_retry_at": (now + wait).isoformat(),
    }


def next_interval(attributes: dict, details: dict, base_days: int) -> float | None:
    """The adaptive revisit interval after a page read, or None on a first read.

    A re-read that found the page as it was grows the listing's interval, one
    that found it changed shrinks it, within the bounds (see the module doc).
    """
    if not attributes.get("details_fetched_at"):
        return None  # nothing to compare: the setting's age applies until a re-read
    previous = attributes.get("details_interval_days")
    if isinstance(previous, bool) or not isinstance(previous, int | float) or previous <= 0:
        previous = base_days
    factor = INTERVAL_SHRINK if attributes.get("details") != details else INTERVAL_GROW
    return round(min(MAX_INTERVAL_DAYS, max(MIN_INTERVAL_DAYS, previous * factor)), 1)


def _fetched(
    attributes: dict, details: dict, now: datetime, *, interval: float | None = None
) -> dict:
    out = {k: v for k, v in attributes.items() if k not in DETAIL_KEYS}
    out["details"] = details
    # The token as it was when the page was read: the next card that moves it
    # makes the listing due again.
    out["details_token"] = attributes.get("change_token")
    out["details_fetched_at"] = now.isoformat()
    if interval is not None:
        out["details_interval_days"] = interval
    elif attributes.get("details_interval_days") is not None:
        out["details_interval_days"] = attributes["details_interval_days"]
    return out


def _clean(details: object) -> dict:
    """What an adapter returned, minus anything that must never be kept."""
    if not isinstance(details, dict):
        raise TypeError(f"fetch_details returned {type(details).__name__}, not a dict")
    return {k: v for k, v in details.items() if "stock" not in k and v not in (None, "", [], {})}


async def run_details(
    session: AsyncSession,
    adapter: SourceAdapter,
    *,
    errors: list[str],
    pace,
    already_sent: bool,
    checkpoint: Callable[[Counter], None] | None = None,
) -> tuple[Counter, dict]:
    """Fetch details for this run's share of the due listings.

    Returns the requests made (under "details") and the summary kept as
    `stats.details`. Commits after every listing, so a run that dies keeps what
    it read. `pace` is the source's pause; `already_sent` says whether this run
    has sent the host anything yet, so the first page waits its turn too.
    """
    settings = adapter.details
    if settings is None or not settings.enabled:
        return Counter(), {}
    adaptive = adapter.token_kind == TOKEN_CARD_HASH
    due = await due_listings(session, adapter.source_id, settings, adaptive=adaptive)
    summary: dict = {"due": dict(Counter(reason for _, reason in due))} if due else {}
    if not due:
        return Counter(), summary

    fetcher = CycleFetcher(pace, retries=1)
    fetched = failed = 0
    if already_sent:
        await asyncio.sleep(await pace())
    for listing, reason in due:
        now = datetime.now(timezone.utc)
        attributes = dict(listing.attributes or {})
        try:
            details = _clean(await adapter.fetch_details(listing, fetcher))
        except Exception as exc:  # noqa: BLE001 — one page must not stop the source
            if _host_trouble(exc):
                summary["stopped"] = f"{type(exc).__name__}: {exc}"[:200]
                errors.append(f"details stopped: {summary['stopped']}")
                break
            failed += 1
            errors.append(f"details {listing.external_id}: {type(exc).__name__}: {exc}"[:300])
            listing.attributes = _failed(attributes, now)
        else:
            fetched += 1
            interval = (
                next_interval(attributes, details, settings.max_age_days) if adaptive else None
            )
            _apply_to_listing(listing, _fetched(attributes, details, now, interval=interval))
        if checkpoint is not None:
            # The run's request count so far, on its row with this commit.
            checkpoint(Counter({LABEL: fetcher.requests.total()}))
        await session.commit()

    if fetched:
        summary["fetched"] = fetched
    if failed:
        summary["failed"] = failed
    requests = Counter({LABEL: fetcher.requests.total()}) if fetcher.requests else Counter()
    return requests, summary
