"""Triggers: what decides that a pair should go through a pipeline.

A trigger is a producer: it looks at the catalogue and yields `PairRequest`s,
each naming a registered pipeline (`pipelines.PIPELINES`). `enqueue` puts them
into that pipeline's first stage; everything after is the broker's generic
result handling (`pipelines.transition`). A trigger knows nothing about
models, stages or workers, and the broker and workers know nothing about
triggers, so a new reason to score a pair is a new trigger, nothing else.

Today's are in `makhzan_schemas.ai.candidates`, registered when it is imported:

- **candidates** (`match`): each new or changed listing's top-K lexical
  matches in other shops, filtered by today's vetoes (P1, P13); **backlog**
  is the same over the whole catalogue, at a lower priority;
- **audit** (`audit`): each pair the rules merged, Kev only (P12);
- **re-score** (whichever pipeline the pair was in, `reason="rescore"`): a
  changed content hash or a new model or prompt version (P5, P8), standing
  "same" decisions first.

A producer must not offer a pair a person has ruled on (CLAUDE.md: never
re-ask a model about a ruled pair, `overrides.load_overrides`). What a
trigger yields goes through `flow.offer`, which settles at once a pair whose
requests are all scored already and queues the rest.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.ai.pipelines import Stage, pipeline
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.models import AiJob, AiModelVersion
from makhzan_schemas.overrides import pair

#: The priority ladder, higher first: the design's, with the owner's rule that
#: standing "same" decisions whose text changed are re-scored first (P8).
RESCORE_SAME = 100
NEXT_STAGE = 80
CANDIDATE = 60
#: A standing "not same" whose text changed: as urgent as a new candidate.
RESCORE_CHANGED = 60
BACKLOG = 40
#: A standing "same" whose judge changed and whose text did not: after new pairs and the
#: backlog, ahead of the "not same" ones (owner, 2026-11-26, amending P8). A new judge
#: version re-scores every standing decision; new pairs must not wait behind that.
RESCORE_SAME_VERSION = 35
#: A standing "not same" whose judge changed and whose text did not.
RESCORE_VERSION = 30
AUDIT = 10


@dataclass(frozen=True)
class PairRequest:
    """One pair a trigger wants judged, in either order (stored `a < b`)."""

    listing_a: uuid.UUID
    listing_b: uuid.UUID
    pipeline: str
    #: Higher first; see the ladder above.
    priority: int
    #: Which trigger asked, for status: "candidates", "audit", "rescore", ...
    reason: str


class Trigger(Protocol):
    """A producer of pairs. Registered in `TRIGGERS` by name, which is the
    `reason` its jobs carry.

    It may also define `still_wanted(session, job) -> bool`: the broker asks
    it before leasing one of its jobs (a later stage's job keeps the reason,
    so it is asked too), and cancels the job on False
    (docs/ai/broker-api.md §3.2). A trigger without it keeps every job.
    """

    name: str

    async def produce(self, session: AsyncSession) -> Iterable[PairRequest]: ...


#: Producers by name, filled by `makhzan_schemas.ai.candidates` on import.
TRIGGERS: dict[str, Trigger] = {}


def register(trigger: Trigger) -> Trigger:
    if trigger.name in TRIGGERS:
        raise ValueError(f"a trigger named {trigger.name!r} is already registered")
    TRIGGERS[trigger.name] = trigger
    return trigger


async def still_wanted(session: AsyncSession, job: AiJob) -> bool:
    """Whether the trigger that queued `job` still wants it: True when that
    trigger is unknown or defines no `still_wanted`."""
    check = getattr(TRIGGERS.get(job.reason), "still_wanted", None)
    return True if check is None else bool(await check(session, job))


async def model_version_id(session: AsyncSession, stage: Stage) -> int:
    """The `ai_model_versions` row for what `stage` uses now (its model's
    version, its prompt's version), created the first time it is needed. The
    registry in code is what says which judge is current; the table records
    it so each score can name the judge that made it."""
    model = MODELS[stage.model]
    found = await session.scalar(
        select(AiModelVersion.id).where(
            AiModelVersion.model == stage.model,
            AiModelVersion.model_version == model.model_version,
            AiModelVersion.prompt_version == stage.prompt_version,
        )
    )
    if found is not None:
        return found
    await session.execute(
        insert(AiModelVersion)
        .values(
            model=stage.model,
            model_version=model.model_version,
            prompt_version=stage.prompt_version,
            weights_revision=model.weights_revision,
            scoring=model.scoring,
        )
        .on_conflict_do_nothing(constraint="uq_ai_model_version_judge")
    )
    return await model_version_id(session, stage)


#: Rows per INSERT: seven parameters each, well inside asyncpg's 32767.
_BATCH = 2000


async def enqueue(
    session: AsyncSession, requests: Iterable[PairRequest], *, stage: str | None = None
) -> int:
    """Queue each pair at its pipeline's first stage (or `stage`, which is how
    the broker queues a later one). Idempotent: a pair already queued or
    leased at that stage and judge is left alone, and so is one whose job
    there is dead: a poison job is handled by hand (P6, `./makhzan ai jobs
    retry`), not re-queued by every daily run. Flushed, not committed;
    returns how many jobs were created. Rows go in batches, so a backlog of
    many thousand pairs is a few statements rather than one per pair."""
    created = 0
    versions: dict[tuple[str, str], int] = {}
    rows: list[dict] = []
    for request in requests:
        p = pipeline(request.pipeline)
        target = p.stage(stage) if stage is not None else p.stages[0]
        key = (p.name, target.name)
        if key not in versions:
            versions[key] = await model_version_id(session, target)
        a, b = pair(request.listing_a, request.listing_b)
        rows.append(
            {
                "pipeline": p.name,
                "stage": target.name,
                "reason": request.reason,
                "model_version_id": versions[key],
                "listing_a": a,
                "listing_b": b,
                "priority": request.priority,
            }
        )
    for start in range(0, len(rows), _BATCH):
        batch = rows[start : start + _BATCH]
        keys = [
            (r["pipeline"], r["stage"], r["model_version_id"], r["listing_a"], r["listing_b"])
            for r in batch
        ]
        dead = set(
            (
                await session.execute(
                    select(
                        AiJob.pipeline,
                        AiJob.stage,
                        AiJob.model_version_id,
                        AiJob.listing_a,
                        AiJob.listing_b,
                    ).where(
                        AiJob.status == "dead",
                        tuple_(
                            AiJob.pipeline,
                            AiJob.stage,
                            AiJob.model_version_id,
                            AiJob.listing_a,
                            AiJob.listing_b,
                        ).in_(keys),
                    )
                )
            ).all()
        )
        batch = [r for r, key in zip(batch, keys, strict=True) if key not in dead]
        if not batch:
            continue
        result = await session.execute(
            insert(AiJob)
            .values(batch)
            .on_conflict_do_nothing(
                index_elements=["pipeline", "stage", "model_version_id", "listing_a", "listing_b"],
                # Literal, not bound: Postgres matches a partial index's
                # predicate only against constants, and asyncpg's prepared
                # statement goes generic after five runs.
                index_where=text("status IN ('queued', 'leased')"),
            )
        )
        created += result.rowcount or 0
    await session.flush()
    return created
