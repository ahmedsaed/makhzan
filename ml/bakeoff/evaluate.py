"""Pair-judging metrics: the validation grid, the frozen choice, and the one test evaluation.

    python3 ml/bakeoff/evaluate.py validation --pairs <private>/pairs.jsonl --out ml/out/bakeoff
    python3 ml/bakeoff/evaluate.py test --pairs <private>/pairs.jsonl --out ml/out/bakeoff \
        --owner <private>/owner-labels-final.json

`validation` reads every <out>/scores/<service>/<variant>.validation.json and <out>/rules.json
and writes <out>/validation.json: for every variant, average precision, the in-sample best-F1
threshold with its precision/recall/F1, the 5-fold cross-validated F1 (each fold judged at the
best-F1 threshold of the other four), the threshold where precision first reaches 0.98, all
with 95% intervals; every service's selected variant (rule below); and <out>/frozen.json, the
finalists with their thresholds. Selection never reads test scores.

**Selection rule (fixed before scoring).** Per service, the variant with the highest
cross-validated F1 leads. Every variant whose paired-bootstrap 95% interval of
(its CV F1 - the leader's) contains 0 is "within noise", and the simplest of those is chosen:
fewer few-shot examples first, then a lower context rung, then a shorter instruction.

A pair's score is the minimum of its two orders. Same/not_same: same = 1; different and
variant = 0; unsure excluded. Precision bounds: Clopper-Pearson two-sided 95% (exact,
conservative; the plan's gate) and Wilson 95%.

`test` reads only the finalists in frozen.json, scores them on test at their frozen thresholds
and writes <out>/test.json, overall, per department, cross-shop only, and on the owner-
adjudicated test pairs. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    QWEN_INSTRUCTIONS,
    average_precision,
    best_f1_threshold,
    bootstrap_indices,
    clopper_pearson_lower,
    confusion,
    cv_predictions,
    f1_of,
    folds,
    load_pairs,
    percentile_ci,
    precision_threshold,
    prf,
    target,
    wilson_lower,
)

RUNG_FIELD = {"L2": "specs", "L3": "description"}


def score_of(entry: list[float]) -> float:
    return min(entry)


def point(scores, ys, t) -> dict:
    tp, fp, fn, tn = confusion(scores, ys, t)
    p, r, f = prf(tp, fp, fn)
    return {
        "threshold": t if math.isfinite(t) else None,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": p, "recall": r, "f1": f,
        "precision_cp_lower": clopper_pearson_lower(tp, tp + fp),
        "precision_wilson_lower": wilson_lower(tp, tp + fp),
        "recall_wilson_lower": wilson_lower(tp, tp + fn),
    }  # fmt: skip


def by_domain(rows, scores, ys, t) -> dict:
    out = {}
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[r["domain"]].append(i)
    for d, idx in sorted(groups.items()):
        sub_s, sub_y = [scores[i] for i in idx], [ys[i] for i in idx]
        out[d] = {"n": len(idx), "positives": sum(sub_y), **point(sub_s, sub_y, t)}
    return out


def decided(pairs: list[dict], labels: dict[str, str] | None = None) -> list[dict]:
    out = []
    for p in pairs:
        y = target((labels or {}).get(p["pair_id"], p["label"]) if labels else p["label"])
        if y is not None:
            out.append({**p, "y": y})
    return out


def simplicity(variant: str) -> tuple:
    iid, rung, shots = variant.split("-")
    length = len(QWEN_INSTRUCTIONS.get(iid, ""))
    return (int(shots), rung, length)


def validation(args) -> None:
    pairs = [p for p in load_pairs(args.pairs) if p["split"] == "validation"]
    fold_of = folds(pairs)
    rows = decided(pairs)
    ys = [r["y"] for r in rows]
    fids = [fold_of[r["pair_id"]] for r in rows]
    boots = bootstrap_indices(len(rows), args.reps)
    coverage = have_fields(args)
    rules = json.loads((args.out / "rules.json").read_text())["pairs"]
    veto = {pid: v["any_veto"] for pid, v in rules.items()}

    result: dict = {"n": len(rows), "positives": sum(ys), "rules": {}, "services": {}}
    for name in ("rules_pair", "rules_full", "today_stored"):
        s = [float(rules[r["pair_id"]][name]) for r in rows]
        result["rules"][name] = {**point(s, ys, 0.5), "by_domain": by_domain(rows, s, ys, 0.5)}

    for d in sorted((args.out / "scores").iterdir()):
        service = d.name
        variants = {}
        preds = {}
        for f in sorted(d.glob("*.validation.json")):
            variant = f.name.split(".validation")[0]
            data = json.loads(f.read_text())
            s = [score_of(data["scores"][r["pair_id"]]) for r in rows]
            variants[variant] = summarise_variant(rows, s, ys, fids, boots, coverage, variant)
            variants[variant]["pairs_per_s"] = data["meta"]["pairs_per_s"]
            preds[variant] = (s, cv_predictions(s, ys, fids))
        if not variants:
            continue
        leader = max(variants, key=lambda v: variants[v]["cv_f1"])
        lp = preds[leader][1]
        for v, (_, pred) in preds.items():
            deltas = [
                f1_of([pred[i] for i in b], [ys[i] for i in b])
                - f1_of([lp[i] for i in b], [ys[i] for i in b])
                for b in boots
            ]
            variants[v]["cv_f1_minus_leader"] = variants[v]["cv_f1"] - variants[leader]["cv_f1"]
            variants[v]["cv_f1_minus_leader_ci"] = percentile_ci(deltas)
            lo, hi = variants[v]["cv_f1_minus_leader_ci"]
            variants[v]["within_noise_of_leader"] = lo <= 0 <= hi or v == leader
        tied = [v for v in variants if variants[v]["within_noise_of_leader"]]
        chosen = min(tied, key=simplicity)
        result["services"][service] = {"leader": leader, "chosen": chosen, "variants": variants}
        s = preds[chosen][0]
        result["services"][service]["chosen_by_domain"] = by_domain(
            rows, s, ys, variants[chosen]["best_f1"]["threshold"] or math.inf
        )

    # The one combination: today's vetoes on top of the best judge (by chosen CV F1).
    judges = result["services"]
    best = max(judges, key=lambda sv: judges[sv]["variants"][judges[sv]["chosen"]]["cv_f1"])
    variant = judges[best]["chosen"]
    data = json.loads((args.out / "scores" / best / f"{variant}.validation.json").read_text())
    s = [0.0 if veto[r["pair_id"]] else score_of(data["scores"][r["pair_id"]]) for r in rows]
    combo = summarise_variant(rows, s, ys, fids, boots, coverage, variant)
    combo["judge"] = f"{best}:{variant}"
    combo["by_domain"] = by_domain(rows, s, ys, combo["best_f1"]["threshold"] or math.inf)
    result["combination"] = combo

    (args.out / "validation.json").write_text(json.dumps(result, indent=1))
    frozen = {
        "judges": {
            sv: {
                "variant": j["chosen"],
                "threshold_best_f1": j["variants"][j["chosen"]]["best_f1"]["threshold"],
                "threshold_p98": j["variants"][j["chosen"]]["p98"]["threshold"],
            }
            for sv, j in judges.items()
        },
        "combination": {
            "service": best,
            "variant": variant,
            "veto": "any of same_shop, values, form, price (rules.json any_veto)",
            "threshold_best_f1": combo["best_f1"]["threshold"],
            "threshold_p98": combo["p98"]["threshold"],
        },
    }
    (args.out / "frozen.json").write_text(json.dumps(frozen, indent=1))
    print_validation(result)


def have_fields(args) -> dict:
    """pair id -> {"specs": both sides have a spec table, "description": both have one}."""
    path = args.out / "pair_fields.json"
    return json.loads(path.read_text()) if path.exists() else {}


def summarise_variant(rows, s, ys, fids, boots, coverage, variant) -> dict:
    t = best_f1_threshold(s, ys)
    t98 = precision_threshold(s, ys, 0.98)
    pred = cv_predictions(s, ys, fids)
    out = {
        "ap": average_precision(s, ys),
        "ap_ci": percentile_ci(
            [average_precision([s[i] for i in b], [ys[i] for i in b]) for b in boots]
        ),
        "best_f1": point(s, ys, t),
        "best_f1_ci": percentile_ci(
            [f1_of([int(s[i] >= t) for i in b], [ys[i] for i in b]) for b in boots]
        ),  # fmt: skip
        "cv_f1": f1_of(pred, ys),
        "cv_f1_ci": percentile_ci(
            [f1_of([pred[i] for i in b], [ys[i] for i in b]) for b in boots]
        ),  # fmt: skip
        "p98": point(s, ys, t98),
    }
    cross = [i for i, r in enumerate(rows) if not r["same_shop"]]
    cs, cy = [s[i] for i in cross], [ys[i] for i in cross]
    out["cross_shop"] = {"n": len(cross), "ap": average_precision(cs, cy),
                         "best_f1": point(cs, cy, best_f1_threshold(cs, cy))}  # fmt: skip
    for field in ("specs", "description"):
        idx = [i for i, r in enumerate(rows) if coverage.get(r["pair_id"], {}).get(field)]
        if idx:
            fs, fy = [s[i] for i in idx], [ys[i] for i in idx]
            out[f"both_have_{field}"] = {
                "n": len(idx),
                "positives": sum(fy),
                "ap": average_precision(fs, fy),
                "f1_at_full_threshold": point(fs, fy, t)["f1"],
            }
    return out


def print_validation(result: dict) -> None:
    print(f"validation decided pairs {result['n']} (same {result['positives']})")
    for name, r in result["rules"].items():
        print(f"  {name:13s} P {r['precision']:.3f} R {r['recall']:.3f} F1 {r['f1']:.3f}")
    for sv, j in result["services"].items():
        print(f"{sv}: leader {j['leader']} chosen {j['chosen']}")
        for v, m in sorted(j["variants"].items()):
            bf = m["best_f1"]
            print(
                f"  {v:9s} AP {m['ap']:.3f} [{m['ap_ci'][0]:.3f},{m['ap_ci'][1]:.3f}] "
                f"F1 {bf['f1']:.3f} CV-F1 {m['cv_f1']:.3f} [{m['cv_f1_ci'][0]:.3f},"
                f"{m['cv_f1_ci'][1]:.3f}] d {m['cv_f1_minus_leader']:+.3f} "
                f"R@P98 {m['p98']['recall']:.3f} ({m['p98']['tp']}/{m['p98']['fp']}) "
                f"{m['pairs_per_s']:.1f} p/s"
                + (
                    f" desc-sub AP {m['both_have_description']['ap']:.3f}"
                    if "both_have_description" in m
                    else ""
                )  # fmt: skip
            )
    c = result["combination"]
    print(f"combination {c['judge']}+veto: AP {c['ap']:.3f} F1 {c['best_f1']['f1']:.3f} "
          f"CV-F1 {c['cv_f1']:.3f} R@P98 {c['p98']['recall']:.3f}")  # fmt: skip


def test(args) -> None:
    allp = load_pairs(args.pairs)
    pairs = [p for p in allp if p["split"] == "test"]
    frozen = json.loads((args.out / "frozen.json").read_text())
    rules = json.loads((args.out / "rules.json").read_text())["pairs"]
    owner = json.loads(args.owner.read_text()) if args.owner else {}
    owner_test = {k: v for k, v in owner.items() if any(p["pair_id"] == k for p in pairs)}
    sets = {
        "agent_labels": decided(pairs),
        "owner_adjudicated": decided([p for p in pairs if p["pair_id"] in owner_test], owner),
    }
    out: dict = {}
    for set_name, rows in sets.items():
        ys = [r["y"] for r in rows]
        res: dict = {"n": len(rows), "positives": sum(ys), "rules": {}, "judges": {}}
        for name in ("rules_pair", "rules_full", "today_stored"):
            s = [float(rules[r["pair_id"]][name]) for r in rows]
            res["rules"][name] = evaluate_at(rows, s, ys, {"rule": 0.5})
        for sv, cfg in frozen["judges"].items():
            s = load_scores(args.out, sv, cfg["variant"], rows)
            res["judges"][f"{sv}:{cfg['variant']}"] = evaluate_at(rows, s, ys, thresholds(cfg))
        c = frozen["combination"]
        s = load_scores(args.out, c["service"], c["variant"], rows)
        s = [0.0 if rules[r["pair_id"]]["any_veto"] else x for r, x in zip(rows, s, strict=True)]
        res["judges"][f"{c['service']}:{c['variant']}+veto"] = evaluate_at(
            rows, s, ys, thresholds(c)
        )
        out[set_name] = res
    (args.out / "test.json").write_text(json.dumps(out, indent=1))
    for set_name, res in out.items():
        print(f"== test {set_name}: n {res['n']} same {res['positives']}")
        for group in ("rules", "judges"):
            for name, r in res[group].items():
                for tname, m in r["overall"].items():
                    if tname == "ap":
                        continue
                    print(
                        f"  {name:32s} {tname:8s} P {m['precision']:.3f} "
                        f"(CP {m['precision_cp_lower']:.3f}) R {m['recall']:.3f} "
                        f"F1 {m['f1']:.3f} tp {m['tp']} fp {m['fp']} fn {m['fn']}"
                    )


def thresholds(cfg: dict) -> dict:
    return {
        "best_f1": cfg["threshold_best_f1"] if cfg["threshold_best_f1"] is not None else math.inf,
        "p98": cfg["threshold_p98"] if cfg["threshold_p98"] is not None else math.inf,
    }


def load_scores(out: Path, service: str, variant: str, rows: list[dict]) -> list[float]:
    data = json.loads((out / "scores" / service / f"{variant}.test.json").read_text())
    return [score_of(data["scores"][r["pair_id"]]) for r in rows]


def evaluate_at(rows, s, ys, ts: dict) -> dict:
    cross = [i for i, r in enumerate(rows) if not r["same_shop"]]
    res = {"overall": {k: point(s, ys, t) for k, t in ts.items()}}
    res["overall"]["ap"] = average_precision(s, ys)
    res["cross_shop"] = {
        k: point([s[i] for i in cross], [ys[i] for i in cross], t) for k, t in ts.items()
    }
    res["by_domain"] = {k: by_domain(rows, s, ys, t) for k, t in ts.items()}
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stage", choices=["validation", "test"])
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--owner", type=Path)
    ap.add_argument("--reps", type=int, default=1000)
    args = ap.parse_args()
    (validation if args.stage == "validation" else test)(args)


if __name__ == "__main__":
    main()
