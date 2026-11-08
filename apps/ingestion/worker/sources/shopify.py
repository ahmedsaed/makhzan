"""Shopify adapter via the public `/products.json` feed.

Returns structured JSON (title, variants with price + availability, images,
vendor, product_type), so no HTML scraping is needed.

The listing's price and stock are the first variant's. The other variants, the
options they choose between, the specs, datasheets and YouTube/Vimeo videos in
`body_html`, the publication date and the compare-at price all arrive in the
same feed page, so they are kept too — in `attributes`, since none of them
changes what the listing costs. Shopify prices are already in major units
("4950.00"). `updated_at` is not kept: one shop stamps every product with the
time of the request, so it says nothing about change.

What the feed does NOT carry is stock quantity: `inventory_quantity` is only in
`/products/<handle>.json` and the product page, one request per product.

Nor does it say which **collections** a product is in. That takes one request per
collection (`/collections/<handle>/products.json`), so it is a per-source
switch, off by default. See `ShopifyAdapter.collections`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from urllib.parse import quote, urlsplit

from makhzan_schemas.contracts import RawItem
from makhzan_schemas.domains.crosswalks import fold_crosswalk, normalize_category_name
from makhzan_schemas.enums import SourceType

from worker.http import get_json, make_client
from worker.normalize import parse_price
from worker.richtext import documents_from_html, html_to_text, specs_from_html, videos_from_html
from worker.robots import DisallowedByRobots, polite_pause
from worker.sources.base import Page, SourceAdapter, SupplierInfo

log = logging.getLogger(__name__)

PER_PAGE = 250  # Shopify max
MAX_PAGES = 200
#: Collections every Shopify shop has that say nothing about what a product is:
#: the home page's picks and the catalogue itself.
_MERCHANDISING_COLLECTIONS = ("frontpage", "all")

#: What Shopify calls the one option of a product that has no options.
_NO_OPTION = ("title", "default title")
#: Values a spec table puts under "Brand" that name no brand.
_NOT_A_BRAND = {"generic", "oem", "no brand", "none", "n/a", "na", "original", "unbranded"}
#: Host labels that say nothing about whose shop it is.
_HOST_NOISE = {"www", "store", "shop", "com", "eg", "net", "org", "co", "myshopify"}


def _fold(text: str | None) -> str:
    return re.sub(r"[^0-9a-z]", "", (text or "").lower())


class ShopifyAdapter(SourceAdapter):
    source_type = SourceType.SCRAPED

    def __init__(
        self,
        source_id: str,
        base_url: str,
        supplier: SupplierInfo,
        *,
        currency: str = "EGP",
        enabled: bool = True,
        polite_delay: float | None = None,
        max_pages_per_run: int | None = None,
        max_partitions_per_run: int | None = None,
        categories: dict[str, tuple[str, str]] | None = None,
        prefer: Sequence[str] = (),
        collections: bool = False,
        skip_collections: Sequence[str] = (),
    ) -> None:
        self.source_id = source_id
        self.base_url = base_url.rstrip("/")
        self.supplier = supplier
        self.currency = currency
        self.enabled = enabled
        #: Optional crosswalk from this shop's own `product_type` (and, with
        #: `collections` on, its collection titles) to (domain, taxonomy leaf).
        self.categories = categories or {}
        # product_type is free text and shops spell it inconsistently ("Sensor"
        # and "sensor", "NFC" and "nfc"), so lookups go through the shared
        # normalizer rather than a bare .lower().
        self._categories_folded = fold_crosswalk(self.categories)
        #: Which of two mapped names wins, ahead of the order they come in (the
        #: crosswalk's `prefer`). Without collections a product has one
        #: product_type and nothing to rank, so a preference is a mistake.
        if prefer and not collections:
            raise TypeError("prefer ranks collections; it needs collections = true")
        self._preference = {normalize_category_name(name): i for i, name in enumerate(prefer)}
        #: Read which collections each product is in. Off by default: it costs
        #: one request per collection on top of the feed (a shop with ~150
        #: collections and ~1,300 products goes from 7 requests a sweep to ~155).
        #:
        #: Collections are a tag cloud, not a taxonomy — "Frontpage", "New
        #: Products" and "Object Detection" side by side, ~2.7 per product — so
        #: they are recorded as `collections`, offered to the crosswalk after
        #: product_type, and never make the source authoritative. Map only the
        #: ones whose contents match their name.
        self.collections = collections
        #: Collection handles not worth a request: merchandising ("new-products"),
        #: not categories. Shopify's own "frontpage" and "all" are always skipped.
        self.skip_collections = {*_MERCHANDISING_COLLECTIONS, *skip_collections}
        #: product id -> collection titles, read once per adapter (i.e. per run).
        self._memberships: dict[str, list[str]] | None = None
        #: Requests made for memberships, which happen inside `fetch_page`.
        self._collection_requests = 0
        if polite_delay is not None:
            self.polite_delay = polite_delay
        if max_pages_per_run is not None:
            if collections:
                # Memberships last one run. Spread over one page a day, every run
                # would re-read every collection to label one page of products:
                # the cost of a sweep, multiplied by its page count.
                raise ValueError(
                    "collections = true needs the whole feed in one run; "
                    "drop max_pages_per_run for this source"
                )
            self.max_pages_per_run = max_pages_per_run
        if max_partitions_per_run is not None:
            self.max_partitions_per_run = max_partitions_per_run

    def source_categories(self, raw: RawItem) -> list[str]:
        """The shop's own `product_type` and collections, so drift and the
        "Services" skip see them."""
        attrs = raw.raw or {}
        product_type = (attrs.get("product_type") or "").strip()
        return ([product_type] if product_type else []) + list(attrs.get("collections") or [])

    def category_for(self, raw: RawItem) -> tuple[str, str] | None:
        """Resolve a listing's category from the shop's `product_type`, then its
        collections.

        product_type is one value per product, so on its own there is no "which
        tag wins" question — only the spelling, which the folded table handles.
        Collections add one: product_type comes first, collections follow in
        title order, and the crosswalk's `prefer` outranks both.
        """
        if not self._categories_folded:
            return None
        best: tuple[int, tuple[str, str]] | None = None
        for position, name in enumerate(self.source_categories(raw)):
            key = normalize_category_name(name)
            mapped = self._categories_folded.get(key) if key else None
            if mapped is None:
                continue
            rank = self._preference.get(key, len(self._preference) + position)
            if best is None or rank < best[0]:
                best = (rank, mapped)
        return best[1] if best else None

    async def fetch_page(self, partition: str, page: int) -> Page:
        url = f"{self.base_url}/products.json"
        async with make_client() as client:
            if self.collections and self._memberships is None:
                self._memberships = await self._read_memberships(client)
                await asyncio.sleep(await polite_pause(self.base_url, self.polite_delay))
            data = await get_json(client, url, {"limit": PER_PAGE, "page": page})
        products = data.get("products", [])
        # products.json simply runs dry — an empty array is the end of the feed.
        return Page([self._to_raw(p) for p in products], has_more=bool(products))

    async def _paged(self, client, path: str, key: str):
        """Every row of a paged Shopify JSON list, paced like the pipeline paces pages.

        Each request goes through `get_json`, so robots.txt is checked against
        the exact URL — the handles in these paths come from the shop, not from
        us, and a rule like `Disallow: /collections/*+*` is about such paths.
        """
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                await asyncio.sleep(await polite_pause(self.base_url, self.polite_delay))
            # Counted before it is sent: a request that failed still reached the host.
            self._collection_requests += 1
            data = await get_json(
                client, f"{self.base_url}{path}", {"limit": PER_PAGE, "page": page}
            )
            rows = data.get(key) or []
            for row in rows:
                yield row
            # A short page is the last: no need to ask for the empty one after it.
            if len(rows) < PER_PAGE:
                return

    def extra_requests(self) -> dict[str, int]:
        return {"collections": self._collection_requests} if self._collection_requests else {}

    async def _read_memberships(self, client) -> dict[str, list[str]]:
        """product id -> titles of the collections it is in.

        One request for the collection list, then one per collection (each holds
        under 250 products at the shops seen so far, so one page). Empty and
        merchandising collections are not requested, and neither is one that
        robots.txt disallows. Any other failure fails the page: a partial map
        would quietly drop categories for whatever it missed.
        """
        found: list[dict] = [
            c async for c in self._paged(client, "/collections.json", "collections")
        ]
        wanted = sorted(
            (c for c in found if c.get("handle") and c.get("title")),
            key=lambda c: c["handle"],
        )
        memberships: dict[str, set[str]] = defaultdict(set)
        for collection in wanted:
            handle, title = collection["handle"], str(collection["title"]).strip()
            if handle in self.skip_collections or collection.get("products_count") == 0:
                continue
            await asyncio.sleep(await polite_pause(self.base_url, self.polite_delay))
            path = f"/collections/{quote(handle, safe='')}/products.json"
            try:
                async for product in self._paged(client, path, "products"):
                    if product.get("id") is not None:
                        memberships[str(product["id"])].add(title)
            except DisallowedByRobots as exc:
                log.info("%s: skipping collection %r: %s", self.source_id, handle, exc)
        return {pid: sorted(titles, key=str.lower) for pid, titles in memberships.items()}

    def is_own_name(self, vendor: str | None) -> bool:
        """Whether a `vendor` is the shop naming itself rather than a maker.

        Shopify fills `vendor` with the store's name unless the merchant types a
        brand, and many shops never do: one had every one of its 1,265 products
        "by" itself, some as "<Shop> (<other trading name>)". Published as a
        brand, that is searchable — every listing matches the shop's own name.
        """
        folded = _fold(vendor)
        if not folded:
            return True
        own = {_fold(self.supplier.name)}
        host = urlsplit(self.base_url).hostname or ""
        own.update(_fold(label) for label in host.split(".") if label not in _HOST_NOISE)
        own.discard("")
        # The reverse direction ("Acme" for "Acme Electronics") only for a vendor
        # long enough to mean it: "TI" is a maker, not the start of "Tiny Shop".
        return any(
            folded.startswith(name) or (len(folded) >= 4 and name.startswith(folded))
            for name in own
        )

    def _brand(self, vendor: str | None, specs: dict[str, str]) -> str | None:
        if vendor and not self.is_own_name(vendor):
            return vendor
        # Failing that, the shop's own spec table is the next best word on it.
        for key, value in specs.items():
            if key.lower() in ("brand", "manufacturer"):
                usable = value.lower() not in _NOT_A_BRAND and len(value) <= 40
                return value if usable and not self.is_own_name(value) else None
        return None

    def _to_raw(self, p: dict) -> RawItem:
        variants = p.get("variants") or []
        variant = variants[0] if variants else {}
        images = [img["src"] for img in p.get("images", []) if img.get("src")]
        vendor = (p.get("vendor") or "").strip() or None
        body = p.get("body_html")
        specs = specs_from_html(body)

        raw: dict = {
            "platform": "shopify",
            "sku": variant.get("sku"),
            "variant_count": len(variants),
            "product_type": p.get("product_type") or None,
        }
        if specs:
            raw["specs"] = specs
        if documents := documents_from_html(body, self.base_url):
            raw["documents"] = documents
        if videos := videos_from_html(body):
            raw["videos"] = videos
        if compare_at := _compare_at(variant):
            raw["compare_at_price"] = compare_at
        if options := _options(p):
            raw["options"] = options
        if len(variants) > 1:
            raw["variants"] = [_variant(v) for v in variants]
        # When the shop published it — a real date, unlike `updated_at`, which
        # at least one shop stamps with the time of the request on every product.
        if published := _iso_date(p.get("published_at")):
            raw["published_at"] = published
        if self._memberships is not None:
            if titles := self._memberships.get(str(p.get("id"))):
                raw["collections"] = titles

        return RawItem(
            source=self.source_id,
            external_id=str(p["id"]),
            source_url=f"{self.base_url}/products/{p.get('handle')}" if p.get("handle") else None,
            title=p.get("title"),
            description=html_to_text(body),
            brand=self._brand(vendor, specs),
            price_text=variant.get("price"),
            currency=self.currency,
            availability_text="in stock" if variant.get("available") else "out of stock",
            category_hint=(p.get("product_type") or None),
            images=images,
            raw=raw,
        )


def _compare_at(variant: dict) -> str | None:
    """The struck-through "was" price, when it is above the price charged.

    A compare-at left equal to (or below) the price after a sale ends is no
    discount, and is not kept.
    """
    was, now = parse_price(variant.get("compare_at_price")), parse_price(variant.get("price"))
    if was is None or (now is not None and was <= now):
        return None
    return str(was)


def _options(p: dict) -> dict[str, list[str]]:
    """What a buyer chooses between ("Color": ["Red", "Black"]), by option name."""
    options: dict[str, list[str]] = {}
    for option in p.get("options") or []:
        name = (option.get("name") or "").strip()
        values = [str(v).strip() for v in option.get("values") or [] if str(v).strip()]
        if not name or not values:
            continue
        if name.lower() == _NO_OPTION[0] and [v.lower() for v in values] == [_NO_OPTION[1]]:
            continue
        options[name] = values
    return options


def _variant(v: dict) -> dict:
    """One purchasable variant, in the shared shape: {title, price, in_stock, sku?}.

    No stock quantity: the feed does not carry it. No compare-at price either —
    the site shows current prices only (DESIGN.md C3).
    """
    out = {
        "title": v.get("title"),
        "price": v.get("price"),
        "in_stock": bool(v.get("available")),
        "sku": v.get("sku") or None,
    }
    return {k: val for k, val in out.items() if val is not None}


def _iso_date(value: str | None) -> str | None:
    """The calendar date of an ISO timestamp, as the shop's own clock has it.

    `2026-10-31T01:30:00+02:00` is the 31st, though in UTC it is still the 30th.
    """
    try:
        return datetime.fromisoformat(value).date().isoformat() if value else None
    except (TypeError, ValueError):
        return None
