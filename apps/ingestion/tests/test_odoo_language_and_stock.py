"""An Odoo shop read in a language other than its default, and one whose cards say
nothing about stock (`lang_prefix`, `stock_signal`).

The fixture is a listing page read under /en/ from a shop whose default language
is Arabic: one product translated, one not (Odoo then shows the Arabic name),
and one whose English name was saved empty.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from makhzan_schemas.enums import StockSignal
from worker.normalize import normalize_item
from worker.sources import odoo as odoo_mod
from worker.sources.base import SupplierInfo
from worker.sources.odoo import OdooAdapter

FIXTURES = Path(__file__).parent / "fixtures"
SUPPLIER = SupplierInfo(slug="t", name="T")
BASE = "https://shop.example.test"
PAGE_EN = (FIXTURES / "odoo_page_en.html").read_text()


def _english(**kw) -> OdooAdapter:
    return OdooAdapter("t", BASE, SUPPLIER, lang_prefix="/en", stock_signal=False, **kw)


async def _items(adapter, monkeypatch, html=PAGE_EN, partition=""):
    seen = {}

    async def fake_get_text(client, url, params):
        seen["url"] = url
        return html

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    page = await adapter.fetch_page(partition, 1)
    return page.items, seen["url"]


# --------------------------------------------------------------------------- #
# lang_prefix
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "partition,url",
    [("", f"{BASE}/en/shop"), ("wires-cables-14", f"{BASE}/en/shop/category/wires-cables-14")],
)
async def test_listing_pages_are_read_under_the_prefix(monkeypatch, partition, url):
    _, fetched = await _items(_english(), monkeypatch, partition=partition)
    assert fetched == url


def test_the_probe_reads_the_prefixed_first_page():
    assert _english().probe_url() == f"{BASE}/en/shop?page=1"
    assert (
        _english(categories={"lighting-10": ("electrical", "light-fixtures")}).probe_url()
        == f"{BASE}/en/shop/category/lighting-10?page=1"
    )


@pytest.mark.parametrize("given", ["/en", "en", "/en/", "en_US"])
def test_the_prefix_is_one_language_segment(given):
    assert OdooAdapter("t", BASE, SUPPLIER, lang_prefix=given).lang_prefix.lstrip("/") in (
        "en",
        "en_US",
    )


@pytest.mark.parametrize("bad", ["/en/shop", "https://x.test/en", "../en", "/e n"])
def test_a_prefix_that_is_not_a_language_is_refused(bad):
    with pytest.raises(ValueError):
        OdooAdapter("t", BASE, SUPPLIER, lang_prefix=bad)


async def test_prefixed_cards_are_read_with_their_ids_and_prefixed_urls(monkeypatch):
    items, _ = await _items(_english(), monkeypatch)
    assert [i.external_id for i in items] == ["2561", "45988", "/shop/2795"]
    assert items[0].source_url == (
        f"{BASE}/en/shop/ex-34-acme-emergency-exit-sign-led-3w-maintained-2561"
    )


async def test_a_plain_source_does_not_read_prefixed_cards(monkeypatch):
    """Without the option nothing changes: /shop, and links starting /shop/ only."""
    items, fetched = await _items(OdooAdapter("t", BASE, SUPPLIER), monkeypatch)
    assert fetched == f"{BASE}/shop"
    assert items == []


async def test_a_translated_title_is_english_and_an_untranslated_one_arabic(monkeypatch):
    """Odoo shows the default-language name where no translation exists; normalization
    files a title by its script, so the fallback lands in title_ar and costs nothing."""
    items, _ = await _items(_english(), monkeypatch)
    translated, untranslated, emptied = (normalize_item(i) for i in items)

    assert translated.title_en == "Acme Emergency Exit Sign LED 3W Maintained"
    assert translated.title_ar is None
    assert untranslated.title_en is None
    assert untranslated.title_ar == "لفة سلك نحاس مجدول معزول 1.5 مم"
    # Saved empty: the card's image alt still names it, without the [reference].
    assert emptied.title_en == "Multi-Core Stranded Copper Cable 2x1 mm"


async def test_prices_are_read_from_the_card_in_egp(monkeypatch):
    items, _ = await _items(_english(), monkeypatch)
    first, second, third = (normalize_item(i) for i in items)
    assert str(first.price) == "3698.99"
    assert first.currency == "EGP"
    assert items[0].raw["compare_at_price"] == "4150.00"
    assert str(second.price) == "1250.00"
    assert third.price is None  # on request


def test_product_pages_are_read_in_the_prefixed_language():
    for stored in (f"{BASE}/en/shop/widget-12", f"{BASE}/shop/widget-12?category=3"):
        assert odoo_mod._product_url(stored, BASE, "/en") == f"{BASE}/en/shop/widget-12"
    with pytest.raises(ValueError):
        odoo_mod._product_url(f"{BASE}/en/contactus", BASE, "/en")


def test_without_a_prefix_product_urls_are_as_before():
    assert odoo_mod._product_url(f"{BASE}/shop/w-12?x=1", BASE) == f"{BASE}/shop/w-12"
    with pytest.raises(ValueError):
        odoo_mod._product_url(f"{BASE}/en/shop/w-12", BASE)


class _Fetcher:
    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    async def get(self, label, url, params=None):
        self.asked.append(url)
        return httpx.Response(200, text=self.pages[url], request=httpx.Request("GET", url))


async def test_the_sitemap_names_products_in_either_language():
    sitemap = (
        "<urlset><url><loc>https://shop.example.test/shop/a-11</loc></url>"
        "<url><loc>https://shop.example.test/en/shop/b-12</loc></url></urlset>"
    )
    ids = await _english()._sitemap_ids(_Fetcher({f"{BASE}/sitemap.xml": sitemap}))
    assert ids == {"11", "12"}


# --------------------------------------------------------------------------- #
# stock_signal
# --------------------------------------------------------------------------- #


async def test_without_a_stock_signal_every_listing_is_unknown(monkeypatch):
    """No ribbon is not "in stock" on a shop whose cards never say: the site then
    shows "Availability unknown" and counts no shop as having it."""
    items, _ = await _items(_english(), monkeypatch)
    assert {i.availability_text for i in items} == {None}
    assert {normalize_item(i).stock_signal for i in items} == {StockSignal.UNKNOWN}


async def test_with_a_stock_signal_no_ribbon_still_means_in_stock(monkeypatch):
    items, _ = await _items(OdooAdapter("t", BASE, SUPPLIER, lang_prefix="/en"), monkeypatch)
    assert {normalize_item(i).stock_signal for i in items} == {StockSignal.IN_STOCK}
