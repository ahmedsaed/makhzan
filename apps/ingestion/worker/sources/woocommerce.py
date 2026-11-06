"""WooCommerce Store API adapter.

Reusable across any WooCommerce shop — parameterized by base URL. The public
Store API (`/wp-json/wc/store/v1/products`) returns structured JSON (price,
stock, images, categories), so no HTML scraping is needed.

Two platform quirks handled here:
  - prices are integers in the currency's MINOR unit ("11000" @ minor_unit=2 ->
    110.00 EGP).
  - shops with "hide out of stock from catalog" enabled omit those items from the
    default feed, so we page each `stock_status` explicitly to capture (and badge)
    the out-of-stock and backorder tail instead of silently dropping it.
"""

from __future__ import annotations

import html


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
        """
        if not self._folded_categories:
            return None
        for name in (raw.raw or {}).get("categories") or []:
            # Names arrive HTML-escaped ("Spare Parts &amp; Accessories") and with
            # whatever punctuation the CMS last rewrote them with; the crosswalk
            # is written in readable form and matched through the normalizer.
            mapped = self._folded_categories.get(normalize_category_name(name))
            if mapped:
                return mapped
        return None

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

        return RawItem(
            source=self.source_id,
            external_id=str(p["id"]),
            source_url=p.get("permalink"),
            title=p.get("name"),
            description=strip_html(p.get("description") or p.get("short_description")),
            price_text=price_text,
            currency=prices.get("currency_code"),
            availability_text=availability,
            category_hint=categories[-1] if categories else None,
            images=images,
            raw={"platform": "woocommerce", "sku": p.get("sku"), "categories": categories},
        )
