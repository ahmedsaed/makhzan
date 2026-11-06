"""Shopify adapter via the public `/products.json` feed.

Returns structured JSON (title, variants with price + availability, images,
vendor, product_type), so no HTML scraping is needed.

For V1 we take the first variant's price/sku; multi-variant handling can come
later. Shopify prices are already in major units ("4950.00").
"""

from __future__ import annotations


from makhzan_schemas.contracts import RawItem
from makhzan_schemas.domains.crosswalks import fold_crosswalk, normalize_category_name
from makhzan_schemas.enums import SourceType

from worker.http import get_json, make_client
from worker.sources.base import Page, SourceAdapter, SupplierInfo
from worker.util import strip_html

PER_PAGE = 250  # Shopify max
MAX_PAGES = 200


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

    def _to_raw(self, p: dict) -> RawItem:
        variants = p.get("variants") or []
        variant = variants[0] if variants else {}
        images = [img["src"] for img in p.get("images", []) if img.get("src")]
        vendor = (p.get("vendor") or "").strip() or None

        return RawItem(
            source=self.source_id,
            external_id=str(p["id"]),
            source_url=f"{self.base_url}/products/{p.get('handle')}" if p.get("handle") else None,
            title=p.get("title"),
            description=strip_html(p.get("body_html")),
            brand=vendor,
            price_text=variant.get("price"),
            currency=self.currency,
            availability_text="in stock" if variant.get("available") else "out of stock",
            category_hint=(p.get("product_type") or None),
            images=images,
            raw={
                "platform": "shopify",
                "sku": variant.get("sku"),
                "variant_count": len(variants),
                "product_type": p.get("product_type") or None,
            },
        )
