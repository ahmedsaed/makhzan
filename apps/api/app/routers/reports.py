""" "Report a problem": the API's first write from a visitor.

`POST /reports` takes one report from a product page's form, checks it, and
stores it with a snapshot of what the page showed (`makhzan_schemas.models.Report`).
A person reviews every report on the server (`./makhzan reports`); nothing
here acts on one.

Spam, without a CAPTCHA (the owner's choice; a CAPTCHA would send visitor data
to a third party):

- Refused before parsing: a body over 16 KB (413, app/body_limit.py).
- Dropped silently, answered as if stored, so a bot learns nothing: the
  hidden honeypot field filled in; sent under 3 s after the form opened, by
  a server-signed opened-at token (`GET /reports/token`, no cookie, nothing
  stored), or with no valid token at all; free text over 1,000 characters;
  more than 2 links in it.
- Counted once: the same reason about the same product from the same address
  within a day answers with the first report's reference.
- Limited: 5 stored reports an hour and 20 a day per address, and 500 a day
  from everyone together (REPORTS_PER_DAY_ALL), after which 429, with how
  long to wait.

Text is stored without control characters (`rules.strip_controls`), and a
snapshot keeps at most 50 offers a product, every ticked one among them.

The address is counted under a salted hash (`REPORT_IP_SALT`, a server secret)
and never stored as such; the hash is erased after 24 hours, and an email 90
days after the report was sent, by the worker (`makhzan_schemas.reports`).
What the visitor is told is in apps/web/app/(site)/privacy.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from makhzan_schemas import reports as rules
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Listing, Product, ProductRedirect, Report
from makhzan_schemas.search import category_ref
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.client_ip import client_address, rate_limit_key
from app.deps import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reports"])

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
_LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


class ReportIn(BaseModel):
    """What the form sends. Anything else in the body is ignored."""

    model_config = ConfigDict(extra="ignore")

    product_id: uuid.UUID
    reason: Literal[
        "offers_not_same",
        "same_as_other",
        "wrong_price_stock",
        "wrong_category",
        "wrong_details",
        "shop_contact",
        "other",
    ]
    offer_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    other_product_id: uuid.UUID | None = None
    field: str | None = Field(default=None, max_length=32)
    correct_value: str | None = Field(default=None, max_length=200)
    # Over MAX_DESCRIPTION is dropped as spam rather than refused, so the
    # schema only bounds what is parsed at all.
    description: str | None = Field(default=None, max_length=20_000)
    email: str | None = Field(default=None, max_length=254)
    #: The honeypot: a field no person sees or can tab to.
    website: str | None = Field(default=None, max_length=2_000)
    #: When the form opened, as this API signed it (`GET /reports/token`).
    token: str | None = Field(default=None, max_length=200)


class ReportToken(BaseModel):
    token: str


class ReportAck(BaseModel):
    #: "R-24817"; null when the report was not kept (and the visitor need not know).
    reference: str | None


def _salt() -> bytes | None:
    salt = os.environ.get("REPORT_IP_SALT", "")
    return salt.encode() if salt else None


def _ip_hash(key: str | None, salt: bytes) -> str | None:
    if key is None:
        return None
    return hmac.new(salt, key.encode(), hashlib.sha256).hexdigest()


def _token_key(salt: bytes) -> bytes:
    # A key of its own, derived from the secret, so a token is never a hash
    # of anything else signed with it.
    return hashlib.sha256(b"makhzan report opened-at token\0" + salt).digest()


def issue_token(salt: bytes, now_ms: int | None = None) -> str:
    """`<ms since the epoch>.<signature>`: when a form opened, signed by us."""
    stamp = str(int(time.time() * 1000) if now_ms is None else now_ms)
    signature = hmac.new(_token_key(salt), stamp.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{stamp}.{signature}"


def _token_age(token: str | None, salt: bytes, now_ms: int) -> float | None:
    """Seconds since the form opened, or None for a token we did not sign."""
    if not token or token.count(".") != 1:
        return None
    stamp, signature = token.split(".")
    if not stamp.isdigit():
        return None
    expected = hmac.new(_token_key(salt), stamp.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(signature, expected):
        return None
    return (now_ms - int(stamp)) / 1000


def _is_spam(body: ReportIn, salt: bytes, now_ms: int) -> str | None:
    """Why a report is dropped without a word, or None to keep going."""
    if body.website and body.website.strip():
        return "honeypot"
    age = _token_age(body.token, salt, now_ms)
    if age is None:
        return "no token"
    if age < rules.MIN_FILL_SECONDS or age > rules.TOKEN_MAX_AGE.total_seconds():
        return "too fast" if age < rules.MIN_FILL_SECONDS else "token expired"
    description = body.description or ""
    if len(description) > rules.MAX_DESCRIPTION:
        return "too long"
    if len(_LINK.findall(description)) > rules.MAX_LINKS:
        return "links"
    return None


async def _resolve(session: AsyncSession, product_id: uuid.UUID) -> Product | None:
    """The product an id names now: itself, the one it was merged into, or an
    older id's successor (docs/decisions/0004-stable-product-ids.md). One hop:
    every merge repoints whatever led to the product it absorbs."""
    product = await session.get(Product, product_id, options=[selectinload(Product.category)])
    if product is not None and product.merged_into is not None:
        product = await session.get(
            Product, product.merged_into, options=[selectinload(Product.category)]
        )
    elif product is None:
        successor = await session.scalar(
            select(ProductRedirect.new_id).where(ProductRedirect.old_id == product_id)
        )
        if successor is not None:
            product = await session.get(
                Product, successor, options=[selectinload(Product.category)]
            )
    if product is None or product.merged_into is not None:
        return None
    return product


async def _offers(session: AsyncSession, product_id: uuid.UUID) -> list[Listing]:
    rows = await session.scalars(
        select(Listing)
        .where(Listing.product_id == product_id, Listing.status == ListingStatus.ACTIVE)
        .options(selectinload(Listing.supplier))
        .order_by(Listing.price.asc().nulls_last(), Listing.id)
    )
    return list(rows)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _listing_snapshot(listing: Listing, ticked: set[uuid.UUID]) -> dict:
    return {
        "id": str(listing.id),
        "title": listing.title_en or listing.title_ar,
        "shop": {"slug": listing.supplier.slug, "name": listing.supplier.name},
        "price": _money(listing.price),
        "currency": listing.currency,
        "stock": str(listing.stock_signal),
        "part_number": listing.part_number,
        "source_url": listing.source_url,
        "last_verified_at": listing.last_verified_at.isoformat(),
        "ticked": listing.id in ticked,
    }


def _kept(offers: list[Listing], ticked: set[uuid.UUID]) -> list[Listing]:
    """Every ticked offer, then the rest in order, up to the snapshot's cap."""
    room = max(0, rules.MAX_SNAPSHOT_LISTINGS - len(ticked))
    rest = [o for o in offers if o.id not in ticked][:room]
    keep = {o.id for o in rest} | ticked
    return [o for o in offers if o.id in keep]


def _product_snapshot(product: Product, offers: list[Listing], ticked: set[uuid.UUID]) -> dict:
    category = product.category
    kept = _kept(offers, ticked)
    return {
        "id": str(product.id),
        "title": product.title_en or product.title_ar,
        "part_number": product.part_number,
        "category": category_ref(category.domain, category.slug) if category else None,
        "category_name": category.name_en if category else None,
        "min_price": _money(product.min_price),
        "max_price": _money(product.max_price),
        "currency": product.currency,
        "listings": [_listing_snapshot(o, ticked) for o in kept],
        # How many there were, so a capped list says it is one.
        "listings_total": len(offers),
    }


def _refuse(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def _check(body: ReportIn, offers: list[Listing]) -> tuple[list[uuid.UUID], str | None, str | None]:
    """The offers, field and value this reason takes, or a 422.

    What a reason does not take is dropped rather than refused: a form that
    switched reasons may still hold the last one's answers.
    """
    reason = body.reason
    ids = list(dict.fromkeys(body.offer_ids))
    known = {o.id for o in offers}
    takes_offers = reason in (
        "offers_not_same",
        "wrong_price_stock",
        "wrong_details",
        "shop_contact",
    )
    if not takes_offers:
        ids = []
    if any(i not in known for i in ids):
        raise _refuse("an offer is not one of this product's")
    if reason == "offers_not_same":
        if len(offers) < 2:
            raise _refuse("this product has only one offer")
        if not ids:
            raise _refuse("tick at least one offer")
    if reason == "wrong_price_stock" and len(ids) != 1:
        raise _refuse("choose the offer that is wrong")
    if reason == "shop_contact" and not ids:
        raise _refuse("choose the shop")

    allowed = rules.FIELDS_BY_REASON.get(reason, ())
    field = body.field if allowed else None
    if reason == "wrong_category":
        field = "category"
    elif allowed and field not in allowed:
        raise _refuse(f"say which detail: one of {', '.join(allowed)}")

    value = (rules.strip_controls(body.correct_value) or "").strip() or None
    if reason not in ("wrong_price_stock", "wrong_category"):
        value = None
    if reason == "wrong_price_stock" and field == "stock" and value is not None:
        if value not in rules.STOCK_VALUES:
            raise _refuse(f"stock is one of {', '.join(rules.STOCK_VALUES)}")
    return ids, field, value


@router.get("/reports/token", response_model=ReportToken)
async def report_token(response: Response) -> ReportToken:
    """When a form opened, signed: the form sends it back with the report.

    Stateless (nothing is stored, no cookie is set): the report is checked
    against it, so a bot cannot claim it took its time.
    """
    salt = _salt()
    if salt is None:
        raise HTTPException(status_code=503, detail="reports are not available right now")
    response.headers["Cache-Control"] = "no-store"
    return ReportToken(token=issue_token(salt))


def _per_day_all() -> int:
    try:
        return max(1, int(os.environ.get("REPORTS_PER_DAY_ALL", rules.PER_DAY_ALL)))
    except ValueError:
        return rules.PER_DAY_ALL


def _too_many(over: tuple[str, int, timedelta]) -> HTTPException:
    limit, count, wait = over
    minutes = max(1, -(-int(wait.total_seconds()) // 60))
    return HTTPException(
        status_code=429,
        detail={"limit": limit, "count": count, "retry_after_minutes": minutes},
        headers={"Retry-After": str(minutes * 60)},
    )


@router.post("/reports", response_model=ReportAck, status_code=202)
async def create_report(
    body: ReportIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> ReportAck:
    """Take one report. 202 with its reference; 429 over the limit."""
    salt = _salt()
    if salt is None:
        # Without the secret there is no rate limit and no token; refusing is
        # safer than storing reports nobody can hold back. deploy.sh refuses
        # to deploy without it, so this is a development machine.
        logger.error("REPORT_IP_SALT is not set; reports are refused")
        raise HTTPException(status_code=503, detail="reports are not available right now")

    spam = _is_spam(body, salt, int(time.time() * 1000))
    if spam:
        logger.info("report dropped: %s", spam)
        return ReportAck(reference=None)

    description = (rules.strip_controls(body.description) or "").strip() or None
    if body.reason == "other" and len(description or "") < 5:
        raise _refuse("say what is wrong, in a few words")
    email = (rules.strip_controls(body.email) or "").strip() or None
    if email is not None and not _EMAIL.match(email):
        raise _refuse("that email does not look complete")

    product = await _resolve(session, body.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    offers = await _offers(session, product.id)
    offer_ids, field, value = _check(body, offers)

    other = None
    other_offers: list[Listing] = []
    if body.reason == "same_as_other":
        if body.other_product_id is None:
            raise _refuse("pick the other product")
        other = await _resolve(session, body.other_product_id)
        if other is None:
            raise _refuse("the other product was not found")
        if other.id == product.id:
            raise _refuse("that is this product")
        other_offers = await _offers(session, other.id)

    now = datetime.now(UTC)
    ip_hash = _ip_hash(rate_limit_key(client_address(request)), salt)
    if ip_hash is not None:
        # One sender at a time, so two reports sent together cannot both slip
        # under the limit. Released with the transaction.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"report:{ip_hash}"}
        )
        same = await session.scalar(
            select(Report.id)
            .where(
                Report.ip_hash == ip_hash,
                Report.product_id == product.id,
                Report.reason == body.reason,
                Report.created_at > now - timedelta(days=1),
            )
            .order_by(Report.id)
            .limit(1)
        )
        if same is not None:
            await session.rollback()
            return ReportAck(reference=rules.reference(same))
        over = await _over_limit(session, ip_hash, now)
        if over is not None:
            await session.rollback()
            raise _too_many(over)
    # Everyone together, last: a flood from many addresses stops here.
    over = await _window_full(session, None, now, "site", timedelta(days=1), _per_day_all())
    if over is not None:
        await session.rollback()
        logger.warning("reports: the daily ceiling of %d is reached", over[1])
        raise _too_many(over)

    ticked = set(offer_ids)
    report = Report(
        product_id=product.id,
        reported_product_id=body.product_id if body.product_id != product.id else None,
        reason=body.reason,
        offer_ids=[str(i) for i in offer_ids],
        other_product_id=other.id if other else None,
        field=field,
        correct_value=value,
        description=description,
        email=email,
        snapshot={
            "taken_at": now.isoformat(),
            "product": _product_snapshot(product, offers, ticked),
            "other_product": _product_snapshot(other, other_offers, set()) if other else None,
        },
        ip_hash=ip_hash,
        created_at=now,
    )
    session.add(report)
    await session.commit()
    return ReportAck(reference=rules.reference(report.id))


async def _over_limit(
    session: AsyncSession, ip_hash: str, now: datetime
) -> tuple[str, int, timedelta] | None:
    """("hour" | "day", how many, how long until one more is allowed), or None."""
    for limit, window, most in (
        ("hour", timedelta(hours=1), rules.PER_HOUR),
        ("day", timedelta(days=1), rules.PER_DAY),
    ):
        over = await _window_full(session, ip_hash, now, limit, window, most)
        if over is not None:
            return over
    return None


async def _window_full(
    session: AsyncSession,
    ip_hash: str | None,
    now: datetime,
    limit: str,
    window: timedelta,
    most: int,
) -> tuple[str, int, timedelta] | None:
    """Whether `most` reports are already stored in the window, from one
    address or (`ip_hash` None) from everyone; with the wait if so."""
    where = [Report.created_at > now - window]
    if ip_hash is not None:
        where.append(Report.ip_hash == ip_hash)
    count, oldest = (
        await session.execute(select(func.count(), func.min(Report.created_at)).where(*where))
    ).one()
    if count < most:
        return None
    if count > most:
        # Only the newest `most` matter: one more is allowed once the
        # (count - most + 1)th oldest leaves the window.
        oldest = await session.scalar(
            select(Report.created_at)
            .where(*where)
            .order_by(Report.created_at)
            .offset(count - most)
            .limit(1)
        )
    return limit, most, oldest + window - now
