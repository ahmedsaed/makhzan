"""Shared pieces of the Phase D bake-off: labels, folds, prompts, metrics. Standard library only.

Labels: same -> 1; different and variant -> 0 (not_same); unsure -> excluded.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Sequence
from pathlib import Path

SEED = 20261113
FOLDS = 5

# ---------------------------------------------------------------------------------------------
# Prompts, fixed before any scoring (the grid is in docs/ai/phase-d-bakeoff.md).
# ---------------------------------------------------------------------------------------------

#: <Instruct> lines for the Qwen3 rerankers (vLLM fills the repo's fixed template with them).
QWEN_INSTRUCTIONS = {
    # The model card's default instruction (also the template's fallback).
    "I1": "Given a web search query, retrieve relevant passages that answer the query",
    # The serving setup's default (makhzan_ml.client.SAME_PRODUCT).
    "I2": (
        "Given two product listings from hardware shops, judge whether they are the same "
        "product: the same item, the same variant and the same pack size"
    ),
    # Task-specific wording, as the owner gave it.
    "I3": (
        "Decide whether these two shop listings sell the identical product: same maker, model "
        "and specification; a different value, pack size, variant or accessory is a different "
        "product"
    ),
    # makhzan's variant rule (the Phase C label definitions).
    "I4": (
        "Decide whether two shop listings are the same product, so that a buyer could buy "
        "either and receive the same item. Listings from the same product line that differ in "
        "one option (colour, size, length, capacity, rating or value) are NOT the same product; "
        "neither are a different model, a different package, a different pack size or bundle, "
        "or a part versus a module or accessory. Differences only in wording, word order or "
        "spelling do not matter"
    ),
}

#: Kev's `noul` instructions are a yes/no question about the state (its README); Kev has no
#: card default instruction, so I1 has no Kev counterpart.
KEV_QUESTIONS = {
    "I2": (
        "Are listing A and listing B the same product: the same item, the same variant and the "
        "same pack size?"
    ),
    "I3": (
        "Do listing A and listing B sell the identical product: same maker, model and "
        "specification? A different value, pack size, variant or accessory is a different "
        "product."
    ),
    "I4": (
        "Are listing A and listing B the same product, so that a buyer could buy either and "
        "receive the same item? Listings from the same product line that differ in one option "
        "(colour, size, length, capacity, rating or value) are NOT the same product; neither are "
        "a different model, a different package, a different pack size or bundle, or a part "
        "versus a module or accessory. Differences only in wording, word order or spelling do "
        "not matter."
    ),
}

SHOTS = 4  # two same, one different, one variant


def qwen_fewshot(instruction: str, examples: list[tuple[str, str, int]]) -> str:
    lines = [instruction + ".", "Examples (Query | Document -> answer):"]
    lines += [f"{a} | {b} -> {'yes' if y else 'no'}" for a, b, y in examples]
    return "\n".join(lines)


def kev_fewshot(question: str, examples: list[tuple[str, str, int]]) -> dict:
    # Kev's `instructions` field takes JSON content and renders it as labelled text (kev/api.py
    # `render`), so worked examples go in as data next to the question.
    return {
        "question": question,
        "examples": [
            {"listing A": a, "listing B": b, "answer": "yes" if y else "no"} for a, b, y in examples
        ],
    }


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------


def target(label: str) -> int | None:
    return None if label == "unsure" else int(label == "same")


def load_pairs(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def folds(pairs: Sequence[dict]) -> dict[str, int]:
    """Validation pair id -> fold 0..4, stratified by label, seeded."""
    rng = random.Random(SEED)
    out: dict[str, int] = {}
    for label in ("same", "different", "variant", "unsure"):
        ids = sorted(p["pair_id"] for p in pairs if p["label"] == label)
        rng.shuffle(ids)
        for i, pid in enumerate(ids):
            out[pid] = i % FOLDS
    return out


def fewshot_ids(validation: Sequence[dict], fold: int | None) -> list[tuple[str, int]]:
    """The example pairs for scoring fold `fold` (None: scoring the test split), as
    (pair id, target). Drawn only from validation pairs outside that fold; never a test pair."""
    f = folds(validation)
    pool = [p for p in validation if fold is None or f[p["pair_id"]] != fold]
    rng = random.Random(SEED + (fold if fold is not None else 99))
    picks = []
    for label, n, cross in (("same", 2, True), ("different", 1, False), ("variant", 1, False)):
        cands = sorted(
            p["pair_id"] for p in pool if p["label"] == label and (not cross or not p["same_shop"])
        )
        picks += [(pid, int(label == "same")) for pid in rng.sample(cands, n)]
    rng.shuffle(picks)
    return picks


# ---------------------------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------------------------


def confusion(scores: Sequence[float], ys: Sequence[int], t: float) -> tuple[int, int, int, int]:
    tp = sum(1 for s, y in zip(scores, ys, strict=True) if s >= t and y == 1)
    fp = sum(1 for s, y in zip(scores, ys, strict=True) if s >= t and y == 0)
    fn = sum(1 for s, y in zip(scores, ys, strict=True) if s < t and y == 1)
    tn = len(ys) - tp - fp - fn
    return tp, fp, fn, tn


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return p, r, f


def candidate_thresholds(scores: Sequence[float]) -> list[float]:
    return sorted(set(scores)) + [math.inf]


def best_f1_threshold(scores: Sequence[float], ys: Sequence[int]) -> float:
    """The threshold maximising F1; ties go to the higher threshold (fewer merges)."""
    best = (-1.0, 0.0)
    for t in candidate_thresholds(scores):
        tp, fp, fn, _ = confusion(scores, ys, t)
        f = prf(tp, fp, fn)[2]
        if f >= best[0]:
            best = (f, t)
    return best[1]


def precision_threshold(scores: Sequence[float], ys: Sequence[int], target_p: float) -> float:
    """The lowest threshold whose precision is at least target_p (inf if none is)."""
    for t in candidate_thresholds(scores):
        tp, fp, _, _ = confusion(scores, ys, t)
        if tp + fp and tp / (tp + fp) >= target_p:
            return t
    return math.inf


def average_precision(scores: Sequence[float], ys: Sequence[int]) -> float:
    order = sorted(zip(scores, ys, strict=True), key=lambda x: -x[0])
    pos = sum(ys)
    if not pos:
        return float("nan")
    hits, total = 0, 0.0
    for i, (_, y) in enumerate(order, 1):
        if y:
            hits += 1
            total += hits / i
    return total / pos


def cv_predictions(scores: Sequence[float], ys: Sequence[int], fold_of: Sequence[int]) -> list[int]:
    """Out-of-fold decisions: each fold judged at the best-F1 threshold of the other folds."""
    pred = [0] * len(ys)
    for k in range(FOLDS):
        train = [i for i, f in enumerate(fold_of) if f != k]
        t = best_f1_threshold([scores[i] for i in train], [ys[i] for i in train])
        for i, f in enumerate(fold_of):
            if f == k:
                pred[i] = int(scores[i] >= t)
    return pred


def f1_of(pred: Sequence[int], ys: Sequence[int]) -> float:
    tp = sum(1 for p, y in zip(pred, ys, strict=True) if p and y)
    fp = sum(1 for p, y in zip(pred, ys, strict=True) if p and not y)
    fn = sum(1 for p, y in zip(pred, ys, strict=True) if not p and y)
    return prf(tp, fp, fn)[2]


def bootstrap_indices(n: int, reps: int = 2000, seed: int = SEED) -> list[list[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(reps)]


def percentile_ci(values: list[float], level: float = 0.95) -> tuple[float, float]:
    v = sorted(x for x in values if not math.isnan(x))
    lo = v[int((1 - level) / 2 * (len(v) - 1))]
    hi = v[int((1 + level) / 2 * (len(v) - 1))]
    return lo, hi


def wilson_lower(k: int, n: int, z: float = 1.959964) -> float:
    if n == 0:
        return float("nan")
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def _binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def clopper_pearson_lower(k: int, n: int, alpha: float = 0.05) -> float:
    """Two-sided (1 - alpha) exact lower bound: the p with P(X >= k | p) = alpha / 2."""
    if n == 0:
        return float("nan")
    if k == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _binom_sf(k, n, mid) < alpha / 2:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
