"""What a product costs, as a result row and the product page's summary state it.

One definition, computed once per rebuild (`grouping.rebuild_products`) and
stored on the product, so the card, the price sort, the price filter and the
page's headline can never disagree. The rules are the product page's (approved
November 2026, docs/DESIGN.md C2b/C3):

- Offers are compared by the **price of one**, as every shop publishes it. An
  offer with a minimum order still competes on its price of one; the summary
  then says "each" and names the minimum (`quantity`, `each`).
- An offer's **lowest in-stock option** is its price: an option is a price the
  shop publishes for this listing. An out-of-stock option never sets it. The
  option that does is named (`option`).
- An offer **on request** has no price to compare: it never enters the range.
  It is counted (`on_request`), so a row can read "Price on request" rather
  than nothing, and tell it from an offer with no price at all.
- Only **fresh, in-stock** offers count while there is one (priced or on
  request). An out-of-date offer (C2b) counts nowhere, even when it is the
  cheapest.

When no fresh offer is in stock, the fresh out-of-stock offers set the range
(the page's "Out of stock at all shops" still shows a price), and when no offer
is fresh at all, every offer does (the page then warns that it is out of date):
a product is never priced from a worse tier while a better one has anything to
say. Each tier is computed the same way.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from makhzan_schemas.contracts import is_price_on_request, min_quantity_of, variants_of
from makhzan_schemas.enums import StockSignal
from makhzan_schemas.freshness import fresh_since


class _Offer(Protocol):
    id: uuid.UUID
    supplier_id: uuid.UUID
    price: Decimal | None
    stock_signal: StockSignal
    last_verified_at: datetime | None
    attributes: dict


@dataclass(frozen=True)
class PriceSummary:
    """The range and what a reader needs to say about its low end."""

    min_price: Decimal | None = None
    max_price: Decimal | None = None
    #: The offer whose price of one is `min_price`, and its shop.
    listing_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    #: The option of that offer giving `min_price`, when an option undercuts
    #: the listing's own price. None: the listing's price.
    option: str | None = None
    #: That offer's minimum order. None: sold singly.
    quantity: int | None = None
    #: Some offer in the range has a minimum order: the range reads "each".
    each: bool = False
    #: Offers on request in the tier that set the range.
    on_request: int = 0


def unit_price(offer: _Offer) -> tuple[Decimal, str | None] | None:
    """An offer's price of one: its price, or its cheapest in-stock option's.

    None for an offer with no price (on request, or none published). An option
    is only a price beside a listing price: a listing with none is not priced
    by its options, as the page's own row is not.
    """
    if offer.price is None:
        return None
    best, option = Decimal(offer.price), None
    for variant in variants_of(offer.attributes):
        if variant.in_stock is True and variant.price is not None:
            price = Decimal(str(variant.price))
            if price < best:
                best, option = price, variant.title
    return best, option


def _fresh(offer: _Offer, cutoff: int) -> bool:
    return offer.last_verified_at is not None and offer.last_verified_at.timestamp() > cutoff


def _summarize(tier: list[_Offer]) -> PriceSummary | None:
    """The tier's summary, or None when it has nothing to say: no price, none on request."""
    priced: list[tuple[Decimal, str | None, _Offer]] = []
    on_request = 0
    for offer in tier:
        if is_price_on_request(offer.price, offer.attributes):
            on_request += 1
            continue
        unit = unit_price(offer)
        if unit is not None:
            priced.append((unit[0], unit[1], offer))
    if not priced:
        return PriceSummary(on_request=on_request) if on_request else None
    # Cheapest first; on a tie, the one a buyer can take singly, then the
    # freshest check, then a fixed order so a rebuild is reproducible.
    priced.sort(
        key=lambda p: (
            p[0],
            min_quantity_of(p[2].attributes) is not None,
            -(p[2].last_verified_at.timestamp() if p[2].last_verified_at else 0),
            str(p[2].id),
        )
    )
    low, option, best = priced[0]
    return PriceSummary(
        min_price=low,
        max_price=max(p[0] for p in priced),
        listing_id=best.id,
        supplier_id=best.supplier_id,
        option=option,
        quantity=min_quantity_of(best.attributes),
        each=any(min_quantity_of(p[2].attributes) is not None for p in priced),
        on_request=on_request,
    )


def summarize_prices(offers: Iterable[_Offer], now: datetime | None = None) -> PriceSummary:
    """The product's price summary over its active offers (see the module docstring)."""
    cutoff = fresh_since(now)
    offers = list(offers)
    fresh = [o for o in offers if _fresh(o, cutoff)]
    in_stock = [o for o in fresh if o.stock_signal == StockSignal.IN_STOCK]
    for tier in (in_stock, fresh, offers):
        summary = _summarize(tier)
        if summary is not None:
            return summary
    return PriceSummary()
