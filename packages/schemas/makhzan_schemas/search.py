"""Search contract shared by the writer (ingestion) and reader (api).

The search index holds **products** (canonical, deduped), each carrying aggregates
over its offers (min price, supplier count, any-in-stock) so results can show
"from EGP X · N suppliers" without a join. Listings/offers are read from the DB
on the product and supplier pages.

**Search never depends on grouping.** Every active listing's titles, brands and
part numbers are searchable on its product's document (the `member_*` arrays),
and the product appears once. The product's own `title_en`, `title_ar`, `brand`
and `part_number` are copied from one representative listing, chosen by stock
and price; were they all that was searched, a merge would hide every other
shop's wording and a price change could move a product out of a query's
results. The member arrays hold the same text whichever listing represents the
product, so what a query finds depends only on which listings are active.

Intentionally free of the meilisearch client dependency: this module only builds
plain dicts and holds config. Each app owns its own client.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from makhzan_schemas.domains import DEFAULT_DOMAIN, PROFILES, get_profile

if TYPE_CHECKING:
    from makhzan_schemas.models import Product

INDEX_NAME = "products"

#: Searchable text gathered from every active listing of a product, not only
#: its representative (see the module docstring). Arrays, deduplicated and
#: sorted, so they do not depend on which listing represents the product and a
#: rebuild of an unchanged product produces an identical document.
MEMBER_ATTRIBUTES = [
    "member_titles_en",
    "member_titles_ar",
    "member_brands",
    # Each listing's `part_number`, its stated code (`attributes.mfr_part_number`)
    # and its adapter's (`attributes.adapter_part_number`).
    "member_part_numbers",
]

#: What a search hit returns (`attributesToRetrieve`): every document field but
#: the member arrays, which exist to be searched, not shown. Listing every
#: listing's title on every hit would multiply the payload for nothing a result
#: card displays, and leaving them out here costs the query path nothing, where
#: stripping them from the hits afterwards would be Python over every result.
#: A test holds this to `build_product_document`'s keys, so a new display field
#: cannot silently go missing from results.
DISPLAYED_ATTRIBUTES = [
    "id",
    "domain",
    "part_number",
    "title_en",
    "title_ar",
    "brand",
    "category_slug",
    "category_ref",
    "category_refs",
    "category_name",
    "supplier_name",
    "supplier_count",
    "supplier_slugs",
    "offer_count",
    "min_price",
    "max_price",
    "min_price_offer_id",
    "min_price_shop",
    "min_price_option",
    "min_price_quantity",
    "price_each",
    "on_request_count",
    "price_on_request",
    "currency",
    "in_stock",
    "image",
    "image_shop",
    "last_verified_at",
]

#: Matched only by identifier-shaped queries (`looks_like_identifier`). For a
#: word query a stray code match would outrank real title hits, and a member's
#: code is weaker evidence than the product's own: it is often read from a title
#: that merely references the part ("bracket for SG90").
IDENTIFIER_ATTRIBUTES = ["part_number", "member_part_numbers"]


def _searchable_attributes(own: Iterable[str]) -> list[str]:
    """The product's own attributes in its profile's order, each member array
    straight after the last of its own kind: the product's titles, then the
    members' titles, then brands, and the members' codes last.

    The default domain's profile says the product's `part_number` ranks first
    (electronics search is identifier-driven); that holds only for identifier
    queries, which are the only ones that search it.
    """
    own = list(own)
    order: list[str] = []
    for attr in own:
        order.append(attr)
        if attr == "title_ar" or (attr == "title_en" and "title_ar" not in own):
            order += ["member_titles_en", "member_titles_ar"]
        elif attr == "brand":
            order.append("member_brands")
    order += [a for a in MEMBER_ATTRIBUTES if a not in order]
    return order


# Order matters: earlier attributes rank higher. The product's own attributes
# come from the default domain's profile; the member arrays follow their own
# kind (`_searchable_attributes`). Meilisearch's `attribute` rule comes after
# `words`, `typo` and `proximity`, so the order breaks ties between equally
# good matches: a member's title that holds the query's words closer together
# still outranks a looser match in the product's own title.
#
# Meilisearch settings are index-wide, so this cannot yet differ per domain. A
# vertical that ranks very differently (nobody searches an MPN for gloves) will
# need either a compromise order or a per-domain index; revisit when the second
# domain lands. Documents carry `domain` so results can at least be filtered.
SEARCHABLE_ATTRIBUTES = _searchable_attributes(get_profile(DEFAULT_DOMAIN).search_attributes)

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

#: Attributes to search when the query is plain words. Deliberately excludes the
#: part numbers, the product's and its members': part_number ranks first
#: index-wide, which is right for "LM358" and wrong for "digital caliper" — a
#: stray identifier match would outrank real title hits.
TEXT_SEARCH_ATTRIBUTES = [a for a in SEARCHABLE_ATTRIBUTES if a not in IDENTIFIER_ATTRIBUTES]

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


@dataclass(frozen=True)
class MemberText:
    """What one active listing contributes to its product's searchable text."""

    title_en: str | None = None
    title_ar: str | None = None
    brand: str | None = None
    #: The listing's `part_number`, stated code and adapter's code, any of them None.
    part_numbers: tuple[str | None, ...] = ()


def _distinct(values: Iterable[str | None]) -> list[str]:
    """Non-empty values, one per spelling that differs other than in case or
    spacing, sorted so the result does not depend on the listings' order."""
    seen: dict[str, str] = {}
    for value in values:
        text = " ".join((value or "").split())
        if text:
            key = text.casefold()
            if key not in seen or text < seen[key]:
                seen[key] = text
    return [seen[k] for k in sorted(seen)]


def member_fields(members: Iterable[MemberText]) -> dict[str, list[str]]:
    """The `member_*` arrays of a product's document, from its active listings."""
    members = list(members)
    return {
        "member_titles_en": _distinct(m.title_en for m in members),
        "member_titles_ar": _distinct(m.title_ar for m in members),
        "member_brands": _distinct(m.brand for m in members),
        "member_part_numbers": _distinct(p for m in members for p in m.part_numbers),
    }


def build_product_document(
    product: "Product",
    category_slug: str | None,
    category_name: str | None,
    category_domain: str | None = None,
    supplier_slugs: list[str] | None = None,
    category_refs: list[str] | None = None,
    image_shop: dict | None = None,
    min_price_shop: dict | None = None,
    members: Iterable[MemberText] = (),
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

    `members` is the text of each of the product's **active** listings, the
    representative included (`member_fields`). Searched, never displayed: the
    API's searches retrieve only `DISPLAYED_ATTRIBUTES`.
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
        **member_fields(members),
    }
