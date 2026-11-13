"""Does a lower-precision variant change the answers? Compare two score files from bench.py.

    python3 ml/quant.py <out>/scores-rr-qwen3-4b.json <out>/scores-rr-qwen3-4b-fp8.json

Reports, over the pairs both files score: Pearson and Spearman correlation, max and mean |Δp|,
and the share of yes/no decisions that agree at thresholds 0.5 and 0.9. The owner's rule:
adopt the variant only if agreement >= 99% at both thresholds and Spearman >= 0.99.
For embedders the "score" is the cosine of the two listings, so thresholds on it are only a
rough check; the correlations are the ones that matter there.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

THRESHOLDS = (0.5, 0.9)
MIN_AGREEMENT, MIN_SPEARMAN = 0.99, 0.99


def pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else float("nan")


def ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=v.__getitem__)
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1  # ties share the mean rank
        i = j + 1
    return r


def compare(ref: dict[str, float], alt: dict[str, float]) -> dict:
    """Both files must score the same, non-empty set of pairs; `adopt` uses unrounded values."""
    if set(ref) != set(alt):
        raise ValueError(f"different pairs: {len(set(ref) ^ set(alt))} in only one file")
    if not ref:
        raise ValueError("no pairs to compare")
    keys = sorted(ref)
    x, y = [ref[k] for k in keys], [alt[k] for k in keys]
    d = [abs(a - b) for a, b in zip(x, y)]
    spearman = pearson(ranks(x), ranks(y))
    agree = {t: sum((a >= t) == (b >= t) for a, b in zip(x, y)) / len(keys) for t in THRESHOLDS}
    out = {
        "pairs": len(keys),
        "pearson": round(pearson(x, y), 5),
        "spearman": round(spearman, 5),
        "max_abs_delta": round(max(d), 5),
        "mean_abs_delta": round(sum(d) / len(d), 5),
    }
    for t in THRESHOLDS:
        out[f"agree@{t}"] = round(agree[t], 4)
        out[f"flips@{t}"] = sum((a >= t) != (b >= t) for a, b in zip(x, y))
    out["adopt"] = all(agree[t] >= MIN_AGREEMENT for t in THRESHOLDS) and spearman >= MIN_SPEARMAN
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    ref, alt = (json.loads(Path(p).read_text()) for p in sys.argv[1:])
    print(json.dumps(compare(ref, alt), indent=2))


if __name__ == "__main__":
    main()
