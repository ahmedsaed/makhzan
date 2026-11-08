"""SQLAlchemy ORM models — the makhzan Postgres schema.

Core entities: Supplier, Category (tree), Listing (the atom), plus the
operational tables IngestionRun and ReviewQueueItem. Cross-supplier product
matching (canonical Product) is deliberately OUT of V1 — see docs/PLAN.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from makhzan_schemas.domains.base import DEFAULT_DOMAIN
from makhzan_schemas.enums import (
    DEFAULT_CURRENCY,
    IngestionStatus,
    ListingStatus,
    ReviewReason,
    ReviewStatus,
    SourceType,
    StockSignal,
    SupplierStatus,
)


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Supplier(TimestampMixin, Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(255))

    source_type: Mapped[SourceType] = mapped_column(nullable=False)
    status: Mapped[SupplierStatus] = mapped_column(
        default=SupplierStatus.UNVERIFIED, nullable=False
    )
    #: Default vertical for this supplier's listings. Only a fallback: a listing's
    #: domain comes from its category, because a marketplace spans many verticals.
    domain: Mapped[str] = mapped_column(String(60), default=DEFAULT_DOMAIN, nullable=False)

    website_url: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40))

    # Greater Cairo for V1, but stored generically.
    area: Mapped[str | None] = mapped_column(String(120))  # e.g. "Bab El Louk"
    governorate: Mapped[str | None] = mapped_column(String(120))  # e.g. "Cairo"
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()

    logo_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    #: How to reach the shop, as the shop itself publishes it (its own
    #: LocalBusiness JSON-LD): {address?, area?, governorate?, phone?, whatsapp?,
    #: email?, opening_hours?: [str], source_url, fetched_at}. Kept apart from the
    #: hand-entered columns above, which it never overwrites: this is what the
    #: crawler read, refreshed once a cycle, and says where and when it read it.
    contact: Mapped[dict | None] = mapped_column(JSONB)

    listings: Mapped[list[Listing]] = relationship(back_populates="supplier")


class Category(TimestampMixin, Base):
    """Self-referencing bilingual category tree.

    `path` is a materialized path of slugs ("/electronics/passive/resistors")
    for cheap descendant/breadcrumb queries without recursive CTEs everywhere.
    """

    __tablename__ = "categories"
    __table_args__ = (
        # Slugs are unique per domain, not globally: two verticals may both want
        # "tools" and mean different things.
        UniqueConstraint("domain", "slug", name="uq_category_domain_slug"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    #: The vertical this branch of the tree belongs to. Authoritative — a
    #: listing inherits its domain from its category.
    domain: Mapped[str] = mapped_column(
        String(60), default=DEFAULT_DOMAIN, nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(255))

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    path: Mapped[str] = mapped_column(String(1024), default="/", nullable=False, index=True)
    position: Mapped[int] = mapped_column(default=0, nullable=False)

    parent: Mapped[Category | None] = relationship(remote_side="Category.id", backref="children")


class Listing(TimestampMixin, Base):
    """The atom: one supplier's offering of one product.

    Every listing carries freshness (`last_verified_at`) and `confidence` so the
    UI can signal how much to trust a price and the pipeline can route uncertain
    items to review. Stale data destroys trust in a directory.
    """

    __tablename__ = "listings"
    __table_args__ = (
        # Idempotent upserts: a supplier's own id for the item is the natural key.
        UniqueConstraint("supplier_id", "external_id", name="uq_listing_supplier_external"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_listing_confidence"),
        Index("ix_listing_part_number", "part_number"),
        Index("ix_listing_category_status", "category_id", "status"),
        Index("ix_listing_last_verified", "last_verified_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    # Canonical product this listing is an offer of (shared for matched MPNs,
    # singleton otherwise). Assigned by the grouping step — see makhzan_schemas.grouping.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )

    # Provenance
    source: Mapped[str] = mapped_column(String(120), nullable=False)  # adapter id
    source_type: Mapped[SourceType] = mapped_column(nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255))  # supplier's SKU/id
    #: Denormalized from the category (falling back to the supplier default) so
    #: enrichment and search can select a profile without a join.
    domain: Mapped[str] = mapped_column(
        String(60), default=DEFAULT_DOMAIN, nullable=False, index=True
    )
    source_url: Mapped[str | None] = mapped_column(Text)

    # Content (bilingual)
    title_en: Mapped[str | None] = mapped_column(String(512))
    title_ar: Mapped[str | None] = mapped_column(String(512))
    description_en: Mapped[str | None] = mapped_column(Text)
    description_ar: Mapped[str | None] = mapped_column(Text)

    # Electronics-critical: heavily weighted, exact/prefix-matchable in search.
    part_number: Mapped[str | None] = mapped_column(String(120))
    brand: Mapped[str | None] = mapped_column(String(120))

    # Commercials
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default=DEFAULT_CURRENCY, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40))  # piece, meter, ...
    stock_signal: Mapped[StockSignal] = mapped_column(default=StockSignal.UNKNOWN, nullable=False)

    images: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    # Flexible specs (voltage, package, tolerance...) — schema-less on purpose.
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    status: Mapped[ListingStatus] = mapped_column(default=ListingStatus.ACTIVE, nullable=False)
    confidence: Mapped[float] = mapped_column(default=1.0, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    supplier: Mapped[Supplier] = relationship(back_populates="listings")
    category: Mapped[Category | None] = relationship()
    product: Mapped[Product | None] = relationship(back_populates="listings")


class Product(TimestampMixin, Base):
    """A canonical product — the thing suppliers offer. Every listing maps to one.

    Listings sharing a confident part number collapse into a shared product;
    everything else is a singleton ("product of one"). Aggregate fields are
    denormalized from the product's offers (listings) so the search index and
    product cards can render "from EGP X · N suppliers" without a join.
    Rebuilt by makhzan_schemas.grouping.
    """

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Deterministic dedup key: "mpn:<PN>" for matched parts, "single:<source>:<ext>"
    # for singletons — so a product's identity (and URL) is stable across re-scrapes.
    group_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    part_number: Mapped[str | None] = mapped_column(String(120), index=True)
    domain: Mapped[str] = mapped_column(
        String(60), default=DEFAULT_DOMAIN, nullable=False, index=True
    )

    title_en: Mapped[str | None] = mapped_column(String(512))
    title_ar: Mapped[str | None] = mapped_column(String(512))
    brand: Mapped[str | None] = mapped_column(String(120))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    image: Mapped[str | None] = mapped_column(Text)
    # Representative (cheapest) offer's supplier name — for single-supplier cards.
    supplier_name: Mapped[str | None] = mapped_column(String(255))

    # Aggregates over the product's offers.
    offer_count: Mapped[int] = mapped_column(default=0, nullable=False)
    supplier_count: Mapped[int] = mapped_column(default=0, nullable=False)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default=DEFAULT_CURRENCY, nullable=False)
    in_stock: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When what a reader sees last changed: title, price range, stock, how many
    # offers and shops, the photo. The sitemap's lastmod. Not bumped by a
    # recheck that found nothing new (that is last_verified_at), and not by
    # updated_at, which every rebuild touches: Google ignores a lastmod that is
    # not "consistently and verifiably accurate". Set by grouping.rebuild_products.
    content_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    listings: Mapped[list[Listing]] = relationship(back_populates="product")
    category: Mapped[Category | None] = relationship()


class ProductRedirect(Base):
    """Where a deleted product's URL now goes: the product its offers moved to.

    A regroup replaces a product whenever its group key changes (a second shop
    starts selling it, the grouping rules change), and its id goes with it. The
    id is a URL people have shared and search engines have indexed, so
    `rebuild_products` records the move here and the product page redirects.
    A first step of docs/decisions/0004-stable-product-ids.md, not the whole of it.

    Always one hop: when a redirect's target is itself replaced, the rebuild
    repoints the redirect at the new target. A target deleted with nowhere to
    go (every offer withdrawn) takes its redirects with it, so a redirect never
    leads to a missing page.
    """

    __tablename__ = "product_redirects"

    old_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    new_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Source(TimestampMixin, Base):
    """One configured data source: which adapter to run, against what, how paced.

    The runtime source of truth for what gets crawled — the worker builds its
    adapters from these rows, so adding or disabling a supplier needs no code
    change and no redeploy. Rows are seeded from `sources.toml`
    (`python -m worker.sources.sync`), which can live outside the repository.

    `supplier` describes the shop for the pipeline's get-or-create of its
    Supplier row; it is not a second copy of that row to edit.
    """

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = _uuid_pk()
    #: Stable, unique identifier — persisted on every listing, run and cursor as
    #: `source`, so renaming it orphans all three.
    source_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    #: A built-in adapter type ("woocommerce", "shopify", "odoo", ...) or an
    #: import path ("package.module:Class") for one that lives elsewhere.
    adapter: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    #: SupplierInfo fields: slug, name, domain, website_url, name_ar, ...
    supplier: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: Adapter keyword arguments — pacing, crosswalk name, platform options.
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: The source's per-cycle reference data (its category tree, every variant's
    #: price, its quantity breaks, its address), by part:
    #: {part: {"fetched_at": iso, "data": ...}}. Written by the pipeline at the
    #: start of a cycle and read by every run of it, so a cycle spread over a
    #: week of daily runs fetches it once rather than seven times. Runtime state,
    #: not configuration: syncing sources.toml never touches it.
    cycle_data: Mapped[dict | None] = mapped_column(JSONB)


class IngestionRun(Base):
    """One execution of one source adapter — the audit trail for the pipeline."""

    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_type: Mapped[SourceType] = mapped_column(nullable=False)
    status: Mapped[IngestionStatus] = mapped_column(default=IngestionStatus.RUNNING, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items_seen: Mapped[int] = mapped_column(default=0, nullable=False)
    items_created: Mapped[int] = mapped_column(default=0, nullable=False)
    items_updated: Mapped[int] = mapped_column(default=0, nullable=False)
    items_failed: Mapped[int] = mapped_column(default=0, nullable=False)
    items_for_review: Mapped[int] = mapped_column(default=0, nullable=False)

    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ReviewQueueItem(TimestampMixin, Base):
    """A low-confidence extraction awaiting human confirmation before going live."""

    __tablename__ = "review_queue"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(120), nullable=False)

    reason: Mapped[ReviewReason] = mapped_column(nullable=False)
    confidence: Mapped[float | None] = mapped_column()

    raw_payload: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # what the adapter saw
    proposed: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # normalized proposal

    status: Mapped[ReviewStatus] = mapped_column(default=ReviewStatus.PENDING, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class SourceCursor(Base):
    """Resume point for one partition of one source.

    Scraping a supplier is not guaranteed to finish in a single run: hosts rate-
    limit, and a run that dies on page 6 of 43 must not restart at page 1 next
    time, or the tail of the catalog becomes permanently unreachable. The cursor
    persists how far a partition got so the next run continues from there.

    A *cycle* is one full sweep of every partition of a source. It may span many
    runs. `cycle_started_at` marks when the current sweep began — archiving keys
    off that, not off the individual run, so listings are only retired once the
    whole catalog has genuinely been re-checked.
    """

    __tablename__ = "source_cursors"
    __table_args__ = (UniqueConstraint("source", "partition_key", name="uq_source_cursor"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    source: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    #: Partition within the source ("" when a source has a single partition).
    partition_key: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    #: 1-based page to fetch next. Reset to 1 when a sweep of this partition ends.
    next_page: Mapped[int] = mapped_column(default=1, nullable=False)
    #: True once this partition has been swept to its end in the current cycle.
    exhausted: Mapped[bool] = mapped_column(default=False, nullable=False)
    #: When the current sweep of this partition began (None between cycles).
    cycle_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
