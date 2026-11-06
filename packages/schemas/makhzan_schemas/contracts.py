"""Pydantic contracts.

Two families:
  - Ingestion DTOs (RawItem -> NormalizedListing): the pipeline's internal
    hand-off shape, produced by source adapters and consumed by the upsert step.
  - API read models: what the FastAPI backend returns to the frontend.

Keeping these here (next to the ORM) is what lets the writer (ingestion) and
the reader (api) share one definition of truth.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field

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


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    name_ar: str | None = None
    area: str | None = None
    governorate: str | None = None
    website_url: str | None = None


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


class ListingRead(BaseModel):
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


class OfferRead(BaseModel):
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
