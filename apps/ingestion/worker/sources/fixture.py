"""Fixture adapter — a tiny hardcoded source for exercising the pipeline.

This is NOT a real supplier. It exists so the fetch -> normalize -> upsert ->
review flow can be run and tested end-to-end before any real scraper is written.
Delete or disable once real adapters exist. The two items are chosen to hit both
branches: one clean (goes live), one missing a price (goes to review).
"""

from __future__ import annotations

from makhzan_schemas.contracts import RawItem
from makhzan_schemas.enums import SourceType

from worker.sources.base import Page, SourceAdapter, SupplierInfo

_ITEMS = [
    RawItem(
        source="fixture",
        external_id="ESP32-DEVKIT-V1",
        source_url="https://example.test/esp32",
        title="ESP32 DevKit V1 WiFi+Bluetooth Development Board",
        part_number="ESP32-WROOM-32",
        brand="Espressif",
        price_text="350 EGP",
        availability_text="In stock",
        category_hint="Development Boards",
        images=["https://example.test/esp32.jpg"],
        raw={"pins": 30},
    ),
    RawItem(
        source="fixture",
        external_id="RES-10K-14W",
        source_url="https://example.test/res-10k",
        title="مقاومة 10 كيلو أوم 1/4 وات",  # Arabic -> title_ar
        part_number=None,
        price_text=None,  # missing price -> review queue
        availability_text="متوفر",
        category_hint=None,
        raw={},
    ),
]


class FixtureAdapter(SourceAdapter):
    source_id = "fixture"
    source_type = SourceType.MANUAL
    supplier = SupplierInfo(slug="fixture", name="Fixture (test source)")
    enabled = False  # test-only; real sources now exist (woocommerce, shopify)

    def __init__(
        self,
        source_id: str = "fixture",
        supplier: SupplierInfo | None = None,
        *,
        enabled: bool = False,
    ) -> None:
        # Built from a Source row like every other adapter, so the same factory
        # path is exercised; the defaults keep FixtureAdapter() usable directly.
        self.source_id = source_id
        if supplier is not None:
            self.supplier = supplier
        self.enabled = enabled

    async def fetch_page(self, partition: str, page: int) -> Page:
        return Page(list(_ITEMS) if page == 1 else [], has_more=False)
