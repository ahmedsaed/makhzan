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
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
        CheckConstraint(
            "matched_via IS NULL OR matched_via IN ('rules', 'ai')", name="ck_listing_matched_via"
        ),
        CheckConstraint(
            "matched_ai_decision_id IS NULL OR matched_via = 'ai'",
            name="ck_listing_matched_ai_decision",
        ),
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

    # The check log: what estimating a listing's change rate needs (n checks, X
    # changes seen, since when), which `price_observations` alone cannot give,
    # because an unchanged re-read writes no row there. Bumped by
    # `worker.pipeline._record_changes`, so only by a read that also records
    # history (never a `limit=` run), and at most once per run. Listings stored
    # before the log existed start at 0 with no `first_checked_at`, and count
    # from their next read. A stock-only read (a shop listing out-of-stock
    # products by id) is a check too: it would see a stock change, not a price.
    #: Reads of the listing's price or stock since `first_checked_at`, that one included.
    checks: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    #: How many of those reads found the price, currency or stock different from
    #: the listing's latest observation. The first read is never a change, so
    #: this counts changes over the `checks - 1` intervals between reads.
    changes: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    first_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The latest counted read. Not `last_verified_at`, which a stock-only read
    #: leaves alone: spans between checks are measured on this.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: How the listing came to be an offer of its product, written only by the
    #: regroup (`grouping.rebuild_products`), like `part_number`: `rules` (the
    #: grouping rules alone put it with the product's core) or `ai` (an AI
    #: "same" decision did, which the rules alone would not have). NULL until a
    #: regroup has run since the column came; read as `rules`
    #: (`matching.matched_by`).
    matched_via: Mapped[str | None] = mapped_column(String(8))
    #: For `ai`: the `ai_decisions` row that linked this listing's part of the
    #: product to the rest; NULL when no single decision did (see
    #: `grouping._attribute`). Not a foreign key, like
    #: `products.min_price_listing_id`: `ai_decisions` already points at
    #: listings, and a second path between the tables would make their joins
    #: ambiguous. Decision rows are never deleted.
    matched_ai_decision_id: Mapped[int | None] = mapped_column(BigInteger)

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
    #: representative listing: the badge must stay right now that ranking no
    #: longer puts photos first (grouping.representative_key). Set with `image` by
    #: grouping.rebuild_products; null when there is no photo, and on rows not
    #: rebuilt since the column was added.
    image_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    # The representative listing's supplier name (grouping.representative) —
    # for single-supplier cards.
    supplier_name: Mapped[str | None] = mapped_column(String(255))

    # Aggregates over the product's offers.
    offer_count: Mapped[int] = mapped_column(default=0, nullable=False)
    supplier_count: Mapped[int] = mapped_column(default=0, nullable=False)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    # What the page says about the low end of that range, from the same pass
    # (makhzan_schemas.pricing, set by grouping.rebuild_products): the offer and
    # shop setting `min_price`, the option of it that does when an option
    # undercuts the listing, and its minimum order. The listing id is not a
    # foreign key: listings already point at products, and a second path
    # between the two tables would make every join between them ambiguous. It
    # is as current as the last rebuild, like the rest of the aggregates.
    min_price_listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # The listing the product's title, brand, category and domain were copied
    # from (grouping.representative): the product page's shop view picks it on
    # a plain load, so the h1 and <title> name the same listing. Not a foreign
    # key, for the reason above; as current as the last rebuild, like the title.
    representative_listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    min_price_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    # As wide as the longest option title the contracts keep
    # (`contracts._MAX_TEXT`; a test holds the two equal).
    min_price_option: Mapped[str | None] = mapped_column(String(200))
    min_price_quantity: Mapped[int | None] = mapped_column()
    # Some offer in the range has a minimum order: the range reads "each".
    price_each: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)
    # Offers on request among those the range was taken from: with no
    # `min_price`, the product reads "Price on request", not "no price".
    on_request_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
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
    image_supplier: Mapped[Supplier | None] = relationship(foreign_keys=[image_supplier_id])
    min_price_supplier: Mapped[Supplier | None] = relationship(foreign_keys=[min_price_supplier_id])

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
    #: Which kind of read wrote the row: "sweep" (the cycle's list pages, and
    #: the archiving that closes a cycle) for now; later lanes add their own
    #: ("recheck", "modified", "sentinel"), so changes found per request can be
    #: split by lane. Rows from before the column read "sweep", which is true.
    via: Mapped[str] = mapped_column(
        String(16), default="sweep", server_default="sweep", nullable=False
    )
    #: The listing's previous counted read (`Listing.last_checked_at`) when this
    #: row was written: the change happened after it, so `observed_at` minus
    #: this is how long the site may have shown the old value (detection delay).
    #: NULL for a first row, an archiving row, and rows from before the log.
    prev_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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


class Report(Base):
    """One visitor's "Report a problem" from a product page (POST /reports).

    The API's first write that comes from a visitor. A person reviews each one
    on the server (`./makhzan reports`), setting `status` and `reviewed_at`;
    only a reviewed report may ever become a labelled pair for matching
    (docs/ai/plan.md, phase G). The rules for what is kept and for how long are
    `makhzan_schemas.reports` and the site's /privacy page:

    - `email` is optional, only to reply, and is erased 90 days after the
      report was sent, reviewed or not.
    - `ip_hash` is a salted hash of the sender's address, kept only to rate
      limit, and erased 24 hours after the report was sent.
    - the rest, the report itself, is kept.

    `product_id` and `other_product_id` are deliberately not foreign keys,
    like `product_events.product_id`: product ids are permanent, but a merged
    one's row is dropped once its redirect goes unused for a year
    (`worker.retire_redirects`), and a report must outlive that. They hold the
    product as it was resolved when the report was sent (a merged id becomes
    its survivor); `reported_product_id` keeps the id the page sent, when that
    differed.

    `snapshot` is what the page showed, read on the server when the report
    arrived: the product and every active offer of it (title, shop, price,
    stock), and the other product's for "the same as another product". A
    regroup or a re-crawl changes them later, and a label must be about what
    the visitor saw.
    """

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("status IN ('new', 'accepted', 'rejected')", name="ck_report_status"),
        CheckConstraint(
            "reason IN ('offers_not_same', 'same_as_other', 'wrong_price_stock', "
            "'wrong_category', 'wrong_details', 'shop_contact', 'other')",
            name="ck_report_reason",
        ),
        CheckConstraint(
            "(status = 'new') = (reviewed_at IS NULL)", name="ck_report_reviewed_when_closed"
        ),
        # The rate limit counts one address's reports over the last day.
        Index("ix_report_ip_hash_created", "ip_hash", "created_at"),
        Index("ix_report_status_created", "status", "created_at"),
    )

    #: Also the reference the visitor is shown: "R-{id}".
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    reported_product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    #: One of `makhzan_schemas.reports.REASONS`.
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Listing ids the visitor ticked or picked, as strings.
    offer_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: The duplicate, for `same_as_other`.
    other_product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    #: What is wrong: one of `makhzan_schemas.reports.FIELDS`.
    field: Mapped[str | None] = mapped_column(String(32))
    #: What it should say, as the visitor gave it ("EGP 460", "out_of_stock", a category).
    correct_value: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(254))
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default="new", server_default="new", nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: HMAC-SHA256 of the sender's address under a server secret, hex.
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GroupingOverride(Base):
    """A person's ruling on whether two listings are one product.

    Read by the regroup (`grouping.rebuild_products`, the only writer of which
    listings form a product) and, later, by AI matching
    (`makhzan_schemas.overrides.load_overrides`):

    - `never_merge`: no product may hold both listings. It acts as a veto
      between those two, wherever the grouping checks vetoes.
    - `must_merge`: evidence that the two are one product, admitting them to
      one group without title agreement or a shared identifier. Every veto
      still applies between them unless `forced`; the same shop never merges,
      forced or not.

    Keyed by listing ids, because they are permanent and a product's
    membership is what the ruling is about (a product id would follow its
    offers wherever a regroup took them). The pair is unordered, stored with
    `listing_a < listing_b`, so a pair has one *standing* ruling: a new one
    about the same pair must replace it, deliberately.

    Removing a ruling keeps its row (`removed_at`, `removed_by`): the regroup
    and `load_overrides` ignore it, the regroup that undoes its effect cites
    it by id, and the pair may be ruled on again, as a new row (the unique
    index covers standing rows only).

    After every regroup, `status` says whether the ruling holds:
    `in_effect`, `blocked` (a must_merge whose two listings are in different
    products; `blocked_by` and `blocked_reason` say which listing and veto
    kept them apart), `inactive` (a listing is not active, so the ruling acts
    on nothing) or `removed`. It describes; it never feeds back into grouping.

    `source` says who ruled: `report` (an accepted "Report a problem",
    `report_id`; `./makhzan reports accept`) or `manual` (`./makhzan overrides
    add`, which requires a `note`). Every product a ruling changes cites it,
    by id, in its `product_events` row's detail.
    """

    __tablename__ = "grouping_overrides"
    __table_args__ = (
        Index(
            "uq_grouping_override_standing_pair",
            "listing_a",
            "listing_b",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        CheckConstraint(
            "(removed_at IS NULL) = (removed_by IS NULL)",
            name="ck_grouping_override_removed_by",
        ),
        CheckConstraint(
            "status IS NULL OR status IN ('in_effect', 'blocked', 'inactive', 'removed')",
            name="ck_grouping_override_status",
        ),
        CheckConstraint("listing_a < listing_b", name="ck_grouping_override_ordered"),
        CheckConstraint("kind IN ('never_merge', 'must_merge')", name="ck_grouping_override_kind"),
        CheckConstraint(
            "NOT forced OR kind = 'must_merge'", name="ck_grouping_override_forced_must"
        ),
        CheckConstraint("source IN ('report', 'manual')", name="ck_grouping_override_source"),
        CheckConstraint(
            "(source = 'report') = (report_id IS NOT NULL)",
            name="ck_grouping_override_report",
        ),
        CheckConstraint(
            "source <> 'manual' OR length(trim(note)) > 0",
            name="ck_grouping_override_manual_note",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    listing_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    listing_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("listings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: `never_merge` or `must_merge` (`makhzan_schemas.overrides.KINDS`).
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: A must_merge that overrides the value, form and price vetoes too.
    forced: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    #: `report` or `manual`.
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    report_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    #: Who made it, as they gave it: free text.
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: When and by whom it was withdrawn; the row stays.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[str | None] = mapped_column(String(100))
    #: What the last regroup found (`grouping.override_status`); NULL until one has run.
    status: Mapped[str | None] = mapped_column(String(16))
    #: For `blocked`: the listing whose veto kept the pair apart (one of the two
    #: when they veto each other), and why, in words.
    blocked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# AI matching (docs/ai/broker-api.md, makhzan_schemas.ai)
# ---------------------------------------------------------------------------
#
# Pairs are unordered and stored with `listing_a < listing_b`
# (`overrides.pair()`), as `grouping_overrides` stores them: listing ids are
# permanent. "ab" is the reading order that shows `listing_a` as LISTING A.
# Production never runs a model: the broker hands rendered requests to the
# owner's workers and stores what they score. Which worker runs which model,
# when, is each worker's own configuration (owner, 2026-11-17).
#
# Model keys, pipeline and stage names are plain strings, validated against
# the registry in code (`makhzan_schemas.ai.pipelines`, `ai.policy.MODELS`),
# never database enums: a new model or pipeline needs no migration.


class AiModelVersion(Base):
    """One judge as scored: a model version read through a prompt version (P8).

    `model` is the model key (`policy.MODELS`); `model_version` names its
    weights revision, serving code and scoring parameters; `prompt_version`
    the prompt variant's layout, cap and a hash of the rules and the renderer
    (`prompt.PROMPT_VERSIONS`). A score belongs to one row, so its
    `model_version_id` says which model read which prompt. The registry in
    code says which row each pipeline stage uses now; a row is created the
    first time a stage needs it (`triggers.model_version_id`). GPU and CPU
    runs are the same version; each score records its device and dtype.
    """

    __tablename__ = "ai_model_versions"
    __table_args__ = (
        UniqueConstraint(
            "model", "model_version", "prompt_version", name="uq_ai_model_version_judge"
        ),
        CheckConstraint("status IN ('active', 'retired')", name="ck_ai_model_version_status"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    model: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    weights_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Scoring parameters, e.g. {"temperature": 1.0, "prefix_cache": 0}.
    scoring: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiWorker(Base):
    """A machine allowed to lease jobs from the broker (P3).

    One bearer token each, stored only as its sha256 (a high-entropy random
    token needs no slow hash); issued and revoked by `./makhzan ai worker`.
    `models` are the model keys it may serve: it leases any job whose stage
    needs one of them (`pipelines.stages_for_models`). There is no host or
    host group: the broker treats every worker the same, and each worker's
    configuration decides what it runs and when (owner, 2026-11-17).
    """

    __tablename__ = "ai_workers"
    __table_args__ = (CheckConstraint("cardinality(models) > 0", name="ck_ai_worker_models"),)

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True, nullable=False)
    models: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The worker's last hello: its configuration, versions, device, for status.
    last_hello: Mapped[dict | None] = mapped_column(JSONB)


class AiListingState(Base):
    """What the candidates trigger last saw of each listing (P5).

    `content_sha256` is `hashing.listing_hash` as last computed;
    `candidates_sha256` the hash its candidates were last found for. A listing
    whose two differ is new or changed, and due for candidates.
    """

    __tablename__ = "ai_listing_state"

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    content_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    content_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidates_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidates_sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32))


class AiJob(Base):
    """One pair to score at one stage of one pipeline, both reading orders (P11).

    `pipeline` and `stage` name an entry of `pipelines.PIPELINES` (`match`
    and `audit` today); `model_version_id` is the judge that stage used when
    the job was queued. A trigger queues a pair into its pipeline's first
    stage; each later stage is queued by the broker's result handling
    (`pipelines.transition`). `reason` says which trigger, or `rescore`.
    Leased by a worker until `lease_expires_at`; an expired lease is queued
    again and counts an attempt; after `max_attempts` the job is `dead`.
    Enqueueing is idempotent: one open job per (pipeline, stage, judge, pair).
    `request_sha256` holds {"ab": hex, "ba": hex} as rendered at lease time,
    and `content_sha256_a` and `_b` the listings' content hashes then
    (docs/ai/broker-api.md).
    """

    __tablename__ = "ai_jobs"
    __table_args__ = (
        CheckConstraint("listing_a < listing_b", name="ck_ai_job_ordered"),
        CheckConstraint(
            "status IN ('queued', 'leased', 'done', 'cancelled', 'dead')",
            name="ck_ai_job_status",
        ),
        CheckConstraint(
            "(status = 'leased') = (lease_id IS NOT NULL)", name="ck_ai_job_leased_has_lease"
        ),
        Index(
            "uq_ai_job_open_pair",
            "pipeline",
            "stage",
            "model_version_id",
            "listing_a",
            "listing_b",
            unique=True,
            postgresql_where=text("status IN ('queued', 'leased')"),
        ),
        # What `/lease` scans: queued jobs of a judge, best first.
        Index(
            "ix_ai_job_lease",
            "model_version_id",
            text("priority DESC"),
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        # What the expiry reaper scans: leases past their time.
        Index(
            "ix_ai_job_lease_expiry",
            "lease_expires_at",
            postgresql_where=text("status = 'leased'"),
        ),
        Index("ix_ai_job_pair", "listing_a", "listing_b"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    pipeline: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("ai_model_versions.id"), nullable=False
    )
    listing_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    listing_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued", nullable=False
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default="0", nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, default=3, server_default="3", nullable=False
    )
    lease_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    leased_by: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("ai_workers.id"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Set by a heartbeat whose `progress` names this job (and cleared on the
    #: lease's other jobs): the job the worker was scoring. When the lease
    #: expires, only that job is charged an attempt; the rest go back free.
    in_hand_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_sha256: Mapped[dict | None] = mapped_column(JSONB)
    #: The two listings' content hashes (`hashing.listing_hash`) when the
    #: requests were rendered, at lease time: the text the scores are about.
    content_sha256_a: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    content_sha256_b: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiScore(Base):
    """One judge's score for one reading order of one pair.

    Idempotent on (judge, `request_sha256`): the same request is never stored
    twice, so a retried or late result is a duplicate, not a second score. A
    score belongs to its judge, not to a pipeline: any stage that uses the same
    model and prompt version reads it. `content_sha256_a` and `_b` are the
    two listings' content hashes (`hashing.listing_hash`) the request was
    rendered from. `p` is the model's score as `policy.MODELS` defines it
    (Kev: raw P(yes) at temperature 1; pplx: P(true) at its checkpoint
    temperature).
    """

    __tablename__ = "ai_scores"
    __table_args__ = (
        CheckConstraint("listing_a < listing_b", name="ck_ai_score_ordered"),
        CheckConstraint("reading_order IN ('ab', 'ba')", name="ck_ai_score_order"),
        CheckConstraint("p >= 0 AND p <= 1", name="ck_ai_score_p"),
        UniqueConstraint("model_version_id", "request_sha256", name="uq_ai_score_request"),
        Index("ix_ai_score_pair", "listing_a", "listing_b"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    model_version_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("ai_model_versions.id"), nullable=False
    )
    listing_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    listing_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    reading_order: Mapped[str] = mapped_column(String(2), nullable=False)
    request_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    content_sha256_a: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    content_sha256_b: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    p: Mapped[float] = mapped_column(Float, nullable=False)
    #: Anything else the worker reported: margin, token usage.
    extra: Mapped[dict | None] = mapped_column(JSONB)
    seconds: Mapped[float | None] = mapped_column(Float)
    device: Mapped[str | None] = mapped_column(String(16))
    dtype: Mapped[str | None] = mapped_column(String(16))
    threads: Mapped[int | None] = mapped_column(SmallInteger)
    worker_id: Mapped[int | None] = mapped_column(SmallInteger, ForeignKey("ai_workers.id"))
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ai_jobs.id", ondelete="SET NULL")
    )
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiDecision(Base):
    """What a deciding pipeline concluded about one pair, under one policy.

    Written by the broker's result handling when `pipelines.transition` says
    DECIDE. `outcome` is `same` or `not_same`; `decided_by` is the stage that
    settled it (the stage whose score fell below its threshold, or the last
    stage). `scores` keeps every stage's evidence, by stage name:
    {"kev": {"model": "kev", "model_version_id": 1, "ab": 0.91, "ba": 0.88,
    "min": 0.88}, ...}. `state`:

    - `standing`: the pair's decision in force, one per (pipeline, pair). It
      stays in force until the pair is scored again, with no timeout, even
      after a listing's text changed (P6); a re-score that is due and never
      completes shows in status and is handled by hand.
    - `stale`: replaced by a later decision about the pair (a re-score, a new
      judge version, a new policy). Kept as evidence.
    - `revoked`: withdrawn by a person (`revoked_at`, `revoked_by`,
      `revoke_note`).

    The regroup reads standing "same" decisions only when the mode is `live`
    (`ai.mode`), or in a dry run's preview. `effect`,
    `blocked_reason` and `checked_at` are for what a regroup found
    (`in_effect`, `blocked`, `inactive`, `overridden`); nothing writes them yet.
    """

    __tablename__ = "ai_decisions"
    __table_args__ = (
        CheckConstraint("listing_a < listing_b", name="ck_ai_decision_ordered"),
        CheckConstraint("outcome IN ('same', 'not_same')", name="ck_ai_decision_outcome"),
        CheckConstraint("state IN ('standing', 'stale', 'revoked')", name="ck_ai_decision_state"),
        CheckConstraint(
            "effect IS NULL OR effect IN ('in_effect', 'blocked', 'inactive', 'overridden')",
            name="ck_ai_decision_effect",
        ),
        CheckConstraint(
            "(state = 'revoked') = (revoked_at IS NOT NULL)", name="ck_ai_decision_revoked_at"
        ),
        Index(
            "uq_ai_decision_standing_pair",
            "pipeline",
            "listing_a",
            "listing_b",
            unique=True,
            postgresql_where=text("state = 'standing'"),
        ),
        Index("ix_ai_decision_listing_a", "listing_a"),
        Index("ix_ai_decision_listing_b", "listing_b"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    pipeline: Mapped[str] = mapped_column(String(32), nullable=False)
    listing_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    listing_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Every stage's scores, by stage name (see the class docstring).
    scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: The thresholds in force (`ai.policy.POLICIES`).
    policy_version: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The two listings' current content hashes, computed when the decision was
    #: written (not copied from the scores, which may reuse an older label).
    content_sha256_a: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    content_sha256_b: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), default="standing", server_default="standing", nullable=False
    )
    effect: Mapped[str | None] = mapped_column(String(16))
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(100))
    revoke_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiFlag(Base):
    """Something about AI matching a person should look at.

    - `rules_low_kev`: Kev scored a pair the rules merged low (P12: every such
      score is recorded; no threshold is chosen yet).
    - `poison_job`: a job that failed `max_attempts` times.
    - `blocked_same`: a "same" decision today's vetoes or an existing product
      keep from taking effect.
    - `version_drift`: a worker reported a model that is not the one in use;
      `subject` is "<worker>/<model>".
    - `nothing_fits`: a worker's sessions keep ending with work queued but no
      job fitting its time (`broker.NONE_FIT_FLAG_AFTER` in a week);
      `subject` is "<worker>/<model>".

    One open flag per (kind, pair, subject).
    """

    __tablename__ = "ai_flags"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('rules_low_kev', 'poison_job', 'blocked_same', 'version_drift',"
            " 'nothing_fits')",
            name="ck_ai_flag_kind",
        ),
        CheckConstraint("status IN ('open', 'dismissed', 'actioned')", name="ck_ai_flag_status"),
        CheckConstraint(
            "listing_a IS NULL OR listing_b IS NULL OR listing_a < listing_b",
            name="ck_ai_flag_ordered",
        ),
        Index(
            "uq_ai_flag_open",
            "kind",
            "listing_a",
            "listing_b",
            "subject",
            unique=True,
            postgresql_where=text("status = 'open'"),
            # A flag with no pair (a version drift) is one open flag per kind
            # and subject: NULLs compare equal here (Postgres 15+).
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: What a flag without a pair is about: "<worker>/<model>" for a version drift.
    subject: Mapped[str | None] = mapped_column(String(100))
    listing_a: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE")
    )
    listing_b: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE")
    )
    #: Not a foreign key, like `product_events.product_id`: product ids outlive rows.
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ai_jobs.id", ondelete="SET NULL")
    )
    score: Mapped[float | None] = mapped_column(Float)
    model_version_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("ai_model_versions.id")
    )
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="open", server_default="open", nullable=False
    )
    resolved_by: Mapped[str | None] = mapped_column(String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiSession(Base):
    """One worker session with the broker, from its hello (docs/ai/broker-api.md §3.1).

    `models` holds what the worker reported at hello and what the broker
    answered, by model key: {"kev": {"model_version": ..., "weights_revision":
    ..., "ok": true}}. A lease names its session, and is refused for a model
    the session did not report, or reported at another version (§3.2).
    `lease_s` is the lease length the worker asked for at hello. `ended_at`
    and `end_reason` record how it last stopped (`released`: a graceful
    `/release`; `empty`: a lease came back empty), for status; a session that
    leases again afterwards is open again.
    """

    __tablename__ = "ai_sessions"
    __table_args__ = (Index("ix_ai_session_worker_started", "worker_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    worker_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("ai_workers.id", ondelete="CASCADE"), nullable=False
    )
    models: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: The rest of the hello: image, device, dtype, threads, config.
    hello: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    lease_s: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(16))
    #: The worker's id for its last /lease and the lease it got: a retried
    #: /lease with the same id gets the same jobs back instead of orphaning them.
    last_lease_request: Mapped[str | None] = mapped_column(String(64))
    last_lease_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
