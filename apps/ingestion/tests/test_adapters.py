"""Adapter parsing and paging rules, without touching the network.

The platform quirks encoded here are the ones that silently corrupt data when
they regress: WooCommerce prices are minor units, and Odoo never serves an empty
page so a naive loop runs forever.
"""

from __future__ import annotations

import pytest
from worker.sources import odoo as odoo_mod
from worker.sources import woocommerce as woo_mod
from worker.sources.base import SupplierInfo
from worker.http import BROWSER_HEADERS, CHROME_VERSION
from worker.sources.odoo import OdooAdapter
from worker.sources.shopify import ShopifyAdapter
from worker.sources.woocommerce import WooCommerceAdapter

SUPPLIER = SupplierInfo(slug="t", name="T")


def _woo():
    return WooCommerceAdapter("t", "https://example.test", SUPPLIER)


def _product(pid="1", price="2500", minor=2):
    return {
        "id": pid,
        "name": "Widget",
        "permalink": "https://example.test/p",
        "prices": {"price": price, "currency_minor_unit": minor, "currency_code": "EGP"},
        "categories": [{"name": "Bolts"}],
        "images": [],
        "sku": "SKU1",
    }


def test_woocommerce_price_is_minor_units():
    """2500 with minor_unit 2 is 25.00 EGP, not 2500 EGP."""
    raw = _woo()._to_raw(_product(), "in stock")
    assert raw.price_text == "25.00"
    assert raw.currency == "EGP"


def test_woocommerce_price_respects_minor_unit_zero():
    raw = _woo()._to_raw(_product(price="350", minor=0), "in stock")
    assert raw.price_text == "350.00"


def test_woocommerce_partitions_cover_every_stock_status():
    """The default feed hides out-of-stock on some shops, so each status is swept."""
    assert set(_woo().partitions()) == {"instock", "outofstock", "onbackorder"}


@pytest.mark.parametrize("returned,expected_more", [([], False), ([_product()], True)])
async def test_woocommerce_has_more_follows_page_contents(monkeypatch, returned, expected_more):
    async def fake_get_json(client, url, params):
        return returned

    monkeypatch.setattr(woo_mod, "get_json", fake_get_json)
    page = await _woo().fetch_page("instock", 1)
    assert page.has_more is expected_more
    assert len(page.items) == len(returned)


_CARD = """
<div class="oe_product">
  <a href="/shop/product/widget-{id}"><span itemprop="name">Widget {id}</span></a>
  <span itemprop="price">10.0</span>
</div>
"""


def _html(ids):
    return "<html><body>" + "".join(_CARD.format(id=i) for i in ids) + "</body></html>"


async def test_odoo_stops_when_a_page_repeats(monkeypatch):
    """Odoo serves its last page forever; a repeat is the only end signal."""
    pages = {1: _html([1, 2]), 2: _html([3, 4]), 3: _html([3, 4])}

    async def fake_get_text(client, url, params):
        return pages[params["page"]]

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = OdooAdapter("t", "https://example.test", SUPPLIER)

    assert (await adapter.fetch_page("", 1)).has_more is True
    assert (await adapter.fetch_page("", 2)).has_more is True
    third = await adapter.fetch_page("", 3)
    assert third.has_more is False, "a page identical to the previous one ends the sweep"


async def test_odoo_empty_page_ends_sweep(monkeypatch):
    async def fake_get_text(client, url, params):
        return "<html><body></body></html>"

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = OdooAdapter("t", "https://example.test", SUPPLIER)
    assert (await adapter.fetch_page("", 1)).has_more is False


CROSSWALK = {
    "Ceramic Capacitors": ("electronics", "capacitors"),
    "Spindles | Chucks | Collets": ("tools", "drill-bits"),
}


def _woo_mapped():
    return WooCommerceAdapter("t", "https://example.test", SUPPLIER, categories=CROSSWALK)


def test_crosswalk_resolves_from_any_tag_not_the_last_one():
    """WooCommerce returns categories alphabetically, not most-specific-last.

    ["Capacitors", "Ceramic Capacitors", "Components"] ends on the vaguest name,
    so reading a fixed position picks the wrong one.
    """
    product = _product()
    product["categories"] = [
        {"name": "Capacitors"},
        {"name": "Ceramic Capacitors"},
        {"name": "Components"},
    ]
    raw = _woo_mapped()._to_raw(product, "in stock")
    assert _woo_mapped().category_for(raw) == ("electronics", "capacitors")


def test_crosswalk_can_send_a_listing_to_another_domain():
    """An electronics shop that sells collets; a supplier-level domain would file
    them as electronics."""
    product = _product()
    product["categories"] = [{"name": "Spindles | Chucks | Collets"}]
    raw = _woo_mapped()._to_raw(product, "in stock")
    assert _woo_mapped().category_for(raw) == ("tools", "drill-bits")


def test_unmapped_tags_fall_through_rather_than_guessing():
    """Package facets like 0805 hold both resistors and capacitors — no mapping."""
    product = _product()
    product["categories"] = [{"name": "0805 (2012M)"}, {"name": "Components"}]
    raw = _woo_mapped()._to_raw(product, "in stock")
    assert _woo_mapped().category_for(raw) is None


def test_adapter_without_a_crosswalk_maps_nothing():
    raw = _woo()._to_raw(_product(), "in stock")
    assert _woo().category_for(raw) is None


def test_crosswalk_still_matches_after_the_shop_retypes_the_punctuation():
    """A shop replaced the hyphen in "Diodes - General Purpose" with an en-dash.
    The category and its products are unchanged, so the mapping must survive —
    an exact-string lookup would have silently uncategorized all of them."""
    adapter = WooCommerceAdapter(
        "t",
        "https://example.test",
        SUPPLIER,
        categories={"Diodes - General Purpose": ("electronics", "diodes")},
    )
    product = _product()
    product["categories"] = [{"name": "Diodes &#8211; General Purpose"}]
    raw = adapter._to_raw(product, "in stock")
    assert adapter.category_for(raw) == ("electronics", "diodes")


# --------------------------------------------------------------------------- #
# Shopify crosswalk
# --------------------------------------------------------------------------- #

SHOPIFY_CROSSWALK = {"sensor": ("electronics", "sensors"), "pump": ("machinery", "general-pumps")}


def _shopify(categories=None):
    return ShopifyAdapter("t", "https://example.test", SUPPLIER, categories=categories)


def _shopify_product(product_type="sensor"):
    return {
        "id": 1,
        "handle": "widget",
        "title": "Widget",
        "vendor": "Acme",
        "product_type": product_type,
        "variants": [{"price": "10.00", "available": True, "sku": "S1"}],
        "images": [],
    }


@pytest.mark.parametrize("spelling", ["sensor", "Sensor", "SENSOR", "  sensor  "])
def test_shopify_crosswalk_folds_the_case_the_shop_publishes(spelling):
    """product_type is free text; one shop spells the same type several ways."""
    adapter = _shopify(SHOPIFY_CROSSWALK)
    raw = adapter._to_raw(_shopify_product(spelling))
    assert adapter.category_for(raw) == ("electronics", "sensors")


def test_shopify_crosswalk_can_send_a_listing_to_another_domain():
    adapter = _shopify(SHOPIFY_CROSSWALK)
    raw = adapter._to_raw(_shopify_product("pump"))
    assert adapter.category_for(raw) == ("machinery", "general-pumps")


@pytest.mark.parametrize("product_type", ["", None, "not-in-the-crosswalk"])
def test_shopify_unmapped_product_types_fall_through(product_type):
    """A miss must stay a miss — the adapter is not authoritative, so inference
    gets its turn at the title."""
    adapter = _shopify(SHOPIFY_CROSSWALK)
    raw = adapter._to_raw(_shopify_product(product_type))
    assert adapter.category_for(raw) is None


def test_shopify_adapter_without_a_crosswalk_maps_nothing():
    adapter = _shopify()
    assert adapter.category_for(adapter._to_raw(_shopify_product())) is None


# --------------------------------------------------------------------------- #
# Odoo browsed by category
# --------------------------------------------------------------------------- #

ODOO_CROSSWALK = {
    "connectors-12": ("electronics", "connectors"),
    "drill-bits-31": ("tools", "drill-bits"),
}


def _odoo_by_category(**kw):
    return OdooAdapter("t", "https://example.test", SUPPLIER, categories=ODOO_CROSSWALK, **kw)


async def test_odoo_fetches_the_category_page_for_a_partition(monkeypatch):
    seen = {}

    async def fake_get_text(client, url, params):
        seen["url"] = url
        return _html([1])

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    await _odoo_by_category().fetch_page("connectors-12", 1)
    assert seen["url"] == "https://example.test/shop/category/connectors-12"


async def test_odoo_without_a_crosswalk_still_sweeps_the_whole_shop(monkeypatch):
    seen = {}

    async def fake_get_text(client, url, params):
        seen["url"] = url
        return _html([1])

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = OdooAdapter("t", "https://example.test", SUPPLIER)
    assert adapter.partitions() == [""]
    await adapter.fetch_page("", 1)
    assert seen["url"] == "https://example.test/shop"


async def test_the_repeat_check_is_per_partition(monkeypatch):
    """Two categories can legitimately open on the same products — a shared
    end-signal would cut the second category off at its first page."""

    async def fake_get_text(client, url, params):
        return _html([1, 2])

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = _odoo_by_category()

    assert (await adapter.fetch_page("connectors-12", 1)).has_more is True
    second = await adapter.fetch_page("drill-bits-31", 1)
    assert second.has_more is True, "a different partition must start its own repeat check"
    assert (await adapter.fetch_page("drill-bits-31", 2)).has_more is False


async def test_the_partition_becomes_the_listings_category(monkeypatch):
    async def fake_get_text(client, url, params):
        return _html([1])

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = _odoo_by_category()
    (item,) = (await adapter.fetch_page("drill-bits-31", 1)).items
    assert adapter.category_for(item) == ("tools", "drill-bits")
    assert adapter.source_categories(item) == ["drill-bits-31"]


async def test_an_unmapped_partition_stays_uncategorized(monkeypatch):
    """Authoritative: browsing by category makes it a fact, so a miss must not
    fall through to guessing from the title."""

    async def fake_get_text(client, url, params):
        return _html([1])

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = _odoo_by_category()
    (item,) = (await adapter.fetch_page("keypads-40", 1)).items
    assert adapter.category_for(item) is None


def test_categories_are_authoritative_only_when_a_crosswalk_is_given():
    assert _odoo_by_category().authoritative_categories is True
    assert OdooAdapter("t", "https://example.test", SUPPLIER).authoritative_categories is False


async def test_odoo_sweeps_the_whole_shop_alongside_its_categories():
    """A shop can file products under no category at all (one had 8 of 2,875).
    Without this pass the category sweep never sees them and a completed cycle
    archives them."""
    adapter = _odoo_by_category(sweep_whole_shop=True)
    parts = adapter.partitions()
    assert "" in parts
    assert parts[1:] == list(ODOO_CROSSWALK)


async def test_the_whole_shop_pass_is_swept_first():
    """It is the one partition too big for a single run, and a run takes the
    outstanding partitions in order. Left until last it only starts once the
    categories are nearly done, stretching a 7-run cycle to 15."""
    assert _odoo_by_category(sweep_whole_shop=True).partitions()[0] == ""


async def test_the_whole_shop_pass_reports_that_it_knows_no_category(monkeypatch):
    async def fake_get_text(client, url, params):
        return _html([1])

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = _odoo_by_category(sweep_whole_shop=True)

    (from_category,) = (await adapter.fetch_page("connectors-12", 1)).items
    (from_shop,) = (await adapter.fetch_page("", 1)).items

    assert adapter.knows_category(from_category) is True
    assert adapter.knows_category(from_shop) is False


async def test_a_plain_odoo_source_still_knows_its_own_categories(monkeypatch):
    """Without a crosswalk the /shop sweep is the only pass there is, so it has
    to keep deciding — otherwise a category could never be cleared at all."""

    async def fake_get_text(client, url, params):
        return _html([1])

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = OdooAdapter("t", "https://example.test", SUPPLIER)
    (item,) = (await adapter.fetch_page("", 1)).items
    assert adapter.knows_category(item) is True


# --------------------------------------------------------------------------- #
# Browser headers
# --------------------------------------------------------------------------- #


def test_the_advertised_browser_version_is_consistent():
    """A WAF reads both the User-Agent and the client hints. Bumping one and not
    the other advertises a browser that cannot exist, which scores worse than an
    honestly old one."""
    assert f"Chrome/{CHROME_VERSION}.0.0.0" in BROWSER_HEADERS["User-Agent"]
    assert f'"Chromium";v="{CHROME_VERSION}"' in BROWSER_HEADERS["sec-ch-ua"]


def test_we_stay_contactable():
    """Identifiable without tripping WAFs — a supplier who wants us to stop has
    somewhere to write."""
    assert "@" in BROWSER_HEADERS["From"]
