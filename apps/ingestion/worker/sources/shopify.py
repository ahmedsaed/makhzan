"""Shopify adapter via the public `/products.json` feed.

Returns structured JSON (title, variants with price + availability, images,
vendor, product_type), so no HTML scraping is needed.

The listing's price and stock are the first variant's. The other variants, the
options they choose between, the specs and datasheets in `body_html` and the
compare-at price all arrive in the same feed page, so they are kept too — in
`attributes`, since none of them changes what the listing costs. Shopify prices
are already in major units ("4950.00").

What the feed does NOT carry is stock quantity: `inventory_quantity` is only in
`/products/<handle>.json` and the product page, one request per product.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from makhzan_schemas.contracts import RawItem
from makhzan_schemas.domains.crosswalks import fold_crosswalk, normalize_category_name
from makhzan_schemas.enums import SourceType

from worker.http import get_json, make_client
from worker.normalize import parse_price
from worker.richtext import documents_from_html, html_to_text, specs_from_html
from worker.sources.base import Page, SourceAdapter, SupplierInfo

PER_PAGE = 250  # Shopify max
MAX_PAGES = 200

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
    ) -> None:
        self.source_id = source_id
        self.base_url = base_url.rstrip("/")
        self.supplier = supplier
        self.currency = currency
        self.enabled = enabled
        #: Optional crosswalk from this shop's own `product_type` to
        #: (domain, taxonomy leaf).
        self.categories = categories or {}
        # product_type is free text and shops spell it inconsistently ("Sensor"
        # and "sensor", "NFC" and "nfc"), so lookups go through the shared
        # normalizer rather than a bare .lower().
        self._categories_folded = fold_crosswalk(self.categories)
        if polite_delay is not None:
            self.polite_delay = polite_delay
        if max_pages_per_run is not None:
            self.max_pages_per_run = max_pages_per_run
        if max_partitions_per_run is not None:
            self.max_partitions_per_run = max_partitions_per_run

    def category_for(self, raw: RawItem) -> tuple[str, str] | None:
        """Resolve a listing's category from the shop's own `product_type`.

        Unlike WooCommerce, Shopify gives exactly one product_type per product
        rather than an unordered set, so there is no "which tag wins" question
        here — only the spelling, which the folded table handles.
        """
        if not self._categories_folded:
            return None
        product_type = normalize_category_name((raw.raw or {}).get("product_type"))
        return self._categories_folded.get(product_type) if product_type else None

    async def fetch_page(self, partition: str, page: int) -> Page:
        url = f"{self.base_url}/products.json"
        async with make_client() as client:
            data = await get_json(client, url, {"limit": PER_PAGE, "page": page})
        products = data.get("products", [])
        # products.json simply runs dry — an empty array is the end of the feed.
        return Page([self._to_raw(p) for p in products], has_more=bool(products))

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
        if compare_at := _compare_at(variant):
            raw["compare_at_price"] = compare_at
        if options := _options(p):
            raw["options"] = options
        if len(variants) > 1:
            raw["variants"] = [_variant(v) for v in variants]

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
    """One purchasable variant, with only what the shop states about it."""
    out = {
        "title": v.get("title"),
        "price": v.get("price"),
        "sku": v.get("sku") or None,
        "available": bool(v.get("available")),
    }
    if compare_at := _compare_at(v):
        out["compare_at_price"] = compare_at
    return {k: val for k, val in out.items() if val is not None}
