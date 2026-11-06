"""Odoo eCommerce (website_sale) adapter — HTML-scraped.

Odoo has no clean public JSON feed (the JSON-RPC endpoint needs a session), so
we parse the paginated /shop listing pages. We read the **schema.org microdata**
Odoo emits for SEO (`itemprop="price"` etc.) rather than theme CSS classes: it's
a stabler contract and the price comes pre-parsed ("1695.0" vs "1,695.00").

Three Odoo quirks handled here:
  - /shop?page=N clamps to the last page (repeats it) instead of going empty, so
    we stop when a page yields no NEW product ids.
  - product ids live in the URL slug's trailing "-<id>" — used as external_id.
  - stock shows as a ribbon (`.o_ribbon`) only when NOT normally available
    ("Out of stock" / "Arriving Soon"); no ribbon means in stock.

A card also carries the internal reference (in the image alt), a struck-through
list price when the product is reduced, and a short subtitle that some shops use
for the brand ("Acme Brand") or the warranty. All of it is read here. The full
description, the photo gallery and datasheet links are only on the product page —
one request per product, which is why they are not.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import urljoin

from makhzan_schemas.contracts import RawItem
from makhzan_schemas.domains.crosswalks import fold_crosswalk, normalize_category_name
from makhzan_schemas.enums import SourceType
from selectolax.parser import HTMLParser

from worker.http import get_text, make_client
from worker.normalize import parse_price
from worker.richtext import html_to_text
from worker.sources.base import Page, SourceAdapter, SupplierInfo

MAX_PAGES = 300
_ID_RE = re.compile(r"-(\d+)$")

#: Odoo names a product "[<internal reference>] <name>" wherever it shows the
#: display name, and the card's image alt is one of those places.
_REFERENCE_RE = re.compile(r"^\s*\[([^\]\s][^\]]{0,62})\]")

#: A line of the card subtitle naming the maker: "Acme Brand", "Original Acme®
#: Brand", "Original Brand Acme®". Whole-line only, so "Brand New" and a brand
#: mentioned mid-sentence are not read as one.
_BRAND_LINES = (
    re.compile(r"^(?:original\s+)?(?P<b>[^\W_][\w.&+' -]{0,30}?)\s*[®™]?\s+brand$", re.I),
    re.compile(r"^original\s+brand\s+(?P<b>[^\W_][\w.&+' -]{0,30}?)\s*[®™]?$", re.I),
)
_NOT_A_BRAND = {"original", "new", "the", "top", "best", "high quality", "famous", "oem"}
_WARRANTY_RE = re.compile(r"\b\d+\s*(?:years?|months?)\s+warranty\b", re.I)


class OdooAdapter(SourceAdapter):
    source_type = SourceType.SCRAPED

    def __init__(
        self,
        source_id: str,
        base_url: str,
        supplier: SupplierInfo,
        *,
        enabled: bool = True,
        polite_delay: float | None = None,
        max_pages_per_run: int | None = None,
        max_partitions_per_run: int | None = None,
        categories: dict[str, tuple[str, str]] | None = None,
        partition_keys: tuple[str, ...] | Sequence[str] | None = None,
        sweep_whole_shop: bool = False,
    ) -> None:
        self.source_id = source_id
        self.base_url = base_url.rstrip("/")
        self.supplier = supplier
        self.enabled = enabled
        #: Crosswalk from this shop's own category slug to (domain, leaf).
        self.categories = categories or {}
        self._folded_categories = fold_crosswalk(self.categories)
        #: Categories to sweep. Wider than the crosswalk on purpose: an unmapped
        #: category still has to be visited, or its listings are never seen again
        #: and a completed cycle archives them.
        self.partition_keys = tuple(partition_keys or self.categories)
        #: Also sweep /shop, for products the shop files under no category at
        #: all. Without it a completed cycle never sees them and archives them.
        self.sweep_whole_shop = sweep_whole_shop
        # Browsing *by* category makes the category a fact rather than a guess,
        # so a crosswalk miss must stay uncategorized. Falling back to inference
        # here would put "IDC Sockets" and "Micro Switches" in Connectors &
        # Sockets, because the electronics rules match "socket".
        self.authoritative_categories = bool(self.categories)
        # Keyed by partition: the repeat check compares a page against the one
        # before it *in the same category*, and 170 partitions share this adapter.
        self._prev_page_ids: dict[str, set[str]] = {}
        if polite_delay is not None:
            self.polite_delay = polite_delay
        if max_pages_per_run is not None:
            self.max_pages_per_run = max_pages_per_run
        if max_partitions_per_run is not None:
            self.max_partitions_per_run = max_partitions_per_run

    def partitions(self) -> list[str]:
        """One partition per category, or a single unnamed sweep of /shop.

        The whole-shop sweep is what a source without a crosswalk gets; a source
        browsed by category so its listings arrive already categorized.
        """
        keys = list(self.partition_keys)
        if self.sweep_whole_shop:
            # First, not last. A run takes `max_partitions_per_run` of whatever
            # is still outstanding, in order, and the whole-shop pass is the one
            # partition too big to finish in a single run. Left at the end it is
            # not even started until the categories are nearly done, which
            # stretches the cycle from 7 daily runs to 15 — halving how often a
            # product is re-checked, for no extra work.
            keys.insert(0, "")
        return keys or [""]

    async def fetch_page(self, partition: str, page: int) -> Page:
        # /shop/category/<slug> pages exactly like /shop does.
        url = f"{self.base_url}/shop/category/{partition}" if partition else f"{self.base_url}/shop"
        async with make_client() as client:
            html = await get_text(client, url, {"page": page})
        cards = HTMLParser(html).css(".oe_product")

        items = [item for item in (self._to_raw(c, partition) for c in cards) if item is not None]
        ids = {item.external_id for item in items}

        # Odoo serves the last page forever instead of going empty, so "same ids
        # as the previous page" is the real end signal. Tracked per page rather
        # than as a run-wide seen-set because pages are now fetched one call at a
        # time; duplicates that slip through are harmless (upserts are idempotent).
        repeated = bool(ids) and ids == self._prev_page_ids.get(partition)
        self._prev_page_ids[partition] = ids

        return Page(items, has_more=bool(items) and not repeated)

    def source_categories(self, raw: RawItem) -> list[str]:
        category = (raw.raw or {}).get("category")
        return [category] if category else []

    def knows_category(self, raw: RawItem) -> bool:
        """False for the whole-shop pass, which carries no category at all.

        It exists only so products filed under no category are still seen; it
        must not clear the category a category partition just established.
        """
        if not self.categories:
            return True  # no crosswalk: the /shop sweep is the only pass there is
        return bool((raw.raw or {}).get("category"))

    def category_for(self, raw: RawItem) -> tuple[str, str] | None:
        category = (raw.raw or {}).get("category")
        if not category:
            return None
        return self._folded_categories.get(normalize_category_name(category))

    def _to_raw(self, card, partition: str = "") -> RawItem | None:
        link = card.css_first("a[href^='/shop/']")
        href = link.attributes.get("href") if link else None
        if not href:
            return None
        match = _ID_RE.search(href.split("?")[0])
        external_id = match.group(1) if match else href

        # Prefer schema.org microdata (stabler than theme classes); fall back to
        # the visible theme markup if a card ever omits it.
        name_el = card.css_first('[itemprop="name"]') or card.css_first(
            ".o_wsale_products_item_title"
        )
        title = name_el.text(strip=True) if name_el else (link.text(strip=True) if link else None)

        # itemprop=price is a clean machine value ("1695.0"); .oe_currency_value
        # is locale-formatted ("1,695.00"). Take the microdata when present.
        price_el = card.css_first('[itemprop="price"]') or card.css_first(".oe_currency_value")
        price_text = price_el.text(strip=True) if price_el else None

        currency_el = card.css_first('[itemprop="priceCurrency"]')
        currency = currency_el.text(strip=True) if currency_el else "EGP"

        # The card's subtitle (Odoo's "sales description"). Its lines are <br>s,
        # and reading it with text(strip=True) ran them together: "Switching
        # Mode Power Supply1 YEAR Warranty".
        desc_el = card.css_first('[itemprop="description"]')
        description = html_to_text(desc_el.html) if desc_el else None
        lines = description.split("\n") if description else []

        img = card.css_first("img")
        img_src = (img.attributes.get("src") or img.attributes.get("data-src")) if img else None
        images = [urljoin(self.base_url, img_src)] if img_src else []

        raw: dict = {"platform": "odoo", "category": partition or None}
        if sku := _internal_reference(img):
            raw["sku"] = sku
        if compare_at := _compare_at(card, price_text):
            raw["compare_at_price"] = compare_at
        if warranty := next((m.group(0) for m in map(_WARRANTY_RE.search, lines) if m), None):
            raw["warranty"] = warranty

        return RawItem(
            source=self.source_id,
            external_id=external_id,
            # Without the query: the card links carry "?page=N" (or the category
            # being browsed), which changes as the catalogue shifts and is not
            # part of the product's address.
            source_url=urljoin(self.base_url, href.split("?")[0]),
            title=title,
            description=description,
            brand=_brand(lines),
            price_text=price_text,
            currency=currency,
            availability_text=self._stock_hint(card),
            category_hint=partition or None,
            images=images,
            raw=raw,
        )

    @staticmethod
    def _stock_hint(card) -> str:
        """Read the availability ribbon. No ribbon => in stock (Odoo only marks
        the exceptions). Shops seen so far use two 'unavailable' states: out of stock and
        'Arriving Soon' (incoming/backorder)."""
        ribbon = card.css_first(".o_ribbon")
        text = ribbon.text(strip=True).lower() if ribbon else ""
        if "out of stock" in text or "sold out" in text:
            return "out of stock"
        if "arriving soon" in text:
            return "arriving soon"
        return "in stock"


def _internal_reference(img) -> str | None:
    """The shop's own product code, from the image alt "[CODE] Name".

    A private catalogue code like every supplier SKU — kept for reference, never
    for grouping (see CLAUDE.md: across suppliers they coincide by accident).
    """
    alt = (img.attributes.get("alt") or "") if img else ""
    match = _REFERENCE_RE.match(alt)
    return match.group(1).strip() if match else None


def _compare_at(card, price_text: str | None) -> str | None:
    """The struck-through list price Odoo shows beside a reduced one."""
    was_el = card.css_first("del .oe_currency_value")
    was = parse_price(was_el.text(strip=True)) if was_el else None
    now = parse_price(price_text)
    if was is None or (now is not None and was <= now):
        return None
    return str(was)


def _brand(lines: list[str]) -> str | None:
    for line in lines:
        for pattern in _BRAND_LINES:
            match = pattern.match(line.strip())
            if match:
                brand = match.group("b").strip()
                if brand.lower() not in _NOT_A_BRAND:
                    return brand
    return None
