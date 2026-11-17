"""What each model key this worker can serve is pinned to: weights, serving code, scoring.

A copy of `makhzan_schemas.ai.policy.MODELS`, because the model images carry torch and
the model code but not the schema package (and must not need SQLAlchemy to score). The
worker's tests hold every field here equal to the policy, so the two cannot drift
apart unnoticed: a new pin is a change to both, in one commit.

After loading, the worker checks the model it actually holds against these pins (the
snapshot's revision, the temperature it scores at, the serving code's commit where the
image records it) and refuses to score on any difference (P8). The broker then checks
the version string at hello and at every lease (broker-api.md §3.1, §3.2).
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
