"""Score the Phase E judge candidates on the one metric (ml/improve/metric.py) and write results.

    python3 ml/models/score.py --improve ml/out/improve --models ml/out/models

Reads the improvement experiments' inputs (pairs, vetoes, attribute veto, population graph,
Kev's Phase E scores; ml/improve/report.py's Data) and each candidate's scores written by
judge.py (<models>/<judge>.json = {pair_id: [ab, ba]}). A candidate's pair score is the minimum
of its two orders, as the pipeline would use it. Writes <models>/results.json.

Rules scored, each swept over THRESHOLDS (the best certified threshold, else the highest bound):

- alone: today's (old) vetoes and score >= t, for Kev (the Phase E baseline) and each candidate.
- combination: the improvement experiments' winner (old vetoes + strict attribute veto +
  complete-link) with the candidate as the judge. Complete-link needs the candidate's scores on
  the labelled listings' neighbourhood edges (edges.py, then <models>/<judge>-edges{1,2}.json);
  a candidate without them is not run here.
- two-judge: old vetoes, Kev >= t1 and candidate >= t2; and the improvement winner (with Kev's
  graph) plus candidate >= t2.

Qwen3.5-4B returns a logit margin, turned into P(yes) = sigmoid(margin / T). T is fitted by
2-fold: each pair is scored with the T fitted (unweighted log loss) on the other half.

Overfitting guard: every threshold and T here is chosen on the same ~900 pairs, so each rule also
gets a 2-fold held-out check: everything tuned (T, thresholds) is re-chosen on one half (the
largest estimate with no error on that half) and applied to the other, and the out-of-fold
decisions are scored together. `knobs` counts what each rule tunes.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "improve"))
from metric import THRESHOLDS, cell_sizes, evaluate  # noqa: E402
from report import ATTR_STRICT, LOW, Data, folds  # noqa: E402

TH = sorted(set(THRESHOLDS) | {0.9995, 0.9999})
CURVE_TH = [round(0.05 * i, 2) for i in range(1, 10)] + TH
COARSE = [round(0.5 + 0.02 * i, 2) for i in range(25)] + [0.99, 0.995, 0.999]
SECOND = [0.1, 0.2, 0.3, 0.4] + COARSE  # the second judge's threshold may sit lower: a veto
KNOWN_ERRORS = {  # Kev's known false merges in the labelled data (pair ids, all labelled not)
    "IRF250/IRFP250": "E0446", "KSD301 NC/NO": "E0337", "ATmega328/328P": "E0098",
    "LM8UU/LM8LUU": "E0444", "MPU-6500/6050": "E0711", "1N5819/SS14": "E0581",
    "HX711 module/IC": "E0362", "GP2Y0A21 range": "E0822",
}  # fmt: skip


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


def fit_temperature(z: dict[str, float], y: dict[str, int], ids) -> float:
    """T minimising the log loss of sigmoid(z / T) over `ids` (golden-section on log T)."""

    def loss(log_t: float) -> float:
        t = math.exp(log_t)
        s = 0.0
        for i in ids:
            p = min(max(sigmoid(z[i] / t), 1e-12), 1 - 1e-12)
            s -= math.log(p) if y[i] else math.log(1 - p)
        return s

    lo, hi = math.log(0.05), math.log(50)
    g = (math.sqrt(5) - 1) / 2
    for _ in range(80):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        if loss(a) < loss(b):
            hi = b
        else:
            lo = a
    return math.exp((lo + hi) / 2)


class Scores:
    """Pair scores per judge, plus fold-specific versions for anything with a fitted knob."""

    def __init__(self, data: Data, models: Path):
        self.data = data
        self.fold = folds(data)
        self.y = {p["pair_id"]: p["y"] for p in data.pairs if p["y"] is not None}
        self.s: dict[str, dict[str, float]] = {"kev": data.kev["title"]}
        self.by_fold: dict[str, dict[int, dict[str, float]]] = {}
        self.meta: dict[str, dict] = {}
        self.margin: dict[str, dict[str, float]] = {}
        for name in ("kev-rules", "pplx", "qwen35"):
            f = models / f"{name}.json"
            if not f.exists():
                continue
            raw = json.loads(f.read_text())
            self.meta[name] = json.loads((models / f"{name}.meta.json").read_text())
            if name == "qwen35":
                z = {k: min(v) for k, v in raw.items()}
                self.margin[name] = z
                temps = {}
                for k in (0, 1):  # T for fold k's pairs, fitted on the other fold
                    ids = [i for i in self.y if self.fold[i] != k]
                    temps[k] = fit_temperature(z, self.y, ids)
                self.meta[name]["temperature_by_fold"] = temps
                self.meta[name]["temperature_all"] = fit_temperature(z, self.y, list(self.y))
                self.s[name] = {i: sigmoid(z[i] / temps[self.fold[i]]) for i in z}
                # For the held-out check, a T fitted on the training half only, for every pair.
                self.by_fold[name] = {
                    k: {i: sigmoid(z[i] / temps[1 - k]) for i in z} for k in (0, 1)
                }  # train fold k -> its T is temps[1 - k] (fitted on fold != 1 - k, i.e. k)
            else:
                self.s[name] = {k: min(v) for k, v in raw.items()}

    def train_scores(self, name: str, train_fold: int) -> dict[str, float]:
        """Scores with every fitted knob fitted on `train_fold` only."""
        return self.by_fold.get(name, {}).get(train_fold, self.s[name])


# --- rules ------------------------------------------------------------------------------------
def accept_alone(data: Data, s: dict[str, float], t: float):
    return lambda p: not data.veto("old", p) and s.get(p["pair_id"], -1) >= t


def best_of(data: Data, accept_at, grid, subset=None) -> tuple[object, dict, list[dict]]:
    rows, best = [], None
    for t in grid:
        r = evaluate(data.pairs, accept_at(t), subset)
        r["threshold"] = t
        rows.append(r)
        if r["certified"] and (best is None or r["metric"] >= best["metric"]):
            best = r
    if best is None:
        best = max(rows, key=lambda r: r["bound"] if r["bound"] == r["bound"] else -1)
    return best["threshold"], best, rows


def heldout(data: Data, fold: dict[str, int], accept_for) -> dict:
    """accept_for(train_fold, knob) -> accept fn; knobs from accept_for.grid. Choose on one
    half (largest estimate with no error there, ties to the stricter knob), score the other."""
    chosen, accepts = {}, {}
    for k in (0, 1):  # k = the held-out fold
        train_fold = 1 - k
        train = {pid for pid, f in fold.items() if f == train_fold}
        pick = None
        for knob in accept_for.grid:
            r = evaluate(data.pairs, accept_for(train_fold, knob), subset=train)
            if r["errors"] == 0 and r["used"]:
                key = (r["est_matches"], knob)
                if pick is None or key > pick[0]:
                    pick = (key, knob)
        knob = pick[1] if pick else accept_for.grid[-1]
        chosen[k] = knob
        accepts[k] = accept_for(train_fold, knob)
    held = evaluate(data.pairs, lambda p: accepts[fold[p["pair_id"]]](p))
    return {"chosen": chosen, **slim(held)}


def slim(r: dict) -> dict:
    keys = ("threshold", "used", "same", "errors", "precision_raw", "precision_weighted", "bound",
            "est_matches", "certified", "metric", "cells")  # fmt: skip
    return {k: r[k] for k in keys if k in r}


def pr_curve(data: Data, accept_at) -> list[dict]:
    """Estimated population precision and recall (recall against every labelled match in the
    shortlist population, vetoed ones included) per threshold."""
    size, dec = cell_sizes(data.pairs)
    total = sum(size[p["cell"]] / dec[p["cell"]] for p in data.pairs if p["y"] == 1)
    out = []
    for t in CURVE_TH:
        r = evaluate(data.pairs, accept_at(t))
        out.append({"threshold": t, "precision": round(r["precision_weighted"], 4)
                    if r["used"] else None, "recall": round(r["est_matches"] / total, 4),
                    "used": r["used"], "errors": r["errors"], "bound": r["bound"]})  # fmt: skip
    return out


# --- complete-link with any judge's edge scores --------------------------------------------------
class Link:
    """ml/improve/report.py's complete-link guard, with edge scores from any judge. An edge is
    the population pair (x, y); `score` maps a sorted (x, y) to the judge's min-of-orders score
    (None when not scored). The veto on graph edges is today's (old), as in the improvement run."""

    def __init__(self, data: Data, score: dict[tuple[str, str], float | None]):
        g = data.graph()
        self.cand, self.shop, self.edges = g["cand"], g["shop"], g["edges"]
        self.score = score

    def sc(self, x: str, y: str):
        return self.score.get((x, y) if x < y else (y, x))

    def accepted(self, x: str, t: float) -> set[str]:
        out = set()
        for z, _kev, vo, _vn in self.cand[x]:
            s = self.sc(x, z)
            if not vo and s is not None and s >= t:
                out.add(z)
        return out

    def guard(self, t: float):
        def ok(p: dict) -> bool:
            a, b = p["listing_a"], p["listing_b"]
            side_a = (self.accepted(a, t) - {b}) | {a}
            side_b = (self.accepted(b, t) - {a}) | {b}
            for c in side_a:
                for d in side_b:
                    if c == d or (c == a and d == b):
                        continue
                    if self.shop[c] == self.shop[d]:
                        return False
                    e = self.edges.get((c, d))
                    if e is None:
                        continue
                    s = self.sc(c, d)
                    if e[1] or (s is not None and s < LOW):
                        return False
            return True

        return ok


def kev_edge_scores(data: Data) -> dict[tuple[str, str], float | None]:
    out = {}
    for (x, y), (kev, _vo, _vn) in data.graph()["edges"].items():
        out[(x, y) if x < y else (y, x)] = kev
    return out


def judge_edge_scores(data: Data, models: Path, name: str, labelled: dict[str, float]):
    """Candidate scores on population edges: the neighbourhood run plus the labelled pairs."""
    files = [models / f"{name}-edges{k}.json" for k in (1, 2)]
    if not all(f.exists() for f in files):
        return None
    out: dict[tuple[str, str], float | None] = {}
    edge_ids = json.loads((models / "edges.index.json").read_text())  # edge id -> [x, y]
    for f in files:
        for eid, v in json.loads(f.read_text()).items():
            x, y = edge_ids[eid]
            out[(x, y) if x < y else (y, x)] = min(v)
    for p in data.pairs:
        x, y = p["listing_a"], p["listing_b"]
        if p["pair_id"] in labelled:
            out[(x, y) if x < y else (y, x)] = labelled[p["pair_id"]]
    return out


def attrpn(data: Data, p: dict) -> bool:
    return data.veto("old", p) or any(r in ATTR_STRICT for r in data.attr[p["pair_id"]])


# --- main ---------------------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--improve", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    args = ap.parse_args()
    data = Data(args.improve)
    sc = Scores(data, args.models)
    fold = sc.fold
    res: dict = {"meta": sc.meta, "alone": {}, "combination": {}, "two_judge": {}, "curves": {}}

    def line(tag: str, r: dict, h: dict | None = None) -> None:
        hb = f" held-out bound={h['bound']:.4f} ({h['same']}/{h['used']})" if h else ""
        print(f"{tag:38s} t={r['threshold']} {r['same']}/{r['used']} P={r['precision_raw']:.3f} "
              f"bound={r['bound']:.4f} est={r['est_matches']} metric={r['metric']}{hb}")  # fmt: skip

    # 1. each judge alone, behind today's vetoes
    for name, s in sc.s.items():
        t, best, _ = best_of(data, lambda t, s=s: accept_alone(data, s, t), TH)

        def acc_for(train_fold, t, name=name):
            return accept_alone(data, sc.train_scores(name, train_fold), t)

        acc_for.grid = TH
        h = heldout(data, fold, acc_for)
        at90 = slim(evaluate(data.pairs, accept_alone(data, s, 0.9)))
        knobs = 1 + (name == "qwen35")
        res["alone"][name] = {"best": slim(best), "at_0.9": at90, "heldout": h, "knobs": knobs}
        res["curves"][name] = pr_curve(data, lambda t, s=s: accept_alone(data, s, t))
        line(f"alone {name}", best, h)
        line(f"alone {name} @0.9", {**at90, "threshold": 0.9})

    # 2. known Kev errors: each judge's score and whether its chosen threshold accepts the pair
    by_id = data.by_id
    res["known_errors"] = {}
    for label, pid in KNOWN_ERRORS.items():
        row = {"label": by_id[pid]["label"], "old_veto": data.veto("old", by_id[pid]),
               "attrpn_veto": attrpn(data, by_id[pid])}  # fmt: skip
        for name, s in sc.s.items():
            t = res["alone"][name]["best"]["threshold"]
            row[name] = {"score": round(s[pid], 4), "accepted_at_best": s[pid] >= t}
        res["known_errors"][label] = row
        print(f"  {label:18s} " + " ".join(
            f"{n}={row[n]['score']:.3f}{'*' if row[n]['accepted_at_best'] else ''}"
            for n in sc.s))  # fmt: skip

    # 3. the improvement winner with each judge (complete-link needs neighbourhood scores)
    kev_edges = kev_edge_scores(data)
    for name, s in sc.s.items():
        edges = kev_edges if name == "kev" else judge_edge_scores(data, args.models, name, s)
        if edges is None:
            continue
        link = Link(data, edges)

        def combo_at(t, s=s, link=link):
            g = link.guard(t)
            return lambda p: not attrpn(data, p) and s.get(p["pair_id"], -1) >= t and g(p)

        t, best, _ = best_of(data, combo_at, TH)

        def acc_for(train_fold, t, combo_at=combo_at):
            return combo_at(t)  # no fitted knob besides the threshold (qwen's T: see below)

        acc_for.grid = TH
        h = heldout(data, fold, acc_for)
        res["combination"][name] = {"best": slim(best), "heldout": h, "knobs": 4,
                                    "note": "veto old+attrpn, guard link (improvement winner)"}  # fmt: skip
        line(f"combination {name}", best, h)

    # 4. two judges: Kev AND candidate, behind today's vetoes; and the winner AND candidate
    kev = sc.s["kev"]
    kev_link = Link(data, kev_edges)
    for name, s in sc.s.items():
        if name == "kev":
            continue
        grid = [(a, b) for a in COARSE for b in SECOND]

        def both(knob, s=s):
            t1, t2 = knob
            return lambda p: (not data.veto("old", p) and kev.get(p["pair_id"], -1) >= t1
                              and s.get(p["pair_id"], -1) >= t2)  # fmt: skip

        _, best, _ = best_of(data, both, grid)

        def acc_for(train_fold, knob, name=name):
            st = sc.train_scores(name, train_fold)
            t1, t2 = knob
            return lambda p: (not data.veto("old", p) and kev.get(p["pair_id"], -1) >= t1
                              and st.get(p["pair_id"], -1) >= t2)  # fmt: skip

        acc_for.grid = grid
        h = heldout(data, fold, acc_for)
        res["two_judge"][f"kev_and_{name}"] = {"best": slim(best), "heldout": h,
                                               "knobs": 2 + (name == "qwen35")}  # fmt: skip
        line(f"two-judge kev AND {name}", best, h)

        def both_attr(knob, s=s):
            t1, t2 = knob
            return lambda p: (not attrpn(data, p) and kev.get(p["pair_id"], -1) >= t1
                              and s.get(p["pair_id"], -1) >= t2)  # fmt: skip

        _, best, _ = best_of(data, both_attr, grid)

        def acc_for1(train_fold, knob, name=name):
            st = sc.train_scores(name, train_fold)
            t1, t2 = knob
            return lambda p: (not attrpn(data, p) and kev.get(p["pair_id"], -1) >= t1
                              and st.get(p["pair_id"], -1) >= t2)  # fmt: skip

        acc_for1.grid = grid
        h = heldout(data, fold, acc_for1)
        res["two_judge"][f"attrpn_kev_and_{name}"] = {"best": slim(best), "heldout": h,
                                                      "knobs": 3 + (name == "qwen35")}  # fmt: skip
        line(f"attrpn+kev AND {name}", best, h)

        guards = {t: kev_link.guard(t) for t in COARSE}

        def win_and(knob, s=s):
            t1, t2 = knob
            g = guards[t1]
            return lambda p: (not attrpn(data, p) and kev.get(p["pair_id"], -1) >= t1
                              and s.get(p["pair_id"], -1) >= t2 and g(p))  # fmt: skip

        _, best, _ = best_of(data, win_and, grid)

        def acc_for2(train_fold, knob, name=name):
            st = sc.train_scores(name, train_fold)
            t1, t2 = knob
            g = guards[t1]
            return lambda p: (not attrpn(data, p) and kev.get(p["pair_id"], -1) >= t1
                              and st.get(p["pair_id"], -1) >= t2 and g(p))  # fmt: skip

        acc_for2.grid = grid
        h = heldout(data, fold, acc_for2)
        res["two_judge"][f"winner_and_{name}"] = {"best": slim(best), "heldout": h,
                                                  "knobs": 5 + (name == "qwen35")}  # fmt: skip
        line(f"winner(kev) AND {name}", best, h)

    # errors at each reported best (pair ids and cells only; titles stay in ml/out/improve)
    res["n_labelled"] = defaultdict(int)
    for p in data.pairs:
        res["n_labelled"][p["label"]] += 1
    (args.models / "results.json").write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
