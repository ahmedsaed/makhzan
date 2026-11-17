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

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from makhzan_schemas.ai.pipelines import SAME, rank
from makhzan_schemas.ai.policy import GROUP_CHECK_MODEL, KEV_BLOCK
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import AiDecision, Listing
from makhzan_schemas.overrides import Overrides, Pair, pair

STANDING, STALE, REVOKED = "standing", "stale", "revoked"


@dataclass(frozen=True)
class AiSame:
    """What the regroup reads of AI decisions.

    - `pairs`: "same" pairs that may admit their two listings to one product,
      like a non-forced must_merge, at a rank below a person's ruling
      (`grouping._AI`); every one of today's vetoes still applies.
    - `ids`: each pair's decision id, cited on the product events it causes
      and written to `listings.matched_ai_decision_id`.
    - `no`: pairs `policy.GROUP_CHECK_MODEL` scored below `policy.KEV_BLOCK`
      (P14). A join that rests on an AI decision is blocked when the newcomer
      has one of these with any member; a join the rules make alone never is.
    """

    pairs: frozenset[Pair] = frozenset()
    ids: dict[Pair, int] = field(default_factory=dict)
    no: frozenset[Pair] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.pairs)


def stage_mins(scores: dict) -> dict[str, float]:
    """Each stage's lower score, from a decision's `scores`."""
    return {
        name: float(entry["min"])
        for name, entry in (scores or {}).items()
        if isinstance(entry, dict) and entry.get("min") is not None
    }


async def load_ai_same(
    session: AsyncSession, overrides: Overrides, *, include_shadow: bool = False
) -> AiSame:
    """The AI "same" pairs the regroup may act on.

    A pair counts when:

    - its decision is standing, its outcome is "same", and it is not shadow
      (`include_shadow` lifts that, for a dry run's preview only);
    - both listings are active, and from different shops;
    - no person has ruled on the pair (any standing override);
    - it is each listing's best "same" match in the other's shop (P14): for a
      listing and a shop, only the strongest decision counts (its stages'
      lower scores, last stage first, then the newest id; `pipelines.rank`),
      and the pair must be the best on **both** sides.

    `no` holds every standing decision's pair, between two active listings,
    that the group-check model scored below `KEV_BLOCK`, shadow or not: a score
    measures the current text whichever mode wrote it, and it can only block,
    never admit.
    """
    la, lb = aliased(Listing), aliased(Listing)
    joined = (
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
    if not include_shadow:
        query = query.where(AiDecision.shadow.is_(False))
    rows = []
    for decision_id, pipeline_name, a, b, scores, shop_a, shop_b in await session.execute(query):
        # One shop's two listings never merge, so such a decision cannot act.
        if shop_a == shop_b or overrides.kind(a, b) is not None:
            continue
        strength = (*rank(stage_mins(scores), pipeline_name), decision_id)
        rows.append((decision_id, a, b, strength, shop_a, shop_b))

    # P14: each listing's best match per other shop; a pair counts only when it
    # is the best on both sides.
    best: dict[tuple[uuid.UUID, uuid.UUID], tuple] = {}
    for _, a, b, strength, shop_a, shop_b in rows:
        for key in ((a, shop_b), (b, shop_a)):
            if key not in best or strength > best[key]:
                best[key] = strength
    pairs: set[Pair] = set()
    ids: dict[Pair, int] = {}
    for decision_id, a, b, strength, shop_a, shop_b in rows:
        if best[(a, shop_b)] == strength and best[(b, shop_a)] == strength:
            key = pair(a, b)
            pairs.add(key)
            ids[key] = decision_id

    # Constants from code, never input: the jsonpath is written out in full.
    below = literal_column(
        f"""'$.* ? (@.model == "{GROUP_CHECK_MODEL}" && @.min < {KEV_BLOCK!r})'::jsonpath"""
    )
    no_rows = await session.execute(
        joined.with_only_columns(AiDecision.listing_a, AiDecision.listing_b).where(
            func.jsonb_path_exists(AiDecision.scores, below)
        )
    )
    no = frozenset(pair(a, b) for a, b in no_rows.all())
    return AiSame(frozenset(pairs), ids, no)
