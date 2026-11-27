"""Intern-Decision string state vs structured state, and H2O Q4, with the pplx Q4 rule.

docs/ai/decision-models.md, sections 4 and 8. Uses compare_models.py's own definitions (pair
score = the lower of the two orders; Phase E pairs past the vetoes, "unsure" left out) and
writes ml/out/models-compare/intern-struct-analysis.json; analysis.json is not touched.

    python3 ml/models/intern_struct_analyse.py

For each run: AUC, average precision, the threshold matching Kev's and pplx's precision, the
production rule (first judge >= that threshold and pplx >= 0.95, with pplx Q4 and with pplx
BF16; H2O also at 0.578), the mean |ab - ba|, and warm speed. A missing run file is skipped.
Exits non-zero unless the numbers the doc states are reproduced.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import compare_models as cm  # noqa: E402

OUT = ROOT / "ml/out/models-compare"
PPLX_Q4 = ROOT / "ml/out/gguf-pplx/Q4_K_S.jsonl"
RUNS = {
    "intern-K2 (string)": (OUT / "intern-K2.jsonl", 1.0),
    "intern-K2c (string)": (OUT / "intern-K2c.jsonl", 1.0),
    "intern-K2 (structured)": (OUT / "intern-struct-K2.jsonl", 1.0),
    "intern-K2c (structured)": (OUT / "intern-struct-K2c.jsonl", 1.0),
    "h2o-q4-K2": (OUT / "h2o-q4-K2.jsonl", 0.8),
}


def rule(d, pplx_q4, key, pairs, threshold):
    merged = [p for p in pairs if cm.pmin(d, p) >= threshold and cm.pmin(pplx_q4, p) >= 0.95]
    return {
        "merges": len(merged),
        "correct": sum(key[p]["label"] == "same" for p in merged),
        "wrong": [p for p in merged if key[p]["label"] == "not"],
    }


def main() -> None:
    key = {r["pair_id"]: r for r in map(json.loads, cm.KEY.open())}
    kev, pplx, pplx_q4 = cm.load(cm.KEV), cm.load(cm.PPLX), cm.load(PPLX_Q4)
    base = [
        p
        for p, k in key.items()
        if not any(k["veto"].values())
        and k["label"] != "unsure"
        and cm.pmin(kev, p) is not None
        and cm.pmin(pplx, p) is not None
    ]

    def labelled(d, pairs):
        return [(cm.pmin(d, p), key[p]["label"] == "same") for p in pairs]

    kev_prec = cm.pr_at(labelled(kev, base), 0.8)[0]
    pplx_prec = cm.pr_at(labelled(pplx, base), 0.95)[0]
    rep = {
        "pairs_base": len(base),
        "kev_precision": round(kev_prec, 4),
        "pplx_precision": round(pplx_prec, 4),
        "models": {},
    }
    for name, (f, t) in RUNS.items():
        if not f.exists():
            continue
        d = cm.load(f, t)
        rows = [json.loads(line) for line in f.open()]
        ps = [p for p in base if cm.pmin(d, p) is not None and cm.pmin(pplx_q4, p) is not None]
        sc = labelled(d, ps)
        pos = [s for s, y in sc if y]
        neg = [s for s, y in sc if not y]
        m = {
            "pairs": len(ps),
            "auc": round(cm.auc(pos, neg), 4),
            "ap": round(cm.avg_precision(sc), 4),
        }
        for label, target in (("kev_precision", kev_prec), ("pplx_precision", pplx_prec)):
            mt = cm.matched_threshold(sc, target)
            m[f"at_{label}"] = (
                None
                if mt is None
                else {
                    "threshold": round(mt[0], 4),
                    "precision": round(mt[1], 4),
                    "recall": round(mt[2], 4),
                }
            )
        if m["at_kev_precision"]:
            th = m["at_kev_precision"]["threshold"]
            m["rule_first_judge_pplxQ4"] = {"threshold": th, **rule(d, pplx_q4, key, ps, th)}
            m["rule_first_judge_pplxBF16"] = {"threshold": th, **rule(d, pplx, key, ps, th)}
        if name.startswith("h2o"):
            m["rule_at_0.578"] = rule(d, pplx_q4, key, ps, 0.578)
        diffs = [abs(d[(p, "ab")] - d[(p, "ba")]) for p in ps]
        m["order_mean_abs_diff"] = round(sum(diffs) / len(diffs), 4)
        ok = [r for r in rows if r.get("score") is not None]
        warm = ok[5:]
        s = sum(r["seconds"] for r in warm)
        tk = sum((r.get("usage") or {}).get("input_tokens", 0) for r in warm)
        m["requests"] = len(rows)
        m["errors"] = len(rows) - len(ok)
        m["req_per_s_warm"] = round(len(warm) / s, 3) if s else None
        m["mean_tokens"] = round(tk / len(warm)) if warm else None
        rep["models"][name] = m
    (OUT / "intern-struct-analysis.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    check_expected(rep)


# What docs/ai/decision-models.md states: (auc, ap, (threshold, recall) at Kev's precision,
# (threshold, recall) at pplx's precision, the rule replacing Kev with pplx Q4 and with pplx BF16
# as (merges, correct, wrong pair ids), mean |ab - ba|).
EXPECTED = {
    "intern-K2 (string)": (0.932, 0.9522, (0.852, 0.6104), (0.9579, 0.3688),
                           (190, 189, ["E0098"]), (184, 183, ["E0138"]), 0.1188),
    "intern-K2c (string)": (0.9332, 0.9514, (0.9526, 0.5818), (0.9914, 0.0909),
                            (181, 180, ["E0098"]), (178, 178, []), 0.1048),
    "intern-K2 (structured)": (0.9385, 0.9579, (0.7311, 0.7195), (0.9707, 0.2909),
                               (213, 212, ["E0098"]), (204, 203, ["E0138"]), 0.1227),
    "intern-K2c (structured)": (0.9426, 0.96, (0.8808, 0.7558), (0.989, 0.2182),
                                (220, 218, ["E0098", "E0639"]), (211, 209, ["E0138", "E0639"]),
                                0.108),
    "h2o-q4-K2": (0.9514, 0.9706, (0.5968, 0.761), (0.7299, 0.6208),
                  (228, 226, ["E0098", "E0639"]), None, 0.0743),
}  # fmt: skip
EXPECTED_H2O_AT_0578 = (229, 227, ["E0098", "E0639"])


def check_expected(rep: dict) -> None:
    """Exit non-zero unless the analysis matches the numbers the doc states."""

    def mcw(r):
        return None if r is None else (r["merges"], r["correct"], r["wrong"])

    def tr(r):
        return None if r is None else (r["threshold"], r["recall"])

    bad = []
    for name, want in EXPECTED.items():
        m = rep["models"].get(name)
        got = m and (
            m["auc"],
            m["ap"],
            tr(m["at_kev_precision"]),
            tr(m["at_pplx_precision"]),
            mcw(m.get("rule_first_judge_pplxQ4")),
            mcw(m.get("rule_first_judge_pplxBF16")),
            m["order_mean_abs_diff"],
        )
        if want[5] is None and got:
            got = (*got[:5], None, got[6])  # the doc gives no BF16 rule for H2O Q4 here
        if got != want:
            bad.append(f"{name}: expected {want}, got {got}")
    h2o = rep["models"].get("h2o-q4-K2", {})
    if mcw(h2o.get("rule_at_0.578")) != EXPECTED_H2O_AT_0578:
        bad.append(f"h2o-q4-K2 at 0.578: expected {EXPECTED_H2O_AT_0578}")
    print("\n".join(bad) if bad else "check: every documented number reproduced")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
