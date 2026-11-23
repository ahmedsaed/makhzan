"""A shop whose SKU is the manufacturer's part number (`sku_is_part_number`).

Most shops' SKUs are private catalogue codes that coincide across shops only by
accident, so by default a SKU is never an identifier. Some electrical shops'
SKUs are the maker's own references (a Schneider "A9F77150" is that breaker
wherever it is sold), and a source verified as one opts in: the SKU becomes the
listing's adapter-supplied part number, which wins over the title rules and
works in a department that has none.

It is still evidence, not proof: a shared SKU only makes two listings
candidates, title agreement still admits, and every veto still refuses.

The shops and products here are fictional; the title shapes are real ones.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from makhzan_schemas.contracts import RawItem
from makhzan_schemas.enums import SourceType
from makhzan_schemas.grouping import _group_listings, assign_identifiers
from makhzan_schemas.models import Listing, Source

from worker.normalize import normalize_item
from worker.sources import odoo as odoo_mod
from worker.sources.base import SupplierInfo
from worker.sources.odoo import OdooAdapter
from worker.sources.registry import build_adapter
from worker.sources.shopify import ShopifyAdapter

SUPPLIER = SupplierInfo(slug="t", name="T")
BASE = "https://shop.example.test"


# --------------------------------------------------------------------------- #
# Shopify: one variant takes its SKU, a range takes none
# --------------------------------------------------------------------------- #


def _shopify(**kw) -> ShopifyAdapter:
    return ShopifyAdapter("t", BASE, SUPPLIER, **kw)


def _product(*skus: str | None) -> dict:
    return {
        "id": 1,
        "handle": "mcb",
        "title": "Acme iC60N Miniature Circuit Breaker",
        "vendor": "Acme",
        "product_type": "MCB",
        "variants": [
            {"price": "100.00", "available": True, "sku": sku, "title": f"V{i}"}
            for i, sku in enumerate(skus)
        ],
        "images": [],
    }


def test_a_single_variant_takes_its_sku_as_its_part_number():
    raw = _shopify(sku_is_part_number=True)._to_raw(_product(" A9F77150 "))
    assert raw.part_number == "A9F77150"


def test_a_product_with_several_variants_takes_none():
    """The listing is the whole range: no one variant's SKU says what it is."""
    raw = _shopify(sku_is_part_number=True)._to_raw(_product("A9F77116", "A9F77120", "A9F77132"))
    assert raw.part_number is None
    assert [v["sku"] for v in raw.raw["variants"]] == ["A9F77116", "A9F77120", "A9F77132"]


@pytest.mark.parametrize("sku", [None, "", "   "])
def test_a_missing_sku_is_no_part_number(sku):
    assert _shopify(sku_is_part_number=True)._to_raw(_product(sku)).part_number is None


def test_off_by_default_the_sku_is_only_kept():
    raw = _shopify()._to_raw(_product("A9F77150"))
    assert raw.part_number is None
    assert raw.raw["sku"] == "A9F77150"


# --------------------------------------------------------------------------- #
# Odoo: the card's internal reference
# --------------------------------------------------------------------------- #

_CARD = """
<div class="oe_product"><form>
  <a href="/en/shop/acme-mcb-50a-501"><img src="/web/image/product.product/501/image_512/x"
     alt="[A9F77150] Acme Circuit Breaker, iC60N, 1P, 50A"></a>
  <a itemprop="name" href="/en/shop/acme-mcb-50a-501">Acme Circuit Breaker, iC60N, 1P, 50A</a>
  <span itemprop="price">450.0</span>
</form></div>
<div class="oe_product"><form>
  <a href="/en/shop/acme-mcb-range-502"><img src="/web/image/product.template/502/image_512/x"
     alt="Acme Circuit Breaker range"></a>
  <a itemprop="name" href="/en/shop/acme-mcb-range-502">Acme Circuit Breaker range</a>
  <span itemprop="price">300.0</span>
</form></div>
"""


async def _odoo_items(monkeypatch, **kw):
    async def fake_get_text(client, url, params):
        return f"<html><body>{_CARD}</body></html>"

    monkeypatch.setattr(odoo_mod, "get_text", fake_get_text)
    adapter = OdooAdapter("t", BASE, SUPPLIER, lang_prefix="/en", **kw)
    return (await adapter.fetch_page("", 1)).items


async def test_odoo_reads_the_card_reference_as_the_part_number(monkeypatch):
    with_ref, without = await _odoo_items(monkeypatch, sku_is_part_number=True)
    assert with_ref.part_number == "A9F77150"
    # A template with several variants has no reference, so the card names none.
    assert without.part_number is None


async def test_odoo_off_by_default_keeps_the_reference_only(monkeypatch):
    with_ref, _ = await _odoo_items(monkeypatch)
    assert with_ref.part_number is None
    assert with_ref.raw["sku"] == "A9F77150"


# --------------------------------------------------------------------------- #
# The key is validated like any other
# --------------------------------------------------------------------------- #


def _source(adapter: str, **config) -> Source:
    return Source(
        source_id="shop",
        adapter=adapter,
        base_url=BASE,
        supplier={"slug": "shop", "name": "Shop"},
        enabled=True,
        config=config,
    )


@pytest.mark.parametrize("adapter", ["shopify", "odoo"])
def test_the_key_builds_where_the_adapter_reads_a_sku(adapter):
    assert build_adapter(_source(adapter, sku_is_part_number=True)).sku_is_part_number is True
    assert build_adapter(_source(adapter)).sku_is_part_number is False


def test_an_adapter_that_does_not_take_it_refuses_it():
    with pytest.raises(TypeError, match="sku_is_part_number"):
        build_adapter(_source("woocommerce", sku_is_part_number=True))


# --------------------------------------------------------------------------- #
# Grouping: a SKU match admits, it does not force
# --------------------------------------------------------------------------- #

_SUPPLIERS: dict[str, uuid.UUID] = {}


def _listing(shop: str, title: str, price, sku: str | None, domain: str = "electrical") -> Listing:
    """A listing as the pipeline stores it: the adapter's RawItem, normalized."""
    norm = normalize_item(
        RawItem(
            source=shop,
            external_id=str(uuid.uuid4()),
            title=title,
            price_text=str(price),
            part_number=sku,
            raw={"sku": sku} if sku else {},
        ),
        domain,
    )
    return Listing(
        id=uuid.uuid4(),
        supplier_id=_SUPPLIERS.setdefault(shop, uuid.uuid4()),
        source=shop,
        source_type=SourceType.SCRAPED,
        external_id=norm.external_id,
        domain=domain,
        title_en=norm.title_en,
        title_ar=norm.title_ar,
        part_number=norm.part_number,
        price=Decimal(str(price)),
        images=[],
        attributes=norm.attributes,
    )


def _groups(listings: list[Listing]) -> list[list[str]]:
    assign_identifiers(listings)
    return sorted(
        sorted(f"{m.source}: {m.title_en}" for m in members)
        for members in _group_listings(listings).values()
    )


def test_a_sku_match_with_agreeing_titles_is_one_product_in_a_department_without_rules():
    """Electrical has no identifier rules: without the SKU these never meet."""
    a = _listing("shop-a", "Acme A9F77150 iC60N Circuit Breaker 1P 50A C-Curve", 420, "A9F77150")
    # Spelled differently by the other shop, folded like any identifier.
    b = _listing("shop-b", "Acme Circuit Breaker iC60N 1P 50A", 450, "a9f-77150")
    assign_identifiers([a, b])
    groups = _group_listings([a, b])
    assert len(groups) == 1
    (key,) = groups
    assert key.startswith("mpn:electrical:A9F77150:"), "scoped to the department, folded"


def test_without_the_sku_the_same_listings_stay_apart():
    a = _listing("shop-a", "Acme A9F77150 iC60N Circuit Breaker 1P 50A C-Curve", 420, None)
    b = _listing("shop-b", "Acme Circuit Breaker iC60N 1P 50A", 450, None)
    assert len(_groups([a, b])) == 2


def test_a_sku_match_whose_titles_disagree_is_not_merged():
    """A shared code admits only with title agreement, as for any identifier."""
    a = _listing("shop-a", "Acme Easy UPS Uninterruptible Power Supplies UPS", 9000, "SRVS10KI")
    b = _listing("shop-b", "Acme Tower Battery Cabinet Spare Fuse Kit", 8500, "SRVS10KI")
    assert len(_groups([a, b])) == 2


def test_a_value_veto_still_refuses_a_sku_match():
    """Agreeing words, different ratings: one shop's SKU was mistyped."""
    a = _listing("shop-a", "Acme iC60N Circuit Breaker 1P 50A C-Curve", 420, "A9F77150")
    b = _listing("shop-b", "Acme iC60N Circuit Breaker 1P 16A C-Curve", 300, "A9F77150")
    assert len(_groups([a, b])) == 2


def test_the_same_shop_never_merges_on_a_sku():
    a = _listing("shop-a", "Acme iC60N Circuit Breaker 1P 50A", 420, "A9F77150")
    b = _listing("shop-a", "Acme iC60N Circuit Breaker 1P 50A", 430, "A9F77150")
    assert len(_groups([a, b])) == 2


def test_a_price_veto_still_refuses_a_sku_match():
    a = _listing("shop-a", "Acme iC60N Circuit Breaker 1P 50A", 420, "A9F77150")
    b = _listing("shop-b", "Acme iC60N Circuit Breaker 1P 50A", 42000, "A9F77150")
    assert len(_groups([a, b])) == 2
