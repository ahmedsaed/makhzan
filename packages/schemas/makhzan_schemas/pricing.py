"""What a product costs, as a result row and the product page's summary state it.

One definition, computed once per rebuild (`grouping.rebuild_products`) and
stored on the product, so the card, the price sort, the price filter and the
page's headline say the same thing. The rules are the product page's (approved
November 2026, docs/DESIGN.md C2b/C3):

- Offers are compared by the **price of one**, as every shop publishes it. An
  offer with a minimum order still competes on its price of one; the summary
  then says "each" and names the minimum (`quantity`, `each`).
- An offer with options is priced by its **cheapest in-stock option**: an
  option is a price the shop publishes for this listing, and the listing's own
  price may be an out-of-stock option's (Shopify shows the first variant's,
  WooCommerce the cheapest variation's, whatever their stock). The option is
  named (`option`) when its price is not the listing's.
- An offer **on request** has no price to compare: it never enters the range.
  It is counted (`on_request`), so a row can read "Price on request" rather
  than nothing, and tell it from an offer with no price at all.
- **Which offers count** mirrors the shipped web page (`apps/web/lib/product.ts`,
  `summarizeOffers`): the fresh offers when any is fresh, every offer only when
  none is (C2b: never a stale price while a fresh offer exists); among those,
  the in-stock ones (low stock is stock), else those not known to be gone
  (unknown, made to order), else all of them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from makhzan_schemas.contracts import (
    is_price_on_request,
    min_order_of,
    variants_checked_at_of,
    variants_of,
)
from makhzan_schemas.enums import StockSignal
from makhzan_schemas.freshness import fresh_since

#: Low stock is still stock: the shop says it can sell one today.
IN_STOCK_SIGNALS = frozenset({StockSignal.IN_STOCK, StockSignal.LOW_STOCK})


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
    #: The option of that offer giving `min_price`, when its price is not the
    #: listing's own. None: the listing's price.
    option: str | None = None
    #: That offer's minimum order (or its step, when larger). None: sold singly.
    quantity: int | None = None
    #: Some offer in the range has a minimum order: the range reads "each".
    each: bool = False
    #: Offers on request among those counted.
    on_request: int = 0


def _fresh_stamp(when: datetime | None, cutoff: int) -> bool:
    return when is not None and when.timestamp() > cutoff


def unit_price(offer: _Offer, now: datetime | None = None) -> tuple[Decimal, str | None] | None:
    """An offer's price of one, and the option giving it (None: the listing's price).

    Its cheapest in-stock option when it has options and any is in stock with
    a price; otherwise its listing price. An option whose price or stock is
    unknown never sets it, nor do options read more than STALE_AFTER_DAYS ago
    (C2b). None for an offer on request, or with no price at all.
    """
    if is_price_on_request(offer.price, offer.attributes):
        return None
    listing = None if offer.price is None else Decimal(offer.price)
    checked = variants_checked_at_of(offer.attributes)
    if checked is None or _fresh_stamp(checked, fresh_since(now)):
        best: tuple[Decimal, str] | None = None
        for variant in variants_of(offer.attributes):
            if variant.in_stock is not True or variant.price is None:
                continue
            price = Decimal(str(variant.price))
            if best is None or price < best[0]:
                best = (price, variant.title)
        if best is not None:
            return best[0], (None if best[0] == listing else best[1])
    return None if listing is None else (listing, None)


def _counted(offers: list[_Offer], cutoff: int) -> list[_Offer]:
    """The offers the range is taken from: the web's `summarizeOffers` tiers."""
    fresh = [o for o in offers if _fresh_stamp(o.last_verified_at, cutoff)]
    pool = fresh or offers
    in_stock = [o for o in pool if o.stock_signal in IN_STOCK_SIGNALS]
    not_gone = [o for o in pool if o.stock_signal != StockSignal.OUT_OF_STOCK]
    return in_stock or not_gone or pool


def summarize_prices(offers: Iterable[_Offer], now: datetime | None = None) -> PriceSummary:
    """The product's price summary over its active offers (see the module docstring)."""
    counted = _counted(list(offers), fresh_since(now))
    priced: list[tuple[Decimal, str | None, _Offer]] = []
    on_request = 0
    for offer in counted:
        if is_price_on_request(offer.price, offer.attributes):
            on_request += 1
            continue
        unit = unit_price(offer, now)
        if unit is not None:
            priced.append((unit[0], unit[1], offer))
    if not priced:
        return PriceSummary(on_request=on_request)
    # Cheapest first; on a tie, the one a buyer can take singly, then the
    # freshest check, then a fixed order so a rebuild is reproducible.
    priced.sort(
        key=lambda p: (
            p[0],
            min_order_of(p[2].attributes) is not None,
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
        quantity=min_order_of(best.attributes),
        each=any(min_order_of(p[2].attributes) is not None for p in priced),
        on_request=on_request,
    )
