"""What a shop publishes beyond title and price, read from pages we already fetch.

Shopify's products.json and Odoo's listing cards carry descriptions, specs,
brands, datasheets, variants and product codes. None of it may cost a request:
every test here works on a payload the crawler already has.

The shops are fictional.
"""

from __future__ import annotations

from selectolax.parser import HTMLParser

from worker.normalize import clean_description, normalize_item
from worker.richtext import documents_from_html, html_to_text, specs_from_html
from worker.sources.base import SupplierInfo
from worker.sources.odoo import OdooAdapter
from worker.sources.shopify import ShopifyAdapter
from worker.util import strip_html

# --------------------------------------------------------------------------- #
# Rich text
# --------------------------------------------------------------------------- #

BODY = """
<p>A <strong>5V</strong> relay board for hobby projects.</p>
<p><iframe src="https://video.example.test/embed/1"></iframe></p>
<h3>Specifications</h3>
<table>
  <tr><th>Parameter</th><th>Specification</th></tr>
  <tr><td>Coil Voltage:</td><td>5 V DC</td></tr>
  <tr><td>Contact Rating</td><td>10 A / 250 V AC</td></tr>
</table>
<ul>
  <li>Channels: 4</li>
  <li>Opto-isolated inputs</li>
  <li>Excellent switching: rated for a hundred thousand operations at full load, by the maker</li>
</ul>
<table>
  <tr><td>Pin</td><td>Function</td></tr>
  <tr><td>IN1</td><td>Relay 1 control</td></tr>
</table>
<p>Weight: 60 g<br>Coil Voltage: 12 V</p>
<p><a href="/files/relay-datasheet.pdf">Datasheet</a> · <a href="https://other.test/x">shop</a></p>
"""


def test_html_to_text_keeps_the_lines_the_shop_wrote():
    text = html_to_text(BODY)
    lines = text.split("\n")
    assert lines[0] == "A 5V relay board for hobby projects.", "inline markup must not break a line"
    assert "Specifications" in lines
    assert "Coil Voltage: 5 V DC" in lines, "a two-column row reads as name: value"
    assert "• Channels: 4" in lines
    assert "Weight: 60 g" in lines and "Coil Voltage: 12 V" in lines, "<br> is a line break"
    assert "iframe" not in text and "video.example" not in text
    assert "" not in lines


def test_specs_come_from_spec_tables_and_name_value_lines():
    specs = specs_from_html(BODY)
    assert specs == {
        "Coil Voltage": "5 V DC",
        "Contact Rating": "10 A / 250 V AC",
        "Channels": "4",
        "Weight": "60 g",
    }


def test_the_first_statement_of_a_spec_wins():
    """The table says 5 V; a later line repeating the name does not overwrite it."""
    assert specs_from_html(BODY)["Coil Voltage"] == "5 V DC"


def test_a_pinout_is_not_specs():
    assert "IN1" not in specs_from_html(BODY)
    wiring = "<table><tr><td>Wire Color</td><td>Function</td></tr><tr><td>Brown</td><td>+V</td></tr></table>"
    assert specs_from_html(wiring) == {}


def test_a_feature_bullet_is_not_a_spec():
    """Same "Name: value" shape, but a sentence — only its length gives it away."""
    assert not any(k.startswith("Excellent") for k in specs_from_html(BODY))


def test_datasheet_links_are_kept_absolute():
    assert documents_from_html(BODY, "https://shop.volta-parts.test") == [
        {"label": "Datasheet", "url": "https://shop.volta-parts.test/files/relay-datasheet.pdf"}
    ]


def test_nothing_in_nothing_out():
    assert html_to_text(None) is None and html_to_text("<p> </p>") is None
    assert specs_from_html(None) == {} and documents_from_html("", "https://x.test") == []


def test_descriptions_keep_line_breaks_through_normalize():
    assert clean_description("Line one  \n\n  Line &amp; two\n") == "Line one\nLine & two"
    assert clean_description("one line, as before") == "one line, as before"
    assert clean_description(" \n ") is None


def test_strip_html_still_flattens_to_one_line():
    """Its callers expect one line: the newlines in an HTML fragment are
    indentation, not the shop's line breaks, and descriptions now keep breaks."""
    assert strip_html("<p>Relay\n   board</p>\n<p>5V</p>") == "Relay board 5V"


# --------------------------------------------------------------------------- #
# Shopify
# --------------------------------------------------------------------------- #

VOLTA = SupplierInfo(slug="volta-parts", name="Volta Parts Egypt")


def _volta():
    return ShopifyAdapter("volta-parts", "https://shop.volta-parts.test", VOLTA)


def _product(**kw):
    product = {
        "id": 7,
        "handle": "relay-board",
        "title": "4-Channel 5V Relay Board",
        "body_html": BODY,
        "vendor": "Volta Parts Egypt",
        "product_type": "relay",
        "tags": ["relay", "arduino"],
        "options": [{"name": "Title", "position": 1, "values": ["Default Title"]}],
        "variants": [
            {
                "title": "Default Title",
                "price": "150.00",
                "compare_at_price": "180.00",
                "available": True,
                "sku": "VP-RLY4",
            }
        ],
        "images": [
            {"src": "https://cdn.example.test/a.jpg"},
            {"src": "https://cdn.example.test/b.jpg"},
        ],
    }
    product.update(kw)
    return product


def test_shopify_reads_specs_documents_and_compare_at_price():
    raw = _volta()._to_raw(_product())
    assert raw.raw["specs"]["Contact Rating"] == "10 A / 250 V AC"
    assert raw.raw["documents"][0]["label"] == "Datasheet"
    assert raw.raw["compare_at_price"] == "180.00"
    assert raw.images == ["https://cdn.example.test/a.jpg", "https://cdn.example.test/b.jpg"]


def test_shopify_price_is_still_the_first_variants():
    norm = normalize_item(_volta()._to_raw(_product()))
    assert str(norm.price) == "150.00", "the compare-at price must never become the price"


def test_a_stale_compare_at_price_is_no_discount():
    variant = {"price": "150.00", "compare_at_price": "150.00", "available": True}
    raw = _volta()._to_raw(_product(variants=[variant]))
    assert "compare_at_price" not in raw.raw


def test_the_description_reaches_the_listing_line_by_line():
    norm = normalize_item(_volta()._to_raw(_product()))
    assert "Contact Rating: 10 A / 250 V AC" in norm.description_en.split("\n")


def test_the_shop_naming_itself_is_not_a_brand():
    """Shopify defaults `vendor` to the store's name; most shops never change it."""
    adapter = _volta()
    for vendor in ("Volta Parts Egypt", "Volta Parts Egypt ", "Volta Parts Egypt (Volta Kits)"):
        assert adapter._to_raw(_product(vendor=vendor, body_html="")).brand is None
    # The host is the shop's name too.
    assert adapter._to_raw(_product(vendor="volta-parts", body_html="")).brand is None


def test_a_real_vendor_is_the_brand():
    adapter = _volta()
    assert adapter._to_raw(_product(vendor="Acme Relays")).brand == "Acme Relays"
    assert adapter._to_raw(_product(vendor="TI")).brand == "TI", "short brands are brands"


def test_the_spec_tables_brand_stands_in_for_the_shops_own_name():
    body = "<table><tr><td>Brand</td><td>Acme</td></tr><tr><td>Model</td><td>R4</td></tr></table>"
    assert _volta()._to_raw(_product(body_html=body)).brand == "Acme"
    generic = "<ul><li>Brand: Generic</li></ul>"
    assert _volta()._to_raw(_product(body_html=generic)).brand is None


def test_variants_and_options_are_kept_when_there_is_a_choice():
    product = _product(
        options=[{"name": "Color ", "values": ["Red", "Black"]}],
        variants=[
            {"title": "Red", "price": "150.00", "sku": "R", "available": True},
            {"title": "Black", "price": "155.00", "sku": "", "available": False},
        ],
    )
    raw = _volta()._to_raw(product)
    assert raw.raw["options"] == {"Color": ["Red", "Black"]}
    assert raw.raw["variants"] == [
        {"title": "Red", "price": "150.00", "sku": "R", "available": True},
        {"title": "Black", "price": "155.00", "available": False},
    ]
    assert raw.price_text == "150.00" and raw.availability_text == "in stock"


def test_a_product_without_options_records_none():
    raw = _volta()._to_raw(_product())
    assert "options" not in raw.raw and "variants" not in raw.raw


# --------------------------------------------------------------------------- #
# Odoo
# --------------------------------------------------------------------------- #

CARD = """
<td class="oe_product">
  <form itemscope itemtype="http://schema.org/Product">
    <a class="oe_product_image_link" itemprop="url" href="/shop/psu-12v-5a-switching-power-supply-412?page=7">
      <img src="/web/image/product.template/412/image_512/%5BPSU.12V.5A%5D%20Switching%20Power%20Supply?unique=abc"
           alt="[PSU.12V.5A] Switching Power Supply 12V 5A" itemprop="image">
    </a>
    <h6><a itemprop="name" href="/shop/psu-12v-5a-switching-power-supply-412?page=7">Switching Power Supply 12V 5A</a></h6>
    <div class="oe_subdescription"><div itemprop="description">Switching Mode Power Supply<br>1 YEAR Warranty<br>Ampix&reg; Brand</div></div>
    <div class="product_price" itemprop="offers" itemscope itemtype="http://schema.org/Offer">
      <del><em><span class="oe_currency_value">450.00</span>&nbsp;EGP</em></del>
      <span><span class="oe_currency_value">395.00</span>&nbsp;EGP</span>
      <span itemprop="price" style="display:none;">395.0</span>
      <span itemprop="priceCurrency" style="display:none;">EGP</span>
    </div>
  </form>
</td>
"""

OHMIC = SupplierInfo(slug="ohmic-supply", name="Ohmic Supply")


def _card(html=CARD):
    adapter = OdooAdapter("ohmic-supply", "https://www.ohmic-supply.test", OHMIC)
    # Odoo lays the grid out as a table, and a parser drops a <td> found outside one.
    page = HTMLParser(f"<table><tr>{html}</tr></table>")
    return adapter._to_raw(page.css_first(".oe_product"))


def test_odoo_subtitle_lines_are_no_longer_run_together():
    raw = _card()
    assert raw.description == "Switching Mode Power Supply\n1 YEAR Warranty\nAmpix® Brand"


def test_odoo_reads_brand_and_warranty_from_the_subtitle():
    raw = _card()
    assert raw.brand == "Ampix"
    assert raw.raw["warranty"] == "1 YEAR Warranty"


def test_odoo_internal_reference_comes_from_the_image_alt():
    assert _card().raw["sku"] == "PSU.12V.5A"


def test_odoo_compare_at_price_is_the_struck_through_one():
    raw = _card()
    assert raw.raw["compare_at_price"] == "450.00"
    assert raw.price_text == "395.0", "the price charged is still the microdata price"


def test_odoo_source_url_drops_the_listing_page():
    """The card links carry ?page=N, which moves as the catalogue shifts."""
    assert (
        _card().source_url
        == "https://www.ohmic-supply.test/shop/psu-12v-5a-switching-power-supply-412"
    )


def test_odoo_card_without_extras_records_none():
    bare = """<div class="oe_product"><a href="/shop/widget-5"><span itemprop="name">Widget</span></a>
              <span itemprop="price">10.0</span></div>"""
    raw = _card(bare)
    assert raw.brand is None and raw.description is None
    assert raw.raw == {"platform": "odoo", "category": None}


def test_brand_new_and_original_brand_name_no_brand():
    for subtitle in (
        "Brand New",
        "Original Brand",
        "Made in Japan",
        "Rechargeable BatteryBrand New",
    ):
        html = CARD.replace(
            "Switching Mode Power Supply<br>1 YEAR Warranty<br>Ampix&reg; Brand", subtitle
        )
        assert _card(html).brand is None, subtitle


def test_original_brand_before_the_name_is_read_too():
    html = CARD.replace("Ampix&reg; Brand", "Original Brand Ampix&reg;")
    assert _card(html).brand == "Ampix"
