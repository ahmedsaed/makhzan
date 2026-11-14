"""The population edges a candidate judge must score for the complete-link guard.

    # stage 1: every open edge touching a labelled listing
    python3 ml/models/edges.py --improve ml/out/improve --catalogue <phaseE>/work/catalogue.jsonl \
        --out ml/out/models --stage 1
    # stage 2: edges between the neighbours that judge accepts at --min-t (needs stage 1 scored)
    python3 ml/models/edges.py ... --stage 2 --judge pplx

Complete-link (ml/improve/report.py) accepts a labelled pair only if joining the two listings'
accepted neighbourhoods creates no same-shop pair and no vetoed or confidently-different edge.
With a new judge that needs its scores on (1) every open (not vetoed by today's rules) edge
touching a labelled listing, to know which neighbours it accepts, and (2) the open edges between
those neighbours. Stage 2 takes the neighbours the judge accepts at --min-t, the lowest threshold
any rule sweeps, so it covers every threshold.

Writes <out>/edges<stage>.jsonl ({"pair_id", "a", "b"}), adds to <out>/edges.index.json (edge id
-> [a, b]) and <out>/edge-texts.json (listing id -> cleaned title, catalogue text: ml/out is
git-ignored).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "bakeoff"))
from contexts import clean  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--improve", type=Path, required=True)
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stage", type=int, choices=(1, 2), required=True)
    ap.add_argument("--judge")
    ap.add_argument("--min-t", type=float, default=0.5)
    args = ap.parse_args()

    pairs = [json.loads(line) for line in (args.improve / "pairs.jsonl").open()]
    labelled_pairs = {tuple(sorted((p["listing_a"], p["listing_b"]))): p["pair_id"] for p in pairs}
    labelled = {x for p in pairs for x in (p["listing_a"], p["listing_b"])}
    open_edges: dict[tuple[str, str], tuple[str, str]] = {}
    inc: dict[str, list[str]] = defaultdict(list)
    for line in (args.improve / "population.jsonl").open():
        r = json.loads(line)
        if r["veto_old"]:
            continue
        key = tuple(sorted((r["a"], r["b"])))
        open_edges[key] = (r["a"], r["b"])
        inc[r["a"]].append(r["b"])
        inc[r["b"]].append(r["a"])

    index_f = args.out / "edges.index.json"
    index = json.loads(index_f.read_text()) if index_f.exists() else {}
    have = {tuple(sorted(v)) for v in index.values()} | set(labelled_pairs)

    if args.stage == 1:
        want = {tuple(sorted((x, y))) for x in labelled for y in inc[x]}
    else:
        scores: dict[tuple[str, str], float] = {}
        for eid, v in json.loads((args.out / f"{args.judge}-edges1.json").read_text()).items():
            scores[tuple(sorted(index[eid]))] = min(v)
        lab_scores = json.loads((args.out / f"{args.judge}.json").read_text())
        for key, pid in labelled_pairs.items():
            scores[key] = min(lab_scores[pid])

        def accepted(x: str) -> set[str]:
            return {y for y in inc[x] if scores.get(tuple(sorted((x, y))), -1) >= args.min_t}

        want = set()
        for p in pairs:
            a, b = p["listing_a"], p["listing_b"]
            side_a, side_b = accepted(a) | {a}, accepted(b) | {b}
            for c in side_a:
                for d in side_b:
                    key = tuple(sorted((c, d)))
                    if c != d and key in open_edges:
                        want.add(key)
    new = sorted(k for k in want if k not in have)
    start = len(index)
    rows = []
    for i, key in enumerate(new):
        eid = f"X{start + i:06d}"
        a, b = open_edges[key]
        index[eid] = [a, b]
        rows.append({"pair_id": eid, "a": a, "b": b})
    (args.out / f"edges{args.stage}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    index_f.write_text(json.dumps(index))

    need = {x for r in rows for x in (r["a"], r["b"])}
    texts_f = args.out / "edge-texts.json"
    texts = json.loads(texts_f.read_text()) if texts_f.exists() else {}
    for line in args.catalogue.open():
        r = json.loads(line)
        if r["id"] in need and r["id"] not in texts:
            texts[r["id"]] = clean(r["title_en"] or r["title_ar"])
    missing = need - set(texts)
    if missing:
        raise SystemExit(f"{len(missing)} listings missing from the catalogue")
    texts_f.write_text(json.dumps(texts, ensure_ascii=False))
    print(f"stage {args.stage}: {len(rows)} new edges ({len(want)} wanted, {len(need)} listings)")


if __name__ == "__main__":
    main()
