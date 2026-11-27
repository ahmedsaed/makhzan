"""Cross-validate one judge against two (docs/ai/decision-models.md, section 6).

On the Phase E pairs that pass the vetoes (label "same" or "not") and have both orders scored by
H2O Q4 and pplx Q4, 500 seeded random halvings: each picks a threshold on one half and scores
the other. A pair's score is the lower of its two orders; H2O's is on the raw scale
(sigmoid(0.8 * logit p)), pplx's as served (no baked temperature).

    python3 ml/models/decision_models_cv.py

First, in sample: each judge alone at the threshold picked on all the pairs, and the rule p2.
Then setups: H2O alone and pplx alone (each tuned on the training half), the two-judge rule with
H2O tuned on the training pairs pplx passes (pplx >= 0.95), the rule fixed at (0.578, 0.95),
and H2O alone fixed at 0.7299 (its in-sample threshold for precision >= 0.99). Per setup: mean
test precision, its 5th percentile, mean recall, and wrong merges per test half (mean, max,
share of splits with 3 or more). Seeded with 20261127, so the output is exact; the script
exits non-zero unless it matches the doc's table.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY = ROOT.parent / "makhzan-config/labels/answer-key-v2.jsonl"
H2O_Q4 = ROOT / "ml/out/models-compare/h2o-q4-K2.jsonl"
PPLX_Q4 = ROOT / "ml/out/gguf-pplx/Q4_K_S.jsonl"
H2O_T = 0.8
SPLITS = 500
SEED = 20261127
PRECISION = 0.99
# docs/ai/decision-models.md section 6: mean precision, its 5th percentile, mean recall, wrong
# merges per half (mean, max, % of splits with 3 or more).
EXPECTED = {
    "H2O alone (tuned)": (0.9856, 0.9627, 0.624, 1.90, 11, 31),
    "pplx alone (tuned)": (0.9851, 0.9590, 0.622, 1.94, 12, 31),
    "rule, H2O tuned & pplx >= 0.95": (0.9914, 0.9825, 0.591, 1.01, 2, 0),
    "rule fixed 0.578 / 0.95": (0.9911, 0.9818, 0.589, 1.01, 2, 0),
    "H2O alone fixed >= 0.7299": (0.9918, 0.9828, 0.618, 0.99, 2, 0),
}
# In sample (threshold, merges, correct, wrong pair ids); p2 is fixed at (0.578, 0.95).
EXPECTED_IN_SAMPLE = {
    "H2O alone": (0.7299, 241, 239, ["E0098", "E0778"]),
    "pplx alone": (0.9482, 243, 241, ["E0098", "E0639"]),
    "rule p2": (None, 229, 227, ["E0098", "E0639"]),
}


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

    # In sample: each judge's threshold picked on all the pairs it is then scored on.
    bad = []
    for name, score in (("H2O alone", h2o), ("pplx alone", pplx), ("rule p2", None)):
        if score is None:
            t, merged = None, [p for p in pids if h2o[p] >= 0.578 and pplx[p] >= 0.95]
        else:
            t = pick(pids, score, same)
            merged = [p for p in pids if score[p] >= t]
        wrong = [p for p in merged if not same[p]]
        got = (None if t is None else round(t, 4), len(merged), len(merged) - len(wrong), wrong)
        at = "" if t is None else f" >= {t:.4f}"
        print(
            f"in sample, {name}{at}: {got[1]} merges / {got[2]} correct / {len(wrong)} wrong {wrong}"
        )
        if got != EXPECTED_IN_SAMPLE[name]:
            bad.append(f"in sample {name}: expected {EXPECTED_IN_SAMPLE[name]}, got {got}")

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
    rows = {}
    for s in setups:
        r = results[s]
        pr = sorted(r["precision"])
        w = r["wrong"]
        rows[s] = (
            round(sum(pr) / len(pr), 4),
            round(pr[len(pr) // 20], 4),
            round(sum(r["recall"]) / len(r["recall"]), 3),
            round(sum(w) / len(w), 2),
            max(w),
            round(100 * sum(x >= 3 for x in w) / len(w)),
        )
    print(f"{SPLITS} splits, seed {SEED}")
    print(f"{'setup':34} precision [p05]   recall  wrong/half mean, max, share >= 3")
    for s, (prec, p05, rec, wmean, wmax, w3) in rows.items():
        print(f"{s:34} {prec:.4f} [{p05:.4f}]  {rec:.3f}   {wmean:.2f}, {wmax}, {w3}%")
    bad += [f"{s}: expected {EXPECTED[s]}, got {rows[s]}" for s in setups if rows[s] != EXPECTED[s]]
    print("\n".join(bad) if bad else "check: every documented number reproduced")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
