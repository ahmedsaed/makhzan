"""WooCommerce Store API adapter.

Reusable across any WooCommerce shop — parameterized by base URL. The public
Store API (`/wp-json/wc/store/v1/products`) returns structured JSON (price,
stock, images, categories), so no HTML scraping is needed. The same payload also
carries brand, spec attributes, variant options, sale/regular price, stock count,
tags and datasheet links; those are kept on the listing's attributes, since
fetching them costs nothing beyond the page already requested.

Two platform quirks handled here:
  - prices are integers in the currency's MINOR unit ("11000" @ minor_unit=2 ->
    110.00 EGP).
  - shops with "hide out of stock from catalog" enabled omit those items from the
    default feed, so we page each `stock_status` explicitly to capture (and badge)
    the out-of-stock and backorder tail instead of silently dropping it.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin

from makhzan_schemas.contracts import RawItem
from makhzan_schemas.enums import SourceType

from makhzan_schemas.domains.crosswalks import fold_crosswalk, normalize_category_name

from worker.http import get_json, make_client
from worker.sources.base import Page, SourceAdapter, SupplierInfo
from worker.util import strip_html

PER_PAGE = 100
MAX_PAGES = 200  # safety cap (~20k products)

# Page every status: the default feed hides out-of-stock on some shops. The
# queried status is authoritative (is_in_stock is true for backorder too, so it
# can't distinguish these on its own).
STOCK_STATUSES = {
    "instock": "in stock",
    "outofstock": "out of stock",
    "onbackorder": "made to order",
}

#: Brand values a shop uses to say "no brand" — or, for "China", where it was
#: made. Stored as a brand they would make every unbranded part look like it came
#: from one manufacturer.
_NOT_A_BRAND = {"generic", "no brand", "unbranded", "oem", "other", "none", "n/a", "china"}

#: Attribute names that carry the brand on shops without the brands taxonomy.
_BRAND_ATTRIBUTES = {"brand", "manufacturer"}

#: "68 in stock", "Only 1 left in stock" — the count the shop itself prints.
_STOCK_COUNT = re.compile(r"(\d[\d,]*)\s+(?:left\s+)?in stock", re.I)

_PDF_LINK = re.compile(r"""href\s*=\s*["']([^"']+?\.pdf)(?:[?#][^"']*)?["']""", re.I)

#: A catalogue page has no business linking more datasheets than this; past it
#: the description is a link farm and none of them is about this product.
_MAX_DOCUMENTS = 10


def _text(value) -> str | None:
    """A Store API label as plain text: names arrive HTML-escaped ("A &amp; B")."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(html.unescape(value).split())
    return cleaned or None


def _major(amount, minor: int) -> str | None:
    """A Store API amount (minor units, as a string) in major units."""
    if amount in (None, ""):
        return None
    try:
        return f"{int(amount) / (10**minor):.2f}"
    except (TypeError, ValueError):
        return None


class WooCommerceAdapter(SourceAdapter):
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
        prefer: tuple[str, ...] | list[str] = (),
    ) -> None:
        self.source_id = source_id
        self.base_url = base_url.rstrip("/")
        self.supplier = supplier
        self.enabled = enabled
        #: Optional crosswalk from this shop's own category names to
        #: (domain, taxonomy leaf). WooCommerce shops tag a product with several
        #: categories at once, so this is consulted per tag rather than per item.
        self.categories = categories or {}
        # Indexed by normalized name so a shop re-typing "Diodes - General
        # Purpose" with an en-dash does not silently uncategorize it.
        self._folded_categories = fold_crosswalk(self.categories)
        #: Normalized tag name -> rank, for the tags that win a conflict.
        self._preference = {normalize_category_name(name): i for i, name in enumerate(prefer)}
        if polite_delay is not None:
            self.polite_delay = polite_delay
        if max_pages_per_run is not None:
            self.max_pages_per_run = max_pages_per_run
        if max_partitions_per_run is not None:
            self.max_partitions_per_run = max_partitions_per_run

    def source_categories(self, raw: RawItem) -> list[str]:
        return [html.unescape(n).strip() for n in (raw.raw or {}).get("categories") or []]

    def category_for(self, raw: RawItem) -> tuple[str, str] | None:
        """Resolve a listing's category from whichever of its tags we recognise.

        The Store API returns an unordered, alphabetically sorted set of category
        names, so there is no "most specific" position to read — ["Capacitors",
        "Ceramic Capacitors", "Components"] ends on the vaguest of the three.
        Instead every tag is looked up and unmapped ones are ignored, which is
        what keeps generic buckets and package facets ("0805") out of the way.

        When two mapped tags disagree, the crosswalk's `prefer` list decides, and
        only then the alphabet. Alphabetical order alone filed one shop's plain
        3 mm LEDs under Displays — "Displays ( LCD & 7-Seg & LED )" sorts before
        "LEDs" — and its filament and stepper motors under "CNC & 3D Printer
        Parts". Which of two tags is the more specific is a judgement about that
        shop's taxonomy, so it is written down in the shop's crosswalk.
        """
        if not self._folded_categories:
            return None
        best: tuple[int, tuple[str, str]] | None = None
        for position, name in enumerate((raw.raw or {}).get("categories") or []):
            # Names arrive HTML-escaped ("Spare Parts &amp; Accessories") and with
            # whatever punctuation the CMS last rewrote them with; the crosswalk
            # is written in readable form and matched through the normalizer.
            key = normalize_category_name(name)
            mapped = self._folded_categories.get(key)
            if not mapped:
                continue
            # Preferred tags rank ahead of every unpreferred one, which keep the
            # source's own order among themselves.
            rank = self._preference.get(key, len(self._preference) + position)
            if best is None or rank < best[0]:
                best = (rank, mapped)
        return best[1] if best else None

    def partitions(self) -> list[str]:
        # One partition per stock status: the default feed hides out-of-stock on
        # some shops, and each status paginates independently.
        return list(STOCK_STATUSES)

    async def fetch_page(self, partition: str, page: int) -> Page:
        url = f"{self.base_url}/wp-json/wc/store/v1/products"
        availability = STOCK_STATUSES[partition]
        async with make_client() as client:
            products = await get_json(
                client,
                url,
                {"per_page": PER_PAGE, "page": page, "stock_status": partition},
            )
        return Page(
            [self._to_raw(p, availability) for p in products],
            has_more=bool(products),
        )

    def _to_raw(self, p: dict, availability: str) -> RawItem:
        prices = p.get("prices") or {}
        price_text = None
        raw_price = prices.get("price")
        if raw_price not in (None, ""):
            minor = prices.get("currency_minor_unit", 2)
            price_text = f"{int(raw_price) / (10**minor):.2f}"

        categories = [c.get("name") for c in p.get("categories", []) if c.get("name")]
        images = [img["src"] for img in p.get("images", []) if img.get("src")]

        # The SKU is the shop's private catalogue code, not an MPN: kept for
        # reference, never used to group listings across shops.
        raw = {"platform": "woocommerce", "sku": p.get("sku"), "categories": categories}
        raw.update(self._details(p, prices))

        return RawItem(
            source=self.source_id,
            external_id=str(p["id"]),
            source_url=p.get("permalink"),
            title=p.get("name"),
            # Checked one at a time, not `description or short_description`: a
            # description of "<p>&nbsp;</p>" is truthy and flattens to nothing,
            # which would hide a perfectly good short description behind it.
            description=strip_html(p.get("description")) or strip_html(p.get("short_description")),
            brand=self._brand(p),
            price_text=price_text,
            currency=prices.get("currency_code"),
            availability_text=availability,
            category_hint=categories[-1] if categories else None,
            images=images,
            raw=raw,
        )

    @staticmethod
    def _brand(p: dict) -> str | None:
        """The shop's own brand for the product, if it names one.

        Newer WooCommerce has a brands taxonomy; older shops put the brand in an
        ordinary "Brand" attribute. A shop that tags unbranded stock "Generic" is
        saying there is no brand, so that is not recorded as one.
        """
        names = [_text(b.get("name")) for b in p.get("brands") or [] if isinstance(b, dict)]
        if not any(names):
            for attr in p.get("attributes") or []:
                if (_text(attr.get("name")) or "").lower() in _BRAND_ATTRIBUTES:
                    terms = attr.get("terms") or []
                    # Several terms is a choice between brands, not this item's.
                    if len(terms) == 1:
                        names = [_text(terms[0].get("name"))]
                    break
        for name in names:
            if name and name.lower() not in _NOT_A_BRAND:
                return name[:120]
        return None

    def _details(self, p: dict, prices: dict) -> dict:
        """What the shop publishes about a product beyond its title and price.

        All of it is already in the Store API page we fetch, so none of it costs
        a request. Only keys with something in them are written, so a listing's
        attributes stay as small as what the shop actually filled in.
        """
        out: dict = {}
        minor = prices.get("currency_minor_unit", 2)

        # Attributes come in two kinds. Those a variation is chosen by
        # ("Color: Black / White") are options on one listing, not facts about
        # it; the rest are the shop's spec sheet ("Measurement Range: 0-75%").
        specs: dict[str, str] = {}
        options: dict[str, list[str]] = {}
        for attr in p.get("attributes") or []:
            name = _text(attr.get("name"))
            terms = [t for t in (_text(t.get("name")) for t in attr.get("terms") or []) if t]
            if not name or not terms or name.lower() in _BRAND_ATTRIBUTES:
                continue
            if attr.get("has_variations"):
                options[name] = terms
            else:
                specs[name] = " / ".join(terms)
        if specs:
            out["specs"] = specs
        if options:
            out["options"] = options
        if p.get("variations"):
            out["variants"] = len(p["variations"])

        # The listing's price stays `prices.price`. A variable product's is its
        # cheapest variation, so the span is kept beside it rather than lost.
        price_range = prices.get("price_range") or {}
        low = _major(price_range.get("min_amount"), minor)
        high = _major(price_range.get("max_amount"), minor)
        if low and high and low != high:
            out["price_range"] = {"min": low, "max": high}
        # What the shop crosses out next to a sale price.
        regular = _major(prices.get("regular_price"), minor)
        current = _major(prices.get("price"), minor)
        if p.get("on_sale") and regular and current and float(regular) > float(current):
            out["regular_price"] = regular

        quantity = p.get("low_stock_remaining")
        if not isinstance(quantity, int):
            text = strip_html((p.get("stock_availability") or {}).get("text")) or ""
            match = _STOCK_COUNT.search(text)
            quantity = int(match.group(1).replace(",", "")) if match else None
        if quantity is not None and quantity >= 0:
            out["stock_quantity"] = quantity

        # Formatted, because the raw numbers carry no unit and the unit is a
        # per-shop setting; a placeholder ("N/A", in whatever language) has no digit.
        for key, field in (("weight", "formatted_weight"), ("dimensions", "formatted_dimensions")):
            value = _text(p.get(field))
            if value and any(ch.isdigit() for ch in value):
                out[key] = value

        tags = [t for t in (_text(t.get("name")) for t in p.get("tags") or []) if t]
        if tags:
            out["tags"] = tags

        # Datasheets and manuals linked from the description: flattening it to
        # text keeps the words and drops the links, which are the useful part.
        documents: list[str] = []
        for field in ("description", "short_description"):
            for href in _PDF_LINK.findall(p.get(field) or ""):
                url = urljoin(f"{self.base_url}/", html.unescape(href).strip())
                if url.startswith(("http://", "https://")) and url not in documents:
                    documents.append(url)
        if documents:
            out["documents"] = documents[:_MAX_DOCUMENTS]

        return out
