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
  2. *never fetched*: newest first, so a new product is described soonest;
  3. *stale by age*: read more than `max_age_days` ago, oldest first. The
     safety net for an edit no token shows — a card hash (TOKEN_CARD_HASH)
     only sees what the card shows, so a description edited on its own is
     caught here and nowhere else.
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
(`HostBackingOff`), a 429/5xx that outlasted its retries, or a network failure
ends the stage for the run and blames no listing. A `limit=` run never gets here.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Listing
from sqlalchemy import DateTime, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.http import CycleFetcher, HostBackingOff
from worker.normalize import clean_description, clean_text
from worker.richtext import merge_specs
from worker.sources.base import DetailsSettings, SourceAdapter

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
)

#: After the n-th failure in a row, wait 2**(n-1) days before trying the page
#: again, up to this many. A broken page costs one request a month, not one a day.
MAX_BACKOFF_DAYS = 30

#: Reasons a listing is due, in the order the budget is spent on them.
REASONS = ("changed", "never_fetched", "stale")

_ARABIC = re.compile(r"[؀-ۿ]")

#: Status codes that say the host, not the page, is in trouble.
_HOST_TROUBLE = {429, 500, 502, 503, 504}


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


def _conditions(source_id: str, settings: DetailsSettings, now: datetime) -> dict:
    a = Listing.attributes
    fetched = a["details_fetched_at"].astext
    retry = a["details_retry_at"].astext
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
        cast(fetched, DateTime(timezone=True)) < now - timedelta(days=settings.max_age_days),
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
) -> list[tuple[Listing, str]]:
    """Up to `per_run` listings due for a details fetch, with why, in budget order."""
    now = now or datetime.now(timezone.utc)
    c = _conditions(source_id, settings, now)
    orders = {
        "changed": (c["fetched_order"], Listing.id),
        "never_fetched": (Listing.first_seen_at.desc(), Listing.id),
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
) -> dict[str, int]:
    """How many listings are due, by reason, and how many have details: for `make status`."""
    now = now or datetime.now(timezone.utc)
    c = _conditions(source_id, settings, now)
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
    if isinstance(exc, HostBackingOff | httpx.TransportError):
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


def _fetched(attributes: dict, details: dict, now: datetime) -> dict:
    out = {k: v for k, v in attributes.items() if k not in DETAIL_KEYS}
    out["details"] = details
    # The token as it was when the page was read: the next card that moves it
    # makes the listing due again.
    out["details_token"] = attributes.get("change_token")
    out["details_fetched_at"] = now.isoformat()
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
    due = await due_listings(session, adapter.source_id, settings)
    summary: dict = {"due": dict(Counter(reason for _, reason in due))} if due else {}
    if not due:
        return Counter(), summary

    fetcher = CycleFetcher(pace)
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
            _apply_to_listing(listing, _fetched(attributes, details, now))
        await session.commit()

    if fetched:
        summary["fetched"] = fetched
    if failed:
        summary["failed"] = failed
    requests = Counter({LABEL: fetcher.requests.total()}) if fetcher.requests else Counter()
    return requests, summary
