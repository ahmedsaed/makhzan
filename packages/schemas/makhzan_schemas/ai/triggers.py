"""Triggers: what decides that a pair should go through a pipeline.

A trigger is a producer: it looks at the catalogue and yields `PairRequest`s,
each naming a registered pipeline (`pipelines.PIPELINES`). `enqueue` puts them
into that pipeline's first stage; everything after is the broker's generic
result handling (`pipelines.transition`). A trigger knows nothing about
models, stages or workers, and the broker and workers know nothing about
triggers, so a new reason to score a pair is a new trigger, nothing else.

Today's, each built in a later phase (only the interface is here):

- **candidates** (`match`): each new or changed listing's top-K lexical
  matches in other shops, filtered by today's vetoes (P1, P13);
- **audit** (`audit`): each pair the rules merged, Kev only (P12);
- **re-score** (whichever pipeline the pair was in, `reason="rescore"`): a
  changed content hash or a new model or prompt version (P5, P8), standing
  "same" decisions first.

A producer must not offer a pair a person has ruled on (CLAUDE.md: never
re-ask a model about a ruled pair, `overrides.load_overrides`).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.ai.pipelines import Stage, pipeline
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.models import AiJob, AiModelVersion
from makhzan_schemas.overrides import pair


@dataclass(frozen=True)
class PairRequest:
    """One pair a trigger wants judged, in either order (stored `a < b`)."""

    listing_a: uuid.UUID
    listing_b: uuid.UUID
    pipeline: str
    #: Higher first. The design's ladder: 100 re-score of a standing "same",
    #: 80 a later stage, 60 a new candidate, 40 backlog, 10 audit.
    priority: int
    #: Which trigger asked, for status: "candidates", "audit", "rescore", ...
    reason: str


class Trigger(Protocol):
    """A producer of pairs. Registered in `TRIGGERS` by name."""

    name: str

    async def produce(self, session: AsyncSession) -> Iterable[PairRequest]: ...


#: Producers by name. Filled by later phases (`register`); empty today.
TRIGGERS: dict[str, Trigger] = {}


def register(trigger: Trigger) -> Trigger:
    if trigger.name in TRIGGERS:
        raise ValueError(f"a trigger named {trigger.name!r} is already registered")
    TRIGGERS[trigger.name] = trigger
    return trigger


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


async def enqueue(
    session: AsyncSession, requests: Iterable[PairRequest], *, stage: str | None = None
) -> int:
    """Queue each pair at its pipeline's first stage (or `stage`, which is how
    the broker queues a later one). Idempotent: a pair already queued or
    leased at that stage and judge is left alone. Flushed, not committed;
    returns how many jobs were created."""
    created = 0
    versions: dict[tuple[str, str], int] = {}
    for request in requests:
        p = pipeline(request.pipeline)
        target = p.stage(stage) if stage is not None else p.stages[0]
        key = (p.name, target.name)
        if key not in versions:
            versions[key] = await model_version_id(session, target)
        a, b = pair(request.listing_a, request.listing_b)
        result = await session.execute(
            insert(AiJob)
            .values(
                pipeline=p.name,
                stage=target.name,
                reason=request.reason,
                model_version_id=versions[key],
                listing_a=a,
                listing_b=b,
                priority=request.priority,
            )
            .on_conflict_do_nothing(
                index_elements=["pipeline", "stage", "model_version_id", "listing_a", "listing_b"],
                index_where=AiJob.status.in_(("queued", "leased")),
            )
        )
        created += result.rowcount or 0
    await session.flush()
    return created
