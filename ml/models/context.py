"""Does a listing's description and spec table help the merge judges? Title-only vs full context.

    # 1. texts + coverage (stdlib). --db-rows: one row per labelled listing from `makhzan_prod`
    #    ({id, title_en, title_ar, description, part_number, brand, price, domain, category,
    #    attributes}, description = listings.description_en, category = categories.name_en).
    python3 ml/models/context.py texts --improve ml/out/improve --db-rows <db_rows.jsonl> \
        --out ml/out/context
    # 2. cut each pair to each judge's documented length, inside an image with transformers:
    docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 -e HF_HUB_OFFLINE=1 \
      -v "$PWD/ml/.cache/huggingface:/hf:z" -v "$PWD/ml:/ml:ro" -v "$PWD/ml/out/context:/out:z" \
      makhzan-ml/kev:1.0 /ml/models/context.py fit --out /out --hub /hf/hub
    # 3. score, one service running alone on the GPU (ml/README.md), then the other:
    python3 ml/models/context.py score --improve ml/out/improve --judge kev --out ml/out/context
    python3 ml/models/context.py score --improve ml/out/improve --judge pplx --out ml/out/context
    # 4. compare (stdlib):
    python3 ml/models/context.py report --improve ml/out/improve --models ml/out/models \
        --out ml/out/context

Context variants per listing (a field the listing lacks is left out):

- title: exactly the Phase E title text (<improve>/kev-enrich/texts.json, L0), which the
  title-only Kev (kev-enrich/L0.json) and pplx (<models>/pplx.json) runs were scored on.
- full: the title, then `Category | Brand | Part number | Price`, then `Specs:` (the list page's
  spec table merged with the product page's, contexts.spec_table), then `Description:` (the
  stored description, else the product page's, HTML stripped: contexts.description). Part number
  is the shop's stated manufacturer part number, else the identifier makhzan stores.

Lengths (tokens for the two listings together; 768 left for the state layout and question):
Kev-4B 7,424 (its validated 8,192, as bakeoff/fit.py); pplx-decider-flash-v1.3 29,952 (its card:
"training used sequences up to 30,720 tokens. Inputs are never truncated"). A pair over budget
is cut from the end of each text, so the description goes first (bakeoff/fit.py's fit).

Everything else is the title-only runs': question I2, Kev's state layout, raw P(yes) for Kev
(8 in flight), P(true) at the saved temperature for pplx (32 per call); both orders, the pair
score is the minimum. `score` also re-scores REPRO title-only pairs to check the saved scores
reproduce. The rule compared is the planned one, behind today's vetoes: Kev >= 0.9 AND pplx >= 0.5.

Outputs under --out (git-ignored; texts.json and fitted-*.json hold catalogue text): coverage.json,
truncation.json, <judge>-full.json and <judge>-repro.json ({pair_id: [ab, ba]}), <judge>.meta.json,
results.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "bakeoff"))
sys.path.insert(0, str(HERE.parent / "improve"))
sys.path.insert(0, str(HERE))  # models/judge.py, not bakeoff/judge.py

KEV_BUDGET, PPLX_BUDGET = 7424, 29952
REPRO = 50  # title-only pairs re-scored per judge
RULE = (0.9, 0.5)
CURVE = [round(0.05 * i, 2) for i in range(1, 20)] + [0.97, 0.98, 0.99, 0.995]
KNOWN_ERRORS = {
    "IRF250/IRFP250": "E0446", "KSD301 NC/NO": "E0337", "ATmega328/328P": "E0098",
    "LM8UU/LM8LUU": "E0444", "MPU-6500/6050": "E0711", "1N5819/SS14": "E0581",
    "HX711 module/IC": "E0362", "GP2Y0A21 range": "E0822",
}  # fmt: skip


def load_pairs(improve: Path) -> list[dict]:
    return [json.loads(line) for line in (improve / "pairs.jsonl").open()]


# --- 1. texts and coverage -------------------------------------------------------------------
def cmd_texts(args) -> None:
    from contexts import clean, description, spec_table

    titles = {k: v["L0"] for k, v in
              json.loads((args.improve / "kev-enrich" / "texts.json").read_text()).items()}  # fmt: skip
    rows = {r["id"]: r for r in map(json.loads, args.db_rows.open())}
    texts, have = {}, {}
    for lid, title in titles.items():
        row = rows[lid]
        attrs = row.get("attributes") or {}
        price = row.get("price")
        head = [
            ("Category", clean(row.get("category"))),
            ("Brand", clean(row.get("brand"))),
            ("Part number", clean(attrs.get("mfr_part_number")) or clean(row.get("part_number"))),
            ("Price", f"{float(price):g} EGP" if price is not None else ""),
        ]
        specs = "; ".join(f"{k}: {v}" for k, v in spec_table(attrs).items())
        desc = description(row)
        full = title
        if any(v for _, v in head):
            full += "\n" + " | ".join(f"{k}: {v}" for k, v in head if v)
        if specs:
            full += "\nSpecs: " + specs
        if desc:
            full += "\nDescription: " + desc
        texts[lid] = {"title": title, "full": full}
        have[lid] = {"description": bool(desc), "specs": bool(specs), "source": row["source"]}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "texts.json").write_text(json.dumps(texts, ensure_ascii=False))

    cov: dict = defaultdict(Counter)
    flags = {}
    pairs = load_pairs(args.improve)
    (args.out / "pairs.json").write_text(
        json.dumps([[p["pair_id"], p["listing_a"], p["listing_b"]] for p in pairs])
    )
    for p in pairs:
        a, b = have[p["listing_a"]], have[p["listing_b"]]
        f = {f"{n}:{m}": (a[n] and b[n]) if m == "both" else (a[n] or b[n])
             for n in ("description", "specs") for m in ("both", "either")}  # fmt: skip
        flags[p["pair_id"]] = f
        for scope in ("all", p["stratum"], f"label:{p['label']}"):
            cov[scope]["pairs"] += 1
            cov[scope].update(k for k, v in f.items() if v)
    shops = defaultdict(Counter)
    for h in have.values():
        shops[h["source"]]["listings"] += 1
        shops[h["source"]].update(k for k in ("description", "specs") if h[k])
    (args.out / "coverage.json").write_text(
        json.dumps({"pairs": cov, "listings_by_shop": shops, "pair_flags": flags}, indent=1)
    )
    print(json.dumps(cov["all"]))


# --- 2. fit to each judge's length -----------------------------------------------------------
def cmd_fit(args) -> None:
    from fit import fit
    from transformers import AutoTokenizer

    def snap(name: str) -> str:
        d = args.hub / f"models--{name.replace('/', '--')}" / "snapshots"
        return str(next(d.iterdir()))

    texts = json.loads((args.out / "texts.json").read_text())
    pairs = json.loads((args.out / "pairs.json").read_text())  # [[pid, a, b]]
    stats = {}
    for judge, hf_id, budget in (
        ("kev", "Qwen/Qwen3.5-4B-Base", KEV_BUDGET),
        ("pplx", "perplexity-ai/pplx-decider-flash-v1.3", PPLX_BUDGET),
    ):
        tok = AutoTokenizer.from_pretrained(snap(hf_id))
        out, n_tok, cut, cut_specs = {}, defaultdict(list), 0, 0
        for pid, a, b in pairs:
            for v in ("title", "full"):
                ta, tb = texts[a][v], texts[b][v]
                fa, fb, was_cut, n = fit(tok, ta, tb, budget)
                n_tok[v].append(n)
                if v == "full":
                    out[pid] = [fa, fb]
                    if was_cut:
                        cut += 1
                        lost = [t for t, f in ((ta, fa), (tb, fb)) if f != t]
                        cut_specs += any("\nDescription: " not in f and "\nDescription: " in t
                                         for t, f in zip(lost, [fa, fb], strict=False))  # fmt: skip
        (args.out / f"fitted-{judge}.json").write_text(json.dumps(out, ensure_ascii=False))
        stats[judge] = {
            "budget_tokens": budget,
            "pairs_truncated": cut,
            "pairs_cut_past_description": cut_specs,
            "pair_tokens": {
                v: {
                    "mean": round(sum(x) / len(x), 1),
                    "max": max(x),
                    "p95": sorted(x)[int(0.95 * len(x))],
                }
                for v, x in n_tok.items()
            },  # fmt: skip
        }
    (args.out / "truncation.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats))


# --- 3. score ------------------------------------------------------------------------------
def cmd_score(args) -> None:
    from common import KEV_QUESTIONS
    from judge import GpuPeak
    from makhzan_ml.client import Client

    question = KEV_QUESTIONS["I2"]
    pairs = load_pairs(args.improve)
    texts = json.loads((args.out / "texts.json").read_text())
    fitted = json.loads((args.out / f"fitted-{args.judge}.json").read_text())

    def run(batch):
        if args.judge == "kev":
            return Client("kev-4b", batch_size=8).score(batch, question)
        res = Client("pplx-decider", batch_size=32, concurrency=1).decide_noul(batch, question)
        return [r[0] for r in res]

    def both(items):
        batch = [x for a, b in items for x in ((a, b), (b, a))]
        t0 = time.time()
        s = run(batch)
        return [[round(s[2 * i], 6), round(s[2 * i + 1], 6)] for i in range(len(items))], (
            len(batch),
            time.time() - t0,
        )

    meta = {"question": question}
    # Title-only reproduction: every 18th pair (a fixed, stratum-mixed slice).
    rp = pairs[:: len(pairs) // REPRO][:REPRO]
    s, (n, sec) = both([(texts[p["listing_a"]]["title"], texts[p["listing_b"]]["title"])
                        for p in rp])  # fmt: skip
    (args.out / f"{args.judge}-repro.json").write_text(
        json.dumps({p["pair_id"]: v for p, v in zip(rp, s, strict=True)})
    )
    meta["repro"] = {"requests": n, "seconds": round(sec, 1), "req_per_s": round(n / sec, 2)}
    print(json.dumps(meta["repro"]), flush=True)
    with GpuPeak() as gpu:
        s, (n, sec) = both([tuple(fitted[p["pair_id"]]) for p in pairs])
    (args.out / f"{args.judge}-full.json").write_text(
        json.dumps({p["pair_id"]: v for p, v in zip(pairs, s, strict=True)})
    )
    meta["full"] = {"requests": n, "seconds": round(sec, 1), "req_per_s": round(n / sec, 2),
                    "gpu_peak_mib_total": gpu.peak}  # fmt: skip
    (args.out / f"{args.judge}.meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta["full"]), flush=True)


# --- 4. report -----------------------------------------------------------------------------
def cp_upper_err(errors: int, n: int, alpha: float) -> float:
    from metric import cp_lower

    return 1 - cp_lower(n - errors, n, alpha)


def weighted(pairs: list[dict], accept, subset: set[str] | None, veto) -> dict:
    """Population estimate over `subset` (all pairs if None): weights are the cell's N_c over
    its decided count in the WHOLE sample, so a non-random subset (e.g. both sides have a
    description) is estimated for that slice of the population, not rescaled to the cell. The
    bound is metric.evaluate's (per-cell Clopper-Pearson, weight-proportional Bonferroni)."""
    from metric import ALPHA, cell_sizes, cp_lower

    size, dec = cell_sizes(pairs)
    use = [p for p in pairs if p["y"] is not None and (subset is None or p["pair_id"] in subset)]
    acc: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    tot_same = 0.0
    for p in use:
        w = size[p["cell"]] / dec[p["cell"]]
        tot_same += w * p["y"]
        if not veto(p) and accept(p):
            acc[p["cell"]][0 if p["y"] else 1] += 1
    w = {c: size[c] / dec[c] * (s + e) for c, (s, e) in acc.items()}
    accepted = sum(w.values())
    matches = sum(size[c] / dec[c] * s for c, (s, _) in acc.items())
    bound = float("nan")
    if accepted:
        bound = 1.0
        for c, (s, e) in acc.items():
            share = w[c] / accepted
            bound -= share * (1 - cp_lower(s, s + e, ALPHA * share))
    same = sum(s for s, _ in acc.values())
    errors = sum(e for _, e in acc.values())
    return {
        "used": same + errors, "same": same, "errors": errors,
        "precision_w": round(matches / accepted, 4) if accepted else None,
        "bound": round(bound, 4) if accepted else None,
        "recall_w": round(matches / tot_same, 4) if tot_same else None,
        "est_matches": round(matches), "certified_0.98": bool(accepted) and bound >= 0.98,
    }  # fmt: skip


def cmd_report(args) -> None:
    from report import Data

    data = Data(args.improve)
    pairs = data.pairs
    veto = lambda p: data.veto("old", p)  # noqa: E731
    mins = lambda d: {k: min(v) for k, v in d.items()}  # noqa: E731
    s = {
        ("kev", "title"): mins(json.loads((args.improve / "kev-enrich" / "L0.json").read_text())),
        ("pplx", "title"): mins(json.loads((args.models / "pplx.json").read_text())),
        ("kev", "full"): mins(json.loads((args.out / "kev-full.json").read_text())),
        ("pplx", "full"): mins(json.loads((args.out / "pplx-full.json").read_text())),
    }
    flags = json.loads((args.out / "coverage.json").read_text())["pair_flags"]
    subsets = {
        "all": None,
        "both_description": {k for k, f in flags.items() if f["description:both"]},
        "both_specs": {k for k, f in flags.items() if f["specs:both"]},
    }
    res: dict = {"subsets": {k: (len(v) if v else len(pairs)) for k, v in subsets.items()}}

    # reproduction of the saved title-only scores
    repro = {}
    saved = {"kev": json.loads((args.improve / "kev-enrich" / "L0.json").read_text()),
             "pplx": json.loads((args.models / "pplx.json").read_text())}  # fmt: skip
    for j in ("kev", "pplx"):
        f = args.out / f"{j}-repro.json"
        if f.exists():
            r = json.loads(f.read_text())
            d = [abs(x - y) for k, v in r.items() for x, y in zip(v, saved[j][k], strict=False)]
            th = RULE[0] if j == "kev" else RULE[1]
            flips = sum((min(v) >= th) != (min(saved[j][k]) >= th) for k, v in r.items())
            repro[j] = {"pairs": len(r), "max_abs_diff": round(max(d), 4),
                        "mean_abs_diff": round(sum(d) / len(d), 5), "flips_at_rule": flips}  # fmt: skip
    res["repro"] = repro

    def rule(kv: str, pv: str, t=RULE):
        k, q = s[("kev", kv)], s[("pplx", pv)]
        return lambda p: k[p["pair_id"]] >= t[0] and q[p["pair_id"]] >= t[1]

    combos = {"title/title": ("title", "title"), "full/full": ("full", "full"),
              "kev full, pplx title": ("full", "title"), "kev title, pplx full": ("title", "full")}  # fmt: skip
    res["rule"] = {sub: {name: weighted(pairs, rule(*kp), ids, veto) for name, kp in combos.items()}
                   for sub, ids in subsets.items()}  # fmt: skip
    res["curves"] = {
        sub: {f"{j}:{v}": [{"t": t, **weighted(pairs, lambda p, sc=s[(j, v)], t=t:
                                                 sc[p["pair_id"]] >= t, ids, veto)}
                           for t in CURVE]
              for j in ("kev", "pplx") for v in ("title", "full")}
        for sub, ids in subsets.items()
    }  # fmt: skip
    # decisions that change under the rule, with labels
    changed = []
    for p in pairs:
        if veto(p):
            continue
        a, b = rule("title", "title")(p), rule("full", "full")(p)
        if a != b:
            changed.append({"pair_id": p["pair_id"], "label": p["label"], "stratum": p["stratum"],
                            "title_accepts": a, "full_accepts": b,
                            "both_description": flags[p["pair_id"]]["description:both"]})  # fmt: skip
    res["rule_changes"] = changed
    res["known_errors"] = {
        name: {"label": data.by_id[pid]["label"], "old_veto": veto(data.by_id[pid]),
               **{f"{j}:{v}": round(s[(j, v)][pid], 4) for j in ("kev", "pplx")
                  for v in ("title", "full")},
               "rule_title": rule("title", "title")(data.by_id[pid]) and not veto(data.by_id[pid]),
               "rule_full": rule("full", "full")(data.by_id[pid]) and not veto(data.by_id[pid]),
               "both_description": flags[pid]["description:both"]}
        for name, pid in KNOWN_ERRORS.items()
    }  # fmt: skip
    (args.out / "results.json").write_text(json.dumps(res, indent=1))
    for sub in subsets:
        print(f"== {sub} ({res['subsets'][sub]} pairs)")
        for name, r in res["rule"][sub].items():
            print(f"  {name:22s} {r}")
    print(json.dumps(res["repro"]))
    print(json.dumps(res["known_errors"], indent=0))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("texts")
    t.add_argument("--improve", type=Path, required=True)
    t.add_argument("--db-rows", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("fit")
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--hub", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--improve", type=Path, required=True)
    s.add_argument("--judge", choices=["kev", "pplx"], required=True)
    s.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("report")
    r.add_argument("--improve", type=Path, required=True)
    r.add_argument("--models", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    {"texts": cmd_texts, "fit": cmd_fit, "score": cmd_score, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
