"""Wix Stores adapter, read from the JSON a gallery page embeds for itself.

A Wix site renders on the server and ships the state its widgets start from in
`<script type="application/json" id="wix-warmup-data">`. On a store gallery page
(a category page, in Wix's terms) that state holds the category being shown and
its products: `appsWarmupData[<app>][<widget>].catalog.category
.productsWithMetaData = {list, totalCount}`. Each product carries its name, slug,
price, sale price, SKU, stock status and every image, which is everything a
listing shows except the description. No Wix API is called and no token is read.
The widget key embeds the section id (`TPASection_<id>`), which differs per page,
so the block is found by its shape, not its name.

Platform behaviour handled here, none of it specific to one shop:
  - `?page=N` is the "load more" state: it lists everything up to page N, not
    the N-th slice. Page 2 of a 39-product gallery repeats the first 30 and adds
    9. Paging stops once the list reaches `totalCount`, and a page emits only the
    products the pages before it in that gallery did not, so nothing is counted
    twice.
  - `comparePrice` is the *sale* price, not an old one: a product on offer has
    `price` 1050 and `comparePrice` 950, and the buyer pays 950 (the product
    page's schema.org Offer agrees). Zero means not on sale.
  - Images are served through a resizing transform
    (`.../media/<file>/v1/fit/w_500,...`); the file without it is the original.
  - Stock counts (`inventory.quantity`) are kept per variant and read 0 or even
    negative in the gallery while the product page says 38, so only the in/out
    status is used. Options may promise sizes no variant exists for, so they are
    not read as variants either.
  - The SKU is the shop's internal code. It is kept as an attribute and never
    offered as a part number.

**Galleries are configured, and some are not categories.** A shop's gallery pages
are whatever its owner built: one per product type, but also merchandising pages
("New Arrival") whose membership says nothing about what a product is, and which
may be the only page some products are on. Both are swept. A type gallery's name
is the listing's source category (read from the page, so a rename shows up as
crosswalk drift); a merchandising gallery (`tag_galleries`) carries none, and its
pass reports that it does not know the category, so it never clears one a type
gallery set (see `SourceAdapter.knows_category`).

**The products sitemap is the whole-catalogue check.** Galleries need not cover
the catalogue, and a product on no gallery would go unseen and be archived at
the end of the cycle. `/store-products-sitemap.xml` lists every product URL, but
nothing else that matters: no id, price or stock. So its pass creates nothing — a
listing built from it would be priceless and stockless and look real — and
instead compares its slugs with the ones the galleries showed in this run, and
reports any product they missed in the run's stats (`source_report`). The fix
for one is configuration (add the gallery it is on), not a guess. It runs last,
after every gallery, and only compares when every gallery was swept to its end
in the same run; otherwise it says it could not.

**Product pages are the details stage's** (worker/details.py, `details = {...}`):
the description, "additional info" sections such as print settings, and file
links, one request per product, a few a run. The gallery JSON carries no
per-product update time, so the change token is a hash of the card's own fields
(TOKEN_CARD_HASH): it moves when the name, price, sale price, SKU, ribbon, slug,
options or photos do, and not when only the description is edited — the
age-based refresh catches that. Stock is left out of it: a spool selling out
changes nothing on its page worth a request.

Not read: the shop's Downloads page. Its datasheets are per material, not per
product, and nothing on it ties a file to a product except a person reading
the file name.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Sequence
from urllib.parse import unquote, urlsplit

from makhzan_schemas.contracts import RawItem
from makhzan_schemas.domains.crosswalks import fold_crosswalk, normalize_category_name
from makhzan_schemas.enums import SourceType
from selectolax.parser import HTMLParser

from worker.http import get_text, make_client
from worker.richtext import documents_from_html, html_to_text, specs_from_html, videos_from_html
from worker.sources.base import (
    TOKEN_CARD_HASH,
    DetailsSettings,
    Page,
    SourceAdapter,
    SupplierInfo,
    card_hash,
)

log = logging.getLogger(__name__)

#: Partition key of the whole-catalogue pass. Gallery keys are paths ("/shop-2"),
#: so a key without a leading slash cannot collide with one.
SITEMAP_PARTITION = "sitemap"
DEFAULT_SITEMAP = "/store-products-sitemap.xml"
#: Where Wix serves a product, by its slug (`urlPart`).
PRODUCT_PATH = "/product-page/"
WIXSTATIC_MEDIA = "https://static.wixstatic.com/media/"
#: A gallery of more than this many "load more" pages is not a shop we know.
MAX_PAGES = 100

_TOKEN = re.compile(r"[0-9a-z]+")
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_MEDIA_FILE = re.compile(r"^https://static\.wixstatic\.com/media/([^/?#]+)")


class WixStoresAdapter(SourceAdapter):
    source_type = SourceType.SCRAPED

    def __init__(
        self,
        source_id: str,
        base_url: str,
        supplier: SupplierInfo,
        *,
        galleries: Sequence[str] = (),
        tag_galleries: Sequence[str] = (),
        sitemap: str | None = DEFAULT_SITEMAP,
        brand: str | None = None,
        currency: str = "EGP",
        enabled: bool = True,
        polite_delay: float | None = None,
        max_pages_per_run: int | None = None,
        max_partitions_per_run: int | None = None,
        categories: dict[str, tuple[str, str]] | None = None,
        details: dict | None = None,
    ) -> None:
        self.source_id = source_id
        self.base_url = base_url.rstrip("/")
        self.supplier = supplier
        self.enabled = enabled
        #: Gallery pages that each show one product type, as paths ("/shop-2").
        self.galleries = tuple(galleries)
        #: Gallery pages that are merchandising, not a type ("New Arrival"):
        #: swept so their products are seen, but they say nothing about category.
        self.tag_galleries = tuple(tag_galleries)
        for path in (*self.galleries, *self.tag_galleries, *([sitemap] if sitemap else [])):
            if not path.startswith("/") or "?" in path or "#" in path:
                # The adapter adds `?page=N` itself, and a query from config
                # could carry what robots.txt forbids (Wix's `?lightbox=`).
                raise ValueError(f"{path!r}: expected a plain path like '/shop'")
        if not self.galleries and not self.tag_galleries:
            raise ValueError("a Wix Stores source needs at least one gallery to sweep")
        overlap = set(self.galleries) & set(self.tag_galleries)
        if overlap:
            raise ValueError(f"listed as both a gallery and a tag gallery: {sorted(overlap)}")
        self.sitemap = sitemap or None
        #: The maker, for a shop that is one: applied when a product names none.
        self.brand = brand
        self.currency = currency
        #: Crosswalk from a type gallery's own name to (domain, leaf).
        self.categories = categories or {}
        self._folded_categories = fold_crosswalk(self.categories)
        # Not authoritative: a product only on a merchandising gallery has no
        # type gallery to say what it is, and its title is the better evidence.
        self.authoritative_categories = False
        #: Product pages, read a few a run (see the module docstring).
        self.details = DetailsSettings.from_config(details)
        if polite_delay is not None:
            self.polite_delay = polite_delay
        if max_pages_per_run is not None:
            self.max_pages_per_run = max_pages_per_run
        if max_partitions_per_run is not None:
            self.max_partitions_per_run = max_partitions_per_run

        # What this run's galleries showed, for the sitemap comparison. Per
        # adapter instance, which the worker builds afresh for every run.
        self._emitted: dict[str, set[str]] = {}
        self._listed: dict[str, int] = {}
        self._complete: set[str] = set()
        self._slugs: set[str] = set()
        self._report: dict = {}

    # ------------------------------------------------------------------ #
    # Partitions
    # ------------------------------------------------------------------ #

    def partitions(self) -> list[str]:
        """Merchandising galleries, then type galleries, then the sitemap check.

        Merchandising first, so that within a run a product on both is last
        written by the pass that knows its category. The sitemap last, because
        it compares against what the galleries showed.
        """
        keys = [*self.tag_galleries, *self.galleries]
        return keys + [SITEMAP_PARTITION] if self.sitemap else keys

    async def fetch_page(self, partition: str, page: int) -> Page:
        if partition == SITEMAP_PARTITION:
            return await self._check_sitemap()
        return await self._fetch_gallery(partition, page)

    async def _fetch_gallery(self, path: str, page: int) -> Page:
        # Page 1 without a query: that is the URL the shop links, and the one a
        # CDN is most likely to have cached.
        async with make_client() as client:
            text = await get_text(
                client, f"{self.base_url}{path}", {"page": page} if page > 1 else None
            )
        category = gallery_category(text)
        products = category["productsWithMetaData"].get("list") or []
        total = category["productsWithMetaData"].get("totalCount")

        emitted = self._emitted.setdefault(path, set())
        is_type_gallery = path in self.galleries
        name = (category.get("name") or "").strip() or None
        items = []
        for product in products:
            raw = self._to_raw(product, name if is_type_gallery else None)
            if raw is None:
                continue
            self._slugs.add(product.get("urlPart") or "")
            if raw.external_id in emitted:
                continue  # the cumulative page repeating what came before
            emitted.add(raw.external_id)
            items.append(raw)

        # The list only ever grows as the page number does. One that did not
        # grow is not going to: stop rather than ask for the same list again.
        # A gallery read short must FAIL, not end: an ended partition lets the
        # cycle complete, and a completed cycle archives every product that was
        # only on the pages we did not reach. A failed one keeps its cursor and
        # is retried, so a change in Wix's paging shows up as errors, not as
        # products quietly disappearing.
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise ValueError(f"{path}: the gallery states no product total ({total!r})")
        before = self._listed.get(path, 0)
        self._listed[path] = len(products)
        short = len(products) < total
        grew = page == 1 or len(products) > before
        if short and not grew:
            raise ValueError(
                f"{path}: paging stopped growing at {len(products)} of {total} products"
            )
        if short and page >= MAX_PAGES:
            raise ValueError(f"{path}: {total} products need more than {MAX_PAGES} pages")
        if not short:
            self._complete.add(path)
        return Page(items, has_more=short)

    async def _check_sitemap(self) -> Page:
        """Compare the products sitemap with what the galleries showed this run.

        Creates nothing: the sitemap has a product's address and one image, but
        no id, price or stock, and a listing built from that would look real
        while saying nothing true about the offer.
        """
        async with make_client() as client:
            text = await get_text(client, f"{self.base_url}{self.sitemap}")
        listed = sitemap_slugs(text)
        report: dict = {"sitemap_products": len(listed)}
        unswept = [p for p in (*self.tag_galleries, *self.galleries) if p not in self._complete]
        if unswept:
            # A gallery swept on an earlier day, or cut short, would make every
            # product on it look missing.
            report["sitemap_not_compared"] = f"galleries not swept to the end this run: {unswept}"
        else:
            missing = sorted(set(listed) - self._slugs)
            if missing:
                report["only_in_sitemap"] = missing[:50]
                report["only_in_sitemap_count"] = len(missing)
                report["warnings"] = [
                    f"{len(missing)} product(s) in the sitemap but on no configured gallery "
                    "(not crawled; archived at the end of the cycle if stored): "
                    + ", ".join(missing[:5])
                ]
                log.warning("%s: %s", self.source_id, report["warnings"][0])
        self._report = report
        return Page([], has_more=False)

    def run_report(self) -> dict:
        return dict(self._report)

    # ------------------------------------------------------------------ #
    # Details
    # ------------------------------------------------------------------ #

    #: No update time in the gallery JSON: a hash of the card, which misses an
    #: edit to the description alone (the age-based refresh is the net for that).
    token_kind = TOKEN_CARD_HASH

    def change_token(self, raw: RawItem) -> str | None:
        return (raw.raw or {}).get("change_token")

    async def fetch_details(self, listing, fetcher) -> dict:
        url = listing.source_url or ""
        if not url.startswith(f"{self.base_url}{PRODUCT_PATH}") or "?" in url:
            raise ValueError(f"{url!r} is not a product page of {self.base_url}")
        response = await fetcher.get("details", url)
        return parse_product_page(response.text, self.base_url)

    # ------------------------------------------------------------------ #
    # Categories
    # ------------------------------------------------------------------ #

    def source_categories(self, raw: RawItem) -> list[str]:
        category = (raw.raw or {}).get("category")
        return [category] if category else []

    def knows_category(self, raw: RawItem) -> bool:
        """True only on a type gallery's pass.

        A merchandising gallery carries no category signal, and must not clear
        the one a type gallery established. A shop configured with no type
        galleries at all has nothing else to establish one, so there every pass
        knows (as Odoo's whole-shop pass does when it is the only one).
        """
        if not self.galleries:
            return True
        return bool((raw.raw or {}).get("category"))

    def category_for(self, raw: RawItem) -> tuple[str, str] | None:
        category = (raw.raw or {}).get("category")
        if not category:
            return None
        return self._folded_categories.get(normalize_category_name(category))

    # ------------------------------------------------------------------ #
    # One product
    # ------------------------------------------------------------------ #

    def _to_raw(self, p: dict, category: str | None) -> RawItem | None:
        product_id = p.get("id")
        slug = p.get("urlPart")
        if not product_id or not slug:
            return None
        media = [m for m in p.get("media") or [] if isinstance(m, dict)]

        price = _number(p.get("price"))
        sale = _number(p.get("comparePrice"))
        # Wix's naming is inverted: `comparePrice` is what the buyer pays.
        selling = sale if sale else price
        raw: dict = {"platform": "wix"}
        if category:
            raw["category"] = category
        if sku := str(p.get("sku") or "").strip():
            raw["sku"] = sku
        if price and selling and price > selling:
            raw["compare_at_price"] = _text(price)
        raw["change_token"] = card_hash(
            {
                "name": p.get("name"),
                "slug": slug,
                "price": p.get("price"),
                "comparePrice": p.get("comparePrice"),
                "sku": p.get("sku"),
                "ribbon": p.get("ribbon"),
                "options": [o.get("key") for o in p.get("options") or [] if isinstance(o, dict)],
                "media": [m.get("url") for m in media],
            }
        )

        brand = p.get("brand")
        return RawItem(
            source=self.source_id,
            # The product id, not the slug: the owner can rename a slug.
            external_id=str(product_id),
            source_url=f"{self.base_url}{PRODUCT_PATH}{slug}",
            title=_title(p.get("name"), media),
            brand=(brand.strip() if isinstance(brand, str) and brand.strip() else self.brand),
            price_text=_text(selling) if selling else None,
            currency=(p.get("currency") or self.currency),
            availability_text="in stock" if _in_stock(p) else "out of stock",
            category_hint=category,
            images=_images(media),
            raw=raw,
        )


# ---------------------------------------------------------------------- #
# Page parsing
# ---------------------------------------------------------------------- #


def warmup_data(page_html: str) -> dict:
    """The JSON a Wix page embeds for its widgets to start from."""
    node = HTMLParser(page_html).css_first("script#wix-warmup-data")
    if node is None:
        raise ValueError("no wix-warmup-data on the page: not a Wix page, or Wix changed it")
    return json.loads(node.text(deep=True) or "{}")


def gallery_category(page_html: str) -> dict:
    """The category a gallery page shows, with its products.

    Found by shape rather than by key: the key names the widget's section id,
    which differs from page to page. A page without one is an error, not an
    empty gallery — reading it as empty would archive the shop.
    """
    found: dict[str, dict] = {}
    apps = warmup_data(page_html).get("appsWarmupData") or {}
    for app in apps.values():
        for widget in (app or {}).values() if isinstance(app, dict) else ():
            catalog = widget.get("catalog") if isinstance(widget, dict) else None
            category = catalog.get("category") if isinstance(catalog, dict) else None
            if isinstance(category, dict) and isinstance(
                category.get("productsWithMetaData"), dict
            ):
                found[str(category.get("id"))] = category
    if not found:
        raise ValueError("no store gallery in the page's warmup data")
    if len(found) > 1:
        raise ValueError(f"more than one store gallery on the page: {sorted(found)}")
    return next(iter(found.values()))


def sitemap_slugs(xml: str) -> list[str]:
    """Product slugs from a Wix products sitemap, in order, once each."""
    slugs: dict[str, None] = {}
    for loc in _LOC.findall(xml):
        path = urlsplit(html.unescape(loc)).path
        if path.startswith(PRODUCT_PATH):
            slug = unquote(path[len(PRODUCT_PATH) :]).strip("/")
            if slug:
                slugs[slug] = None
    return list(slugs)


def page_product(page_html: str) -> dict:
    """The product a Wix product page embeds (`catalog.product`), found by shape."""
    found: list[dict] = []
    apps = warmup_data(page_html).get("appsWarmupData") or {}
    for app in apps.values():
        for widget in (app or {}).values() if isinstance(app, dict) else ():
            catalog = widget.get("catalog") if isinstance(widget, dict) else None
            product = catalog.get("product") if isinstance(catalog, dict) else None
            if isinstance(product, dict) and product.get("id"):
                found.append(product)
    if not found:
        raise ValueError("no store product in the page's warmup data")
    if len({str(p["id"]) for p in found}) > 1:
        raise ValueError("more than one store product on the page")
    return found[0]


_HEADING_LEVELS = range(1, 7)


def _ricos_html(node: object) -> str:
    """Wix's rich text (Ricos: `{"nodes": [...]}`) as plain HTML, for the shared readers.

    Only structure the readers use survives: paragraphs, headings, list items,
    links and file links. Anything else contributes its text.
    """
    if isinstance(node, list):
        return "".join(_ricos_html(n) for n in node)
    if not isinstance(node, dict):
        return ""
    kind = str(node.get("type") or "").upper()
    if kind == "TEXT":
        data = node.get("textData") or {}
        text = html.escape(str(data.get("text") or ""))
        for decoration in data.get("decorations") or []:
            link = ((decoration or {}).get("linkData") or {}).get("link") or {}
            if (decoration or {}).get("type") == "LINK" and link.get("url"):
                text = f'<a href="{html.escape(str(link["url"]))}">{text}</a>'
        return text
    inner = _ricos_html(node.get("nodes") or [])
    if kind == "FILE":
        data = node.get("fileData") or {}
        url = (data.get("src") or {}).get("url")
        name = html.escape(str(data.get("name") or "file"))
        return f'<p><a href="{html.escape(str(url))}">{name}</a></p>' if url else ""
    if kind == "HEADING":
        level = (node.get("headingData") or {}).get("level")
        level = level if level in _HEADING_LEVELS else 3
        return f"<h{level}>{inner}</h{level}>"
    if kind == "PARAGRAPH":
        return f"<p>{inner}</p>"
    if kind == "LIST_ITEM":
        return f"<li>{inner}</li>"
    if kind in ("BULLETED_LIST", "ORDERED_LIST"):
        return f"<ul>{inner}</ul>"
    return inner


def _rich_html(value: object) -> str | None:
    """A Wix rich-text field, whichever way it came: Ricos JSON or an HTML string.

    Catalog V3 product pages ship Ricos *serialised*, as a string holding JSON.
    """
    if isinstance(value, str):
        if value.lstrip().startswith("{"):
            try:
                value = json.loads(value)
            except ValueError:
                return None  # neither Ricos nor HTML: not something to publish
        else:
            return value if value.strip() else None
    if isinstance(value, dict):
        return _ricos_html(value.get("nodes") or []) or None
    return None


#: "Print Temp: 210-230°C, Print Speed: 100-300mm/s" — several specs on one line.
_NEXT_SPEC = re.compile(r"\s*[,;]\s+(?=[^\W\d_][\w .]{0,30}:\s*\S)")


def _one_spec_a_line(page_html: str | None) -> str | None:
    """`page_html` with a line of several "Name: value" pairs split into one each."""
    text = html_to_text(page_html)
    if not text:
        return None
    lines = [part for line in text.split("\n") for part in _NEXT_SPEC.split(line) if part]
    return "".join(f"<p>{html.escape(line)}</p>" for line in lines)


def _json_ld_description(page_html: str) -> str | None:
    for node in HTMLParser(page_html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text(deep=True) or "null")
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Product":
                text = item.get("description")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return None


def parse_product_page(page_html: str, base_url: str) -> dict:
    """What a Wix product page adds to its gallery card.

    The description, then each "additional info" section ("Print Settings",
    "Shipping") under its own title; specs from their "Name: value" lines, a
    line holding several of them split first; links to files (PDFs) and videos
    in any of them. The schema.org description stands in when the embedded one
    is empty. Never the stock count: it is per variant and often wrong in the
    page's own data.
    """
    product = page_product(page_html)
    parts: list[str] = []
    if body := _rich_html(product.get("description")):
        parts.append(body)
    sections = next(
        (
            product[key]
            for key in ("additionalInfo", "additionalInfoSections", "infoSections")
            if isinstance(product.get(key), list)
        ),
        [],
    )
    for section in sections:
        if not isinstance(section, dict):
            continue
        body = _rich_html(section.get("description"))
        if not body:
            continue
        title = str(section.get("title") or "").strip()
        parts.append((f"<h3>{html.escape(title)}</h3>" if title else "") + body)
    rich = "".join(parts) or None

    out: dict = {}
    text = html_to_text(rich) or _json_ld_description(page_html)
    if text:
        out["description"] = text
    if specs := specs_from_html(_one_spec_a_line(rich)):
        out["specs"] = specs
    if documents := documents_from_html(rich, base_url):
        out["documents"] = documents
    if videos := videos_from_html(rich):
        out["videos"] = videos
    brand = product.get("brand")
    if isinstance(brand, dict):  # catalog V3 names it as an object
        brand = brand.get("name")
    if isinstance(brand, str) and brand.strip():
        out["brand"] = brand.strip()
    return out


def _tokens(text: str | None) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def _title(name: str | None, media: list[dict]) -> str | None:
    """The product's name, or its first image's alt text when that says more.

    Shops name products tersely ("Black PLA +", "ASA") and write the full
    description in the alt text ("<Brand> Black PLA+ 3D printer filament").
    Category inference needs the product type in the title — a bare "ASA" matches
    nothing. The alt text is used only when it contains every word of the name,
    so a stock-photo caption or a file name never replaces it.
    """
    name = " ".join((name or "").split()) or None
    alt = " ".join(str((media[0] if media else {}).get("altText") or "").split())
    if alt and len(alt) <= 200 and _tokens(name) <= _tokens(alt):
        return alt
    return name


def _images(media: list[dict]) -> list[str]:
    """Full-size image URLs: the stored file, without Wix's resizing transform."""
    urls: list[str] = []
    for m in media:
        if m.get("mediaType") not in (None, "image", "IMAGE"):
            continue
        url = str(m.get("url") or "").strip()
        if not url:
            continue
        if url.startswith("http"):
            match = _MEDIA_FILE.match(url)
            if not match:
                continue
            url = match.group(1)
        if "/" in url:
            continue
        full = WIXSTATIC_MEDIA + url
        if full not in urls:
            urls.append(full)
    return urls


def _in_stock(p: dict) -> bool:
    """The gallery's own verdict, else the inventory status. Never the count."""
    if isinstance(p.get("isInStock"), bool):
        return p["isInStock"]
    status = str((p.get("inventory") or {}).get("status") or "").lower()
    return status in ("in_stock", "partially_out_of_stock")


def _number(value) -> float | None:
    """A positive price, or None: zero means "not set" (no sale, no price)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if value > 0 else None


def _text(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")
