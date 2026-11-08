"""Pydantic contracts.

Two families:
  - Ingestion DTOs (RawItem -> NormalizedListing): the pipeline's internal
    hand-off shape, produced by source adapters and consumed by the upsert step.
  - API read models: what the FastAPI backend returns to the frontend.

Keeping these here (next to the ORM) is what lets the writer (ingestion) and
the reader (api) share one definition of truth.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from makhzan_schemas.enums import (
    DEFAULT_CURRENCY,
    ListingStatus,
    StockSignal,
)
from makhzan_schemas.search import category_ref

# --------------------------------------------------------------------------- #
# Ingestion DTOs
# --------------------------------------------------------------------------- #


class RawItem(BaseModel):
    """Loosely-typed output of a source adapter's fetch/parse step.

    Adapters do source-specific extraction and emit these; normalization is a
    shared step so cleaning/confidence rules stay consistent across all sources.
    Everything the adapter couldn't map cleanly goes into `raw`.
    """

    source: str  # adapter id, e.g. "shop-a"
    external_id: str | None = None  # supplier's own SKU/id for the item
    source_url: str | None = None

    title: str | None = None  # as-seen, language unknown
    description: str | None = None
    part_number: str | None = None
    brand: str | None = None

    price_text: str | None = None  # unparsed, e.g. "٣٥٠ ج.م" or "350 EGP"
    currency: str | None = None
    availability_text: str | None = None  # unparsed stock hint
    unit_text: str | None = None
    category_hint: str | None = None  # supplier's own category label

    images: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)  # everything else, kept for review


class NormalizedListing(BaseModel):
    """Cleaned, structured result of normalization — ready to upsert.

    Carries `confidence` and optional `review_reasons`; the pipeline decides
    whether it goes live or into the review queue.
    """

    source: str
    external_id: str | None = None
    source_url: str | None = None

    title_en: str | None = None
    title_ar: str | None = None
    description_en: str | None = None
    description_ar: str | None = None
    part_number: str | None = None
    brand: str | None = None

    price: Decimal | None = None
    currency: str = DEFAULT_CURRENCY
    unit: str | None = None
    stock_signal: StockSignal = StockSignal.UNKNOWN

    category_slug: str | None = None  # resolved to a Category at upsert
    images: list[str] = Field(default_factory=list)
    attributes: dict = Field(default_factory=dict)

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review_reasons: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# API read models
# --------------------------------------------------------------------------- #


def _https(value: object) -> str | None:
    """A web link a page may show: https only, no whitespace, a sane length."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url.lower().startswith("https://") or len(url) > 2000 or any(c.isspace() for c in url):
        return None
    return url


class SupplierContact(BaseModel):
    """How to reach a shop, as the shop publishes it, with where and when it was read.

    Validated from `Supplier.contact`, which the crawler fills from the shop's
    own structured data. Text is the shop's own, in whatever language it wrote
    it; only its shape is checked here.
    """

    address: str | None = None
    area: str | None = None
    governorate: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    opening_hours: list[str] = Field(default_factory=list)
    source_url: str | None = None
    fetched_at: datetime | None = None

    @field_validator("address", "area", "governorate", "phone", "whatsapp", "email", mode="before")
    @classmethod
    def _text(cls, value: object) -> str | None:
        return _short_text(value) if not isinstance(value, int | float) else None

    @field_validator("opening_hours", mode="before")
    @classmethod
    def _hours(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [h for h in (_short_text(v) for v in value if isinstance(v, str)) if h][:14]

    @field_validator("source_url", mode="before")
    @classmethod
    def _url(cls, value: object) -> str | None:
        return _https(value)

    @field_validator("fetched_at", mode="before")
    @classmethod
    def _when(cls, value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            return None


def public_contact(value: object) -> SupplierContact | None:
    """A supplier's stored contact, validated; None when it holds nothing to show."""
    if not isinstance(value, dict):
        return None
    try:
        contact = SupplierContact.model_validate(value)
    except ValueError:
        return None
    shown = contact.model_dump(exclude={"source_url", "fetched_at"})
    return contact if any(shown.values()) else None


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    name_ar: str | None = None
    area: str | None = None
    governorate: str | None = None
    website_url: str | None = None
    #: The shop's own published contact details (address, phone, hours).
    contact: SupplierContact | None = None

    @field_validator("contact", mode="before")
    @classmethod
    def _contact(cls, value: object) -> SupplierContact | None:
        return public_contact(value)


class CategoryRead(BaseModel):
    """A category as embedded in a listing or product payload.

    Carries `domain` and the derived `ref` because a bare slug does not identify
    a category: slugs are unique per domain, so "measurement" names both an
    electronics leaf and a tools one. A consumer that builds a browse link from
    `slug` alone silently filters across every vertical that uses that slug.
    """

    model_config = ConfigDict(from_attributes=True)

    domain: str
    slug: str
    name_en: str
    name_ar: str | None = None

    @computed_field
    @property
    def ref(self) -> str:
        """Canonical `domain:slug` identity — what browse links and filters use."""
        # Single definition, shared with the search documents and /categories:
        # two spellings of a ref is how one of them ends up subtly different.
        # `slug` is required here, so this never falls through to None.
        return category_ref(self.domain, self.slug) or self.slug


class DocumentRead(BaseModel):
    """A file the shop links from its listing — a datasheet or a manual."""

    url: str
    label: str | None = None


# What a listing's `attributes` may show the public, and nothing else. The bag
# also holds the shop's crossed-out "before" price (no discounts are shown: some
# are standing markups) and internal keys (SKUs, platform ids), so it is never
# passed through wholesale.
_MAX_SPECS = 40
_MAX_DOCUMENTS = 10
_MAX_TEXT = 200


def _short_text(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    text = str(value).strip()
    return text if text and len(text) <= _MAX_TEXT else None


def public_specs(attributes: object) -> dict[str, str]:
    """The shop's own name → value spec rows, from a listing's attributes."""
    specs = attributes.get("specs") if isinstance(attributes, dict) else None
    if not isinstance(specs, dict):
        return {}
    out: dict[str, str] = {}
    for raw_name, raw_value in specs.items():
        name, value = _short_text(raw_name), _short_text(raw_value)
        if name and value and len(out) < _MAX_SPECS:
            out[name] = value
    return out


def public_documents(attributes: object) -> list[DocumentRead]:
    """Datasheet links from a listing's attributes: bare URLs or {url, label}."""
    docs = attributes.get("documents") if isinstance(attributes, dict) else None
    if not isinstance(docs, list):
        return []
    out: list[DocumentRead] = []
    seen: set[str] = set()
    for doc in docs:
        url, label = doc, None
        if isinstance(doc, dict):
            url, label = doc.get("url"), _short_text(doc.get("label"))
        url = url.strip() if isinstance(url, str) else ""
        # Only web links: anything else (javascript:, data:) is not a shop's file.
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(DocumentRead(url=url, label=label))
        if len(out) >= _MAX_DOCUMENTS:
            break
    return out


_MAX_VARIANTS = 50
_MAX_PRICE_BREAKS = 10
_MAX_COMPATIBLE = 20
_MAX_VIDEOS = 10


class VariantRead(BaseModel):
    """One option of a listing ("1 kg / Black"), with its own price and stock."""

    title: str
    price: float | None = None
    in_stock: bool | None = None
    stock_quantity: int | None = None
    sku: str | None = None


class PriceBreakRead(BaseModel):
    """Buy at least `min_quantity` and pay `price` each."""

    min_quantity: int
    price: float


class VideoRead(BaseModel):
    """A video the shop links from its listing."""

    url: str
    label: str | None = None


def _attribute(attributes: object, key: str) -> object:
    return attributes.get(key) if isinstance(attributes, dict) else None


def _number(value: object) -> float | None:
    """A non-negative, finite number, from a number or a numeric string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value) if value >= 0 else None


def _whole(value: object) -> int | None:
    """A non-negative whole number, from an int, an integral float or a digit string."""
    number = _number(value)
    return int(number) if number is not None and number == int(number) else None


def _variant(value: object) -> VariantRead | None:
    if not isinstance(value, dict):
        return None
    title = _short_text(value.get("title"))
    if not title:
        return None
    in_stock = value.get("in_stock")
    return VariantRead(
        title=title,
        price=_number(value.get("price")) or None,
        in_stock=in_stock if isinstance(in_stock, bool) else None,
        stock_quantity=_whole(value.get("stock_quantity")),
        sku=_short_text(value.get("sku")),
    )


def _price_break(value: object) -> PriceBreakRead | None:
    if not isinstance(value, dict):
        return None
    quantity, price = _whole(value.get("min_quantity")), _number(value.get("price"))
    if quantity is None or quantity < 2 or not price:
        return None
    return PriceBreakRead(min_quantity=quantity, price=price)


def _video(value: object) -> VideoRead | None:
    if not isinstance(value, dict):
        return None
    url = _https(value.get("url"))
    return VideoRead(url=url, label=_short_text(value.get("label"))) if url else None


def _items(attributes: object, key: str, read, cap: int) -> list:
    values = _attribute(attributes, key)
    if not isinstance(values, list):
        return []
    return [item for item in (read(v) for v in values) if item is not None][:cap]


class _ShopDetails(BaseModel):
    """What the shop published beyond title and price, read from the listing's attributes.

    Every field validates from the ORM's `attributes` column and keeps only the
    whitelisted, well-formed part of it — links https only, numbers numeric,
    lists capped — then serialises under its own name. The shop's breadcrumb
    (`shop_category_path`) and its private codes stay internal.
    """

    specs: dict[str, str] = Field(default_factory=dict, validation_alias="attributes")
    documents: list[DocumentRead] = Field(default_factory=list, validation_alias="attributes")
    #: The unit of sale: the shop sells at least this many...
    min_quantity: int | None = Field(default=None, validation_alias="attributes")
    #: ...and only in multiples of this. `price` stays the price of one.
    multiple_of: int | None = Field(default=None, validation_alias="attributes")
    #: The shop sells it but publishes no price: ask the shop. `price` is null.
    price_on_request: bool = Field(default=False, validation_alias="attributes")
    #: A stock count the shop itself shows the public.
    stock_quantity: int | None = Field(default=None, validation_alias="attributes")
    variants: list[VariantRead] = Field(default_factory=list, validation_alias="attributes")
    price_breaks: list[PriceBreakRead] = Field(default_factory=list, validation_alias="attributes")
    #: What the part fits, as the shop states it. Display only.
    compatible_with: list[str] = Field(default_factory=list, validation_alias="attributes")
    ships_from_abroad: bool | None = Field(default=None, validation_alias="attributes")
    #: A manufacturer part number the shop states explicitly.
    mfr_part_number: str | None = Field(default=None, validation_alias="attributes")
    videos: list[VideoRead] = Field(default_factory=list, validation_alias="attributes")

    @field_validator("specs", mode="before")
    @classmethod
    def _specs(cls, value: object) -> dict[str, str]:
        return public_specs(value)

    @field_validator("documents", mode="before")
    @classmethod
    def _documents(cls, value: object) -> list[DocumentRead]:
        return public_documents(value)

    @field_validator("min_quantity", "multiple_of", mode="before")
    @classmethod
    def _quantity_rule(cls, value: object, info: ValidationInfo) -> int | None:
        number = _whole(_attribute(value, info.field_name))
        return number if number is not None and number > 1 else None

    @field_validator("stock_quantity", mode="before")
    @classmethod
    def _stock_quantity(cls, value: object) -> int | None:
        return _whole(_attribute(value, "stock_quantity"))

    @field_validator("price_on_request", mode="before")
    @classmethod
    def _price_on_request(cls, value: object) -> bool:
        return _attribute(value, "price_on_request") is True

    @field_validator("ships_from_abroad", mode="before")
    @classmethod
    def _ships_from_abroad(cls, value: object) -> bool | None:
        flag = _attribute(value, "ships_from_abroad")
        return flag if isinstance(flag, bool) else None

    @field_validator("mfr_part_number", mode="before")
    @classmethod
    def _mfr_part_number(cls, value: object) -> str | None:
        text = _short_text(_attribute(value, "mfr_part_number"))
        return text if text and len(text) <= 60 else None

    @field_validator("variants", mode="before")
    @classmethod
    def _variants(cls, value: object) -> list[VariantRead]:
        return _items(value, "variants", _variant, _MAX_VARIANTS)

    @field_validator("price_breaks", mode="before")
    @classmethod
    def _price_breaks(cls, value: object) -> list[PriceBreakRead]:
        breaks = _items(value, "price_breaks", _price_break, _MAX_PRICE_BREAKS)
        return sorted(breaks, key=lambda b: b.min_quantity)

    @field_validator("compatible_with", mode="before")
    @classmethod
    def _compatible_with(cls, value: object) -> list[str]:
        return _items(value, "compatible_with", _short_text, _MAX_COMPATIBLE)

    @field_validator("videos", mode="before")
    @classmethod
    def _videos(cls, value: object) -> list[VideoRead]:
        return _items(value, "videos", _video, _MAX_VIDEOS)

    @model_validator(mode="after")
    def _priced_is_not_on_request(self):
        # A price is the answer to "on request": a stale flag must not hide it.
        if getattr(self, "price", None) is not None:
            self.price_on_request = False
        return self


#: The detail fields too heavy for a list row (a shop page of 24 listings).
#: List endpoints exclude them; the product and listing pages show them.
HEAVY_DETAILS = frozenset(
    {"specs", "documents", "variants", "price_breaks", "compatible_with", "videos"}
)


class ListingRead(_ShopDetails):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    #: The canonical product this listing is an offer of. Without it a listing
    #: page is a dead end — it can send a buyer to this one supplier but not back
    #: up to the comparison, which is the only thing makhzan does that the
    #: supplier's own site cannot.
    product_id: uuid.UUID | None = None
    title_en: str | None = None
    title_ar: str | None = None
    description_en: str | None = None
    description_ar: str | None = None
    part_number: str | None = None
    brand: str | None = None
    price: float | None = None
    currency: str
    unit: str | None = None
    stock_signal: StockSignal
    status: ListingStatus
    images: list[str] = Field(default_factory=list)
    source_url: str | None = None
    last_verified_at: datetime
    supplier: SupplierRead | None = None
    category: CategoryRead | None = None


class OfferRead(_ShopDetails):
    """One supplier's offer of a product — a listing, on the product page."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title_en: str | None = None
    title_ar: str | None = None
    price: float | None = None
    currency: str
    stock_signal: StockSignal
    source_url: str | None = None
    images: list[str] = Field(default_factory=list)
    last_verified_at: datetime
    supplier: SupplierRead | None = None
    brand: str | None = None


class ProductSummary(BaseModel):
    """A product without its offers — the shape a result row or rail needs.

    Every list surface shows the same six things: what it is, what the cheapest
    offer costs, how many suppliers have it, whether any of them has stock, and
    how recently that was checked. Fetching the offers to render a row would
    mean a join per result.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    part_number: str | None = None
    title_en: str | None = None
    title_ar: str | None = None
    brand: str | None = None
    image: str | None = None
    supplier_count: int
    offer_count: int
    min_price: float | None = None
    max_price: float | None = None
    currency: str
    in_stock: bool
    last_verified_at: datetime | None = None
    category: CategoryRead | None = None


class ProductRead(ProductSummary):
    """A canonical product with its offers, for the product page."""

    offers: list[OfferRead] = Field(default_factory=list)
