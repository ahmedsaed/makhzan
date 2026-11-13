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
for the brand ("Acme Brand") or the warranty, and its image URL ends in a token
that changes when the product is edited. All of it is read here. The full
description, the photo gallery and datasheet links are only on the product page —
one request per product — so they are read by the details stage
(worker/details.py), a few a run, when that token says the product changed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from html import unescape as html_unescape
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from makhzan_schemas.contracts import RawItem
from makhzan_schemas.domains.crosswalks import fold_crosswalk, normalize_category_name
from makhzan_schemas.enums import SourceType
from selectolax.parser import HTMLParser

from worker.http import get_text, make_client
from worker.normalize import parse_price
from worker.robots import DisallowedByRobots
from worker.richtext import (
    documents_from_html,
    html_to_text,
    maker_from_specs,
    section_links,
    specs_from_html,
    videos_from_html,
)
from worker.sources.base import (
    TOKEN_MODIFIED,
    Confirmation,
    DetailsSettings,
    Page,
    SourceAdapter,
    SupplierInfo,
)
from worker.sources.short_page import SHADOW, ShortPageEnd

DETAILS_LABEL = "details"
#: The `stats.requests` label of the requests that confirm archive candidates.
CONFIRM_LABEL = "confirm"
#: Product pages read a run to confirm candidates the sitemap held (T12).
CONFIRM_PAGES = 20
#: A sitemap index naming more files than this is not followed.
MAX_SITEMAP_FILES = 5
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
#: More photos than this on one product is a gallery, not a product's pictures.
_MAX_GALLERY = 12
_MAX_DOCUMENTS = 10
_GALLERY_IMAGE = re.compile(r"/web/image/product\.image/(\d+)/")

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
        details: dict | None = None,
        end_on_short_page: str = SHADOW,
        sitemap_veto: bool = True,
    ) -> None:
        self.source_id = source_id
        #: End a partition on the page whose pager says it is the last, instead
        #: of fetching the repeat Odoo serves after it. Shadow until proven:
        #: see worker/sources/short_page.py.
        self.short_page = ShortPageEnd(end_on_short_page)
        #: Before archiving, hold any candidate the shop's sitemap still lists
        #: and read its product page (T12). The sitemap never counts as "seen".
        self.sitemap_veto = sitemap_veto
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
        #: Product pages, read a few a run and only when the card's token moved.
        self.details = DetailsSettings.from_config(details)
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

    def probe_url(self) -> str | None:
        partition = self.partitions()[0]
        url = f"{self.base_url}/shop/category/{partition}" if partition else f"{self.base_url}/shop"
        return str(httpx.URL(url, params={"page": 1}))

    async def fetch_page(self, partition: str, page: int) -> Page:
        # /shop/category/<slug> pages exactly like /shop does.
        url = f"{self.base_url}/shop/category/{partition}" if partition else f"{self.base_url}/shop"
        async with make_client() as client:
            html = await get_text(client, url, {"page": page})
        tree = HTMLParser(html)
        cards = tree.css(".oe_product")

        items = [item for item in (self._to_raw(c, partition) for c in cards) if item is not None]
        ids = {item.external_id for item in items}

        # Odoo serves the last page forever instead of going empty, so "same ids
        # as the previous page" is the real end signal. Tracked per page rather
        # than as a run-wide seen-set because pages are now fetched one call at a
        # time; duplicates that slip through are harmless (upserts are idempotent).
        repeated = bool(ids) and ids == self._prev_page_ids.get(partition)
        self._prev_page_ids[partition] = ids

        # The pager says so one request earlier (T1): the repeat costs a
        # request per partition, about a third of this shop's cycle.
        stop = self.short_page.page(
            partition,
            page,
            ids,
            short=_pager_says_last(tree, page),
            end=not items or repeated,
        )
        return Page(items, has_more=bool(items) and not repeated and not stop)

    async def confirm_listed(self, listings, fetcher) -> Confirmation | None:
        """The sitemap as a veto on archiving, then the product page as the proof (T12).

        One request for `/sitemap.xml`, which lists every published product. A
        candidate it does not list is archived as before. One it does list is
        held: the sweep missed it, but the shop still publishes it. Its
        product page is read, at most `CONFIRM_PAGES` a run, and a page that is
        the product keeps the listing (`last_seen_at` only: no price is read).
        A page that is gone (404/410, or not this product) archives it.

        Sitemap presence itself never counts as seen: a sitemap can lag the
        shop, and "seen" would then outlive the product.
        """
        if not self.sitemap_veto:
            return None
        try:
            listed = await self._sitemap_ids(fetcher)
        except DisallowedByRobots:
            return None  # the shop does not want it read: archive as before
        out = Confirmation(notes={"via": "sitemap", "sitemap_products": len(listed)})
        held = []
        for row in listings:
            if row.external_id in listed:
                held.append(row)
            else:
                out.absent.add(row.external_id)
        out.notes["held_by_sitemap"] = len(held)
        for row in held[:CONFIRM_PAGES]:
            try:
                url = _product_url(row.source_url, self.base_url)
            except ValueError:
                out.absent.add(row.external_id)  # no page to ask: as before
                continue
            try:
                response = await fetcher.get(CONFIRM_LABEL, url)
            except DisallowedByRobots:
                out.absent.add(row.external_id)  # not ours to read: as before
                continue
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 410):
                    out.absent.add(row.external_id)
                    continue
                raise
            if _is_product_page(response, row.external_id):
                out.seen.add(row.external_id)
            else:
                out.absent.add(row.external_id)
        return out

    async def _sitemap_ids(self, fetcher) -> set[str]:
        """Product ids in the shop's sitemap (following an index a few files deep)."""
        response = await fetcher.get(CONFIRM_LABEL, f"{self.base_url}/sitemap.xml")
        text = response.text
        locs = _LOC.findall(text)
        if "<sitemapindex" in text:
            if len(locs) > MAX_SITEMAP_FILES:
                raise ValueError(f"sitemap index of {len(locs)} files; not read")
            children = locs
            locs = []
            for child in children:
                if urlsplit(html_unescape(child)).netloc != urlsplit(self.base_url).netloc:
                    continue
                locs += _LOC.findall((await fetcher.get(CONFIRM_LABEL, html_unescape(child))).text)
        ids = set()
        for loc in locs:
            path = urlsplit(html_unescape(loc.strip())).path.rstrip("/")
            if not path.startswith("/shop/") or path.startswith(("/shop/category/", "/shop/page/")):
                continue
            if match := _ID_RE.search(path):
                ids.add(match.group(1))
        if not ids:
            # A sitemap with no products is not evidence that none exist.
            raise ValueError("the sitemap lists no product pages")
        return ids

    def source_categories(self, raw: RawItem) -> list[str]:
        category = (raw.raw or {}).get("category")
        return [category] if category else []

    #: The card image's `?unique=` is Odoo's own last-write stamp of the product
    #: template, so it moves on any edit — the description's included.
    token_kind = TOKEN_MODIFIED

    def change_token(self, raw: RawItem) -> str | None:
        return (raw.raw or {}).get("change_token")

    async def fetch_details(self, listing, fetcher) -> dict:
        """The product page: long description, its specs and documents, the gallery.

        Not read: the barcode (the manufacturer part number on most products),
        which is only in `POST /website_sale/get_combination_info`. That is a
        second request per product, and the page never shows the barcode — it
        reaches the browser only for the shop's analytics, beside a stock count
        the shop chose not to display.
        """
        url = _product_url(listing.source_url, self.base_url)
        response = await fetcher.get(DETAILS_LABEL, url)
        return parse_product_page(response.text, self.base_url)

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
        if token := _change_token(img_src):
            raw["change_token"] = token
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


def _pager_says_last(tree: HTMLParser, page: int) -> bool:
    """Whether the listing page's pager says this is the last page.

    Odoo's pager ends on a "next" item, disabled on the last page; it leaves the
    pager out altogether when there is only one page. With no pager on a later
    page there is no telling, so that is not read as the last.
    """
    pager = tree.css_first("ul.pagination")
    if pager is None:
        return page == 1
    items = pager.css("li")
    return bool(items) and "disabled" in (items[-1].attributes.get("class") or "").split()


def _is_product_page(response: httpx.Response, external_id: str | None) -> bool:
    """Whether a confirmation read landed on this product's own page."""
    match = _ID_RE.search(response.url.path.rstrip("/"))
    if match is None or match.group(1) != external_id:
        return False  # redirected elsewhere: the shop's way of saying it is gone
    return HTMLParser(response.text).css_first("#product_detail") is not None


def _internal_reference(img) -> str | None:
    """The shop's own product code, from the image alt "[CODE] Name".

    A private catalogue code like every supplier SKU — kept for reference, never
    for grouping (see CLAUDE.md: across suppliers they coincide by accident).
    """
    alt = (img.attributes.get("alt") or "") if img else ""
    match = _REFERENCE_RE.match(alt)
    return match.group(1).strip() if match else None


def _change_token(img_src: str | None) -> str | None:
    """The `?unique=` token on the card's product image, kept but never shown.

    Odoo derives it from the product template's last write, so it moves when the
    shop edits the product (a price, a description) and stays put otherwise —
    stock moves do not write the template, but the card's ribbon covers stock.
    It is what lets a later detail fetch visit only the products that changed,
    instead of every product page every cycle. An opaque token, not a date.
    """
    if not img_src or "/product.template/" not in img_src:
        return None  # the shop's logo or a placeholder, not the product's photo
    values = parse_qs(urlsplit(img_src).query).get("unique") or []
    token = values[0].strip() if values else ""
    return token if 0 < len(token) <= 64 else None


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


# ---------------------------------------------------------------------- #
# The product page (the details stage)
# ---------------------------------------------------------------------- #


def _product_url(source_url: str | None, base_url: str) -> str:
    """The product page to read: the stored URL, on the shop's own host, no query.

    Card links carry `?category=N` while a category is browsed, which robots.txt
    forbids; the stored URL is already without it, and this makes sure.
    """
    if not source_url:
        raise ValueError("the listing has no product URL")
    parts, shop = urlsplit(urljoin(base_url + "/", source_url)), urlsplit(base_url)
    if (parts.scheme, parts.netloc) != (shop.scheme, shop.netloc):
        raise ValueError(f"{source_url} is not on {base_url}")
    if not parts.path.startswith("/shop/"):
        raise ValueError(f"{source_url} is not a product page")
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def parse_product_page(page_html: str, base_url: str) -> dict:
    """What an Odoo product page adds to its card.

    - the long description, `#product_full_description` (free HTML), flattened
      to text with its line structure, and the "Name: value" lines and spec
      tables in it read as specs (the shared readers WooCommerce uses);
    - documents: PDFs linked anywhere in it, and every link under a
      "Documents" / "Download" heading — most shops link the maker's page or
      wiki rather than a PDF;
    - videos embedded in the description or the photo carousel;
    - the gallery's extra photos (`product.image`), at the size the page shows;
    - a brand and a manufacturer part number only where the description states
      them in so many words. `itemprop="mpn"` is Odoo's *internal reference*
      (the shop's own code), not a manufacturer's part number, so it is not read.

    Never the stock: microdata says "InStock" on everything, and counts are not
    shown. A page that is not a product page is an error, so the listing is
    retried after a backoff rather than marked read with nothing.
    """
    tree = HTMLParser(page_html)
    description_el = tree.css_first("#product_full_description")
    carousel = tree.css_first("#o-carousel-product")
    if description_el is None and carousel is None and tree.css_first("#product_detail") is None:
        raise ValueError("not an Odoo product page (no description, gallery or detail block)")

    description_html = description_el.html if description_el is not None else None
    out: dict = {}
    if text := html_to_text(description_html):
        out["description"] = text
    specs = specs_from_html(description_html)
    if specs:
        out["specs"] = specs

    documents: list[dict[str, str]] = []
    for doc in documents_from_html(description_html, base_url) + section_links(
        description_html, base_url
    ):
        if all(doc["url"] != known["url"] for known in documents):
            documents.append(doc)
    if documents:
        out["documents"] = documents[:_MAX_DOCUMENTS]

    videos: list[dict[str, str]] = []
    for html in (description_html, carousel.html if carousel is not None else None):
        for video in videos_from_html(html):
            if all(video["url"] != known["url"] for known in videos):
                videos.append(video)
    if videos:
        out["videos"] = videos

    images: list[str] = []
    seen: set[str] = set()
    for img in carousel.css("img") if carousel is not None else []:
        src = img.attributes.get("data-src") or img.attributes.get("src") or ""
        # The extra photos only: the template's own image is the card's photo.
        # Each photo appears twice, as the slide and as its thumbnail below it;
        # the first, the slide, is the larger.
        match = _GALLERY_IMAGE.search(src)
        if match is None or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        images.append(urljoin(base_url + "/", src))
    if images:
        out["images"] = images[:_MAX_GALLERY]

    brand, part = maker_from_specs(specs)
    if brand:
        out["brand"] = brand
    if part:
        out["mfr_part_number"] = part
    return out
