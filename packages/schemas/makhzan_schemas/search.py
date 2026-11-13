"""Search contract shared by the writer (ingestion) and reader (api).

The search index holds **products** (canonical, deduped), each carrying aggregates
over its offers (min price, supplier count, any-in-stock) so results can show
"from EGP X · N suppliers" without a join. Listings/offers are read from the DB
on the product and supplier pages.

Intentionally free of the meilisearch client dependency: this module only builds
plain dicts and holds config. Each app owns its own client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from makhzan_schemas.domains import DEFAULT_DOMAIN, PROFILES, get_profile

if TYPE_CHECKING:
    from makhzan_schemas.models import Product

INDEX_NAME = "products"

# Order matters: earlier attributes rank higher. Taken from the default domain's
# profile — electronics ranks the part number first because its search is
# identifier-driven.
#
# Meilisearch settings are index-wide, so this cannot yet differ per domain. A
# vertical that ranks very differently (nobody searches an MPN for gloves) will
# need either a compromise order or a per-domain index; revisit when the second
# domain lands. Documents carry `domain` so results can at least be filtered.
SEARCHABLE_ATTRIBUTES = list(get_profile(DEFAULT_DOMAIN).search_attributes)

FILTERABLE_ATTRIBUTES = [
    # Canonical category identity. A bare slug is ambiguous: slugs are unique per
    # domain, so "measurement" names both an electronics leaf and a tools one.
    # Filtering on the bare slug silently mixes verticals.
    "category_ref",
    # The leaf's ref and every ancestor's, leaf first. Products are filed on
    # leaves, so a filter on `category_ref` alone can never narrow to a group
    # ("Passives") whose products all sit on its children. The API's category
    # filter matches here, so a group page narrows like a leaf page does.
    "category_refs",
    "category_slug",
    "domain",
    "in_stock",
    "currency",
    "min_price",
    # Filterable as well as sortable, so "sold by more than one supplier" — the
    # one thing no single supplier's own site can show — is a query rather than
    # a post-filter over a page of results.
    "supplier_count",
    # Every shop with an offer on the product, so "search within this shop" is a
    # filter over the same product index rather than a second, listing-level
    # search with its own ranking. An array: a product sold by three shops
    # matches a filter on any one of them.
    "supplier_slugs",
    # The newest check of any of the product's offers, in epoch seconds. Filtered
    # as a range (`last_verified_at > cutoff`) to hide stale products by default
    # (makhzan_schemas.freshness, rule C2b). Not a facet: a facet over a
    # timestamp is one bucket per second. And not a stored "is stale" flag: that
    # would go stale itself between reindexes, as time passes and nothing else does.
    "last_verified_at",
]

#: Facets returned with a search so a browse rail can show counts without a
#: second round trip. Only attributes a user can actually narrow by; `min_price`
#: is a range, not a facet, and would return one bucket per distinct price.
FACET_ATTRIBUTES = ["domain", "category_ref", "in_stock"]

SORTABLE_ATTRIBUTES = ["min_price", "last_verified_at", "supplier_count", "offer_count"]

#: Attributes to search when the query is plain words. Deliberately excludes
#: part_number: it ranks first index-wide, which is right for "LM358" and wrong
#: for "digital caliper" — a stray identifier match would outrank real title hits.
TEXT_SEARCH_ATTRIBUTES = [a for a in SEARCHABLE_ATTRIBUTES if a != "part_number"]

#: Longer than this and it is a phrase, not a part number. Guards against a
#: descriptive query happening to contain something identifier-shaped.
_MAX_IDENTIFIER_TOKENS = 2


def looks_like_identifier(query: str) -> bool:
    """True when a search query looks like a part number rather than words.

    Meilisearch ranks by the index-wide order of `searchableAttributes`, so
    part_number cannot be promoted per query. Instead the caller narrows which
    attributes are searched: identifier-shaped queries search everything (and so
    get part_number's ranking), while word queries skip it entirely.

    Reuses each domain's own identifier extractor rather than inventing a second
    notion of what a part number looks like.
    """
    stripped = query.strip()
    if not stripped or len(stripped.split()) > _MAX_IDENTIFIER_TOKENS:
        return False
    return any(profile.extract_identifier(stripped) for profile in PROFILES.values())


def category_ref(domain: str | None, slug: str | None) -> str | None:
    """Canonical `domain:slug` identity for a category.

    Search itself stays cross-domain — a shopper looking for a multimeter should
    see electronics and tools results together, and ranking decides the order.
    This exists for the places that must name one exact category: the browse
    tree and the category filter.
    """
    if not slug:
        return None
    return f"{domain or DEFAULT_DOMAIN}:{slug}"


def price_on_request(min_price: Any, on_request_count: int | None) -> str | None:
    """ "all", "some" or None: see `ProductSummary.price_on_request`, which
    reads the same two fields."""
    if not on_request_count:
        return None
    return "all" if min_price is None else "some"


def _enum(value: Any) -> Any:
    return getattr(value, "value", value)


def build_product_document(
    product: "Product",
    category_slug: str | None,
    category_name: str | None,
    category_domain: str | None = None,
    supplier_slugs: list[str] | None = None,
    category_refs: list[str] | None = None,
    image_shop: dict | None = None,
    min_price_shop: dict | None = None,
) -> dict:
    """Project a Product (with its aggregates) into a flat Meilisearch document.

    `supplier_slugs` is not a Product column — it comes from the product's active
    listings, so the caller passes it in. Sorted, so a rebuild of an unchanged
    product produces an identical document.

    `category_refs` is the category's ref followed by its ancestors' (the caller
    walks the tree). Omitted, it is just the leaf's own ref; a product with no
    category gets an empty list rather than a missing attribute.

    `image_shop` is `{"slug", "name"}` of the shop the photo comes from
    (`Product.image_supplier_id`), for the badge on it; null without a photo or
    a known shop. Display only: not searched, filtered or sorted on.

    `min_price_shop` is `{"slug", "name"}` of the shop whose offer sets
    `min_price` (`Product.min_price_supplier_id`). It and the other fields
    about the low end (`min_price_option`, `min_price_quantity`, `price_each`,
    `on_request_count`, `price_on_request`) are display only, and mean what
    `ProductSummary` says they mean (makhzan_schemas.pricing).
    """
    lv = product.last_verified_at
    leaf = category_ref(category_domain or product.domain, category_slug)
    if category_refs is None:
        category_refs = [leaf] if leaf else []
    return {
        "id": str(product.id),
        "domain": product.domain,
        "part_number": product.part_number,
        "title_en": product.title_en,
        "title_ar": product.title_ar,
        "brand": product.brand,
        "category_slug": category_slug,
        "category_ref": leaf,
        "category_refs": list(dict.fromkeys(category_refs)),
        "category_name": category_name,
        "supplier_name": product.supplier_name,
        "supplier_count": product.supplier_count,
        "supplier_slugs": sorted(set(supplier_slugs or [])),
        "offer_count": product.offer_count,
        "min_price": float(product.min_price) if product.min_price is not None else None,
        "max_price": float(product.max_price) if product.max_price is not None else None,
        "min_price_offer_id": (
            str(product.min_price_listing_id) if product.min_price_listing_id else None
        ),
        "min_price_shop": min_price_shop if product.min_price is not None else None,
        "min_price_option": product.min_price_option,
        "min_price_quantity": product.min_price_quantity,
        "price_each": bool(product.price_each),
        "on_request_count": product.on_request_count or 0,
        "price_on_request": price_on_request(product.min_price, product.on_request_count),
        "currency": product.currency,
        "in_stock": product.in_stock,
        "image": product.image,
        "image_shop": image_shop if product.image else None,
        "last_verified_at": int(lv.timestamp()) if lv else None,
    }
