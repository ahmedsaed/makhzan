"""Offline analysis of the prompt grid's scores: two-judge combinations and a two-stage cascade.

No model runs. Reads the per-pair scores the grid already wrote and the answer key, and scores
every rule with the shared metric (ml/improve/metric.py: population weights, one-sided 95%
Clopper-Pearson bound). Each pair's score is the lower of its two orders.

    python3 ml/models/combos.py --grid ml/out/prompt-grid --improve ml/out/improve \
        --key ml/out/labels/answer-key-v2.jsonl --models ml/out/models \
        --population ml/out/gain/kev_open.json --out ml/out/prompt-grid/analysis

A) Two judges: Kev (four full-prompt configs, plus title-only for reference) at a threshold,
   AND a second judge (pplx, Qwen, or none) at a threshold, behind today's vetoes and without.
   The Pareto front on (weighted precision, weighted recall); a 2-fold stratified held-out check
   of the front's top points, thresholds re-derived on one half.
B) Two stages: title-only Kev first; < lo rejected, >= hi accepted, the band [lo, hi) goes to a
   full-prompt rule. The share reaching stage 2 is read from the 89,738 unvetoed shortlist
   pairs' title-only Kev scores (the real population), not from the sample.

Standard library only. Outputs results.json and report.md under --out.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "improve"))

from metric import cell_sizes, evaluate  # noqa: E402

SEED = 20261116  # the grid's fold seed (prompt_grid.py)
KEV = ["K1-150", "K1-full", "K2-150", "K2-full"]
KEV_T = [0.8, 0.85, 0.9, 0.95]
SECOND = {f"pplx-{c}": [0.9, 0.95, 0.98, 0.99] for c in KEV}
SECOND |= {"qwen-chat-150": [0.5, 0.7, 0.9], "qwen-chat-full": [0.5, 0.7, 0.9]}
SECOND |= {"pplx-title": [0.9, 0.95, 0.98, 0.99]}  # reference: title-only pplx
LO = [0.01, 0.05, 0.1, 0.2]
HI = [0.95, 0.99, 1.01]


def pair_min(v) -> float:
    """The lower of a pair's scores; a pair with no score in either order is never accepted."""
    return min((x for x in v if x is not None), default=0.0)


def mins(d: dict) -> dict[str, float]:
    return {k: pair_min(v) for k, v in d.items()}


def load(args) -> tuple[list[dict], dict[str, dict[str, float]], dict[str, str]]:
    cells = {}
    for line in (args.improve / "pairs.jsonl").open():
        r = json.loads(line)
        cells[r["pair_id"]] = r["cell"]
    y = {"same": 1, "not": 0}
    pairs = []
    for line in args.key.open():
        p = json.loads(line)
        p["cell"] = cells[p["pair_id"]]
        p["y"] = y.get(p["label"])
        p["kt"] = pair_min((p["kev_ab"], p["kev_ba"]))
        pairs.append(p)
    s = {"kev-title": {p["pair_id"]: p["kt"] for p in pairs}}
    s["pplx-title"] = mins(json.loads((args.models / "pplx.json").read_text()))
    for f in sorted((args.grid / "scores").glob("*.json")):
        s[f.stem] = mins(json.loads(f.read_text()))
    listings = json.loads((args.grid / "listings.json").read_text())
    title = {k: v["title"] for k, v in listings.items()}
    return pairs, s, title


class Rules:
    def __init__(self, pairs, s, title):
        self.pairs, self.s, self.title = pairs, s, title
        size, dec = cell_sizes(pairs)
        self.tot_same = sum(size[p["cell"]] / dec[p["cell"]] for p in pairs if p["y"] == 1)

    def accept(self, kev, tk, second, ts, veto, lo=None, hi=None):
        k = self.s[f"kev-{kev}"]
        q = self.s[second] if second else None

        def acc(p):
            pid = p["pair_id"]
            if veto and p["vetoed"]:
                return False
            if lo is not None:
                if p["kt"] < lo:
                    return False
                if p["kt"] >= hi:
                    return True
            return k[pid] >= tk and (q is None or q[pid] >= ts)

        return acc

    def summary(self, acc, subset=None, with_errors=False) -> dict:
        r = evaluate(self.pairs, acc, subset)
        out = {
            "used": r["used"],
            "same": r["same"],
            "errors": r["errors"],
            "precision_w": round(r["precision_weighted"], 4) if r["used"] else None,
            "bound": round(r["bound"], 4) if r["used"] else None,
            "recall_w": round(r["est_matches"] / self.tot_same, 4),
            "est_matches": r["est_matches"],
            "est_accepted": r["est_accepted"],
        }
        if with_errors:
            out["error_pairs"] = [
                {"pair_id": p["pair_id"], "cell": p["cell"], "soft": p["soft"],
                 "a": self.title.get(p["listing_a"]), "b": self.title.get(p["listing_b"])}
                for p in self.pairs
                if p["y"] == 0 and acc(p) and (subset is None or p["pair_id"] in subset)
            ]  # fmt: skip
        return out


def grid():
    kevs = KEV + ["title"]
    for kev in kevs:
        for tk in KEV_T:
            yield kev, tk, None, None
            for second, ts_all in SECOND.items():
                for ts in ts_all:
                    yield kev, tk, second, ts


def name(kev, tk, second, ts) -> str:
    return f"kev-{kev}>={tk}" + (f" & {second}>={ts}" if second else "")


def pareto(rows: list[dict]) -> list[dict]:
    def dom(a, b):  # a dominates b
        return (a["precision_w"] >= b["precision_w"] and a["recall_w"] >= b["recall_w"]
                and (a["precision_w"] > b["precision_w"] or a["recall_w"] > b["recall_w"]))  # fmt: skip

    ok = [r for r in rows if r["precision_w"] is not None]
    front = [r for r in ok if not any(dom(o, r) for o in ok)]
    # one representative per (precision, recall) point: the cheapest-looking (fewest judges)
    seen = {}
    for r in sorted(front, key=lambda r: (r["second"] is not None, r["name"])):
        seen.setdefault((r["precision_w"], r["recall_w"]), r)
    return sorted(seen.values(), key=lambda r: -r["precision_w"])


def folds(pairs) -> dict[str, int]:
    by = defaultdict(list)
    for p in pairs:
        by[(p["cell"], p["label"])].append(p["pair_id"])
    rng = random.Random(SEED)
    fold = {}
    for k in sorted(by):
        ids = sorted(by[k])
        rng.shuffle(ids)
        for i, pid in enumerate(ids):
            fold[pid] = i % 2
    return fold


def heldout(R: Rules, point: dict, veto: bool, fold: dict[str, int]) -> list[dict]:
    """Re-derive both thresholds on one half: the largest weighted recall whose tune-half
    weighted precision reaches the point's own in-sample precision; score the other half."""
    kev, second = point["kev"], point["second"]
    target = point["precision_w"]
    out = []
    for f in (0, 1):
        tune = {pid for pid, x in fold.items() if x == f}
        test = {pid for pid, x in fold.items() if x != f}
        best = None
        for tk in KEV_T:
            for ts in SECOND.get(second, [None]) if second else [None]:
                r = R.summary(R.accept(kev, tk, second, ts, veto), tune)
                if r["precision_w"] is None or r["precision_w"] < target:
                    continue
                key = (r["recall_w"], tk, ts or 0)
                if best is None or key > best[0]:
                    best = (key, tk, ts, r)
        if best is None:
            out.append({"tuned_on_fold": f, "threshold": None, "note": "no threshold met target"})
            continue
        _, tk, ts, r_tune = best
        r_test = R.summary(R.accept(kev, tk, second, ts, veto), test, with_errors=True)
        out.append({"tuned_on_fold": f, "kev_t": tk, "second_t": ts,
                    "tune": {k: r_tune[k] for k in ("used", "errors", "precision_w", "recall_w")},
                    "test": r_test})  # fmt: skip
    return out


def two_stage(R: Rules, pop: list[float], stage2: dict) -> list[dict]:
    n = len(pop)
    rows = []
    for lo in LO:
        for hi in HI:
            band = sum(lo <= k < hi for k in pop)
            auto = sum(k >= hi for k in pop)
            acc = R.accept(stage2["kev"], stage2["kev_t"], stage2["second"], stage2["second_t"],
                           True, lo, hi)  # fmt: skip
            r = R.summary(acc, with_errors=True)
            # matches stage 1 throws away: same pairs below lo that the stage-2 rule accepts
            full = R.accept(stage2["kev"], stage2["kev_t"], stage2["second"], stage2["second_t"],
                            True)  # fmt: skip
            lost = R.summary(lambda p, full=full, lo=lo: full(p) and p["kt"] < lo)
            below = R.summary(lambda p, lo=lo: not p["vetoed"] and p["kt"] < lo and p["y"] == 1)
            auto_r = R.summary(lambda p, hi=hi: not p["vetoed"] and p["kt"] >= hi)
            rows.append({"lo": lo, "hi": hi, "share_stage2": round(band / n, 4),
                         "pairs_stage2_of_89738": band, "auto_accepted_pop": auto,
                         "auto_accept_part": {k: auto_r[k] for k in
                                              ("used", "errors", "precision_w", "bound",
                                               "est_accepted")},
                         "final": {k: r[k] for k in ("used", "errors", "precision_w", "bound",
                                                     "recall_w", "est_matches")},
                         "final_error_pairs": r["error_pairs"],
                         "lost_matches_rule_would_accept": lost["est_matches"],
                         "lost_labelled_pairs": lost["same"],
                         "matches_below_lo_any": below["est_matches"]})  # fmt: skip
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for a in ("grid", "improve", "key", "models", "population", "out"):
        ap.add_argument(f"--{a}", type=Path, required=True)
    args = ap.parse_args()
    pairs, s, title = load(args)
    R = Rules(pairs, s, title)
    res: dict = {"total_matches_est": round(R.tot_same), "modes": {}}
    fold = folds(pairs)
    for mode, veto in (("behind_vetoes", True), ("no_vetoes", False)):
        rows = []
        for kev, tk, second, ts in grid():
            r = R.summary(R.accept(kev, tk, second, ts, veto), with_errors=True)
            rows.append({"name": name(kev, tk, second, ts), "kev": kev, "kev_t": tk,
                         "second": second, "second_t": ts, **r})  # fmt: skip
        front = pareto(rows)
        # held-out: every front point at >= 0.95 in-sample precision (the top of the front)
        top = [r for r in front if r["precision_w"] >= 0.95]
        for r in top:
            r["heldout"] = heldout(R, r, veto, fold)
        res["modes"][mode] = {"front": front, "heldout_names": [r["name"] for r in top],
                              "all": [{k: v for k, v in r.items() if k != "error_pairs"}
                                      for r in rows]}  # fmt: skip
    # stage 2 = the front's best >=0.95 point and its highest-precision point (behind vetoes)
    front = res["modes"]["behind_vetoes"]["front"]
    picks = {"max_matches_p95": max((r for r in front if r["precision_w"] >= 0.95),
                                    key=lambda r: r["recall_w"]),
             "safest": max(front, key=lambda r: (r["precision_w"], r["recall_w"]))}  # fmt: skip
    pop = [x[2] for x in json.loads(args.population.read_text())]
    res["population_n"] = len(pop)
    res["two_stage"] = {k: {"stage2": v["name"], "rows": two_stage(R, pop, v)}
                        for k, v in picks.items()}  # fmt: skip
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    (args.out / "report.md").write_text(report(res))
    print(report(res))


def report(res: dict) -> str:
    lines = [f"Estimated matches in the shortlist population: {res['total_matches_est']}", ""]
    for mode, m in res["modes"].items():
        lines += [f"## Pareto front, {mode}", "",
                  "| rule | acc | err | P_w | CP95 | R_w | est. matches |", "|---|---|---|---|---|---|---|"]  # fmt: skip
        for r in m["front"]:
            lines.append(f"| {r['name']} | {r['used']} | {r['errors']} | {r['precision_w']} | "
                         f"{r['bound']} | {r['recall_w']} | {r['est_matches']} |")  # fmt: skip
        lines += ["", f"### Held-out (2-fold), {mode}", "",
                  "| rule | fold | thresholds | tune P_w/err | test acc | test err | test P_w | test R_w |",
                  "|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for r in m["front"]:
            for h in r.get("heldout", []):
                if h.get("kev_t") is None:
                    lines.append(f"| {r['name']} | {h['tuned_on_fold']} | none met target |||||")
                    continue
                t, u = h["test"], h["tune"]
                lines.append(f"| {r['name']} | {h['tuned_on_fold']} | {h['kev_t']}/{h['second_t']} | "
                             f"{u['precision_w']}/{u['errors']} | {t['used']} | {t['errors']} | "
                             f"{t['precision_w']} | {t['recall_w']} |")  # fmt: skip
        lines.append("")
    for k, v in res["two_stage"].items():
        lines += [f"## Two-stage, stage 2 = {v['stage2']} ({k}), behind vetoes", "",
                  "| lo | hi | share to stage 2 | auto-accept P_w (err) | final P_w | CP95 | "
                  "R_w | est. matches | lost (rule would accept) |",
                  "|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for r in v["rows"]:
            a = r["auto_accept_part"]
            aa = f"{a['precision_w']} ({a['errors']})" if r["hi"] < 1 else "-"
            f = r["final"]
            lines.append(f"| {r['lo']} | {r['hi']} | {r['share_stage2']} | {aa} | "
                         f"{f['precision_w']} | {f['bound']} | {f['recall_w']} | "
                         f"{f['est_matches']} | {r['lost_matches_rule_would_accept']} |")  # fmt: skip
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
