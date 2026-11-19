"""AI decisions: which "same" pairs the regroup reads.

Decisions are written by the broker when `pipelines.transition` says DECIDE
(phase 2); this module is the reading side. `load_ai_same` is what the regroup
reads (`grouping.rebuild_products`, only in `live` mode, or in a dry run's
preview): the "same" pairs that may act, plus the pairs the group check needs
(P14).

Decisions are not rulings. They live in `ai_decisions`, not in
`grouping_overrides`, and a person's ruling on a pair always wins: a pair with
any standing override is never read here (CLAUDE.md: never re-ask a model
about a ruled pair).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, func, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from makhzan_schemas.ai.pipelines import PIPELINES, SAME, rank
from makhzan_schemas.ai.policy import DOMAINS, GROUP_CHECK_MODEL, KEV_BLOCK
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import AiDecision, Listing
from makhzan_schemas.overrides import Overrides, Pair, pair

STANDING, STALE, REVOKED = "standing", "stale", "revoked"

#: What a live regroup found of a standing "same" decision (`ai_decisions.effect`).
IN_EFFECT, BLOCKED, INACTIVE, OVERRIDDEN = "in_effect", "blocked", "inactive", "overridden"
#: The reasons `load_ai_same` itself refuses a decision; the AI phase's own are
#: `grouping._ai_veto`'s.
SAME_SHOP, NOT_MUTUAL_BEST = "same shop", "not mutual best"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AiSame:
    """What the regroup reads of AI decisions.

    - `pairs`: "same" pairs that may join their two listings' clusters in
      the regroup's final AI phase (`grouping._ai_phase`), after the rules and
      a person's rulings; every one of today's vetoes still applies.
    - `ids`: each pair's decision id, cited on the product events it causes
      and written to `listings.matched_ai_decision_id`.
    - `no`: pairs `policy.GROUP_CHECK_MODEL` scored below `policy.KEV_BLOCK`
      (P14). An AI join is blocked when any member of one side has one of
      these with any member of the other; a join the rules make alone never is.
    - `rank`: each pair's strength (`pipelines.rank`: its stages' lower
      scores, last stage first), which orders competing pairs in the AI
      phase. Not the decision id: a re-score renews that.
    - `skipped`: standing "same" decisions between two active, served
      listings that are not read, by decision id, with the effect and reason
      they get unless the pair ends up in one product anyway
      (`record_effects`): `blocked` for one shop's two listings or a pair not
      each other's best, `overridden` for a ruled pair, `inactive` for an
      unregistered pipeline.
    """

    pairs: frozenset[Pair] = frozenset()
    ids: dict[Pair, int] = field(default_factory=dict)
    no: frozenset[Pair] = frozenset()
    rank: dict[Pair, tuple[float, ...]] = field(default_factory=dict)
    skipped: dict[int, tuple[str, str | None]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.pairs)


def stage_mins(scores: dict) -> dict[str, float]:
    """Each stage's lower score, from a decision's `scores`."""
    return {
        name: float(entry["min"])
        for name, entry in (scores or {}).items()
        if isinstance(entry, dict) and entry.get("min") is not None
    }


async def load_ai_same(session: AsyncSession, overrides: Overrides) -> AiSame:
    """The AI "same" pairs the regroup may act on.

    A pair counts when:

    - its decision is standing and its outcome is "same";
    - both listings are active, from different shops, and in a department
      AI matching serves (`policy.DOMAINS`);
    - no person has ruled on the pair (any standing override);
    - it is each listing's best "same" match in the other's shop (P14): for a
      listing and a shop, only the strongest decision counts (its stages'
      lower scores, last stage first, `pipelines.rank`; an exact tie goes to
      the pair whose listing ids sort first, never to the decision id),
      and the pair must be the best on **both** sides (owner decision under
      P14, 2026-11-17: option (a), mutual best). A decision of a pipeline no
      longer in the registry is skipped, and logged.

    `no` holds every standing decision's pair, between two active listings in
    any department, that the group-check model scored below `KEV_BLOCK`,
    whatever its outcome: it can only block, never admit.
    """
    la, lb = aliased(Listing), aliased(Listing)
    active = (
        select(AiDecision)
        .join(la, la.id == AiDecision.listing_a)
        .join(lb, lb.id == AiDecision.listing_b)
        .where(
            and_(
                la.status == ListingStatus.ACTIVE,
                lb.status == ListingStatus.ACTIVE,
                AiDecision.state == STANDING,
            )
        )
    )
    # Only while both listings are in a served department may a decision
    # admit: one that moves out takes the AI merge apart (owner, 2026-11-17).
    joined = active.where(la.domain.in_(DOMAINS), lb.domain.in_(DOMAINS))
    query = (
        joined.with_only_columns(
            AiDecision.id,
            AiDecision.pipeline,
            AiDecision.listing_a,
            AiDecision.listing_b,
            AiDecision.scores,
            la.supplier_id,
            lb.supplier_id,
        )
        .where(AiDecision.outcome == SAME)
        .order_by(AiDecision.id)
    )
    rows = []
    unknown: set[str] = set()
    skipped: dict[int, tuple[str, str | None]] = {}
    for decision_id, pipeline_name, a, b, scores, shop_a, shop_b in await session.execute(query):
        # A person's ruling wins; one shop's two listings never merge, so such
        # a decision cannot act.
        if overrides.kind(a, b) is not None:
            skipped[decision_id] = (OVERRIDDEN, None)
            continue
        if shop_a == shop_b:
            skipped[decision_id] = (BLOCKED, SAME_SHOP)
            continue
        if pipeline_name not in PIPELINES:
            unknown.add(pipeline_name)
            skipped[decision_id] = (INACTIVE, None)
            continue
        rows.append((decision_id, a, b, rank(stage_mins(scores), pipeline_name), shop_a, shop_b))

    if unknown:
        log.warning("AI decisions of unregistered pipelines skipped: %s", sorted(unknown))

    # P14: each listing's best match per other shop; a pair counts only when it
    # is the best on both sides. Strongest first; an exact tie goes to the
    # pair whose listing ids sort first (as in the regroup's AI phase), never
    # to the decision id, which a re-score renews.
    def order(strength: tuple, a: uuid.UUID, b: uuid.UUID) -> tuple:
        return (tuple(-x for x in strength), str(a), str(b))

    best: dict[tuple[uuid.UUID, uuid.UUID], tuple] = {}
    for _, a, b, strength, shop_a, shop_b in rows:
        for key in ((a, shop_b), (b, shop_a)):
            mine = order(strength, a, b)
            if key not in best or mine < best[key]:
                best[key] = mine
    pairs: set[Pair] = set()
    ids: dict[Pair, int] = {}
    ranks: dict[Pair, tuple[float, ...]] = {}
    for decision_id, a, b, strength, shop_a, shop_b in rows:
        mine = order(strength, a, b)
        if best[(a, shop_b)] == mine and best[(b, shop_a)] == mine:
            key = pair(a, b)
            # One pair decided by two pipelines: the stronger decision stands.
            if key in ranks and order(ranks[key], a, b) <= mine:
                continue
            pairs.add(key)
            ids[key] = decision_id
            ranks[key] = strength
        else:
            skipped[decision_id] = (BLOCKED, NOT_MUTUAL_BEST)

    # Constants from code, never input: the jsonpath is written out in full.
    below = literal_column(
        f"""'$.* ? (@.model == "{GROUP_CHECK_MODEL}" && @.min < {KEV_BLOCK!r})'::jsonpath"""
    )
    # Unfiltered by department: a confident "no" blocks whatever the domain.
    no_rows = await session.execute(
        active.with_only_columns(AiDecision.listing_a, AiDecision.listing_b).where(
            func.jsonb_path_exists(AiDecision.scores, below)
        )
    )
    no = frozenset(pair(a, b) for a, b in no_rows.all())
    return AiSame(frozenset(pairs), ids, no, ranks, skipped)


async def record_effects(
    session: AsyncSession,
    ai: AiSame,
    refused: Mapping[Pair, str],
    group_of: Mapping[uuid.UUID, str],
    now: datetime,
) -> dict[str, int]:
    """Write what a live regroup found of every standing "same" decision:
    `effect`, `blocked_reason` and `checked_at` (= `now`).

    Nothing is worked out again here; the outcomes come from where they were
    decided. In this order:

    - `inactive`: a listing not active or outside `policy.DOMAINS` (the
      decision was not among those `load_ai_same` read), or a pipeline no
      longer registered;
    - `overridden`: a person's ruling covers the pair (`load_ai_same`);
    - `in_effect`: the two listings are in one product (`group_of`), by an AI
      join or already by the rules;
    - `blocked`, with `blocked_reason`: refused by `load_ai_same` (same shop,
      not mutual best), or by the AI phase (`refused`, `grouping._ai_veto`).

    Stale and revoked "same" decisions are marked `inactive` once. Returns
    the counts by effect.
    """
    rows = (
        await session.execute(
            select(AiDecision.id, AiDecision.listing_a, AiDecision.listing_b).where(
                AiDecision.state == STANDING, AiDecision.outcome == SAME
            )
        )
    ).all()
    counts: dict[str, int] = {}
    values = []
    for decision_id, a, b in rows:
        key = pair(a, b)
        if decision_id in ai.skipped:
            effect, reason = ai.skipped[decision_id]
        elif key in ai.pairs:
            effect, reason = BLOCKED, refused.get(key)
        else:
            effect, reason = INACTIVE, None
        if effect == BLOCKED and a in group_of and group_of.get(a) == group_of.get(b):
            effect, reason = IN_EFFECT, None
        counts[effect] = counts.get(effect, 0) + 1
        values.append(
            {"id": decision_id, "effect": effect, "blocked_reason": reason, "checked_at": now}
        )
    if values:
        await session.execute(update(AiDecision), values)
    await session.execute(
        update(AiDecision)
        .where(
            AiDecision.state != STANDING,
            AiDecision.outcome == SAME,
            AiDecision.effect.is_distinct_from(INACTIVE),
        )
        .values(effect=INACTIVE, blocked_reason=None, checked_at=now)
        .execution_options(synchronize_session=False)
    )
    return counts
