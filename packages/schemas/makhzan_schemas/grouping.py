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

A group key says which listings form one product; it is not the product's
identity. `plan_identity` matches each group to the product its listings already
belong to, so a product's id (its URL) survives a second shop selling it, the
listing that named its key going away, and a change to these rules
(docs/decisions/0004-stable-product-ids.md). `rebuild_products` is a full,
idempotent recompute — cheap at this scale; can be made incremental later.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from makhzan_schemas.domains import get_profile
from makhzan_schemas.enums import ListingStatus, ProductEventKind, StockSignal
from makhzan_schemas.freshness import fresh_since
from makhzan_schemas.models import Listing, Product, ProductEvent, ProductRedirect
from makhzan_schemas.values import value_tokens, values_conflict
from sqlalchemy import select, text, update
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


def _pictured(rep: Listing, items: list[Listing]) -> Listing | None:
    """The listing whose first photo is the product's: the representative's
    when it has one, else the first listing in the group that does."""
    if rep.images:
        return rep
    return next((i for i in items if i.images), None)


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


# ---------------------------------------------------------------------------
# Identity: which existing product each group is
# ---------------------------------------------------------------------------


@dataclass
class IdentityPlan:
    """What a regroup does to product ids, decided before anything is written.

    `_group_listings` says which listings form one product; this says which
    existing product each of those groups *is*, so that ids survive the regroup
    (docs/decisions/0004-stable-product-ids.md).
    """

    #: Group key → the existing product it keeps, or None for a new product.
    assigned: dict[str, uuid.UUID | None]
    #: Absorbed product → survivor. The absorbed id now redirects.
    merges: dict[uuid.UUID, uuid.UUID]
    #: (product, group key) for each part of a product's offers that left it for
    #: another group. The product itself keeps its core.
    splits: list[tuple[uuid.UUID, str]]
    #: Products none of whose offers is active any more.
    emptied: list[uuid.UUID]
    #: Emptied products that have an active offer again, and keep their id.
    revived: list[uuid.UUID]
    #: Merged-away product → the survivor it is taken back from: the group it
    #: last was has formed again, so the merge is undone and the id is live.
    unmerged: dict[uuid.UUID, uuid.UUID]
    #: Active offers each existing product carried into the regroup.
    offers_before: dict[uuid.UUID, int]


def _listing_order(listing: Listing) -> tuple:
    """Earliest-seen first; the natural key breaks ties, so the order is total."""
    seen = listing.first_seen_at
    return (seen.timestamp() if seen else float("inf"), *_natural_order(listing), str(listing.id))


def plan_identity(
    groups: dict[str, list[Listing]],
    current: dict[uuid.UUID, uuid.UUID | None],
    created: dict[uuid.UUID, datetime],
    delisted: set[uuid.UUID],
    dormant: dict[str, list[tuple[uuid.UUID, uuid.UUID, datetime | None]]] | None = None,
) -> IdentityPlan:
    """Match target groups to the products their listings already belong to.

    `current` is each listing's product before the regroup, already followed
    through any merge; `created` is every product that can still be matched
    (listed or emptied, not merged away), with when it was created; `delisted`
    is the emptied ones among them; `dormant` is the merged-away products by
    the group key they last had, as (id, merged into, created).

    - **Undo** comes first: a group formed only of one product's offers that is
      exactly the group a product merged into it last was gets that merged-away
      id back, provided the product keeps another part.
    - A product's **core** is, of what is left, the group holding most of its
      active offers; ties go to the group holding its earliest-seen listing.
      The product keeps its id there.
    - A group that is the core of several products is a **merge**. The survivor
      is the one that carried more active offers into the regroup, then the
      older; the rest redirect to it.
    - A product's offers that fall into groups other than its core are a
      **split**: they go to whatever product that group is, a new one if it is
      no one's core.
    - A group that is no one's core is a new product.
    - A product with no active offer left is **emptied**, never deleted.

    Pure and deterministic: the same inputs give the same plan, whatever order
    a query returned rows in.
    """
    tally: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    earliest: dict[uuid.UUID, dict[str, tuple]] = defaultdict(dict)
    for key, items in groups.items():
        for listing in items:
            product_id = current.get(listing.id)
            if product_id is None or product_id not in created:
                continue
            tally[product_id][key] += 1
            order = _listing_order(listing)
            if key not in earliest[product_id] or order < earliest[product_id][key]:
                earliest[product_id][key] = order

    offers_before = {product_id: sum(keys.values()) for product_id, keys in tally.items()}

    # Undo first. A part of a product's offers that forms exactly the group a
    # product merged into it last was goes back to that id: a rule tried and
    # reverted, or an offer gone for a while and back, then leaves every id
    # where it was instead of minting new ones beside redirects. Only while the
    # product keeps another part, so a product people were sent to never turns
    # into "no longer listed" because its offers moved back.
    assigned: dict[str, uuid.UUID | None] = {}
    unmerged: dict[uuid.UUID, uuid.UUID] = {}
    remaining = {product_id: set(keys) for product_id, keys in tally.items()}
    for key in sorted(groups):
        sources = {current.get(listing.id) for listing in groups[key]} - {None}
        if len(sources) != 1:
            continue
        (into,) = sources
        if into not in remaining or len(remaining[into]) < 2:
            continue
        candidates = sorted(
            (_when(when), str(product_id), product_id)
            for product_id, merged_into, when in (dormant or {}).get(key, ())
            if merged_into == into
        )
        if candidates:
            product_id = candidates[0][2]
            assigned[key] = product_id
            unmerged[product_id] = into
            remaining[into].discard(key)

    core: dict[uuid.UUID, str] = {
        product_id: min(
            remaining[product_id],
            key=lambda k, p=product_id, n=keys: (-n[k], earliest[p][k], k),
        )
        for product_id, keys in tally.items()
    }

    claimants: dict[str, list[uuid.UUID]] = defaultdict(list)
    for product_id, key in core.items():
        claimants[key].append(product_id)

    merges: dict[uuid.UUID, uuid.UUID] = {}
    for key in groups:
        if key in assigned:
            continue
        claims = claimants.get(key)
        if not claims:
            assigned[key] = None
            continue
        survivor = min(claims, key=lambda p: (-offers_before[p], _when(created[p]), str(p)))
        assigned[key] = survivor
        for product_id in sorted(claims, key=str):
            if product_id != survivor:
                merges[product_id] = survivor

    splits = sorted(
        (
            (product_id, key)
            for product_id, keys in tally.items()
            for key in keys
            if key != core[product_id]
        ),
        key=lambda pair: (str(pair[0]), pair[1]),
    )
    emptied = sorted((p for p in created if p not in tally and p not in delisted), key=str)
    revived = sorted((p for p in assigned.values() if p is not None and p in delisted), key=str)
    return IdentityPlan(
        assigned=assigned,
        merges=merges,
        splits=splits,
        emptied=emptied,
        revived=revived,
        unmerged=unmerged,
        offers_before=offers_before,
    )


def _when(moment: datetime | None) -> float:
    """A sortable creation time; one not yet known sorts last (newest)."""
    return moment.timestamp() if moment else float("inf")


def _resolve(
    product_id: uuid.UUID | None, merged_into: dict[uuid.UUID, uuid.UUID]
) -> uuid.UUID | None:
    """Follow a merged-away product to the one it became.

    Normally one hop, since every merge repoints what led to the absorbed
    product; bounded so that a corrupt chain cannot loop.
    """
    for _ in range(8):
        if product_id is None or product_id not in merged_into:
            return product_id
        product_id = merged_into[product_id]
    return product_id


#: Postgres advisory lock key held, for the rest of the transaction, by anything
#: that rewrites which products exist: a regroup and redirect retirement.
PRODUCTS_LOCK_KEY = 0x6D616B687A616E  # "makhzan"


async def lock_products(session: AsyncSession) -> None:
    """Wait for, then hold until commit or rollback, the products lock.

    Two regroups at once would each mint a product for the same new group, and
    with permanent ids neither would ever go away. The worker's `_REBUILD_LOCK`
    only covers its own jobs; `worker.regroup` and `./makhzan retire` run in
    processes of their own, so the lock is the database's.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PRODUCTS_LOCK_KEY})


async def rebuild_products(session: AsyncSession, *, dry_run: bool = False) -> dict:
    """Regroup active listings into products, keeping every product's id.

    Groups are computed exactly as before (`_group_listings`, every veto
    intact); `plan_identity` then decides which existing product each group is.
    Nothing is deleted: a product whose offers joined another is marked
    `merged_into` it, and one whose offers are all gone is marked `delisted_at`.
    Each merge, split, emptying and revival is recorded in `product_events`.

    `dry_run` applies everything inside the transaction and then rolls it back:
    the counts returned are what a real run would do, and nothing is kept.
    """
    await lock_products(session)
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
    groups = _group_listings(listings)

    products = {p.id: p for p in (await session.execute(select(Product))).scalars().all()}
    merged_into = {p.id: p.merged_into for p in products.values() if p.merged_into is not None}
    matchable = {p.id: p.created_at for p in products.values() if p.merged_into is None}
    delisted = {p.id for p in products.values() if p.merged_into is None and p.delisted_at}
    current = {listing.id: _resolve(listing.product_id, merged_into) for listing in listings}
    dormant: dict[str, list[tuple[uuid.UUID, uuid.UUID, datetime | None]]] = defaultdict(list)
    for p in products.values():
        if p.merged_into is not None:
            dormant[p.group_key].append((p.id, p.merged_into, p.created_at))

    plan = plan_identity(groups, current, matchable, delisted, dormant)

    now = datetime.now(UTC)
    changed = created = 0
    group_product: dict[str, Product] = {}
    for key, items in groups.items():
        existing = plan.assigned[key]
        if existing is None:
            # The id is set here rather than on flush, so the listings and the
            # events below can point at it straight away.
            product = Product(id=uuid.uuid4(), group_key=key)
            session.add(product)
            before = None
            created += 1
        else:
            product = products[existing]
            # A revived or un-merged product's page comes back, whatever its
            # aggregates say.
            hidden = product.delisted_at is not None or product.merged_into is not None
            before = None if hidden else _visible(product)
            product.delisted_at = None
            product.merged_into = None
            product.merged_at = None
        group_product[key] = product

        rep = _representative(items)
        prices = [i.price for i in items if i.price is not None]
        product.group_key = key
        product.part_number = items[0].part_number if key.startswith("mpn:") else None
        product.domain = rep.domain
        product.title_en = rep.title_en
        product.title_ar = rep.title_ar
        product.brand = rep.brand
        product.category_id = rep.category_id
        product.supplier_name = rep.supplier.name if rep.supplier else None
        pictured = _pictured(rep, items)
        product.image = pictured.images[0] if pictured else None
        # The photo's own shop, read off the listing it was taken from: the
        # badge on it names whose photo it is, which is not always the shop
        # `supplier_name` names.
        product.image_supplier_id = pictured.supplier_id if pictured else None
        product.offer_count = len(items)
        product.supplier_count = len({i.supplier_id for i in items})
        # The price a result card shows, sorts and filters by: the fresh offers'
        # when any has a price, so a card never quotes a stale shop's cheaper
        # price while the product page leads with the fresh one. All offers'
        # only when none is fresh (the page then warns that it is out of date).
        cutoff = fresh_since(now)
        fresh = [
            i.price
            for i in items
            if i.price is not None
            and i.last_verified_at is not None
            and i.last_verified_at.timestamp() > cutoff
        ]
        shown = fresh or prices
        product.min_price = min(shown) if shown else None
        product.max_price = max(shown) if shown else None
        product.in_stock = any(i.stock_signal == StockSignal.IN_STOCK for i in items)
        verified = [i.last_verified_at for i in items if i.last_verified_at]
        product.last_verified_at = max(verified) if verified else None
        if before is None or _visible(product) != before:
            product.content_changed_at = now
            changed += 1
        for listing in items:
            listing.product_id = product.id

    events = [
        ProductEvent(
            product_id=product_id,
            kind=ProductEventKind.REVIVED,
            detail={"group_key": products[product_id].group_key},
        )
        for product_id in plan.revived
    ]
    # Un-merged: the id was a redirect and is a product again.
    events += [
        ProductEvent(
            product_id=product_id,
            kind=ProductEventKind.REVIVED,
            other_id=survivor_id,
            detail={"group_key": products[product_id].group_key, "unmerged": True},
        )
        for product_id, survivor_id in sorted(plan.unmerged.items(), key=lambda kv: str(kv[0]))
    ]
    events += [
        ProductEvent(
            product_id=product_id,
            kind=ProductEventKind.SPLIT,
            other_id=group_product[key].id,
            detail={"group_key": key, "offers": len(groups[key])},
        )
        for product_id, key in plan.splits
    ]

    for absorbed_id, survivor_id in plan.merges.items():
        absorbed = products[absorbed_id]
        absorbed.merged_into = survivor_id
        absorbed.merged_at = now
        _withdraw(absorbed)
        events.append(
            ProductEvent(
                product_id=absorbed_id,
                kind=ProductEventKind.MERGE,
                other_id=survivor_id,
                detail={
                    "group_key": products[survivor_id].group_key,
                    "offers_before": plan.offers_before.get(absorbed_id, 0),
                    "survivor_offers_before": plan.offers_before.get(survivor_id, 0),
                },
            )
        )
    if plan.merges:
        # One hop: whatever led to an absorbed product now leads to its survivor.
        for product in products.values():
            if product.merged_into in plan.merges:
                product.merged_into = plan.merges[product.merged_into]
        for absorbed_id, survivor_id in plan.merges.items():
            await session.execute(
                update(ProductRedirect)
                .where(ProductRedirect.new_id == absorbed_id)
                .values(new_id=survivor_id)
            )

    for product_id in plan.emptied:
        product = products[product_id]
        product.delisted_at = now
        product.content_changed_at = now
        _withdraw(product)
        events.append(
            ProductEvent(
                product_id=product_id,
                kind=ProductEventKind.EMPTIED,
                detail={"group_key": product.group_key},
            )
        )

    session.add_all(events)
    await session.flush()
    stats = {
        "products": len(groups),
        "multi_supplier": sum(
            1 for items in groups.values() if len({i.supplier_id for i in items}) > 1
        ),
        "kept": len(groups) - created,
        "created": created,
        "merged": len(plan.merges),
        "split": len({product_id for product_id, _ in plan.splits}),
        "emptied": len(plan.emptied),
        "revived": len(plan.revived),
        "unmerged": len(plan.unmerged),
        "changed": changed,
    }
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return stats


def describe(stats: dict) -> str:
    """One line for a command's output: what a regroup did to products."""
    return (
        f"products: {stats['products']} listed ({stats['multi_supplier']} multi-supplier); "
        f"ids kept {stats['kept']}, new {stats['created']}, merged {stats['merged']}, "
        f"split {stats['split']}, emptied {stats['emptied']}, revived {stats['revived']}, "
        f"un-merged {stats['unmerged']}"
    )


def _withdraw(product: Product) -> None:
    """Zero what counts a product's live offers.

    The title, photo, category and last price range stay: they are what the
    "no longer listed" page shows, and what similar products are found from.
    """
    product.offer_count = 0
    product.supplier_count = 0
    product.in_stock = False


def _visible(product: Product) -> tuple:
    """What a reader sees of a product, as far as `content_changed_at` goes.

    Deliberately not `last_verified_at`: a recheck that found everything as it
    was is not a change, and the sitemap's lastmod is only worth anything to a
    search engine while it is accurate.
    """
    return (
        product.title_en,
        product.min_price,
        product.max_price,
        product.in_stock,
        product.offer_count,
        product.supplier_count,
        product.image,
    )
