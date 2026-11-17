"""What happens to a pair once it has scores: the one generic step, and the decision writer.

`advance` is the whole of the broker's result handling (docs/ai/broker-api.md
§3.4), and also what a trigger's pairs go through (`offer`): read the pair's
current scores for every stage of its pipeline, by **request hash** (render
each stage's requests from the current rows and look up (judge, request hash)
in `ai_scores`), ask `pipelines.transition`, then queue the stage still owed,
write the decision, or (a recording pipeline) do nothing more. Nothing here
names a model or a stage.

So a pair whose requests are byte-identical to scored ones is settled at once
with no model call: a re-score after a change no judge can see (the Arabic
title under an English one) rewrites the standing decision in place with the
new content hashes and stops; a re-score after a new pplx version re-uses the
Kev scores and goes straight to pplx.

`write_decision` keeps one standing decision per (pipeline, pair), serialised
by a transaction-scoped advisory lock on the pair. Same outcome: the same row,
updated in place. A different outcome: the old row is marked stale and a new
standing row is inserted.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.ai import triggers
from makhzan_schemas.ai.decisions import REVOKED, STALE, STANDING
from makhzan_schemas.ai.pipelines import DECIDE, PIPELINES, SCORE, Step, pipeline, transition
from makhzan_schemas.ai.policy import ACTIVE
from makhzan_schemas.ai.render import Shown, load_shown, render
from makhzan_schemas.models import AiDecision, AiJob, AiScore
from makhzan_schemas.overrides import pair

log = logging.getLogger(__name__)

Judges = dict[tuple[str, str], int]


async def current_judges(session: AsyncSession) -> Judges:
    """The judge (`ai_model_versions.id`) every registered stage uses now,
    by (pipeline, stage); created the first time a stage needs one."""
    return {
        (p.name, s.name): await triggers.model_version_id(session, s)
        for p in PIPELINES.values()
        for s in p.stages
    }


@dataclass(frozen=True)
class PairScores:
    """A pair's current scores in one pipeline.

    `scores` is what `transition` reads: {stage: {"ab": p, "ba": p}}, an order
    missing when it has no score under the stage's current judge for the
    request as it would be rendered now. `evidence` is what a decision stores
    for each stage: model, judge id, both orders' scores, and both orders'
    request hashes (`requests`).
    """

    scores: dict[str, dict[str, float]]
    evidence: dict[str, dict]


async def scores_for(
    session: AsyncSession,
    pairs: Sequence[tuple[str, uuid.UUID, uuid.UUID]],
    shown: dict[uuid.UUID, Shown],
    judges: Judges,
) -> dict[tuple[str, uuid.UUID, uuid.UUID], PairScores]:
    """Current scores of many (pipeline, a, b) at once, in one lookup per
    5,000 request hashes. A pair whose listing is missing from `shown` is
    left out."""
    wanted: dict[tuple, dict[str, dict[str, bytes]]] = {}
    hashes: set[bytes] = set()
    for key in pairs:
        name, a, b = key
        if a not in shown or b not in shown:
            continue
        per_stage = {}
        for stage in pipeline(name).stages:
            rendered = render(stage, shown[a], shown[b])
            per_stage[stage.name] = rendered.sha256
            hashes.update(rendered.sha256.values())
        wanted[key] = per_stage
    found: dict[tuple[int, bytes], float] = {}
    ordered = list(hashes)
    # Led by the judge, so the lookup is `uq_ai_score_request`'s index.
    current = sorted(set(judges.values()))
    for start in range(0, len(ordered), 5000):
        rows = await session.execute(
            select(AiScore.model_version_id, AiScore.request_sha256, AiScore.p).where(
                AiScore.model_version_id.in_(current),
                AiScore.request_sha256.in_(ordered[start : start + 5000]),
            )
        )
        for judge, digest, p in rows:
            found[(judge, digest)] = p
    out = {}
    for key, per_stage in wanted.items():
        name = key[0]
        scores: dict[str, dict[str, float]] = {}
        evidence: dict[str, dict] = {}
        for stage in pipeline(name).stages:
            judge = judges[(name, stage.name)]
            orders = {
                order: found[(judge, digest)]
                for order, digest in per_stage[stage.name].items()
                if (judge, digest) in found
            }
            if orders:
                scores[stage.name] = orders
                evidence[stage.name] = {
                    "model": stage.model,
                    "model_version_id": judge,
                    **orders,
                    # What the judge was shown, per order: a revoked decision
                    # is offered again only when these change (candidates).
                    "requests": {o: d.hex() for o, d in per_stage[stage.name].items()},
                }
        out[key] = PairScores(scores, evidence)
    return out


async def advance(
    session: AsyncSession,
    requests: Sequence[triggers.PairRequest],
    *,
    shown: dict[uuid.UUID, Shown] | None = None,
    judges: Judges | None = None,
) -> dict[str, int]:
    """Take each pair one step: queue the stage it still owes, or write its
    decision, or (a recording pipeline with every stage scored) nothing.

    A job's next stage keeps the job's priority when that is higher than
    `NEXT_STAGE`, so a re-score of a standing "same" stays first all the way
    through (P8). Returns counts by what happened.
    """
    counts = {
        "queued": 0,
        "decided": 0,
        "recorded": 0,
        "already": 0,
        "missing": 0,
        "revoked_blocked": 0,
    }
    if not requests:
        return counts
    judges = judges or await current_judges(session)
    if shown is None:
        shown = await load_shown(session, {x for r in requests for x in (r.listing_a, r.listing_b)})
    keyed = []
    for r in requests:
        a, b = pair(r.listing_a, r.listing_b)
        keyed.append(((r.pipeline, a, b), r))
    current = await scores_for(session, [k for k, _ in keyed], shown, judges)
    by_stage: dict[str, list[triggers.PairRequest]] = {}
    for key, request in keyed:
        if key not in current:
            counts["missing"] += 1
            continue
        step = transition(request.pipeline, current[key].scores, ACTIVE)
        if step.action == SCORE:
            by_stage.setdefault(step.stage, []).append(request)
        elif step.action == DECIDE:
            row = await write_decision(
                session, request.pipeline, key[1], key[2], step, current[key]
            )
            counts["revoked_blocked" if row is BLOCKED else "decided"] += 1
        else:
            counts["recorded"] += 1
    for stage_name, batch in by_stage.items():
        created = await triggers.enqueue(session, batch, stage=stage_name)
        counts["queued"] += created
        counts["already"] += len(batch) - created
    return counts


async def offer(session: AsyncSession, requests: Iterable[triggers.PairRequest]) -> dict[str, int]:
    """What a trigger's pairs go through: `advance` from wherever each pair is."""
    return await advance(session, list(requests))


async def on_scores(session: AsyncSession, job: AiJob) -> Step:
    """The generic result handling, after a job's scores are in (or found
    already scored at lease time): the pair's next step in its pipeline."""
    p = pipeline(job.pipeline)
    request = triggers.PairRequest(
        job.listing_a, job.listing_b, p.name, max(triggers.NEXT_STAGE, job.priority), job.reason
    )
    shown = await load_shown(session, (job.listing_a, job.listing_b))
    judges = await current_judges(session)
    current = await scores_for(session, [(p.name, job.listing_a, job.listing_b)], shown, judges)
    key = (p.name, job.listing_a, job.listing_b)
    if key not in current:
        return Step("missing")
    step = transition(p.name, current[key].scores, ACTIVE)
    if step.action == SCORE:
        await triggers.enqueue(session, [request], stage=step.stage)
    elif step.action == DECIDE:
        row = await write_decision(
            session, p.name, job.listing_a, job.listing_b, step, current[key]
        )
        if row is BLOCKED:
            return Step(BLOCKED_ACTION)
    return step


def _lock_key(pipeline_name: str, a: uuid.UUID, b: uuid.UUID):
    """A bigint for `pg_advisory_xact_lock`, from the pipeline and the pair."""
    return func.hashtextextended(f"ai_decision:{pipeline_name}:{a}:{b}", 0)


#: What `write_decision` returns when a person's revocation stands in the way.
BLOCKED = object()
#: The step a job's result reports then (`/results` `next.action`).
BLOCKED_ACTION = "blocked"


async def _revocation_stands(
    session: AsyncSession, pipeline_name: str, a: uuid.UUID, b: uuid.UUID, evidence: dict
) -> bool:
    """Whether a revoked decision for the pair keeps this one from standing.

    It does, unless at least one score the new decision uses was scored
    after the latest revocation **and** for a request no revoked decision
    recorded: a model looked, at text the revocation did not see. Old
    scores (a revert to text scored earlier, a job queued before the
    revocation) and fresh scores of text the revocation saw (a new model
    version) cannot undo a person's revocation. A revoked decision recorded
    without request hashes counts as having seen everything."""
    revoked = (
        await session.execute(
            select(AiDecision.revoked_at, AiDecision.scores).where(
                AiDecision.pipeline == pipeline_name,
                AiDecision.listing_a == a,
                AiDecision.listing_b == b,
                AiDecision.state == REVOKED,
            )
        )
    ).all()
    if not revoked:
        return False
    latest = max(r.revoked_at for r in revoked)
    seen: set[tuple[str, str]] = set()
    for _, scores in revoked:
        for name, entry in (scores or {}).items():
            if not isinstance(entry, dict):
                continue
            if not entry.get("requests"):
                return True
            seen.update((name, digest) for digest in entry["requests"].values())
    for name, entry in evidence.items():
        for order, digest in (entry.get("requests") or {}).items():
            if order not in entry or (name, digest) in seen:
                continue  # not a score this decision uses, or text already revoked
            scored_at = await session.scalar(
                select(AiScore.scored_at).where(
                    AiScore.model_version_id == entry["model_version_id"],
                    AiScore.request_sha256 == bytes.fromhex(digest),
                )
            )
            if scored_at is not None and scored_at > latest:
                return False
    return True


async def write_decision(
    session: AsyncSession,
    pipeline_name: str,
    a: uuid.UUID,
    b: uuid.UUID,
    step: Step,
    current: PairScores,
) -> AiDecision | None | object:
    """Write the pair's decision as `step` says (docs/ai/broker-api.md §3.4).

    - serialised per (pipeline, pair) by a transaction-scoped advisory lock,
      so two results for one pair at once (two workers, two stages) take
      turns;
    - the content hashes stored are both listings' **current** ones, not the
      scores' (a stage may re-use a byte-identical score labelled with an
      older hash; a decision labelled with it would be re-queued forever);
    - a standing decision with the same outcome is kept, same id, and its
      scores, `decided_by`, policy and hashes updated in place; otherwise it
      is marked stale and a new standing row is inserted;
    - the partial unique index is the backstop: on a violation it retries once;
    - **a person's revocation holds** (`_revocation_stands`): with a revoked
      decision for the pair, nothing is written unless a model has looked,
      after the revocation, at text the revocation did not see. Every path
      that decides (a trigger's offer, a result, a lease finding a job
      scored, a replay) comes through here, so this is the one guard.

    Returns the standing row; None when a listing no longer exists; `BLOCKED`
    when a revocation keeps the decision from being written.
    """
    a, b = pair(a, b)
    await session.execute(select(func.pg_advisory_xact_lock(_lock_key(pipeline_name, a, b))))
    shown = await load_shown(session, (a, b))
    if a not in shown or b not in shown:
        return None
    evidence = {}
    for name, low in step.mins:
        evidence[name] = {**current.evidence[name], "min": low}
    if await _revocation_stands(session, pipeline_name, a, b, evidence):
        log.info("decision for %s %s %s blocked by a revocation", pipeline_name, a, b)
        return BLOCKED
    fields = {
        "outcome": step.outcome,
        "decided_by": step.decided_by,
        "scores": evidence,
        "policy_version": ACTIVE,
        "content_sha256_a": shown[a].content_sha256,
        "content_sha256_b": shown[b].content_sha256,
    }
    for attempt in (1, 2):
        try:
            async with session.begin_nested():
                standing = await session.scalar(
                    select(AiDecision)
                    .where(
                        AiDecision.pipeline == pipeline_name,
                        AiDecision.listing_a == a,
                        AiDecision.listing_b == b,
                        AiDecision.state == STANDING,
                    )
                    .with_for_update()
                )
                if standing is not None and standing.outcome == step.outcome:
                    for column, value in fields.items():
                        setattr(standing, column, value)
                    await session.flush()
                    return standing
                if standing is not None:
                    standing.state = STALE
                    await session.flush()
                row = AiDecision(pipeline=pipeline_name, listing_a=a, listing_b=b, **fields)
                session.add(row)
                await session.flush()
                return row
        except IntegrityError:
            if attempt == 2:
                raise
            log.info("standing decision raced for %s %s %s; retrying", pipeline_name, a, b)
    return None  # unreachable
