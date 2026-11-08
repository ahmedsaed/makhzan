"""WooCommerce Store API adapter.

Reusable across any WooCommerce shop — parameterized by base URL. The public
Store API (`/wp-json/wc/store/v1/products`) returns structured JSON (price,
stock, images, categories), so no HTML scraping is needed. The same payload also
carries brand, spec attributes, variant options, sale/regular price, stock count,
purchase quantities, tags and datasheet links; those are kept on the listing's
attributes, since fetching them costs nothing beyond the page already requested.

A few things are per shop rather than per product page, and are fetched once a
cycle as reference data (see `SourceAdapter.cycle_data_parts`), each behind its
own switch:
  - `variations`: every variation's price, stock and label, one page per hundred
    variations, attached to its parent. One listing per parent stays the rule.
  - `category_tree`: the shop's category tree, so a listing carries the shop's
    own breadcrumb (`shop_category_path`) for crosswalk authoring.
  - `price_breaks`: quantity-break prices from the Tiered Pricing plugin, which
    only the WordPress REST route (`/wp-json/wp/v2/product`) returns.
  - `contact`: the shop's address, phone and hours from its own JSON-LD.

Platform quirks handled here:
  - prices are integers in the currency's MINOR unit ("11000" @ minor_unit=2 ->
    110.00 EGP). Tiered-pricing rules, from a different plugin, are MAJOR units.
  - shops with "hide out of stock from catalog" enabled omit those items from the
    default feed, so we page each `stock_status` explicitly to capture (and badge)
    the out-of-stock and backorder tail instead of silently dropping it. Some
    hide them from the Store API altogether, whatever is asked; for those,
    `hides_out_of_stock` adds a pass over the WordPress route, which still lists
    them, so they are kept as out of stock instead of archived.
  - "contact for price": an item the shop sells but will not price online is
    unpurchasable with a price of "0". That is not free, and not unpriced by
    accident: it is `price_on_request`, and the price stays empty.
"""

from __future__ import annotations

import html
import re

from makhzan_schemas.contracts import RawItem
from makhzan_schemas.enums import SourceType

from makhzan_schemas.domains.crosswalks import fold_crosswalk, normalize_category_name

from worker import compatibility
from worker.contact import contact_from_html
from worker.http import CycleFetcher, get_json, get_response, make_client, total_pages
from worker.richtext import (
    documents_from_html,
    html_to_text,
    merge_specs,
    specs_from_html,
    videos_from_html,
    without_sections,
)
from worker.sources.base import CONTACT_PART, Page, SourceAdapter, SupplierInfo
from worker.util import strip_html

PER_PAGE = 100
#: The API exposes at most this many (contracts._ShopDetails).
_MAX_VIDEOS = 10
MAX_PAGES = 200  # safety cap (~20k products)

# Page every status: the default feed hides out-of-stock on some shops. The
# queried status is authoritative (is_in_stock is true for backorder too, so it
# can't distinguish these on its own).
STOCK_STATUSES = {
    "instock": "in stock",
    "outofstock": "out of stock",
    "onbackorder": "made to order",
}

#: The pass over `/wp-json/wp/v2/product` for a shop whose Store API leaves out
#: its out-of-stock products entirely (see `hides_out_of_stock`).
UNLISTED_OUT_OF_STOCK = "outofstock-unlisted"

#: Brand values a shop uses to say "no brand" — or, for "China", where it was
#: made. Stored as a brand they would make every unbranded part look like it came
#: from one manufacturer.
_NOT_A_BRAND = {"generic", "no brand", "unbranded", "oem", "other", "none", "n/a", "china"}

#: Attribute names that carry the brand on shops without the brands taxonomy.
_BRAND_ATTRIBUTES = {"brand", "manufacturer"}

#: Spec names under which a shop states the manufacturer and its part number, as
#: in a distributor-style "Manufacturer | Mfr. Part #" table. Compared with
#: everything but letters and "#" removed. A bare "Part Number" is not here: on
#: a shop's own page that is as likely to be its catalogue code.
_MANUFACTURER_KEYS = {"manufacturer", "mfr", "mfg"}
_MPN_KEYS = {
    "mfrpart#", "mfrpartno", "mfrpartnumber", "manufacturerpart#", "manufacturerpartno",
    "manufacturerpartnumber", "mpn",
}  # fmt: skip

#: "68 in stock", "Only 1 left in stock" — the count the shop itself prints.
_STOCK_COUNT = re.compile(r"(\d[\d,]*)\s+(?:left\s+)?in stock", re.I)

#: WooCommerce's purchase limit when the shop sets none. A maximum below it is the
#: managed stock count; at it, it says nothing.
_NO_PURCHASE_LIMIT = 9999

#: A catalogue page has no business linking more datasheets than this; past it
#: the description is a link farm and none of them is about this product.
_MAX_DOCUMENTS = 10
_MAX_VARIANTS = 50
_MAX_PRICE_BREAKS = 10

#: "Color: Black, Size: 0.8mm | Steel" -> one piece per option. A value can hold
#: commas itself ("Type: X2D , P2S"), so a split needs a "Name: " after it.
_OPTION_SPLIT = re.compile(r",\s*(?=[^,:]{1,40}:\s)")


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


def _amount(amount, minor: int) -> float | None:
    """A Store API amount as a number in major units; zero or unreadable is None."""
    text = _major(amount, minor)
    value = float(text) if text else 0.0
    return value if value > 0 else None


def _quantity_rule(value) -> int | None:
    """A purchase minimum or step worth stating: a whole number above one."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 1 else None


def _option_label(variation: str | None) -> str | None:
    """A variation's label as its option values: "Color: Black, Size: L" -> "Black / L"."""
    label = _text(variation)
    if not label:
        return None
    values = [part.split(":", 1)[-1].strip() for part in _OPTION_SPLIT.split(label)]
    return " / ".join(v for v in values if v) or label


def _spec_key(name: str) -> str:
    return re.sub(r"[^a-z#]", "", name.lower())


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
        variations: bool = True,
        category_tree: bool = True,
        contact: bool = True,
        price_breaks: bool = False,
        hides_out_of_stock: bool = False,
        strip_description_sections: tuple[str, ...] | list[str] = (),
        compatibility_from_titles: bool = False,
        stock_from_purchase_limit: bool = False,
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

        # Once-a-cycle reference data, each a few requests a cycle (see module doc).
        self.variations = variations
        self.category_tree = category_tree
        self.contact = contact
        #: Off by default: a full pass over the WordPress route, so it costs as
        #: many pages as the catalogue has hundreds of products. Worth it only on
        #: a shop that runs the Tiered Pricing plugin.
        self.price_breaks = price_breaks
        #: For a shop whose Store API omits out-of-stock products whatever is
        #: asked. Adds a partition over the WordPress route, which still lists
        #: them, so they stay listed as out of stock instead of being archived.
        self.hides_out_of_stock = hides_out_of_stock
        #: Headings of boilerplate sections the shop appends to every description.
        self.strip_description_sections = tuple(strip_description_sections)
        #: Read "for <printer>" from titles into `compatible_with`: for a
        #: spare-parts shop, whose titles say what a part fits.
        self.compatibility_from_titles = compatibility_from_titles
        #: Read the stock count from the purchase limit (`add_to_cart.maximum`).
        #: Off by default: `stock_quantity` is only for a count the shop shows the
        #: public, and a shop can manage stock without ever printing the number.
        self.stock_from_purchase_limit = stock_from_purchase_limit

        self._variants: dict[str, list[dict]] = {}
        self._category_parents: dict[str, list] = {}
        self._tiers: dict[str, dict] = {}
        self._variants_checked_at: str | None = None

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
        parts = list(STOCK_STATUSES)
        if self.hides_out_of_stock:
            # Last: it only confirms what the Store API passes did not return.
            parts.append(UNLISTED_OUT_OF_STOCK)
        return parts

    async def fetch_page(self, partition: str, page: int) -> Page:
        if partition == UNLISTED_OUT_OF_STOCK:
            return await self._fetch_unlisted(page)
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

    async def _fetch_unlisted(self, page: int) -> Page:
        """One page of the WordPress product route: the ids it marks out of stock.

        The WordPress route lists every published product, including the
        out-of-stock ones such a shop's Store API leaves out, and says which
        those are in `class_list`. Only the id and the classes are asked for, so
        a page of a hundred is a few kilobytes. It has no price or images, so
        nothing is created from it: it keeps the listings already stored alive,
        as out of stock.
        """
        url = f"{self.base_url}/wp-json/wp/v2/product"
        params = {"per_page": PER_PAGE, "page": page, "_fields": "id,class_list"}
        async with make_client() as client:
            response = await get_response(client, url, params)
        rows = response.json()
        rows = rows if isinstance(rows, list) else []
        ids = []
        for row in rows:
            if not isinstance(row, dict) or "id" not in row:
                continue
            classes = row.get("class_list") or []
            # An array, or an object keyed by position when WordPress filtered one out.
            classes = classes.values() if isinstance(classes, dict) else classes
            if "outofstock" in classes:
                ids.append(str(row["id"]))
        pages = total_pages(response)
        more = page < pages if pages is not None else len(rows) == PER_PAGE
        return Page([], has_more=more and page < MAX_PAGES, out_of_stock_ids=ids)

    # ------------------------------------------------------------------ #
    # Once-a-cycle reference data
    # ------------------------------------------------------------------ #

    def cycle_data_parts(self) -> list[str]:
        parts = []
        if self.category_tree:
            parts.append("categories")
        if self.variations:
            parts.append("variations")
        if self.price_breaks:
            parts.append("price_breaks")
        if self.contact:
            parts.append(CONTACT_PART)
        return parts

    async def fetch_cycle_part(self, fetcher: CycleFetcher, part: str) -> object:
        if part == "categories":
            rows = await self._paged(fetcher, part, "/wp-json/wc/store/v1/products/categories", {})
            # id -> [name, parent id]: enough to walk any category up to its root.
            return {
                str(c["id"]): [_text(c.get("name")) or "", c.get("parent") or 0]
                for c in rows
                if isinstance(c, dict) and "id" in c
            }
        if part == "variations":
            rows = await self._paged(
                fetcher, part, "/wp-json/wc/store/v1/products", {"type": "variation"}
            )
            by_parent: dict[str, list[dict]] = {}
            for row in rows:
                if isinstance(row, dict) and row.get("parent"):
                    by_parent.setdefault(str(row["parent"]), []).append(self._variant(row))
            return by_parent
        if part == "price_breaks":
            # Only the tier fields: a whole page of a hundred is then a few kilobytes.
            fields = ",".join(
                ("id", "tiered_pricing_type")
                + tuple(f"tiered_pricing_{kind}_rules" for kind in ("fixed", "percentage"))
            )
            rows = await self._paged(fetcher, part, "/wp-json/wp/v2/product", {"_fields": fields})
            tiers: dict[str, dict] = {}
            for row in rows:
                if not isinstance(row, dict) or "id" not in row:
                    continue
                kind = row.get("tiered_pricing_type") or "fixed"
                rules = row.get(f"tiered_pricing_{kind}_rules")
                # An empty rule set comes back as [] rather than {}.
                if isinstance(rules, dict) and rules:
                    tiers[str(row["id"])] = {"type": kind, "rules": rules}
            return tiers
        if part == CONTACT_PART:
            response = await fetcher.get(part, f"{self.base_url}/")
            return contact_from_html(response.text, str(response.url))
        raise ValueError(f"unknown cycle data part {part!r}")

    async def _paged(self, fetcher: CycleFetcher, label: str, path: str, params: dict) -> list:
        """Every row of a paged WordPress collection, a hundred at a time."""
        rows: list = []
        for page in range(1, MAX_PAGES + 1):
            response = await fetcher.get(
                label, f"{self.base_url}{path}", {**params, "per_page": PER_PAGE, "page": page}
            )
            batch = response.json()
            if not isinstance(batch, list):
                raise ValueError(f"{path} returned {type(batch).__name__}, not a list")
            rows.extend(batch)
            pages = total_pages(response)
            # The header when there is one: past the last page WordPress answers
            # 400, not an empty list.
            if (pages is not None and page >= pages) or len(batch) < PER_PAGE:
                break
        return rows

    def use_cycle_data(self, data: dict, fetched_at: dict[str, str] | None = None) -> None:
        def part(name: str, wanted: bool) -> dict:
            value = data.get(name) if wanted else None
            return value if isinstance(value, dict) else {}

        self._variants = part("variations", self.variations)
        self._category_parents = part("categories", self.category_tree)
        self._tiers = part("price_breaks", self.price_breaks)
        #: When the variants were read. They come from once-a-cycle data, so can
        #: be weeks older than the listing's own price, and say so beside it.
        self._variants_checked_at = (fetched_at or {}).get("variations") if self._variants else None

    def _variant(self, v: dict) -> dict:
        """One variation as the shared `variants` entry."""
        prices = v.get("prices") or {}
        minor = prices.get("currency_minor_unit", 2)
        out: dict = {
            "title": _option_label(v.get("variation")) or _text(v.get("name")) or "",
            # Unpurchasable at "0" is "ask the shop", as for a product.
            "price": _amount(prices.get("price"), minor),
            "in_stock": bool(v.get("is_in_stock")),
        }
        quantity = self._stock_quantity(v)
        if quantity is not None:
            out["stock_quantity"] = quantity
        sku = _text(v.get("sku"))
        if sku:
            out["sku"] = sku[:80]
        return out

    # ------------------------------------------------------------------ #
    # One product
    # ------------------------------------------------------------------ #

    def _to_raw(self, p: dict, availability: str) -> RawItem:
        prices = p.get("prices") or {}
        price_text = None
        raw_price = prices.get("price")
        if raw_price not in (None, ""):
            minor = prices.get("currency_minor_unit", 2)
            price_text = f"{int(raw_price) / (10**minor):.2f}"

        categories = [c.get("name") for c in p.get("categories", []) if c.get("name")]
        images = [img["src"] for img in p.get("images", []) if img.get("src")]
        description = without_sections(p.get("description"), self.strip_description_sections)

        # The SKU is the shop's private catalogue code, not an MPN: kept for
        # reference, never used to group listings across shops.
        raw = {"platform": "woocommerce", "sku": p.get("sku"), "categories": categories}
        details, manufacturer = self._details(p, prices, description)
        raw.update(details)
        if raw.get("price_on_request"):
            price_text = None

        return RawItem(
            source=self.source_id,
            external_id=str(p["id"]),
            source_url=p.get("permalink"),
            title=p.get("name"),
            # Checked one at a time, not `description or short_description`: a
            # description of "<p>&nbsp;</p>" is truthy and flattens to nothing,
            # which would hide a perfectly good short description behind it.
            # Line by line, as the Shopify and Odoo shops' are: a list or a spec
            # table stays one item per line on the product page.
            description=(html_to_text(description) or html_to_text(p.get("short_description"))),
            # The brand the shop files it under, else the manufacturer its own
            # spec table names.
            brand=self._brand(p) or manufacturer,
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

    def _stock_quantity(self, p: dict) -> int | None:
        """The stock count the shop shows the public, if it shows one.

        "Only 3 left in stock" is `low_stock_remaining`; "68 in stock" is only in
        the availability text. The purchase limit is a count too on a shop that
        manages stock, but the shop need not print it, so it is read only where
        `stock_from_purchase_limit` says this shop's counts are public.
        """
        quantity = p.get("low_stock_remaining")
        if not isinstance(quantity, int):
            text = strip_html((p.get("stock_availability") or {}).get("text")) or ""
            match = _STOCK_COUNT.search(text)
            quantity = int(match.group(1).replace(",", "")) if match else None
        if quantity is None and self.stock_from_purchase_limit and not p.get("sold_individually"):
            # Sold individually caps every order at one: that is a rule, not a count.
            maximum = (p.get("add_to_cart") or {}).get("maximum")
            if isinstance(maximum, int) and 0 < maximum < _NO_PURCHASE_LIMIT:
                quantity = maximum
        return quantity if quantity is not None and quantity >= 0 else None

    def _category_path(self, p: dict) -> list[str]:
        """The shop's breadcrumb for this product: its deepest category, root first."""
        if not self._category_parents:
            return []
        best: list[str] = []
        for category in p.get("categories") or []:
            path: list[str] = []
            node = str(category.get("id"))
            while node in self._category_parents and len(path) < 10:
                name, parent = self._category_parents[node]
                path.insert(0, name)
                node = str(parent)
            if len(path) > len(best):
                best = path
        return [name for name in best if name]

    def _price_breaks(self, p: dict, price: float | None) -> list[dict]:
        """Quantity-break prices, ascending: buy at least `min_quantity`, pay `price` each."""
        tier = self._tiers.get(str(p.get("id")))
        if not tier:
            return []
        out = []
        for quantity, value in tier["rules"].items():
            try:
                quantity, value = int(quantity), float(value)
            except (TypeError, ValueError):
                continue
            if tier["type"] == "percentage":
                if price is None:
                    continue
                value = round(price * (1 - value / 100), 2)
            # A "break" that is not cheaper than the single price is not a break.
            if quantity > 1 and value > 0 and (price is None or value < price):
                out.append({"min_quantity": quantity, "price": value})
        return sorted(out, key=lambda b: b["min_quantity"])[:_MAX_PRICE_BREAKS]

    def _details(self, p: dict, prices: dict, description: str | None) -> tuple[dict, str | None]:
        """What the shop publishes about a product beyond its title and price.

        All of it is already in the Store API page we fetch, or in the reference
        data fetched once a cycle. Only keys with something in them are written,
        so a listing's attributes stay as small as what the shop actually filled
        in. Also returns the manufacturer the shop's spec table names, if any.
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
        # Then the description's own spec table and "Name: value" lines, by the
        # same reader (and caps) as Shopify's. The attributes are the shop's
        # structured statement, so a name both give keeps the attribute's value.
        for field in (description, p.get("short_description")):
            specs = merge_specs(specs, specs_from_html(field))
        if specs:
            out["specs"] = specs
        if options:
            out["options"] = options
        if p.get("variations"):
            out["variant_count"] = len(p["variations"])
            variants = self._variants.get(str(p.get("id")))
            if variants:
                out["variants"] = variants[:_MAX_VARIANTS]
                if self._variants_checked_at:
                    out["variants_checked_at"] = self._variants_checked_at

        # A manufacturer part number the shop states in so many words. Kept for
        # display and search only: grouping does not read it (yet).
        manufacturer = None
        for name, value in specs.items():
            key = _spec_key(name)
            if key in _MPN_KEYS and "mfr_part_number" not in out and len(value) <= 60:
                out["mfr_part_number"] = value
            elif key in _MANUFACTURER_KEYS and manufacturer is None:
                if value.lower() not in _NOT_A_BRAND:
                    manufacturer = value[:120]

        # "Contact for price": the shop sells it but will not price it online.
        price = _amount(prices.get("price"), minor)
        if p.get("is_purchasable") is False and price is None:
            out["price_on_request"] = True

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
        if p.get("on_sale") and regular and current and float(regular) > float(current) > 0:
            out["regular_price"] = regular
        if breaks := self._price_breaks(p, price):
            out["price_breaks"] = breaks

        # The unit of sale: a shop pricing resistors per piece but selling them
        # in tens says so here, and a per-piece price alone would mislead.
        add_to_cart = p.get("add_to_cart") or {}
        if minimum := _quantity_rule(add_to_cart.get("minimum")):
            out["min_quantity"] = minimum
        if step := _quantity_rule(add_to_cart.get("multiple_of")):
            out["multiple_of"] = step

        quantity = self._stock_quantity(p)
        if quantity is not None:
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

        # What a part fits, for display. Never a grouping signal.
        fits = compatibility.merge(
            compatibility.from_options(options),
            compatibility.from_title(_text(p.get("name")))
            if self.compatibility_from_titles
            else [],
        )
        if fits:
            out["compatible_with"] = fits

        if path := self._category_path(p):
            out["shop_category_path"] = path

        # Datasheets and manuals linked from the description: flattening it to
        # text keeps the words and drops the links, which are the useful part.
        documents: list[dict[str, str]] = []
        for field in (description, p.get("short_description")):
            for doc in documents_from_html(field, self.base_url):
                if all(doc["url"] != known["url"] for known in documents):
                    documents.append(doc)
        if documents:
            out["documents"] = documents[:_MAX_DOCUMENTS]

        # Product videos the description embeds or links, as the Shopify shop's
        # are: canonical YouTube/Vimeo URLs, so one video counts once.
        videos: list[dict[str, str]] = []
        for field in (description, p.get("short_description")):
            for video in videos_from_html(field):
                if all(video["url"] != known["url"] for known in videos):
                    videos.append(video)
        if videos:
            out["videos"] = videos[:_MAX_VIDEOS]

        return out, manufacturer
