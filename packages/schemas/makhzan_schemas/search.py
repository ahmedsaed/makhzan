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
    "category_slug",
    "domain",
    "in_stock",
    "currency",
    "min_price",
    # Filterable as well as sortable, so "sold by more than one supplier" — the
    # one thing no single supplier's own site can show — is a query rather than
    # a post-filter over a page of results.
    "supplier_count",
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


def _enum(value: Any) -> Any:
    return getattr(value, "value", value)


def build_product_document(
    product: "Product",
    category_slug: str | None,
    category_name: str | None,
    category_domain: str | None = None,
) -> dict:
    """Project a Product (with its aggregates) into a flat Meilisearch document."""
    lv = product.last_verified_at
    return {
        "id": str(product.id),
        "domain": product.domain,
        "part_number": product.part_number,
        "title_en": product.title_en,
        "title_ar": product.title_ar,
        "brand": product.brand,
        "category_slug": category_slug,
        "category_ref": category_ref(category_domain or product.domain, category_slug),
        "category_name": category_name,
        "supplier_name": product.supplier_name,
        "supplier_count": product.supplier_count,
        "offer_count": product.offer_count,
        "min_price": float(product.min_price) if product.min_price is not None else None,
        "max_price": float(product.max_price) if product.max_price is not None else None,
        "currency": product.currency,
        "in_stock": product.in_stock,
        "image": product.image,
        "last_verified_at": int(lv.timestamp()) if lv else None,
    }
