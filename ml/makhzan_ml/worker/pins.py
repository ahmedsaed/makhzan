"""What each model key this worker can serve is pinned to: weights, serving code, scoring.

A copy of `makhzan_schemas.ai.policy.MODELS`, because the model images carry torch and
the model code but not the schema package (and must not need SQLAlchemy to score). The
worker's tests hold every field here equal to the policy, so the two cannot drift
apart unnoticed: a new pin is a change to both, in one commit.

After loading, the worker checks the model it actually holds against these pins (the
snapshot's revision, the temperature it scores at, the serving code's commit where the
image records it) and refuses to score on any difference (P8). The broker then checks
the version string at hello and at every lease (broker-api.md §3.1, §3.2).

`PINS` is what production serves, one pin per model key, equal to the policy. A key may
also have an **alternative backend** (`ALTERNATIVES`): Kev-4B Q4_K_M and pplx Q4_K_S served by
a llama.cpp sidecar, accepted by the owner on 2026-11-26 (D20 amended; docs/ai/kev-llamacpp.md,
docs/ai/pplx-llamacpp.md). A
worker selects it with `[compute] backend = "llamacpp"`; it carries its own model version,
so the broker refuses it (hello `ok: false`) until the policy's `MODELS` names that version.
Switching production is that one change to the policy and to `PINS`, owner-gated.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pin:
    key: str
    repo: str
    weights_revision: str
    temperature: float
    #: The serving code's commit (Kev's own server); None where the code is part of the
    #: checkpoint itself (pplx's package is copied from the pinned Hub revision, sha256-checked).
    code: str | None
    model_version: str
    #: "torch" (the model's own Python code, in the worker's process) or "llamacpp" (a
    #: llama.cpp server beside the worker, `/v1/systemone`).
    backend: str = "torch"
    #: llama.cpp only: the GGUF file (of, or converted from, `repo`@`weights_revision`), its
    #: sha256, and the decision temperature its metadata carries, which llama.cpp always
    #: applies; the worker rescales the answer to `temperature` (Kev: raw, 1.0) or, when the
    #: two agree (pplx), takes it as served.
    gguf_file: str | None = None
    gguf_sha256: str | None = None
    gguf_temperature: float | None = None


KEV_REVISION = "6cfce5c2fa4b4bd64026336ab649c5ca78857d52"
KEV_CODE = "6b719c3c3f367295f6ef336f4f751cf5ff970abc"
PPLX_REVISION = "d06fb3f2d97e0a52325a0d463c450cf0338f44fe"
PPLX_TEMPERATURE = 1.3303

PINS: dict[str, Pin] = {
    "kev": Pin(
        key="kev",
        repo="jaredpalmer/kev-4b",
        weights_revision=KEV_REVISION,
        # Raw P(yes): KEV_TEMPERATURE=1.0, as every validated Kev score was read.
        temperature=1.0,
        code=KEV_CODE,
        model_version=f"kev-4b@{KEV_REVISION[:12]}+kev-{KEV_CODE[:7]}+T1.0",
    ),
    "pplx": Pin(
        key="pplx",
        repo="perplexity-ai/pplx-decider-flash-v1.3",
        weights_revision=PPLX_REVISION,
        # The checkpoint's own temperature, which pplx's P(true) is read at.
        temperature=PPLX_TEMPERATURE,
        code=None,
        model_version=f"pplx-decider-flash-v1.3@{PPLX_REVISION[:12]}+T{PPLX_TEMPERATURE}",
    ),
}


#: The llama.cpp alternative for Kev (docs/ai/kev-llamacpp.md, measured 2026-11-26).
KEV_GGUF_REPO = "ggml-org/Kev-4B-GGUF"
KEV_GGUF_REVISION = "f4624b6bb7072f1bab726a622c1cad3f96030b9e"
KEV_GGUF_FILE = "Kev-4B-Q4_K_M.gguf"
KEV_GGUF_SHA256 = "33ae6b18926502b2209a1bf7d3b61a350d65938441515c686bb87d226a19eff9"
#: `qwen35.decision.temperature.noul` in that file (Kev-4B's fitted temperature, 2.406).
KEV_GGUF_TEMPERATURE = 2.406049966812134
#: llama.cpp's official server-vulkan image, build 12767, by digest: the "code" of this pin.
LLAMACPP_IMAGE = (
    "ghcr.io/ggml-org/llama.cpp@sha256:"
    "87d189d403fda2a612a23c9dcd35c482967f48586e93d812a01e7a1f5e3a1486"
)
LLAMACPP_BUILD = "b12767"

#: The llama.cpp alternative for pplx (docs/ai/pplx-llamacpp.md, measured 2026-11-26): our own
#: conversion of the pinned checkpoint (ml/models/convert_pplx_v13.py, llama.cpp a8ad690ca),
#: Q4_K_S with an importance matrix from 300 backlog pairs outside the Phase E set.
PPLX_GGUF_FILE = "pplx-flash-v1.3-Q4_K_S.gguf"
PPLX_GGUF_SHA256 = "819a9ad0f8f4aacb055f6d1783a155e3bd0bf33afb9c2f33749ef25350c61ab3"
#: `qwen35.decision.temperature.noul` in that file: decision_config.json's temperature in full,
#: which llama.cpp applies; pplx's validated scores (and the policy's 0.95) are on that scale.
PPLX_GGUF_TEMPERATURE = 1.3302961587905884

BACKENDS = ("torch", "llamacpp")

ALTERNATIVES: dict[tuple[str, str], Pin] = {
    ("kev", "llamacpp"): Pin(
        key="kev",
        repo=KEV_GGUF_REPO,
        weights_revision=KEV_GGUF_REVISION,
        # Raw P(yes), as every validated Kev score: the GGUF's temperature is undone.
        temperature=1.0,
        code=LLAMACPP_IMAGE,
        model_version=(
            f"kev-4b-Q4_K_M@{KEV_GGUF_SHA256[:12]}+llama.cpp-{LLAMACPP_BUILD}"
            f"-{LLAMACPP_IMAGE.rsplit(':', 1)[1][:12]}+T1.0"
        ),
        backend="llamacpp",
        gguf_file=KEV_GGUF_FILE,
        gguf_sha256=KEV_GGUF_SHA256,
        gguf_temperature=KEV_GGUF_TEMPERATURE,
    ),
    ("pplx", "llamacpp"): Pin(
        key="pplx",
        repo="perplexity-ai/pplx-decider-flash-v1.3",
        weights_revision=PPLX_REVISION,
        # Read as served: llama.cpp applies the checkpoint's own temperature, the scale every
        # validated pplx score is on (nothing is undone, unlike Kev's).
        temperature=PPLX_TEMPERATURE,
        code=LLAMACPP_IMAGE,
        model_version=(
            f"pplx-decider-flash-v1.3-Q4_K_S@{PPLX_GGUF_SHA256[:12]}+llama.cpp-{LLAMACPP_BUILD}"
            f"-{LLAMACPP_IMAGE.rsplit(':', 1)[1][:12]}+T{PPLX_TEMPERATURE}"
        ),
        backend="llamacpp",
        gguf_file=PPLX_GGUF_FILE,
        gguf_sha256=PPLX_GGUF_SHA256,
        gguf_temperature=PPLX_GGUF_TEMPERATURE,
    ),
}


def pin_for(key: str, backend: str = "torch") -> Pin:
    """The pin a worker serving `key` on `backend` loads and reports. KeyError when that
    model has no such backend."""
    if backend == "torch":
        return PINS[key]
    return ALTERNATIVES[(key, backend)]
