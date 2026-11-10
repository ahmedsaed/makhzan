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
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from makhzan_schemas.domains.base import DEFAULT_DOMAIN
from makhzan_schemas.enums import (
    DEFAULT_CURRENCY,
    IngestionStatus,
    ListingStatus,
    ProductEventKind,
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

    # How to reach the shop, as a person read it where the shop's details are
    # published (its site, its Facebook, its Google Maps listing) and entered it
    # in the shop's `supplier` table in sources.toml. Written only by
    # `worker.sources.sync` (every deploy) and on the row's creation, so the file
    # is the truth: a value removed there is cleared here. Merged with `contact`
    # below by makhzan_schemas.contact.resolve_contact, these winning per field.
    #: E.164 (or a hotline's five digits), first the one to call.
    phones: Mapped[list | None] = mapped_column(JSONB)
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))

    # Greater Cairo for V1, but stored generically.
    area: Mapped[str | None] = mapped_column(String(120))  # e.g. "Bab El Louk"
    governorate: Mapped[str | None] = mapped_column(String(120))  # e.g. "Cairo"
    address: Mapped[str | None] = mapped_column(Text)
    #: The shop's own map link for that address.
    maps_url: Mapped[str | None] = mapped_column(Text)
    #: Lines as the shop words them ("Sat–Thu 10:00–22:00"), in its order.
    opening_hours: Mapped[list | None] = mapped_column(JSONB)
    #: Further places it trades from: [{name, address, area, governorate,
    #: phones, maps_url}]. The columns above are its main (or only) one.
    branches: Mapped[list | None] = mapped_column(JSONB)
    #: Where and when a person read the details above, a page at a time:
    #: [{url, checked_on: "YYYY-MM-DD", fields: [names as in ResolvedContact]}].
    contact_sources: Mapped[list | None] = mapped_column(JSONB)
    # The table still has `phone`, the single number `phones` replaced, until a
    # later migration drops it: a release still running while this one migrates
    # selects it (expand/contract, migration 2b656e4b5adc).
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()

    logo_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    #: How to reach the shop, as the shop itself publishes it (its own
    #: LocalBusiness JSON-LD): {address?, area?, governorate?, phone?, whatsapp?,
    #: email?, opening_hours?: [str], source_url, fetched_at}. Kept apart from the
    #: listed columns above, which it never overwrites: this is what the
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
    #: When the listing's price and details were last read from the shop: what
    #: the site shows as "checked". Only a sweep that returned the product moves it.
    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: When the source last said the listing exists, by any route. Archiving keys
    #: off this, not `last_verified_at`: a shop that lists an out-of-stock product
    #: only by id still sells it, but has not re-stated its price.
    last_seen_at: Mapped[datetime] = mapped_column(
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
    Regrouped by makhzan_schemas.grouping.

    The id is permanent (docs/decisions/0004-stable-product-ids.md): a regroup
    never deletes a product or gives it a new id. It is in one of three states:

    - listed: `merged_into` and `delisted_at` both NULL. In search, the sitemap,
      counts and similar-product rails.
    - no longer listed: `delisted_at` set. Every offer has gone; the row keeps
      the title, photo and last price range, and the page says so.
    - merged: `merged_into` set. Grouping decided it is the same product as
      another; its URL redirects there, one hop.

    Only `worker.retire_redirects` ever deletes a row: a merged-away one whose
    redirect nobody has followed in a year (docs/decisions/0005-url-retirement.md).
    """

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("merged_into IS NULL OR merged_into <> id", name="ck_product_not_self"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    #: The grouping key this product's offers last formed ("mpn:<PN>:<words>",
    #: "single:<source>:<external id>"). Diagnostic only, not identity: it is
    #: rewritten on every regroup and two products may share one (an emptied
    #: product keeps its last key, which a new product can form again).
    group_key: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    #: The product this one was merged into, and which its URL redirects to.
    #: Always one hop: a merge into a product that is later merged itself
    #: repoints every id that led to it.
    merged_into: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), index=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When its last active offer went. Cleared if one comes back (revived).
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When a merged-away id's redirect was last followed, at most once a day.
    #: A year unused and `worker.retire_redirects` drops the row.
    redirect_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    #: The shop whose listing `image` was taken from, so every place the photo
    #: is shown can credit that shop (it is hotlinked from the shop's own site,
    #: decision 0003). Recorded from the listing the photo was taken from rather
    #: than read off `supplier_name`, which is a display name only and names the
    #: representative listing: the badge must stay right if that ranking ever
    #: stops putting photos first. Set with `image` by
    #: grouping.rebuild_products; null when there is no photo, and on rows not
    #: rebuilt since the column was added.
    image_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL")
    )
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
    image_supplier: Mapped[Supplier | None] = relationship()

    @classmethod
    def is_listed(cls):
        """SQL: listed, neither merged away nor emptied. What search, the sitemap
        and every count and rail show."""
        return and_(cls.merged_into.is_(None), cls.delisted_at.is_(None))


class ProductRedirect(Base):
    """A product id deleted before ids became permanent, and where it leads now.

    Until November 2026 a regroup replaced a product whenever its group key
    changed and deleted the old row; this table recorded where each deleted
    id's offers went. Since ids became permanent (docs/decisions/
    0004-stable-product-ids.md) nothing adds to it: a merge marks the row
    `Product.merged_into` instead. The rows already here keep working, are
    repointed when their target is merged, and retire after a year unused
    (`last_used_at`, docs/decisions/0005-url-retirement.md).
    """

    __tablename__ = "product_redirects"

    old_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    new_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: When the redirect was last followed, at most once a day.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductEvent(Base):
    """One change to a product's identity, for audit: merge, split, emptied, revived.

    Written by `grouping.rebuild_products`, which applies every merge and split
    itself rather than queueing it for review. This is how to find out, later,
    why an id redirects or why an offer left it.

    `product_id` is not a foreign key, so the history outlives a merged-away
    row that `worker.retire_redirects` has dropped.

    - merge: `product_id` was merged into `other_id`.
    - split: some of `product_id`'s offers formed the new product `other_id`.
    - emptied / revived: `other_id` is NULL.

    `detail` holds the counts and group keys behind the decision.
    """

    __tablename__ = "product_events"
    __table_args__ = (Index("ix_product_event_product_time", "product_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[ProductEventKind] = mapped_column(nullable=False)
    other_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PriceObservation(Base):
    """A listing's price and stock as of `observed_at`: one change point of its history.

    Each crawl overwrites a listing's price and stock, so without this what a
    product cost last month is gone for good and can never be backfilled. A row is
    written only when a listing is first stored or its price, currency or stock
    signal differs from its latest row (`worker.pipeline`), so a recheck that finds
    nothing new adds nothing and the table grows with change, not with crawling.
    A value holds from its `observed_at` until the next row's.

    Archiving writes a row too, with `available` false: from then until a row
    that says otherwise, the shop no longer offers the listing at all, and its
    price and stock signal are only the last ones read. Without it a listing
    archived for weeks read as "in stock" across them, and one coming back at
    the same values added no row to say when it did.

    History starts at the migration that created this table, seeded with one row
    per active listing as of its `last_verified_at`.
    """

    __tablename__ = "price_observations"
    __table_args__ = (Index("ix_price_observation_listing_time", "listing_id", "observed_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: NULL is "price on request", which is itself a change worth recording.
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    stock_signal: Mapped[StockSignal] = mapped_column(nullable=False)
    #: `available and stock_signal == IN_STOCK`: the definition `Product.in_stock`
    #: uses, false while archived, stored so "in stock N of the last 12 weeks"
    #: needs no enum logic in the query.
    in_stock: Mapped[bool] = mapped_column(nullable=False)
    #: False from the moment the listing was archived (the shop stopped listing
    #: it) until it is seen again. Clip "in stock N of 12 weeks" on it.
    available: Mapped[bool] = mapped_column(default=True, server_default=true(), nullable=False)

    #: Many-to-one only: lets a row be added beside a listing not yet flushed.
    listing: Mapped[Listing] = relationship()


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


class RobotsCopy(Base):
    """The last robots.txt read successfully from each host, kept across restarts.

    When a host's robots.txt cannot be read (a 5xx, a 429, a timeout), RFC 9309
    §2.3.1.4 says to assume complete disallow; the crawler instead uses this
    copy for up to 30 days (worker/robots.py). It lived in memory only, so the
    first blip after a deploy refused the host for the day. One row per host,
    so concurrent sources never overwrite each other's.
    """

    __tablename__ = "robots_copies"

    #: `worker.http.host_of()`: `scheme://host[:port]`, the pace gate's key.
    host: Mapped[str] = mapped_column(Text, primary_key=True)
    #: The file as read, or None when the host answered 4xx ("no rules").
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkerState(Base):
    """What the running worker believes, written by it, for the API to report.

    The worker reads some settings from its environment when its container is
    created, and the API runs in a container of its own. Asking the API's
    environment what the worker is doing goes stale the moment one is recreated
    without the other (`./makhzan crawl off` recreates only the worker), so the
    worker states it here at startup instead. Keyed by name: `crawl` holds
    `{"enabled": bool}` (see `makhzan_schemas.crawl`).
    """

    __tablename__ = "worker_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
