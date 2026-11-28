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

**The group check** (P14): a score by a first-stage judge below its floor
(`JUDGE_FLOORS`) between a listing and any member of a product blocks a join
that rests on an AI decision. It reads scores already stored and triggers
nothing; it never splits what the rules merged.

**Models** (P8), keyed by the model key that pipeline stages and worker
configurations name. A model version is the weights revision, the serving
code and the scoring parameters; the prompt version belongs to the stage's
prompt variant (`prompt.PROMPT_VERSIONS`). GPU and CPU runs count as one
version; each score records its device and dtype. A new model is an entry in
`MODELS`: no migration.

**Production switch (owner, 2026-11-27):** `MODELS` names Kev-4B Q4_K_M and pplx-decider Q4_K_S
served by llama.cpp (D20 amended 2026-11-26; docs/ai/kev-llamacpp.md, pplx-llamacpp.md), on the
home server's AMD card taking turns. The torch versions stay in `TORCH_MODELS`, the rollback:
moving `MODELS` back to them (and the worker's `pins.ACTIVE_BACKEND`) is one commit. A version
change makes every standing decision's judge stale, so the re-score producer re-queues them at the
amended P8 priorities (after new pairs and the backlog; decision-review.md).

**First judge: H2O-Lightning (owner, 2026-11-27, D25):** policy `p2` replaces Kev with
H2O-Lightning-4B Q4_K_M (llama.cpp) as the match pipeline's first stage, at 0.578 on the raw
scale (its precision on the labelled Phase E set matched to full-precision Kev's at 0.8), pplx
Q4_K_S at 0.95 unchanged. With pplx Q4 on the labels: 229 merges, 227 correct, 2 wrong (both
grey), against Kev Q4's 217/216/1. `p1` stays, a record of what decisions were made under; its
stage no longer exists. The H2O floor of the group check (0.19) was proposed by the session and
confirmed by the owner, 2026-11-27 (decision-review.md, D25).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Named threshold sets. Never edit one in place: add the next and move ACTIVE.
POLICIES: dict[str, dict[str, float]] = {
    "p1": {"kev": 0.80, "pplx": 0.95},
    # Owner, 2026-11-27 (D25): H2O-Lightning Q4_K_M first, raw P(yes) (its GGUF's 0.8 undone).
    "p2": {"h2o": 0.578, "pplx": 0.95},
}
ACTIVE = "p2"

#: P15: the departments AI matching serves. Triggers offer pairs only from
#: these, and the regroup reads a decision only while both of its listings are
#: still in one of them (owner, 2026-11-17): a listing that moves out takes
#: the AI merge apart at the next regroup.
DOMAINS: tuple[str, ...] = ("electronics",)

#: P14: per first-stage model, the score below which its "confident no" blocks an AI-dependent
#: join. Kev's 0.05 (owner, P14) still reads the Kev scores standing decisions carry until they are
#: re-scored. H2O's 0.19 blocks the same share of the labelled Phase E "not same" pairs as Kev's
#: 0.05 (358 of 463, 77.3%) while blocking fewer labelled "same" ones (12 vs 16): confirmed by
#: the owner, 2026-11-27 (decision-review.md, D25).
JUDGE_FLOORS: dict[str, float] = {"h2o": 0.19, "kev": 0.05}

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


#: The llama.cpp versions (worker `pins.ALTERNATIVES`): GGUF files pinned by sha256, served by
#: llama.cpp build b12767. The server-vulkan image's digest prefix in the version strings is a
#: historical label, kept byte-identical so nothing re-scores: any official image of build
#: b12767 (Vulkan, CUDA, CPU) serves the same judge, and the serving image is recorded with
#: each score (D26, owner, 2026-11-28; P8: device and dtype are recorded, not versioned).
LLAMACPP_BUILD = "b12767"
LLAMACPP_IMAGE_DIGEST = "87d189d403fda2a612a23c9dcd35c482967f48586e93d812a01e7a1f5e3a1486"
KEV_GGUF_REPO = "ggml-org/Kev-4B-GGUF"
KEV_GGUF_REVISION = "f4624b6bb7072f1bab726a622c1cad3f96030b9e"
KEV_GGUF_SHA256 = "33ae6b18926502b2209a1bf7d3b61a350d65938441515c686bb87d226a19eff9"
#: pplx Q4_K_S: our own conversion of PPLX_REPO@PPLX_REVISION (ml/models/convert_pplx_v13.py).
PPLX_GGUF_SHA256 = "819a9ad0f8f4aacb055f6d1783a155e3bd0bf33afb9c2f33749ef25350c61ab3"
#: H2O-Lightning-4B Q4_K_M, the publisher's own GGUF (decision type `h2o-lightning`, noul
#: temperature 0.8 built in; the worker undoes it: raw P(yes)).
H2O_GGUF_REPO = "h2oai/h2o-lightning-4b-gguf"
H2O_GGUF_REVISION = "61f8d8b7a8c2d84426d0d143ca187f65d235934b"
H2O_GGUF_SHA256 = "5ec969c6edbad5f1750141742f635cc7f01576bf9432151f730f0a6c30042768"


@dataclass(frozen=True)
class Model:
    """One model, as `ai_model_versions` records it with a prompt version."""

    key: str
    repo: str
    weights_revision: str
    model_version: str
    scoring: dict = field(default_factory=dict)


#: Kev-4B Q4_K_M through llama.cpp: the first judge from the production switch until D25 (the
#: rollback of D25 is putting it back in `MODELS` with policy `p1`).
LLAMACPP_KEV = Model(
    key="kev",
    repo=KEV_GGUF_REPO,
    weights_revision=KEV_GGUF_REVISION,
    model_version=(
        f"kev-4b-Q4_K_M@{KEV_GGUF_SHA256[:12]}+llama.cpp-{LLAMACPP_BUILD}"
        f"-{LLAMACPP_IMAGE_DIGEST[:12]}+T1.0"
    ),
    # Raw P(yes) at temperature 1: the worker undoes the GGUF's built-in 2.406.
    scoring={
        "score": "p_yes",
        "temperature": 1.0,
        "backend": "llamacpp",
        "gguf_sha256": KEV_GGUF_SHA256,
    },  # fmt: skip
)

#: What production serves: H2O-Lightning first (D25), pplx second, both through llama.cpp.
MODELS: dict[str, Model] = {
    "h2o": Model(
        key="h2o",
        repo=H2O_GGUF_REPO,
        weights_revision=H2O_GGUF_REVISION,
        model_version=(
            f"h2o-lightning-4b-Q4_K_M@{H2O_GGUF_SHA256[:12]}+llama.cpp-{LLAMACPP_BUILD}"
            f"-{LLAMACPP_IMAGE_DIGEST[:12]}+T1.0"
        ),
        # Raw P(yes) at temperature 1: the worker undoes the GGUF's built-in 0.8.
        scoring={
            "score": "p_yes",
            "temperature": 1.0,
            "backend": "llamacpp",
            "gguf_sha256": H2O_GGUF_SHA256,
        },  # fmt: skip
    ),
    "pplx": Model(
        key="pplx",
        repo=PPLX_REPO,
        weights_revision=PPLX_REVISION,
        model_version=(
            f"pplx-decider-flash-v1.3-Q4_K_S@{PPLX_GGUF_SHA256[:12]}+llama.cpp-{LLAMACPP_BUILD}"
            f"-{LLAMACPP_IMAGE_DIGEST[:12]}+T{PPLX_TEMPERATURE}"
        ),
        # P(true) at the checkpoint's temperature, which llama.cpp applies as served.
        scoring={
            "score": "p_true",
            "temperature": PPLX_TEMPERATURE,
            "backend": "llamacpp",
            "gguf_sha256": PPLX_GGUF_SHA256,
        },  # fmt: skip
    ),
}

#: The torch versions production served until 2026-11-27: the rollback (see the module doc).
TORCH_MODELS: dict[str, Model] = {
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
