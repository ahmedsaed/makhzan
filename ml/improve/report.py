"""Score every improvement experiment on the one metric (metric.py) and write the results.

    python3 ml/improve/report.py --improve ml/out/improve

Reads what the experiment scripts wrote under --improve (pairs.jsonl, vetoes2.json,
attr_veto.json, kev-enrich/*.json, population.jsonl) and writes <improve>/results.json (pair ids and counts; titles only in
the error listings, and ml/out is git-ignored).

A rule is (veto, text, guard, threshold): pairs pass when the veto does not fire, Kev's score
on that text is at least the threshold, and the guard (if any) agrees. Thresholds are swept on
metric.THRESHOLDS and the best certified one is reported; when none certifies, the highest
bound. Every choice here is made on the same 900 pairs, so `knobs` counts what was tuned and
`heldout` re-makes the final choice on one half and scores the other (2-fold within cells).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from metric import THRESHOLDS, evaluate, sweep  # noqa: E402

ATTR_STRICT = {"part_number", "contact", "connector", "package"}
LOW = 0.0772  # Phase E best-F1 threshold: below it Kev is confident the pair differs
SEED = 20261114


class Data:
    def __init__(self, d: Path):
        self.pairs = [json.loads(line) for line in (d / "pairs.jsonl").open()]
        self.by_id = {p["pair_id"]: p for p in self.pairs}
        self.v2 = json.loads((d / "vetoes2.json").read_text())
        av = d / "attr_veto.json"
        self.attr = json.loads(av.read_text()) if av.exists() else None
        self.kev: dict[str, dict[str, float]] = {
            "title": {p["pair_id"]: p.get("kev_raw", p["kev"]) for p in self.pairs}
        }
        self.orders: dict[str, dict[str, list[float]]] = {}
        for f in sorted((d / "kev-enrich").glob("*.json")):
            if f.stem in ("texts", "meta"):
                continue
            s = json.loads(f.read_text())
            self.orders[f.stem] = s
            self.kev[f.stem] = {k: min(v) for k, v in s.items()}
        self.pop = d / "population.jsonl"
        self._graph: dict | None = None

    # --- vetoes ------------------------------------------------------------------------------
    def veto(self, name: str, p: dict) -> bool:
        pid = p["pair_id"]
        old = any(self.v2[pid]["old"].values())
        new = any(self.v2[pid]["new"].values())
        reasons = self.attr[pid] if self.attr is not None else []
        attr = bool(reasons)
        # attrpn: only the identity fields (part number, NO/NC, USB connector, package); the
        # extractor's form and pack readings proved noisy (chosen after seeing them: a knob).
        attrpn = any(r in ATTR_STRICT for r in reasons)
        return {"none": False, "old": old, "new": new, "attr": attr, "old+attr": old or attr,
                "new+attr": new or attr, "old+attrpn": old or attrpn,
                "new+attrpn": new or attrpn}[name]  # fmt: skip

    # --- the population graph for experiment 4c ----------------------------------------------
    def graph(self):
        if self._graph is None:
            cand: dict[str, list] = defaultdict(list)
            shop: dict[str, str] = {}
            for line in self.pop.open():
                r = json.loads(line)
                shop[r["a"]], shop[r["b"]] = r["shop_a"], r["shop_b"]
                for x, y in ((r["a"], r["b"]), (r["b"], r["a"])):
                    cand[x].append((y, r["kev"], r["veto_old"], r["veto_new"]))
            edges = {}
            for x, lst in cand.items():
                for y, kev, vo, vn in lst:
                    edges[(x, y)] = (kev, vo, vn)
            self._graph = {"cand": cand, "shop": shop, "edges": edges}
        return self._graph


def guard_fn(data: Data, guard: str, veto: str, t: float):
    """Extra conditions on top of veto + threshold."""
    if guard == "none":
        return lambda p: True
    if guard == "rules":
        return lambda p: p["rules_pair"]
    if guard == "key":
        return lambda p: "key" in p["via"]
    g = data.graph()
    vi = 2 if veto.startswith("new") else 1

    def ok_edge(e) -> bool:
        return e[0] is not None and not e[vi]

    def mutual_best(p: dict) -> bool:
        a, b = p["listing_a"], p["listing_b"]
        for x, y in ((a, b), (b, a)):
            sy = g["shop"][y]
            mine = g["edges"].get((x, y))
            if mine is None or not ok_edge(mine):
                return False
            for z, kev, vo, vn in g["cand"][x]:
                if z != y and g["shop"][z] == sy and ok_edge((kev, vo, vn)) and kev > mine[0]:
                    return False
        return True

    def accepted_neighbours(x: str) -> set[str]:
        return {
            z for z, kev, vo, vn in g["cand"][x]
            if kev is not None and not (vn if vi == 2 else vo) and kev >= t
        }  # fmt: skip

    def complete_link(p: dict) -> bool:
        a, b = p["listing_a"], p["listing_b"]
        side_a, side_b = accepted_neighbours(a) | {a}, accepted_neighbours(b) | {b}
        side_a.discard(b)
        side_b.discard(a)
        side_a.add(a)
        side_b.add(b)
        for c in side_a:
            for d in side_b:
                if c == d or (c == a and d == b):
                    continue
                if g["shop"][c] == g["shop"][d]:
                    return False  # one group would hold two listings of one shop
                e = g["edges"].get((c, d))
                if e is not None and (e[vi] or (e[0] is not None and e[0] < LOW)):
                    return False  # a confident "different" edge would join the groups
        return True

    if guard == "mutual":
        return mutual_best
    if guard == "link":
        return complete_link
    if guard == "mutual+link":
        return lambda p: mutual_best(p) and complete_link(p)
    raise ValueError(guard)


def rule(data: Data, veto: str, text: str, guard: str, combine: str = "min"):
    def at(t: float):
        g = guard_fn(data, guard, veto, t)
        if combine == "min":
            s = data.kev[text]
        else:
            fn = max if combine == "max" else (lambda v: sum(v) / 2)
            s = {k: fn(v) for k, v in data.orders[text].items()}

        def accept(p: dict) -> bool:
            score = s.get(p["pair_id"])
            return score is not None and not data.veto(veto, p) and score >= t and g(p)

        return accept

    return at


def run_rule(data: Data, veto: str, text: str, guard: str, combine: str = "min", subset=None,
             thresholds=THRESHOLDS):  # fmt: skip
    t, best, rows = sweep(data.pairs, rule(data, veto, text, guard, combine), thresholds, subset)
    return t, best, rows


def errors_listing(data: Data, accept, titles: dict) -> list[dict]:
    out = []
    for p in data.pairs:
        if p["y"] == 0 and accept(p):
            out.append({"pair_id": p["pair_id"], "cell": p["cell"],
                        "a": titles.get(p["listing_a"]), "b": titles.get(p["listing_b"])})  # fmt: skip
    return out


def folds(data: Data) -> dict[str, int]:
    by_cell = defaultdict(list)
    for p in data.pairs:
        by_cell[p["cell"]].append(p["pair_id"])
    out = {}
    rng = random.Random(SEED)
    for cell in sorted(by_cell):
        ids = sorted(by_cell[cell])
        rng.shuffle(ids)
        for i, pid in enumerate(ids):
            out[pid] = i % 2
    return out


def veto_stats(data: Data, titles: dict) -> dict:
    """Per veto: estimated real matches it blocks and non-matches it stops, population-wide
    (HT), the false-veto rate per today's veto group, and the labelled same pairs it vetoes."""
    from metric import cell_sizes

    size, dec = cell_sizes(data.pairs)
    out = {}
    for name in ("old", "new", "attr", "attrpn"):
        if "attr" in name and data.attr is None:
            continue
        key = name

        def fires(p, name=name):
            if name in ("old", "new"):
                return data.veto(name, p)
            reasons = data.attr[p["pair_id"]]
            return any(r in ATTR_STRICT for r in reasons) if name == "attrpn" else bool(reasons)

        w = {
            p["pair_id"]: size[p["cell"]] / dec[p["cell"]] for p in data.pairs if p["y"] is not None
        }
        blocked = sum(w[p["pair_id"]] for p in data.pairs if p["y"] == 1 and fires(p))
        stopped = sum(w[p["pair_id"]] for p in data.pairs if p["y"] == 0 and fires(p))
        groups = {}
        for g in ("only-values", "only-price", "only-form", "multiple"):
            cells = [c for c in size if c.startswith(f"veto:{g}")]
            n_g = sum(size[c] for c in cells)
            b = sum(w[p["pair_id"]] for p in data.pairs if p["cell"] in cells and p["y"] == 1
                    and fires(p))  # fmt: skip
            groups[g] = {"N": round(n_g), "false_veto_rate": round(b / n_g, 4),
                         "blocked_matches": round(b)}  # fmt: skip
        kp_same_vetoed = [
            {"pair_id": p["pair_id"], "kev": round(data.kev["title"][p["pair_id"]], 3),
             "why": data.attr[p["pair_id"]] if data.attr is not None else None,
             "a": titles.get(p["listing_a"]), "b": titles.get(p["listing_b"])}
            for p in data.pairs
            if p["y"] == 1 and p["cell"] == "kev_positive" and fires(p)
        ]  # fmt: skip
        out[key] = {"blocked_matches": round(blocked), "stopped_nonmatches": round(stopped),
                    "precision_of_veto": round(stopped / (stopped + blocked), 4)
                    if stopped + blocked else None,
                    "by_group": groups, "kev_positive_same_vetoed": kp_same_vetoed}  # fmt: skip
        print(
            f"veto {key:12s} blocks ~{round(blocked)} matches, stops ~{round(stopped)} "
            f"non-matches; kev_positive same vetoed: {len(kp_same_vetoed)}"
        )
    return out


VETOES = ("old", "new", "old+attr", "new+attr", "old+attrpn", "new+attrpn")
GUARDS = ("none", "mutual", "link", "mutual+link")


def grid(data: Data) -> list[tuple[str, str, str]]:
    texts = [t for t in ("title", "E1", "E2") if t in data.kev]
    vetoes = [v for v in VETOES if data.attr is not None or "attr" not in v]
    return [(v, t, g) for v in vetoes for t in texts for g in GUARDS]


def combination(data: Data, titles: dict) -> dict:
    """The best certified (veto, text, guard, threshold) on all 900 pairs, then a 2-fold
    held-out check: choose on one half (largest estimate with no error on that half), decide
    the other half's pairs with that choice, and score the out-of-fold decisions together."""
    best = None
    table = []
    for cfg in grid(data):
        t, r, _ = run_rule(data, *cfg)
        table.append({"config": cfg, "threshold": t, **{k: r[k] for k in (
            "used", "same", "errors", "bound", "est_matches", "metric")}})  # fmt: skip
        key = (r["metric"], r["bound"])
        if best is None or key > best[0]:
            best = (key, cfg, t, r)
    _, cfg, t, r = best
    out = {"config": cfg, "threshold": t, "best": r, "grid": table,
           "knobs": {"discrete": 3, "threshold": 1, "grid_size": len(table)},
           "errors_at_best": errors_listing(data, rule(data, *cfg)(t), titles)}  # fmt: skip
    fold = folds(data)
    chosen = {}
    for k in (0, 1):
        train = {pid for pid, f in fold.items() if f != k}
        pick = None
        for c in grid(data):
            _, _, rows = run_rule(data, *c, subset=train)
            for row in rows:
                if row["errors"] == 0 and row["used"]:
                    key = (row["est_matches"], row["threshold"])
                    if pick is None or key > pick[0]:
                        pick = (key, c, row["threshold"], row)
        chosen[k] = pick
    accepts = {k: rule(data, *chosen[k][1])(chosen[k][2]) for k in (0, 1)}
    held = evaluate(data.pairs, lambda p: accepts[fold[p["pair_id"]]](p))
    per_fold = {}
    for k in (0, 1):
        test = {pid for pid, f in fold.items() if f == k}
        per_fold[k] = {"chosen_on_other_half": [*chosen[k][1], chosen[k][2]],
                       "train": {x: chosen[k][3][x] for x in ("used", "same", "errors",
                                                               "est_matches")},
                       "test": evaluate(data.pairs, accepts[k], subset=test)}  # fmt: skip
    # (B) the winning config fixed, only its threshold re-chosen on the other half.
    fixed = {}
    for k in (0, 1):
        train = {pid for pid, f in fold.items() if f != k}
        _, _, rows = run_rule(data, *cfg, subset=train)
        ok = [r for r in rows if r["errors"] == 0 and r["used"]]
        fixed[k] = max(ok, key=lambda r: (r["est_matches"], r["threshold"]))["threshold"]
    acc_fixed = {k: rule(data, *cfg)(fixed[k]) for k in (0, 1)}
    held_fixed = evaluate(data.pairs, lambda p: acc_fixed[fold[p["pair_id"]]](p))
    out["heldout"] = {"out_of_fold": held, "per_fold": per_fold,
                      "config_fixed": {"thresholds": fixed, "out_of_fold": held_fixed}}  # fmt: skip
    print(
        f"held-out, config fixed (thresholds {fixed}) used={held_fixed['used']} "
        f"same={held_fixed['same']} err={held_fixed['errors']} "
        f"bound={held_fixed['bound']:.4f} est={held_fixed['est_matches']}"
    )
    print(
        f"combination {cfg} t={t} used={r['used']} same={r['same']} err={r['errors']} "
        f"bound={r['bound']:.4f} est={r['est_matches']} metric={r['metric']}"
    )
    print(
        f"held-out (out of fold) used={held['used']} same={held['same']} "
        f"err={held['errors']} bound={held['bound']:.4f} est={held['est_matches']}"
    )
    for k in (0, 1):
        f = per_fold[k]
        print(
            f"  fold {k}: chose {f['chosen_on_other_half']} train={f['train']} "
            f"test same={f['test']['same']} err={f['test']['errors']}"
        )
    return out


def main() -> None:

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--improve", type=Path, required=True)
    args = ap.parse_args()
    data = Data(args.improve)
    titles = {}
    for line in (args.improve / "listings.jsonl").open():
        r = json.loads(line)
        titles[r["id"]] = r["title_en"] or r["title_ar"]
    results: dict = {"rules_pair": evaluate(data.pairs, lambda p: p["rules_pair"])}

    configs = {
        "baseline": ("old", "title", "none"),
        "exp1_vetoes": ("new", "title", "none"),
        "exp2_attr_old": ("old+attr", "title", "none"),
        "exp2_attr_new": ("new+attr", "title", "none"),
        "exp2_attr_only": ("attr", "title", "none"),
        "exp2_attrpn_old": ("old+attrpn", "title", "none"),
    }
    for text in ("L0", "E1", "E2"):
        if text in data.kev:
            configs[f"exp3_{text}"] = ("old", text, "none")
    configs.update({
        "exp4b_rules": ("old", "title", "rules"),
        "exp4b_key": ("old", "title", "key"),
        "exp4c_mutual": ("old", "title", "mutual"),
        "exp4c_link": ("old", "title", "link"),
        "exp4c_mutual_link": ("old", "title", "mutual+link"),
    })  # fmt: skip
    for name, (veto, text, guard) in configs.items():
        if "attr" in veto and data.attr is None:
            continue
        t, best, rows = run_rule(data, veto, text, guard)
        results[name] = {"config": [veto, text, guard], "best": best,
                         "curve": [{k: r[k] for k in ("threshold", "used", "same", "errors",
                                                      "bound", "est_matches")} for r in rows]}  # fmt: skip
        results[name]["errors_at_best"] = errors_listing(
            data, rule(data, veto, text, guard)(t), titles
        )
        print(f"{name:20s} t={t} used={best['used']} same={best['same']} err={best['errors']} "
              f"bound={best['bound']:.4f} est={best['est_matches']} metric={best['metric']}")  # fmt: skip
    for combine in ("max", "mean"):
        if "L0" in data.orders:
            t, best, _ = run_rule(data, "old", "L0", "none", combine)
            results[f"exp4a_{combine}"] = {"config": ["old", "L0", "none", combine], "best": best}
            print(f"exp4a_{combine:14s} t={t} used={best['used']} err={best['errors']} "
                  f"bound={best['bound']:.4f} est={best['est_matches']}")  # fmt: skip
    results["veto_stats"] = veto_stats(data, titles)
    results["combination"] = combination(data, titles)
    (args.improve / "results.json").write_text(json.dumps(results, indent=1, default=str))


if __name__ == "__main__":
    main()
