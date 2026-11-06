"""Product grouping — derive canonical products from listings.

Every active listing maps to exactly one product:
  - a confident part number  -> shared product  "mpn:<PN>:<signature>"
  - otherwise                 -> singleton       "single:<source>:<external_id>"

A shared part number is evidence, not proof, so every group that shares one is
sub-clustered (`_subcluster`): listings merge only when their titles agree, and
any of these vetoes a merge outright —

  - the two listings come from the same supplier (a shop's two SKUs are two
    products);
  - their titles state different values of the same unit (30-pin vs 38-pin,
    40 °C vs 140 °C, 180° vs 360°, a 3-pack vs one) — see `makhzan_schemas.values`;
  - their titles state different forms (a bare chip vs a module, or an
    accessory such as a bracket vs the part it fits) — see
    `DomainProfile.form_markers`;
  - their prices are implausibly far apart.

Keys are derived from stable listing data, so a product's identity (and URL)
survives re-scrapes. `rebuild_products` is a full, idempotent recompute — cheap
at this scale; can be made incremental later.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from makhzan_schemas.domains import get_profile
from makhzan_schemas.enums import ListingStatus, StockSignal
from makhzan_schemas.models import Listing, Product, ProductRedirect
from makhzan_schemas.values import value_tokens, values_conflict
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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


_FORM_CACHE: dict[str, list[tuple[str, re.Pattern[str]]]] = {}


def _form(title: str | None, mpn: str, domain: str | None = None) -> str | None:
    """The physical form a title states ("chip", "module"...), or None if silent.

    Read before noise stripping, because the noise list is exactly where the
    words that say it ("ic", "module", "board") are thrown away.
    """
    profile = get_profile(domain)
    compiled = _FORM_CACHE.get(profile.slug)
    if compiled is None:
        compiled = [(form, re.compile(pattern)) for form, pattern in profile.form_markers]
        _FORM_CACHE[profile.slug] = compiled
    text = (title or "").lower().replace(mpn.lower(), " ")
    return next((form for form, pattern in compiled if pattern.search(text)), None)


def _forms_conflict(a: str | None, b: str | None, strict: frozenset[str]) -> bool:
    """Two stated forms that differ conflict; silence conflicts only with a strict one."""
    if a == b:
        return False
    if a and b:
        return True
    return (a or b) in strict


@dataclass
class _Evidence:
    """What one listing's title says about it, read once."""

    tokens: set[str]
    values: dict[str, frozenset[Decimal]]
    form: str | None


@dataclass
class _Cluster:
    """One sub-product being accumulated out of a shared-identifier group."""

    #: Tokens of the member that seeded it — the stable part of the group key.
    seed_tokens: set[str]
    #: Every member's evidence. A candidate is compared against all of them, not
    #: just the seed: the seed can be title-poor ("ESP32 Development Board 30
    #: pin" reduces to {pin} once noise is stripped), and comparing only against
    #: it made the cluster unmatchable by title and so a price-only magnet.
    evidence: list[_Evidence]
    prices: list[Decimal]
    members: list[Listing]
    suppliers: set[uuid.UUID]

    def similarity(
        self,
        listing: Listing,
        ev: _Evidence,
        threshold: float,
        ratio: float,
        strict: frozenset[str] = frozenset(),
    ) -> float | None:
        """How well a candidate matches, or None if it may not join at all.

        Title similarity admits; everything else can only veto. Each veto is
        checked against *every* member, because a cluster is joined through
        whichever member matches best — checking only that one is how a 30-pin
        board chained a 38-pin one in through a third, vaguer title.
        """
        # A shop lists two SKUs because they differ. Two of its own listings in
        # one product were, in practice, always variants collapsed together:
        # KSD301 switches from 40 to 140 °C, thirteen trimpot values, 180° and
        # 360° servos. A shop's genuine duplicate stays a separate product, which
        # is the honest under-merge.
        if listing.supplier_id in self.suppliers:
            return None
        if any(values_conflict(ev.values, known.values) for known in self.evidence):
            return None
        if any(_forms_conflict(ev.form, known.form, strict) for known in self.evidence):
            return None
        best = max(_jaccard(ev.tokens, known.tokens) for known in self.evidence)
        if best < threshold or not _span_ok(self.prices, listing.price, ratio):
            return None
        return best

    def add(self, listing: Listing, ev: _Evidence) -> None:
        self.members.append(listing)
        self.evidence.append(ev)
        self.suppliers.add(listing.supplier_id)
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
    # External ids are only unique within a source, so two shops' "1234" would
    # otherwise fall back to whatever order the query happened to return.
    ordered = sorted(items, key=_natural_order)

    clusters: list[_Cluster] = []
    for listing in ordered:
        title = listing.title_en or listing.title_ar
        ev = _Evidence(
            tokens=_sig_tokens(title, mpn, domain),
            values=value_tokens((title or "").lower().replace(mpn.lower(), " ")),
            form=_form(title, mpn, domain),
        )
        # The best-matching cluster, not the first that will have it: with a
        # shop's variants now kept apart, a listing can be admissible to several
        # sibling clusters and should join the one it most resembles.
        best: tuple[float, _Cluster] | None = None
        for cluster in clusters:
            score = cluster.similarity(listing, ev, threshold, max_ratio, profile.accessory_forms)
            if score is not None and (best is None or score > best[0]):
                best = (score, cluster)
        if best is not None:
            best[1].add(listing, ev)
        else:
            clusters.append(
                _Cluster(
                    seed_tokens=ev.tokens,
                    evidence=[ev],
                    prices=[listing.price] if listing.price is not None else [],
                    members=[listing],
                    suppliers={listing.supplier_id},
                )
            )

    result: dict[str, list[Listing]] = {}
    for cluster in clusters:
        members = cluster.members
        sig = "-".join(sorted(cluster.seed_tokens)) or "base"
        key = f"{mpn_key}:{sig}"
        if key in result:
            # Variants of one shop often word their titles identically apart from
            # the value ("Thermal Switch NC 40°C" / "… 90°C"), so signatures
            # collide. Disambiguate by the seed listing's own natural key, which
            # survives a re-scrape, rather than by position, which shifts whenever
            # a sibling appears or disappears.
            seed = members[0]
            natural = f"{seed.source}:{seed.external_id or seed.id}"
            key += "~" + hashlib.sha1(natural.encode()).hexdigest()[:10]
        result[key] = members
    return result


def _natural_order(listing: Listing) -> tuple[str, str]:
    return (listing.source, listing.external_id or str(listing.id))


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
                # Group order follows query order (the first listing names a
                # group's domain); a fixed order keeps a rebuild reproducible.
                .order_by(Listing.source, Listing.external_id, Listing.id)
            )
        )
        .scalars()
        .all()
    )

    # Each listing's product before this rebuild: where a replaced product's
    # offers end up is where its URL should lead.
    previous = {listing.id: listing.product_id for listing in listings}

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
    redirected = 0
    if stale_ids:
        successors = _successors(set(stale_ids), listings, previous)
        redirected = await _record_redirects(session, successors)
        # Redirects whose target is going and has no successor go with it
        # (ON DELETE CASCADE): a redirect must never lead to a 404.
        await session.execute(delete(Product).where(Product.id.in_(stale_ids)))

    await session.commit()
    removed = len(stale_ids)
    return {
        "products": len(groups),
        "multi_supplier": sum(
            1 for items in groups.values() if len({i.supplier_id for i in items}) > 1
        ),
        "removed": removed,
        "redirected": redirected,
    }


def _successors(
    stale: set[uuid.UUID],
    listings: Sequence[Listing],
    previous: dict[uuid.UUID, uuid.UUID | None],
) -> dict[uuid.UUID, uuid.UUID]:
    """Each replaced product → the product most of its active offers moved to.

    Ties go to the earliest listing in rebuild order, so the answer does not
    change between two identical rebuilds. A product none of whose offers is
    still active has no successor, and is simply gone.
    """
    votes: dict[uuid.UUID, Counter[uuid.UUID]] = defaultdict(Counter)
    first_seen: dict[uuid.UUID, dict[uuid.UUID, int]] = defaultdict(dict)
    for position, listing in enumerate(listings):
        old = previous.get(listing.id)
        if old in stale and listing.product_id is not None:
            votes[old][listing.product_id] += 1
            first_seen[old].setdefault(listing.product_id, position)
    return {
        old: min(counter, key=lambda new: (-counter[new], first_seen[old][new]))
        for old, counter in votes.items()
    }


async def _record_redirects(session: AsyncSession, successors: dict[uuid.UUID, uuid.UUID]) -> int:
    """Store old → new for this rebuild, and keep every redirect one hop long."""
    if not successors:
        return 0
    # Earlier redirects into a product being replaced now lead to its successor.
    for old, new in successors.items():
        await session.execute(
            update(ProductRedirect).where(ProductRedirect.new_id == old).values(new_id=new)
        )
    stmt = pg_insert(ProductRedirect).values(
        [{"old_id": old, "new_id": new} for old, new in successors.items()]
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[ProductRedirect.old_id], set_={"new_id": stmt.excluded.new_id}
        )
    )
    return len(successors)
