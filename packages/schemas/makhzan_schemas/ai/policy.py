"""Thresholds and models for AI matching: what a decision means, and which model made it.

**Policies** (decision P7, 2026-11-17). Thresholds are named versions in code, so a
change is a pull request and git is its record. A policy maps threshold keys to
values; each pipeline stage names the key it is judged by
(`pipelines.Stage.threshold`). Each decision stores the policy it was made
under (`ai_decisions.policy_version`); a new policy is applied to stored scores,
with no model call, by recomputing decisions (`pipelines.decide`). `p1` is the
owner's "safest" operating point of 2026-11-16: Kev (K2, description capped at
150 words) at least 0.80 **and** pplx (K1, full description) at least 0.95,
each the lower of its two reading orders, behind today's vetoes.

**The group check** (P14): a score by `GROUP_CHECK_MODEL` below `KEV_BLOCK`
between a listing and any member of a product blocks a join that rests on an
AI decision. It reads scores already stored and triggers nothing; it never
splits what the rules merged.

**Models** (P8), keyed by the model key that pipeline stages and worker
configurations name. A model version is the weights revision, the serving
code and the scoring parameters; the prompt version belongs to the stage's
prompt variant (`prompt.PROMPT_VERSIONS`). GPU and CPU runs count as one
version; each score records its device and dtype. A new model is an entry in
`MODELS`: no migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Named threshold sets. Never edit one in place: add the next and move ACTIVE.
POLICIES: dict[str, dict[str, float]] = {"p1": {"kev": 0.80, "pplx": 0.95}}
ACTIVE = "p1"

#: P14: the model whose "confident no" blocks an AI-dependent join, and below what.
GROUP_CHECK_MODEL = "kev"
KEV_BLOCK = 0.05

#: Kev-4B's weights on the Hub, pinned (the revision the CPU and GPU images load).
KEV_REPO = "jaredpalmer/kev-4b"
KEV_REVISION = "6cfce5c2fa4b4bd64026336ab649c5ca78857d52"
#: The Kev serving code the images are built from.
KEV_CODE = "6b719c3c3f367295f6ef336f4f751cf5ff970abc"

#: pplx-decider's weights on the Hub, pinned (`ml/models/bench_cpu.py`'s PPLX_REVISION).
PPLX_REPO = "perplexity-ai/pplx-decider-flash-v1.3"
PPLX_REVISION = "d06fb3f2d97e0a52325a0d463c450cf0338f44fe"
#: The checkpoint's own temperature, which pplx's score is read at (decision-review §4).
PPLX_TEMPERATURE = 1.3303


@dataclass(frozen=True)
class Model:
    """One model, as `ai_model_versions` records it with a prompt version."""

    key: str
    repo: str
    weights_revision: str
    model_version: str
    scoring: dict = field(default_factory=dict)


MODELS: dict[str, Model] = {
    "kev": Model(
        key="kev",
        repo=KEV_REPO,
        weights_revision=KEV_REVISION,
        model_version=f"kev-4b@{KEV_REVISION[:12]}+kev-{KEV_CODE[:7]}+T1.0",
        # Raw P(yes) at temperature 1 (KEV_TEMPERATURE=1.0), no prefix cache.
        scoring={"score": "p_yes", "temperature": 1.0, "prefix_cache": 0},
    ),
    "pplx": Model(
        key="pplx",
        repo=PPLX_REPO,
        weights_revision=PPLX_REVISION,
        model_version=f"pplx-decider-flash-v1.3@{PPLX_REVISION[:12]}+T{PPLX_TEMPERATURE}",
        # P(true) at the checkpoint's temperature.
        scoring={"score": "p_true", "temperature": PPLX_TEMPERATURE},
    ),
}


def thresholds(policy: str = ACTIVE) -> dict[str, float]:
    """A policy's thresholds; a name not in `POLICIES` is an error, never a default."""
    try:
        return POLICIES[policy]
    except KeyError:
        raise ValueError(f"no AI matching policy {policy!r} (known: {sorted(POLICIES)})") from None
