"""AI matching pipelines, declared as data: a registry and one transition function.

A **pipeline** is a named, ordered list of **stages**. A stage is a model key
(`policy.MODELS`), a prompt variant (`prompt.VARIANTS`) and a threshold key
(into each `policy.POLICIES` entry). What happens after a stage is scored, in
both reading orders, is the same rule everywhere (`transition`):

- a stage whose score (the lower of its two orders) is below its threshold
  ends the pair: decided `not_same` by that stage;
- one that passes hands the pair to the next stage;
- passing the last stage decides `same`.

A pipeline that does not decide (`decides=False`, the audit) only records its
scores: each stage still runs in order, and nothing is concluded.

Today's two:

- `match`: candidate pairs. H2O-Lightning (K2, description capped at 150 words;
  D25, 2026-11-27, replacing Kev), then pplx (K1, full description).
- `audit`: pairs the rules merged, scored by the first judge only and recorded
  (P12: no threshold is chosen yet; status counts each judge's scores below its
  threshold and below its floor).

A stage that leaves the registry (Kev's, at D25) is not an error: a queued job
naming it is re-offered to its pipeline at the next sweep, which queues the
stage the pair now owes, and a standing decision whose stored scores name it is
re-scored like any other changed judge (`candidates.RescoreTrigger`).

A re-score is not a pipeline: a changed content hash or a new model or prompt
version re-queues the pair into the pipeline it was in. The group check (P14)
reads stored scores and triggers nothing.

Everything that acts on a pair asks this module: who enqueues (`triggers`), the
broker when a result arrives (`transition`, never `if stage == ...`), a worker
lease (`stages_for_models`), and a policy change recomputing decisions from
stored scores (`decide`). A new model, prompt or pipeline is a change here and
in `policy`/`prompt`, with no migration: tables store pipeline and stage names
as strings, validated against this registry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from makhzan_schemas.ai.policy import ACTIVE, MODELS, POLICIES, thresholds
from makhzan_schemas.ai.prompt import PROMPT_VERSIONS, VARIANTS

SAME, NOT_SAME = "same", "not_same"


@dataclass(frozen=True)
class Stage:
    """One step: which model reads the pair, in which prompt, judged by which threshold."""

    name: str
    model: str
    prompt: str
    #: Key into a policy's thresholds; None for a stage that only records.
    threshold: str | None

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSIONS[self.prompt]

    @property
    def model_version(self) -> str:
        return MODELS[self.model].model_version


@dataclass(frozen=True)
class Pipeline:
    name: str
    stages: tuple[Stage, ...]
    #: False: scores are recorded, no decision is written (the audit).
    decides: bool = True

    def stage(self, name: str) -> Stage:
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise ValueError(f"pipeline {self.name!r} has no stage {name!r}")


_H2O = Stage("h2o", model="h2o", prompt="K2-150", threshold="h2o")

PIPELINES: dict[str, Pipeline] = {
    "match": Pipeline(
        "match",
        (_H2O, Stage("pplx", model="pplx", prompt="K1-full", threshold="pplx")),
    ),
    "audit": Pipeline(
        "audit", (Stage("h2o", model="h2o", prompt="K2-150", threshold=None),), decides=False
    ),
}


def pipeline(name: str) -> Pipeline:
    """A registered pipeline; an unknown name is an error (a stored row naming
    one is refused, never guessed at)."""
    try:
        return PIPELINES[name]
    except KeyError:
        raise ValueError(f"no AI pipeline {name!r} (known: {sorted(PIPELINES)})") from None


def check_registry() -> None:
    """Every stage names a known model and prompt, every deciding stage a
    threshold the active policy defines, and stage names are unique per
    pipeline. Run at import, so a broken registry never starts. An older policy
    may lack a current stage's threshold (`p1` has no `h2o`): it is the record
    of what decisions were made under, and recomputing with it raises."""
    for p in PIPELINES.values():
        if not p.stages:
            raise ValueError(f"pipeline {p.name!r} has no stages")
        names = [s.name for s in p.stages]
        if len(set(names)) != len(names):
            raise ValueError(f"pipeline {p.name!r} repeats a stage name")
        for s in p.stages:
            if s.model not in MODELS:
                raise ValueError(f"{p.name}.{s.name}: unknown model {s.model!r}")
            if s.prompt not in VARIANTS:
                raise ValueError(f"{p.name}.{s.name}: unknown prompt {s.prompt!r}")
            if p.decides and s.threshold is None:
                raise ValueError(f"{p.name}.{s.name}: a deciding stage needs a threshold")
            if s.threshold is not None and s.threshold not in POLICIES[ACTIVE]:
                raise ValueError(f"policy {ACTIVE!r} has no threshold {s.threshold!r}")


check_registry()


def stages_for_models(models: set[str] | frozenset[str]) -> list[tuple[str, str]]:
    """The (pipeline, stage) pairs a worker serving these model keys may lease."""
    return [(p.name, s.name) for p in PIPELINES.values() for s in p.stages if s.model in models]


# --- the one transition rule ----------------------------------------------------------------

#: What to do next: score a stage, write a decision, or (a non-deciding
#: pipeline whose stages are all scored) only record.
SCORE, DECIDE, RECORD = "score", "decide", "record"

#: One stage's two reading orders: {"ab": p, "ba": p}, either possibly missing.
Scores = Mapping[str, Mapping[str, float | None]]


@dataclass(frozen=True)
class Step:
    action: str
    #: For SCORE: the stage still owed its two orders.
    stage: str | None = None
    #: For DECIDE: `same` or `not_same`, and the stage that settled it.
    outcome: str | None = None
    decided_by: str | None = None
    #: Each scored stage's lower score, in stage order.
    mins: tuple[tuple[str, float], ...] = ()


def _lower(orders: Mapping[str, float | None] | None) -> float | None:
    if not orders or orders.get("ab") is None or orders.get("ba") is None:
        return None
    return min(orders["ab"], orders["ba"])


def transition(name: str, scores: Scores, policy: str = ACTIVE) -> Step:
    """The next step for a pair in pipeline `name`, given its stored scores
    by stage name. Pure: the broker calls it after every result, and a policy
    change calls it over stored scores, with no model.

    Both reading orders are always required (P11): one order settles nothing,
    not even a "no".
    """
    p = pipeline(name)
    limits = thresholds(policy)
    mins: list[tuple[str, float]] = []
    for stage in p.stages:
        low = _lower(scores.get(stage.name))
        if low is None:
            return Step(SCORE, stage=stage.name, mins=tuple(mins))
        mins.append((stage.name, low))
        if p.decides and stage.threshold not in limits:
            raise ValueError(f"policy {policy!r} has no threshold {stage.threshold!r}")
        if p.decides and low < limits[stage.threshold]:
            return Step(DECIDE, outcome=NOT_SAME, decided_by=stage.name, mins=tuple(mins))
    if not p.decides:
        return Step(RECORD, mins=tuple(mins))
    return Step(DECIDE, outcome=SAME, decided_by=p.stages[-1].name, mins=tuple(mins))


def decide(pipeline_name: str, scores: Scores, policy: str = ACTIVE) -> Step:
    """The decision stored scores make in pipeline `pipeline_name` (named
    explicitly, never assumed): `transition` by its other name, the entry
    point for recomputing decisions under a new policy (P7)."""
    return transition(pipeline_name, scores, policy)


def rank(step_mins: Mapping[str, float], pipeline_name: str) -> tuple[float, ...]:
    """How strongly a decision says "same", for choosing a listing's best match
    per other shop (P14): the stages' lower scores, last stage first (pplx,
    then H2O, for `match`)."""
    p = pipeline(pipeline_name)
    return tuple(step_mins.get(s.name, 0.0) for s in reversed(p.stages))
