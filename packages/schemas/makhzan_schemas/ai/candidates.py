"""The producers: which pairs AI matching is asked about, and when.

Registered in `triggers.TRIGGERS` on import (the broker imports this module,
so `still_wanted` is asked of the right one). Each yields `PairRequest`s; the
caller hands them to `flow.offer`, so a pair whose requests are already
scored is settled at once.

**candidates** (`match`, P1, P13, P15). After each rebuild, every active
electronics listing's content hash (`hashing.listing_hash`) is compared with
`ai_listing_state`: one whose hash differs from the hash its candidates were
last found for is new or changed. For each, its K = 10 nearest listings from
other shops by title-token Jaccard, the method of the experiments
(`ml/bakeoff/rules.py` and `retrieval.py`, rebuilt for the gain-v2 run):

- tokens are the alphanumeric words of the lower-cased title (English, else
  Arabic), the department's noise words and 1-character tokens dropped, the
  identifier and numbers kept;
- Jaccard against every other-shop electronics listing sharing a token;
  ties by listing id;
- plus the identifier-key pairs the rules split (same base key, different
  product).

One-directional for the daily run; `mutual=True` also takes each listing
whose own top K includes a new or changed one (P1: for backlogs). A pair is
then dropped when today's vetoes refuse it (same shop, values, form, price
at the department's ratio: P13 option (a), not the relaxed set), when the
rules already put both listings in one product, when a person has ruled on it,
or when it already has a standing or revoked decision in `match` (a standing
one is the re-score trigger's; a revoked one was withdrawn by a person).

The first run on a database with no `ai_listing_state` records a baseline and
offers nothing: the existing catalogue is the backlog's (`./makhzan ai
backlog`), scored on the owner's machines (P4), not the daily trigger's.

**backlog**: the same over every electronics listing, at a lower priority.
With every listing a query, each listing's top K already includes both
directions, so the backlog is mutual whatever the flag says.

**audit** (`audit`, P12): each pair of listings from two shops that the rules
put in one product (neither joined by an AI decision) and that has never been
audited, scored by the audit pipeline's stages and recorded; nothing decided.
New pairs appear only when a product's membership changes, so this is the
pairs a membership change made; the first run also takes the existing ones.

**rescore** (P5, P6, P8): a standing decision whose listings' current content
hashes differ from the ones it stands for, or one of whose stages' judges is
no longer the current one, is offered again in its pipeline. Standing "same"
first; the old decision stays in force until the new one is written.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas import grouping as g
from makhzan_schemas.ai import flow, policy, triggers
from makhzan_schemas.ai.broker import sweep_judges
from makhzan_schemas.ai.decisions import REVOKED, STANDING
from makhzan_schemas.ai.pipelines import PIPELINES, SAME
from makhzan_schemas.ai.render import Shown, render, shown
from makhzan_schemas.domains import get_profile
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import AiDecision, AiJob, AiListingState, Category, Listing
from makhzan_schemas.overrides import Overrides, load_overrides, pair
from makhzan_schemas.values import value_tokens, values_conflict

log = logging.getLogger(__name__)

#: P1: candidates per listing.
K = 10
#: P15: electronics only (`policy.DOMAINS`; the approved prompt says
#: "electronics shops").
DOMAINS = policy.DOMAINS
MATCH, AUDIT = "match", "audit"

# Owner decisions (2026-11-17), one line each.
#: The daily run's first pass records a baseline and queues nothing (the
#: existing catalogue is the backlog's, scored locally, P4).
BASELINE_FIRST_RUN = True
#: A pair with a standing decision is never a candidate (it is the
#: re-score's). A pair whose decision a person revoked is offered again only
#: when what the models would be shown has changed since: the requests it
#: renders now differ from those its revoked decision recorded, so the models
#: are asked again (option (b)). Not the content hash, which also moves on
#: an Arabic title under an English one, or a `HASH_VERSION` bump. False
#: would keep revoked pairs out for good.
REOFFER_REVOKED_ON_TEXT_CHANGE = True

_TOKEN = re.compile(r"[a-z0-9]+")


def title_of(listing: Listing) -> str:
    return listing.title_en or listing.title_ar or ""


def title_tokens(listing: Listing) -> set[str]:
    """The experiments' retrieval tokens: grouping's tokeniser and noise list,
    with the identifier and numbers kept."""
    noise = get_profile(listing.domain).noise_tokens
    return {t for t in _TOKEN.findall(title_of(listing).lower()) if t not in noise and len(t) >= 2}


def key_of(listing: Listing) -> str:
    return g.base_key(
        listing.part_number, listing.source, listing.external_id, listing.id, listing.domain
    )


def vetoes(a: Listing, b: Listing) -> dict[str, bool]:
    """Today's vetoes between two listings, with grouping's own helpers on each
    title with its identifier taken out (as `_subcluster` builds its evidence)."""
    profile = get_profile(a.domain)

    def evidence(listing: Listing):
        title, mpn = title_of(listing), listing.part_number
        return value_tokens(g._without_identifier(title, mpn)), g._form(title, mpn, listing.domain)

    (va, fa), (vb, fb) = evidence(a), evidence(b)
    return {
        "same_shop": a.supplier_id == b.supplier_id,
        "values": values_conflict(va, vb),
        "form": g._forms_conflict(fa, fb, profile.accessory_forms),
        "price": g._prices_apart(a.price, b.price, profile.merge_price_ratio),
    }


def rules_merged(a: Listing, b: Listing) -> bool:
    """Both in one product, and neither there by an AI decision."""
    return (
        a.product_id is not None
        and a.product_id == b.product_id
        and a.matched_via != "ai"
        and b.matched_via != "ai"
    )


# --- the catalogue ----------------------------------------------------------------------------


@dataclass
class Catalogue:
    """Every active listing of the scoped departments, read once."""

    listings: list[Listing]
    shown: dict[uuid.UUID, Shown]
    tokens: list[set[str]] = field(default_factory=list)
    postings: dict[str, list[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.index = {x.id: i for i, x in enumerate(self.listings)}
        self.tokens = [title_tokens(x) for x in self.listings]
        postings: dict[str, list[int]] = defaultdict(list)
        for i, tokens in enumerate(self.tokens):
            for t in tokens:
                postings[t].append(i)
        self.postings = dict(postings)

    def top_k(self, i: int, k: int = K) -> list[tuple[int, float]]:
        """Listing i's k nearest other-shop listings by title-token Jaccard;
        ties by listing id. Only listings sharing a token are candidates."""
        mine = self.tokens[i]
        shop = self.listings[i].supplier_id
        inter: Counter[int] = Counter()
        for t in mine:
            inter.update(self.postings[t])
        scored = []
        for j, common in inter.items():
            if self.listings[j].supplier_id == shop:
                continue
            jac = common / (len(mine) + len(self.tokens[j]) - common)
            scored.append((-jac, str(self.listings[j].id), j))
        scored.sort()
        return [(j, -neg) for neg, _, j in scored[:k]]


async def load_catalogue(session: AsyncSession, domains: Iterable[str] = DOMAINS) -> Catalogue:
    rows = await session.execute(
        select(Listing, Category.name_en)
        .outerjoin(Category, Category.id == Listing.category_id)
        # A hidden source's listings (`listed = false`) are never candidates;
        # listed again, they are new to `ai_listing_state` and found then.
        .where(Listing.is_public(), Listing.domain.in_(list(domains)))
        .order_by(Listing.id)
    )
    listings, views = [], {}
    for listing, category in rows:
        listings.append(listing)
        views[listing.id] = shown(listing, category)
    return Catalogue(listings, views)


def _requests_now(pipeline_name: str, a: Shown, b: Shown) -> dict[str, dict[str, str]]:
    """Each stage's two request hashes for the pair as it would render now."""
    return {s.name: render(s, a, b).hex() for s in PIPELINES[pipeline_name].stages}


def _shows_what_was_revoked(evidence: dict, now: dict[str, dict[str, str]]) -> bool:
    """Whether every stage a revoked decision holds evidence for would be
    shown exactly the same requests now. A decision recorded before request
    hashes were kept, or with no evidence, counts as unchanged: it stays out."""
    stages = {n: e for n, e in (evidence or {}).items() if isinstance(e, dict)}
    if not stages:
        return True
    for name, entry in stages.items():
        recorded = entry.get("requests")
        if not recorded:
            return True
        if now.get(name) != recorded:
            return False
    return True


@dataclass
class Decided:
    """Pairs not to offer, and the revoked decisions of pairs offered again."""

    skip: set[tuple]
    reoffered: dict[tuple, list[dict]]


async def _decided_pairs(
    session: AsyncSession, pipeline_name: str, catalogue: Catalogue
) -> Decided:
    """Pairs not to offer in `pipeline_name`: every pair with a standing
    decision, and every pair with a revoked one whose rendered requests have
    not changed since it was revoked (`REOFFER_REVOKED_ON_TEXT_CHANGE`). Any
    one revocation matching what would be shown now keeps the pair out."""
    rows = await session.execute(
        select(AiDecision.listing_a, AiDecision.listing_b, AiDecision.state, AiDecision.scores)
        .where(AiDecision.pipeline == pipeline_name, AiDecision.state.in_((STANDING, REVOKED)))
        .order_by(AiDecision.id)
    )
    standing: set[tuple] = set()
    revoked: dict[tuple, list[dict]] = {}
    for a, b, state, evidence in rows:
        if state == STANDING or not REOFFER_REVOKED_ON_TEXT_CHANGE:
            standing.add((a, b))
        else:
            revoked.setdefault((a, b), []).append(evidence or {})
    skip, reoffered = set(standing), {}
    for (a, b), decisions in revoked.items():
        if (a, b) in standing:
            continue
        now_a, now_b = catalogue.shown.get(a), catalogue.shown.get(b)
        if now_a is None or now_b is None:
            skip.add((a, b))
            continue
        now = _requests_now(pipeline_name, now_a, now_b)
        if any(_shows_what_was_revoked(e, now) for e in decisions):
            skip.add((a, b))
        else:
            reoffered[(a, b)] = decisions
    return Decided(skip, reoffered)


def find_pairs(
    catalogue: Catalogue, queries: Iterable[int], *, mutual: bool = False, k: int = K
) -> set[tuple[int, int]]:
    """Index pairs (i < j): each query's top k, the identifier-key pairs the
    rules split for each query, and with `mutual` each listing whose own top
    k holds a query."""
    queries = set(queries)
    found: set[tuple[int, int]] = set()
    for i in queries:
        for j, _ in catalogue.top_k(i, k):
            found.add((min(i, j), max(i, j)))
    if mutual:
        near: set[int] = set()
        for i in queries:
            for t in catalogue.tokens[i]:
                near.update(catalogue.postings[t])
        for o in near - queries:
            for j, _ in catalogue.top_k(o, k):
                if j in queries:
                    found.add((min(o, j), max(o, j)))
    by_key: dict[str, list[int]] = defaultdict(list)
    for i, listing in enumerate(catalogue.listings):
        if listing.part_number:
            by_key[key_of(listing)].append(i)
    for i in queries:
        listing = catalogue.listings[i]
        if not listing.part_number:
            continue
        for j in by_key[key_of(listing)]:
            other = catalogue.listings[j]
            if (
                j != i
                and other.supplier_id != listing.supplier_id
                and other.product_id != listing.product_id
            ):
                found.add((min(i, j), max(i, j)))
    return found


@dataclass
class Filtered:
    kept: list[tuple[uuid.UUID, uuid.UUID]]
    counts: Counter


def filter_pairs(
    catalogue: Catalogue,
    pairs: Iterable[tuple[int, int]],
    overrides: Overrides,
    decided: set[tuple],
) -> Filtered:
    counts: Counter = Counter()
    kept = []
    for i, j in sorted(pairs):
        a, b = catalogue.listings[i], catalogue.listings[j]
        counts["found"] += 1
        if overrides.kind(a.id, b.id) is not None:
            counts["override"] += 1
            continue
        if rules_merged(a, b):
            counts["rules_merged"] += 1
            continue
        key = pair(a.id, b.id)
        if key in decided:
            counts["decided"] += 1
            continue
        hit = vetoes(a, b)
        if any(hit.values()):
            counts["vetoed"] += 1
            for name, yes in hit.items():
                counts[f"veto_{name}"] += yes
            continue
        kept.append(key)
    counts["kept"] = len(kept)
    return Filtered(kept, counts)


# --- listing state ----------------------------------------------------------------------------


async def record_hashes(session: AsyncSession, catalogue: Catalogue, now: datetime) -> dict:
    """Store every listing's current content hash in `ai_listing_state`;
    returns the state rows by listing id, as they now are.

    Upserts (`ON CONFLICT`), so a concurrent writer cannot make it fail; the
    change time moves only when the hash does. A listing that left the scope
    (archived, or moved out of electronics) loses its row: the re-score
    trigger joins on it and so stops looking at that listing's decisions,
    and if it comes back it is new again."""
    # The same scope as `load_catalogue`, as a subquery: tens of thousands of
    # ids would not fit in one statement's parameters.
    scope = select(Listing.id).where(Listing.is_public(), Listing.domain.in_(list(DOMAINS)))
    await session.execute(delete(AiListingState).where(AiListingState.listing_id.not_in(scope)))
    rows = [
        {
            "listing_id": x.id,
            "content_sha256": catalogue.shown[x.id].content_sha256,
            "content_changed_at": now,
        }
        for x in catalogue.listings
    ]
    for start in range(0, len(rows), 5000):
        stmt = insert(AiListingState).values(rows[start : start + 5000])
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[AiListingState.listing_id],
                set_={
                    "content_sha256": stmt.excluded.content_sha256,
                    "content_changed_at": case(
                        (
                            AiListingState.content_sha256 != stmt.excluded.content_sha256,
                            stmt.excluded.content_changed_at,
                        ),
                        else_=AiListingState.content_changed_at,
                    ),
                },
            )
        )
    wanted = {x.id for x in catalogue.listings}
    states = {
        row.listing_id: row
        for row in await session.scalars(
            select(AiListingState)
            .where(AiListingState.listing_id.in_(scope))
            .execution_options(populate_existing=True)
        )
        if row.listing_id in wanted
    }
    return states


# --- the triggers -----------------------------------------------------------------------------


class _MatchTrigger:
    """Shared by candidates and backlog: what still wants a `match` job."""

    name = "candidates"

    async def still_wanted(self, session: AsyncSession, job: AiJob) -> bool:
        """Not merged by the rules since it was queued."""
        rows = (
            await session.execute(
                select(Listing.product_id, Listing.matched_via).where(
                    Listing.id.in_((job.listing_a, job.listing_b))
                )
            )
        ).all()
        if len(rows) < 2:
            return False
        (pa, va), (pb, vb) = rows
        return not (pa is not None and pa == pb and va != "ai" and vb != "ai")


class CandidatesTrigger(_MatchTrigger):
    """New or changed listings' top K, filtered (the daily run)."""

    name = "candidates"
    priority = triggers.CANDIDATE

    def __init__(self, *, mutual: bool = False, everything: bool = False) -> None:
        self.mutual = mutual
        self.everything = everything
        self.counts: Counter = Counter()

    async def produce(self, session: AsyncSession) -> list[triggers.PairRequest]:
        now = await session.scalar(select(func.now()))
        first_run = (await session.scalar(select(func.count()).select_from(AiListingState))) == 0
        catalogue = await load_catalogue(session)
        states = await record_hashes(session, catalogue, now)
        if self.everything:
            queries = list(range(len(catalogue.listings)))
        else:
            queries = [
                i
                for i, x in enumerate(catalogue.listings)
                if states[x.id].candidates_sha256 != states[x.id].content_sha256
            ]
        self.counts = Counter(listings=len(catalogue.listings), queries=len(queries))
        if first_run and BASELINE_FIRST_RUN and not self.everything:
            log.info("AI candidates: first run, baseline recorded, nothing offered")
            self.counts["baseline"] = len(queries)
            requests = []
        else:
            found = find_pairs(catalogue, queries, mutual=self.mutual)
            decided = await _decided_pairs(session, MATCH, catalogue)
            filtered = filter_pairs(catalogue, found, await load_overrides(session), decided.skip)
            self.counts.update(filtered.counts)
            # A revoked pair offered again can still not be decided from
            # scores its revocation saw: `flow.write_decision` refuses that.
            self.counts["revoked_reoffered"] = sum(
                1 for key in filtered.kept if key in decided.reoffered
            )
            requests = [
                triggers.PairRequest(a, b, MATCH, self.priority, self.name)
                for a, b in filtered.kept
            ]
        for i in queries:
            state = states[catalogue.listings[i].id]
            state.candidates_sha256, state.candidates_at = state.content_sha256, now
        await session.flush()
        return requests


class BacklogTrigger(CandidatesTrigger):
    """Every listing's top K (the backlog); at the backlog's priority."""

    name = "backlog"
    priority = triggers.BACKLOG

    def __init__(self, *, mutual: bool = True) -> None:
        super().__init__(mutual=mutual, everything=True)


class AuditTrigger:
    """Rules-merged pairs from two shops never audited (P12, record only)."""

    name = "audit"
    priority = triggers.AUDIT

    def __init__(self) -> None:
        self.counts: Counter = Counter()

    async def produce(self, session: AsyncSession) -> list[triggers.PairRequest]:
        listings = list(
            await session.scalars(
                select(Listing).where(
                    Listing.is_public(),
                    Listing.domain.in_(DOMAINS),
                    Listing.product_id.is_not(None),
                )
            )
        )
        by_product: dict[uuid.UUID, list[Listing]] = defaultdict(list)
        for listing in listings:
            if listing.matched_via != "ai":
                by_product[listing.product_id].append(listing)
        audited = {
            (a, b)
            for a, b in await session.execute(
                select(AiJob.listing_a, AiJob.listing_b).where(
                    AiJob.pipeline == AUDIT, AiJob.status != "cancelled"
                )
            )
        }
        overrides = await load_overrides(session)
        self.counts = Counter()
        requests = []
        for members in by_product.values():
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    a, b = members[x], members[y]
                    if a.supplier_id == b.supplier_id:
                        continue
                    key = pair(a.id, b.id)
                    self.counts["pairs"] += 1
                    if key in audited:
                        self.counts["audited"] += 1
                        continue
                    if overrides.kind(*key) is not None:
                        self.counts["override"] += 1
                        continue
                    requests.append(triggers.PairRequest(*key, AUDIT, self.priority, self.name))
        self.counts["offered"] = len(requests)
        return requests

    async def still_wanted(self, session: AsyncSession, job: AiJob) -> bool:
        """Still in one product by the rules."""
        rows = (
            await session.execute(
                select(Listing.product_id, Listing.matched_via).where(
                    Listing.id.in_((job.listing_a, job.listing_b))
                )
            )
        ).all()
        if len(rows) < 2:
            return False
        (pa, va), (pb, vb) = rows
        return pa is not None and pa == pb and va != "ai" and vb != "ai"


class RescoreTrigger:
    """Standing decisions whose text or judge changed (P5, P8)."""

    name = "rescore"

    def __init__(self) -> None:
        self.counts: Counter = Counter()

    async def produce(self, session: AsyncSession) -> list[triggers.PairRequest]:
        judges = await flow.current_judges(session)
        rows = await session.execute(
            select(AiDecision, AiListingState.content_sha256, Listing.status)
            .join(AiListingState, AiListingState.listing_id == AiDecision.listing_a)
            .join(Listing, Listing.id == AiDecision.listing_a)
            .where(AiDecision.state == STANDING, Listing.from_listed_source())
        )
        side_a = {d.id: (d, h, s) for d, h, s in rows}
        rows_b = await session.execute(
            select(AiDecision.id, AiListingState.content_sha256, Listing.status)
            .join(AiListingState, AiListingState.listing_id == AiDecision.listing_b)
            .join(Listing, Listing.id == AiDecision.listing_b)
            .where(AiDecision.state == STANDING, Listing.from_listed_source())
        )
        side_b = {i: (h, s) for i, h, s in rows_b}
        self.counts = Counter()
        requests = []
        for decision_id, (decision, hash_a, status_a) in side_a.items():
            if decision_id not in side_b or decision.pipeline not in PIPELINES:
                continue
            hash_b, status_b = side_b[decision_id]
            if status_a != ListingStatus.ACTIVE or status_b != ListingStatus.ACTIVE:
                continue
            changed = decision.content_sha256_a != hash_a or decision.content_sha256_b != hash_b
            judged = any(
                judges.get((decision.pipeline, name)) != entry.get("model_version_id")
                for name, entry in (decision.scores or {}).items()
            )
            if not (changed or judged):
                continue
            if decision.outcome == SAME:
                priority = triggers.RESCORE_SAME
            elif changed:
                priority = triggers.RESCORE_CHANGED
            else:
                priority = triggers.RESCORE_VERSION
            self.counts["text" if changed else "version"] += 1
            requests.append(
                triggers.PairRequest(
                    decision.listing_a, decision.listing_b, decision.pipeline, priority, self.name
                )
            )
        # Standing "same" first (P8): offered, and so queued, in priority order.
        requests.sort(key=lambda r: -r.priority)
        return requests


CANDIDATES = triggers.register(CandidatesTrigger())
BACKLOG = triggers.register(BacklogTrigger())
AUDIT_TRIGGER = triggers.register(AuditTrigger())
RESCORE = triggers.register(RescoreTrigger())


async def run(session: AsyncSession, trigger) -> dict:
    """Run one producer and offer what it yields; flushed, not committed."""
    requests = await trigger.produce(session)
    outcome = await flow.offer(session, requests)
    return {"trigger": trigger.name, **dict(getattr(trigger, "counts", {})), **outcome}


async def _exclusive(session: AsyncSession) -> bool:
    """One producer run at a time (the daily job, a backlog, one by hand):
    a transaction-scoped advisory lock, released at commit or rollback."""
    return bool(
        await session.scalar(select(func.pg_try_advisory_xact_lock(func.hashtext("ai_producers"))))
    )


BUSY = {"skipped": "another AI producer run is in progress"}


async def daily(session: AsyncSession, *, mutual: bool = False) -> list[dict]:
    """What runs after each rebuild: move jobs queued at an old judge, then
    candidates, re-scores (which need the hashes candidates just recorded)
    and the audit. Skipped when another producer run holds the lock."""
    if not await _exclusive(session):
        return [BUSY]
    moved = await sweep_judges(session)
    return [
        {"trigger": "judge sweep", "moved": moved},
        await run(session, CandidatesTrigger(mutual=mutual)),
        await run(session, RescoreTrigger()),
        await run(session, AuditTrigger()),
    ]


async def backlog(session: AsyncSession, *, mutual: bool = True) -> dict:
    """The whole catalogue's candidates, at the backlog's priority."""
    if not await _exclusive(session):
        return BUSY
    return await run(session, BacklogTrigger(mutual=mutual))
