"""Cross-validate one judge against two (docs/ai/decision-models.md, section 6).

On the Phase E pairs that pass the vetoes (label "same" or "not") and have both orders scored by
H2O Q4 and pplx Q4, 500 seeded random halvings: each picks a threshold on one half and scores
the other. A pair's score is the lower of its two orders; H2O's is on the raw scale
(sigmoid(0.8 * logit p)), pplx's as served (no baked temperature).

    python3 ml/models/decision_models_cv.py

Setups: H2O alone and pplx alone (each tuned on the training half), the two-judge rule with
H2O tuned on the training pairs pplx passes (pplx >= 0.95), the rule fixed at (0.578, 0.95),
and H2O alone fixed at 0.7299 (its in-sample threshold for precision >= 0.99). Per setup: mean
test precision, its 5th percentile, mean recall, and wrong merges per test half (mean, max,
share of splits with 3 or more). Seeded with 20261127, so the output is exact.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY = ROOT.parent / "makhzan-config/labels/answer-key-v2.jsonl"
H2O_Q4 = ROOT / "ml/out/models-compare/h2o-q4-K2.jsonl"
PPLX_Q4 = ROOT / "ml/out/gguf-pplx/Q4_K_S.jsonl"
H2O_T = 0.8
SPLITS = 500
SEED = 20261127
PRECISION = 0.99


def raw(p: float, t: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return 1 / (1 + math.exp(-t * math.log(p / (1 - p))))


def pair_scores(path: Path, t: float = 1.0) -> dict[str, float]:
    orders: dict[str, dict[str, float]] = {}
    for r in map(json.loads, path.open()):
        if r.get("score") is not None:
            s = raw(r["score"], t) if t != 1.0 else r["score"]
            orders.setdefault(r["pair_id"], {})[r["order"]] = s
    return {p: min(o.values()) for p, o in orders.items() if len(o) == 2}


def pick(pids, score, same, prec=PRECISION):
    """The threshold, among those reaching `prec` on `pids`, that admits the most correct pairs."""
    best, best_tp = None, -1
    for t in sorted({score[p] for p in pids}):
        tp = sum(score[p] >= t and same[p] for p in pids)
        fp = sum(score[p] >= t and not same[p] for p in pids)
        if tp + fp and tp / (tp + fp) >= prec and tp > best_tp:
            best, best_tp = t, tp
    return best


def main() -> None:
    key = [json.loads(line) for line in KEY.open()]
    h2o, pplx = pair_scores(H2O_Q4, H2O_T), pair_scores(PPLX_Q4)
    pids = sorted(
        k["pair_id"]
        for k in key
        if not any(k["veto"].values())
        and k["label"] in ("same", "not")
        and k["pair_id"] in h2o
        and k["pair_id"] in pplx
    )
    same = {k["pair_id"]: k["label"] == "same" for k in key}
    print(f"{len(pids)} pairs, {sum(same[p] for p in pids)} same")

    def merged_by(setup, train):
        """The merge predicate a setup uses on the test half, fitted on `train`."""
        if setup == "H2O alone (tuned)":
            t = pick(train, h2o, same)
            return lambda p: h2o[p] >= t
        if setup == "pplx alone (tuned)":
            t = pick(train, pplx, same)
            return lambda p: pplx[p] >= t
        if setup == "rule, H2O tuned & pplx >= 0.95":
            t = pick([p for p in train if pplx[p] >= 0.95], h2o, same)
            return lambda p: h2o[p] >= t and pplx[p] >= 0.95
        if setup == "rule fixed 0.578 / 0.95":
            return lambda p: h2o[p] >= 0.578 and pplx[p] >= 0.95
        if setup == "H2O alone fixed >= 0.7299":
            return lambda p: h2o[p] >= 0.7299
        raise ValueError(setup)

    setups = (
        "H2O alone (tuned)",
        "pplx alone (tuned)",
        "rule, H2O tuned & pplx >= 0.95",
        "rule fixed 0.578 / 0.95",
        "H2O alone fixed >= 0.7299",
    )
    results = {s: {"precision": [], "recall": [], "wrong": []} for s in setups}
    rng = random.Random(SEED)
    for _ in range(SPLITS):
        order = list(pids)  # a fresh copy each split, shuffled by the one seeded generator
        rng.shuffle(order)
        half = len(order) // 2
        train, test = order[:half], order[half:]
        n_same = sum(same[p] for p in test)
        for s in setups:
            merge = merged_by(s, train)
            m = [p for p in test if merge(p)]
            tp = sum(same[p] for p in m)
            results[s]["precision"].append(tp / len(m) if m else 1.0)
            results[s]["recall"].append(tp / n_same)
            results[s]["wrong"].append(len(m) - tp)
    print(f"{SPLITS} splits, seed {SEED}")
    print(f"{'setup':34} precision [p05]   recall  wrong/half mean, max, share >= 3")
    for s in setups:
        r = results[s]
        pr = sorted(r["precision"])
        w = r["wrong"]
        print(
            f"{s:34} {sum(pr) / len(pr):.4f} [{pr[len(pr) // 20]:.4f}]"
            f"  {sum(r['recall']) / len(r['recall']):.3f}"
            f"   {sum(w) / len(w):.2f}, {max(w)}, {sum(x >= 3 for x in w) / len(w):.0%}"
        )


if __name__ == "__main__":
    main()
