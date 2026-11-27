"""The H2O floor for the group check, set against Kev's 0.05 (section 9, D25).

The group check blocks an AI join when any two members score below a floor. On every labelled
Phase E pair ("same" or "not", vetoed ones included, since the check sees members whatever the
vetoes said), scored in both orders by Kev BF16 and H2O Q4_K_M: how many "not same" pairs each
floor blocks, and how many "same" pairs it blocks wrongly. A pair's score is the lower of its
orders, raw scale (H2O's T = 0.8 undone).

    python3 ml/models/decision_models_floor.py    # exits non-zero unless the doc's table holds
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_models as cm  # noqa: E402

H2O_Q4 = cm.OUT / "h2o-q4-K2.jsonl"
FLOORS = (("Kev", 0.05), ("H2O", 0.185), ("H2O", 0.19), ("H2O", 0.195))
# The doc's table: ("not same" blocked, "same" blocked) per floor, of 882 pairs, 463 "not same".
EXPECTED = {
    ("Kev", 0.05): (358, 16),
    ("H2O", 0.185): (351, 11),
    ("H2O", 0.19): (358, 12),
    ("H2O", 0.195): (365, 16),
}
EXPECTED_PAIRS = (882, 463)


def main() -> None:
    key = {r["pair_id"]: r for r in map(json.loads, cm.KEY.open())}
    runs = {"Kev": cm.load(cm.KEV), "H2O": cm.load(H2O_Q4, 0.8)}
    pairs = [
        p
        for p, k in key.items()
        if k["label"] in ("same", "not") and all(cm.pmin(d, p) is not None for d in runs.values())
    ]
    n_not = sum(key[p]["label"] == "not" for p in pairs)
    print(f"{len(pairs)} labelled pairs, {n_not} not same")
    print("floor            not same blocked   same blocked")
    bad = [] if (len(pairs), n_not) == EXPECTED_PAIRS else [f"pairs: expected {EXPECTED_PAIRS}"]
    for model, floor in FLOORS:
        below = [p for p in pairs if cm.pmin(runs[model], p) < floor]
        nots = sum(key[p]["label"] == "not" for p in below)
        print(f"{model} < {floor:<6}     {nots:>4} / {n_not}        {len(below) - nots:>4}")
        if (nots, len(below) - nots) != EXPECTED[(model, floor)]:
            bad.append(f"{model} < {floor}: expected {EXPECTED[(model, floor)]}")
    print("\n".join(bad) if bad else "check: every documented number reproduced")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
