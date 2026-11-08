"""What a WooCommerce product carries beyond title and price, kept at no extra cost.

The Store API page the crawler already fetches holds brand, spec attributes,
variant options, sale and regular price, a stock count, tags and datasheet
links. Dropping them meant a shop's own page showed far more than ours, for no
saving at all. These pin what is kept and, as importantly, what is not invented.

The shop here is fictional; its payload is shaped like the real Store API's.
"""

from __future__ import annotations

import pytest
from worker.sources.base import SupplierInfo
from worker.sources.woocommerce import WooCommerceAdapter

SUPPLIER = SupplierInfo(slug="widget-works", name="Widget Works")


def _woo():
    return WooCommerceAdapter("widget-works", "https://widgetworks.test", SUPPLIER)


def _plain_product():
    return {
        "id": 1,
        "name": "Hex Bolt M3",
        "permalink": "https://widgetworks.test/product/hex-bolt-m3/",
        "prices": {"price": "2500", "currency_minor_unit": 2, "currency_code": "EGP"},
        "categories": [{"name": "Bolts"}],
        "images": [],
        "sku": "SKU1",
    }


def _rich_product(**overrides):
    """A variable product with a spec, a variation attribute, a brand, a sale and
    datasheets linked from its description."""
    product = {
        "id": 77,
        "name": "Widget Meter WM-3",
        "permalink": "https://widgetworks.test/product/wm-3/",
        "sku": "WM3-BLK",
        "type": "variable",
        "on_sale": True,
        "description": (
            "<p>&nbsp;A meter.</p>"
            '<p><a href="/wp-content/uploads/wm3-datasheet.pdf">Datasheet</a> and '
            '<a href="https://vendor.test/docs/WM3%20Manual.PDF?v=2">manual</a> and '
            '<a href="/wp-content/uploads/wm3-datasheet.pdf">again</a></p>'
        ),
        "short_description": "<p>Short.</p>",
        "prices": {
            "price": "11000",
            "regular_price": "13000",
            "sale_price": "11000",
            "price_range": {"min_amount": "11000", "max_amount": "15000"},
            "currency_code": "EGP",
            "currency_minor_unit": 2,
        },
        "images": [
            {"src": "https://widgetworks.test/a.jpg"},
            {"src": "https://widgetworks.test/b.jpg"},
        ],
        "categories": [{"name": "Meters &amp; Testers"}],
        "tags": [{"name": "Meter"}, {"name": "Tools &amp; Kits"}],
        "brands": [{"name": "Acme &amp; Sons", "slug": "acme"}],
        "attributes": [
            {"name": "Range", "has_variations": False, "terms": [{"name": "0&ndash;75%"}]},
            {
                "name": "Display",
                "has_variations": False,
                "terms": [{"name": "LCD"}, {"name": "LED"}],
            },
            {
                "name": "Color",
                "has_variations": True,
                "terms": [{"name": "Black"}, {"name": "White"}],
            },
        ],
        "variations": [{"id": 78}, {"id": 79}],
        "low_stock_remaining": None,
        "stock_availability": {"text": "<span>12 in stock</span>", "class": "in-stock"},
        "formatted_weight": "27 g",
        "formatted_dimensions": "N/A",
    }
    product.update(overrides)
    return product


def test_keeps_what_the_store_api_already_carries():
    raw = _woo()._to_raw(_rich_product(), "in stock")
    attrs = raw.raw
    assert raw.brand == "Acme & Sons"
    assert attrs["specs"] == {"Range": "0–75%", "Display": "LCD / LED"}
    # A variation attribute is a choice on the listing, not a fact about it.
    assert attrs["options"] == {"Color": ["Black", "White"]}
    assert attrs["variant_count"] == 2
    assert "variants" not in attrs  # the variations themselves are fetched once a cycle
    assert attrs["price_range"] == {"min": "110.00", "max": "150.00"}
    assert attrs["regular_price"] == "130.00"
    assert attrs["stock_quantity"] == 12
    assert attrs["weight"] == "27 g"
    assert "dimensions" not in attrs  # "N/A" is a placeholder, not a size
    assert attrs["tags"] == ["Meter", "Tools & Kits"]
    assert attrs["documents"] == [
        {
            "label": "Datasheet",
            "url": "https://widgetworks.test/wp-content/uploads/wm3-datasheet.pdf",
        },
        {"label": "manual", "url": "https://vendor.test/docs/WM3%20Manual.PDF?v=2"},
    ]
    assert len(raw.images) == 2


def test_price_category_and_sku_are_unchanged():
    """Enrichment rides alongside; it must not move the price or the category input."""
    raw = _woo()._to_raw(_rich_product(), "in stock")
    # prices.price, in major units — for a variable product its cheapest variation.
    assert raw.price_text == "110.00"
    assert raw.raw["sku"] == "WM3-BLK"
    assert raw.raw["categories"] == ["Meters &amp; Testers"]
    assert raw.category_hint == "Meters &amp; Testers"


def test_normalized_listing_carries_brand_and_details():
    norm = _woo().normalize(_woo()._to_raw(_rich_product(), "in stock"))
    assert norm.brand == "Acme & Sons"
    assert norm.attributes["specs"]["Range"] == "0–75%"
    assert str(norm.price) == "110.00"


def test_minimal_product_gains_no_empty_keys():
    """A shop that fills in nothing gets exactly the attributes it got before."""
    raw = _woo()._to_raw(_plain_product(), "in stock")
    assert raw.raw == {"platform": "woocommerce", "sku": "SKU1", "categories": ["Bolts"]}
    assert raw.brand is None


def test_no_regular_price_without_a_sale():
    raw = _woo()._to_raw(_rich_product(on_sale=False), "in stock")
    assert "regular_price" not in raw.raw


def test_a_single_price_is_not_a_range():
    prices = dict(_rich_product()["prices"], price_range={"min_amount": "100", "max_amount": "100"})
    raw = _woo()._to_raw(_rich_product(prices=prices), "in stock")
    assert "price_range" not in raw.raw


@pytest.mark.parametrize(
    "availability,low_stock,expected",
    [
        ("Only 3 left in stock", None, 3),
        ("<span>1,200 in stock</span>", None, 1200),
        ("", 4, 4),
        ("<span>In Stock</span>", None, None),
        ("", None, None),
    ],
)
def test_stock_quantity_is_what_the_shop_prints(availability, low_stock, expected):
    raw = _woo()._to_raw(
        _rich_product(
            stock_availability={"text": availability, "class": "in-stock"},
            low_stock_remaining=low_stock,
        ),
        "in stock",
    )
    assert raw.raw.get("stock_quantity") == expected


@pytest.mark.parametrize(
    "brands,attributes,expected",
    [
        ([{"name": "Generic"}], [], None),
        ([{"name": "China"}], [], None),
        ([], [{"name": "Brand", "has_variations": False, "terms": [{"name": "Zeta"}]}], "Zeta"),
        # Several brands under one attribute is a choice, not this item's brand.
        (
            [],
            [{"name": "Brand", "has_variations": True, "terms": [{"name": "A"}, {"name": "B"}]}],
            None,
        ),
        ([], [], None),
    ],
)
def test_brand(brands, attributes, expected):
    raw = _woo()._to_raw(_rich_product(brands=brands, attributes=attributes), "in stock")
    assert raw.brand == expected
    # A brand attribute is the brand, not a spec or an option.
    assert "Brand" not in raw.raw.get("specs", {})
    assert "Brand" not in raw.raw.get("options", {})


def test_blank_description_falls_back_to_short_description():
    """`description or short_description` let a blank-but-truthy description win."""
    raw = _woo()._to_raw(
        _rich_product(description="<p>&nbsp;</p>", short_description="<p>Handy.</p>"),
        "in stock",
    )
    assert raw.description == "Handy."


def test_documents_are_capped_and_only_web_links():
    links = "".join(f'<a href="https://widgetworks.test/d{i}.pdf">d</a>' for i in range(25))
    links += '<a href="mailto:x@widgetworks.test?subject=a.pdf">mail</a>'
    raw = _woo()._to_raw(_rich_product(description=links), "in stock")
    assert len(raw.raw["documents"]) == 10
    assert all(d["url"].startswith("https://") for d in raw.raw["documents"])


def test_the_description_keeps_its_lines():
    """Flattened to one line, a feature list became a wall of text on the product page."""
    raw = _woo()._to_raw(
        _rich_product(description="<p>A meter.</p><ul><li>Fast</li><li>Small</li></ul>"),
        "in stock",
    )
    assert raw.description == "A meter.\n• Fast\n• Small"


def test_description_spec_lines_join_the_attribute_specs():
    """Read as Shopify's are; the structured attribute wins a name both state."""
    description = (
        "<p>Operating Voltage: 5V</p><p>Range: 0-100%</p>"
        "<table><tr><td>Weight</td><td>27 g</td></tr></table>"
    )
    raw = _woo()._to_raw(
        _rich_product(description=description, short_description="<p>Interface: I2C</p>"),
        "in stock",
    )
    assert raw.raw["specs"] == {
        "Range": "0–75%",
        "Display": "LCD / LED",
        "Operating Voltage": "5V",
        "Weight": "27 g",
        "Interface": "I2C",
    }


def test_a_feature_bullet_is_not_a_spec():
    long = "Excellent rejection: provides better than 99 percent rejection across the whole band"
    raw = _woo()._to_raw(_rich_product(description=f"<ul><li>{long}</li></ul>"), "in stock")
    assert raw.raw["specs"] == {"Range": "0–75%", "Display": "LCD / LED"}


def test_videos_in_the_description_are_kept_once_each():
    """An embed and a link to the same video count once, in the shared form
    the Shopify adapter writes (canonical YouTube/Vimeo URLs)."""
    product = _rich_product(
        description=(
            '<iframe title="Wiring demo" src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
            '<p><a href="https://youtu.be/dQw4w9WgXcQ">watch</a> and '
            '<a href="https://vimeo.com/76979871">the teardown</a></p>'
        )
    )
    raw = _woo()._to_raw(product, "in stock")
    assert [video["url"] for video in raw.raw["videos"]] == [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://vimeo.com/76979871",
    ]


def test_no_videos_no_key():
    assert "videos" not in _woo()._to_raw(_plain_product(), "in stock").raw
