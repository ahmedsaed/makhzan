"""Shared enumerations.

Kept in one place so ORM columns, Pydantic contracts, and adapter code all
speak the same vocabulary.
"""

from enum import StrEnum


class SourceType(StrEnum):
    """How a listing entered the system."""

    SCRAPED = "scraped"
    MANUAL = "manual"
    PORTAL = "portal"


class SupplierStatus(StrEnum):
    UNVERIFIED = "unverified"  # discovered via scrape/manual, not confirmed
    VERIFIED = "verified"  # ops-confirmed real business
    CLAIMED = "claimed"  # supplier owns it via the portal


class ListingStatus(StrEnum):
    ACTIVE = "active"  # live, shown in search
    PENDING_REVIEW = "pending_review"  # awaiting human confirmation
    HIDDEN = "hidden"  # deliberately not shown
    ARCHIVED = "archived"  # source gone / withdrawn


class StockSignal(StrEnum):
    """Coarse availability — we only ever get hints, never real stock counts."""

    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    MADE_TO_ORDER = "made_to_order"
    UNKNOWN = "unknown"


class IngestionStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # completed but with some failed items
    FAILED = "failed"


class ReviewReason(StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    MISSING_PRICE = "missing_price"
    UNMAPPED_CATEGORY = "unmapped_category"
    AMBIGUOUS_PARSE = "ambiguous_parse"
    NEW_SUPPLIER = "new_supplier"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


DEFAULT_CURRENCY = "EGP"
