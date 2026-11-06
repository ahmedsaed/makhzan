"""Product grouping — derive canonical products from listings.

Every active listing maps to exactly one product:
  - a confident part number  -> shared product  "mpn:<PN>"
  - otherwise                 -> singleton       "single:<source>:<external_id>"

Precision guard: a handful of part numbers are ambiguous *families* (ESP32,
ATMEGA328P, STM32, L298...) that get built into many distinct products. For
those — and only those — we sub-cluster the group by significant-title-token
similarity, so identical variants across suppliers merge (ESP32-CAM ×3) while
different ones split (ESP32-CAM vs ESP32 T-Beam). Specific parts (LM358, DS3231)
are untouched — their varied descriptions are synonyms that should stay merged.

Singleton keys are derived from the listing's natural key so a product's identity
(and URL) stays stable across re-scrapes. `rebuild_products` is a full, idempotent
recompute — cheap at this scale; can be made incremental later.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from makhzan_schemas.domains import get_profile
from makhzan_schemas.enums import ListingStatus, StockSignal
from makhzan_schemas.models import Listing, Product
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

_TOKEN = re.compile(r"[a-z0-9]+")


def base_key(part_number: str | None, source: str, external_id: str | None, listing_id) -> str:
    if part_number:
        return f"mpn:{part_number.upper()}"
    return f"single:{source}:{external_id or listing_id}"


def _sig_tokens(title: str | None, mpn: str, domain: str | None = None) -> set[str]:
    noise = get_profile(domain).noise_tokens
    text = (title or "").lower().replace(mpn.lower(), " ")
    return {t for t in _TOKEN.findall(text) if t not in noise and len(t) >= 2 and not t.isdigit()}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0  # both "bare" (just the family name) — same product
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _span_ok(prices: list[Decimal], candidate: Decimal | None, max_ratio: float) -> bool:
    """Whether adding `candidate` keeps a cluster's prices within one band.

    A *veto*, not a reason to merge. Price used to be sufficient evidence on its
    own, which is how twenty-two different ESP32 boards became one product: they
    share a family prefix, and within a family everything costs roughly the same,
    so price agreed with everything. It says almost nothing about identity.

    It still says something about non-identity. Identical titles priced 15x apart
    are a pack and a single unit, not one product, and merging them publishes a
    price range that is simply false.

    Measured across the whole cluster rather than against one representative: a
    band centred on one mid-priced member reached from 65 to 1040 EGP and
    swallowed the family.

    A missing price is not evidence either way, so it neither blocks nor widens.
    """
    known = [p for p in [*prices, candidate] if p is not None and p > 0]
    if len(known) < 2:
        return True
    return (max(known) / min(known)) <= Decimal(str(max_ratio))


@dataclass
class _Cluster:
    """One sub-product being accumulated out of a shared-identifier group."""

    #: Tokens of the member that seeded it — the stable part of the group key.
    seed_tokens: set[str]
    #: Every member's tokens. A candidate is compared against all of them, not
    #: just the seed: the seed can be title-poor ("ESP32 Development Board 30
    #: pin" reduces to {pin} once noise is stripped), and comparing only against
    #: it made the cluster unmatchable by title and so a price-only magnet.
    token_sets: list[set[str]]
    prices: list[Decimal]
    members: list[Listing]

    def admits(
        self, tokens: set[str], price: Decimal | None, threshold: float, ratio: float
    ) -> bool:
        if not any(_jaccard(tokens, known) >= threshold for known in self.token_sets):
            return False
        return _span_ok(self.prices, price, ratio)

    def add(self, listing: Listing, tokens: set[str]) -> None:
        self.members.append(listing)
        self.token_sets.append(tokens)
        if listing.price is not None:
            self.prices.append(listing.price)


def _subcluster(
    mpn_key: str, items: list[Listing], domain: str | None = None
) -> dict[str, list[Listing]]:
    """Split a shared-identifier group into sub-products by corroborating evidence.

    An extracted identifier is evidence, not proof. It is pulled from a title, so
    it also matches titles that merely *reference* the part — "bracket for SG90",
    "robot arm kit with 4x SG90" — and merging those produces a product page with
    a mounting bracket inside a servo.

    So two listings sharing an identifier are only treated as the same product
    when their **titles** agree that they are the same thing. Price is not
    evidence of identity: an extracted identifier is often a family prefix
    ("ESP32", "ESP8266", "CR2025") rather than a part, and within a family
    everything costs about the same, so price agreed with everything. Letting it
    merge on its own put an MP3 player, a battery shield and a SIM800L module
    inside one ESP32 board — 22 offers spanning 99 to 850 EGP.

    Price still gets a veto. Identical titles priced 15x apart are a pack and a
    single unit, and merging them publishes a price range that is false.
    """
    mpn = mpn_key[len("mpn:") :]
    profile = get_profile(domain)
    threshold = profile.cluster_threshold
    max_ratio = profile.merge_price_ratio
    # Deterministic order so cluster assignment (and keys) are stable across runs.
    ordered = sorted(items, key=lambda listing: listing.external_id or str(listing.id))

    clusters: list[_Cluster] = []
    for listing in ordered:
        tokens = _sig_tokens(listing.title_en or listing.title_ar, mpn, domain)
        for cluster in clusters:
            if cluster.admits(tokens, listing.price, threshold, max_ratio):
                cluster.add(listing, tokens)
                break
        else:
            clusters.append(
                _Cluster(
                    seed_tokens=tokens,
                    token_sets=[tokens],
                    prices=[listing.price] if listing.price is not None else [],
                    members=[listing],
                )
            )

    result: dict[str, list[Listing]] = {}
    for cluster in clusters:
        members = cluster.members
        sig = "-".join(sorted(cluster.seed_tokens)) or "base"
        key = f"{mpn_key}:{sig}"
        while key in result:  # guard against signature collisions
            key += "_"
        result[key] = members
    return result


def _representative(items: list[Listing]) -> Listing:
    """Pick the best listing to represent the product: has image + title, in stock, cheapest."""

    def score(listing: Listing):
        return (
            0 if listing.images else 1,
            0 if listing.title_en else 1,
            0 if listing.stock_signal == StockSignal.IN_STOCK else 1,
            listing.price if listing.price is not None else Decimal("Infinity"),
        )

    return min(items, key=score)


def _group_listings(listings: list[Listing]) -> dict[str, list[Listing]]:
    """Two-phase grouping: base key, then sub-cluster ambiguous family groups."""
    base: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        base[base_key(listing.part_number, listing.source, listing.external_id, listing.id)].append(
            listing
        )

    groups: dict[str, list[Listing]] = {}
    for key, items in base.items():
        # A group's listings share an identifier, so they share a domain in
        # practice; take it from the first and let the profile decide.
        domain = items[0].domain if items else None
        # Every shared-identifier group is corroborated, not just a hardcoded
        # list of "ambiguous" families. That list was unmaintainable by
        # construction — SG90 and CR10 were never on it, and there is no reason
        # to expect the next one to be either.
        if key.startswith("mpn:") and len(items) > 1:
            groups.update(_subcluster(key, items, domain))
        else:
            groups[key] = items
    return groups


async def rebuild_products(session: AsyncSession) -> dict:
    """Recompute all products + aggregates from active listings, link listings, prune empties."""
    listings = (
        (
            await session.execute(
                select(Listing)
                .where(Listing.status == ListingStatus.ACTIVE)
                .options(selectinload(Listing.supplier))
            )
        )
        .scalars()
        .all()
    )

    groups = _group_listings(listings)

    existing = {p.group_key: p for p in (await session.execute(select(Product))).scalars().all()}

    seen: set[str] = set()
    for key, items in groups.items():
        seen.add(key)
        product = existing.get(key)
        if product is None:
            product = Product(group_key=key)
            session.add(product)

        rep = _representative(items)
        prices = [i.price for i in items if i.price is not None]
        product.part_number = items[0].part_number if key.startswith("mpn:") else None
        product.domain = rep.domain
        product.title_en = rep.title_en
        product.title_ar = rep.title_ar
        product.brand = rep.brand
        product.category_id = rep.category_id
        product.supplier_name = rep.supplier.name if rep.supplier else None
        product.image = (
            rep.images[0] if rep.images else next((i.images[0] for i in items if i.images), None)
        )
        product.offer_count = len(items)
        product.supplier_count = len({i.supplier_id for i in items})
        product.min_price = min(prices) if prices else None
        product.max_price = max(prices) if prices else None
        product.in_stock = any(i.stock_signal == StockSignal.IN_STOCK for i in items)
        verified = [i.last_verified_at for i in items if i.last_verified_at]
        product.last_verified_at = max(verified) if verified else None

    await session.flush()  # assign ids to newly-added products

    all_products = {
        p.group_key: p for p in (await session.execute(select(Product))).scalars().all()
    }
    for key, items in groups.items():
        product_id = all_products[key].id
        for listing in items:
            listing.product_id = product_id
    # Persist the new links BEFORE deleting stale products, so the FK's
    # ON DELETE SET NULL can't null a listing we just re-pointed.
    await session.flush()

    stale_ids = [p.id for key, p in existing.items() if key not in seen]
    if stale_ids:
        await session.execute(delete(Product).where(Product.id.in_(stale_ids)))

    await session.commit()
    removed = len(stale_ids)
    return {
        "products": len(groups),
        "multi_supplier": sum(
            1 for items in groups.values() if len({i.supplier_id for i in items}) > 1
        ),
        "removed": removed,
    }
