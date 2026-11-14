"""Real candidate shortlists for one department: the population the labelling sample is drawn from.

    <python with numpy> ml/labelling/shortlist.py --features <work>/listing_features.jsonl \
        --exclude <phaseC>/pairs.jsonl --out <work>/candidates.jsonl --domain electronics

`listing_features.jsonl` comes from ml/bakeoff/rules.py (today's identifier rules run over the
whole catalogue, plus grouping's title tokens with the identifier kept). For every listing in
the department, its candidates are the Phase D recommendation:

- every listing sharing its identifier key today (`key`), and
- its top 10 by title-token Jaccard (`retrieval.SetIndex`), ties broken by a seeded shuffle,
  only listings with Jaccard > 0,

both restricted to the department and excluding the listing's own shop. The directed lists are
merged into unordered pairs. Pairs listed in --exclude (the Phase C files), and every pair
touching a listing used in any Phase C pair, are dropped so the new set is independent; both
counts are reported.

Writes --out (one pair per line: listing ids a < b, `via` key/jaccard, Jaccard, the rank each
side gave the other) and <out>.meta.json (counts and timings). Ids and numbers only, but the
output sits beside catalogue text: keep it outside the repo.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bakeoff"))
from common import SEED  # noqa: E402
from retrieval import SetIndex  # noqa: E402

K = 10


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--features", type=Path, required=True)
    ap.add_argument("--exclude", type=Path, action="append", default=[])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--domain", default="electronics")
    ap.add_argument("--k", type=int, default=K)
    args = ap.parse_args()

    t0 = time.time()
    feats = [json.loads(line) for line in args.features.open()]
    feats = [f for f in feats if f["domain"] == args.domain]
    ids = [f["id"] for f in feats]
    supplier = np.array([f["supplier_id"] for f in feats])
    n = len(feats)

    excluded_pairs: set[tuple[str, str]] = set()
    excluded_listings: set[str] = set()
    for path in args.exclude:
        for line in path.open():
            p = json.loads(line)
            a, b = p["a"]["listing_id"], p["b"]["listing_id"]
            excluded_pairs.add((min(a, b), max(a, b)))
            excluded_listings |= {a, b}

    pairs: dict[tuple[int, int], dict] = {}

    def add(i: int, j: int, via: str, jac: float | None = None, rank: int | None = None) -> None:
        a, b = (i, j) if ids[i] < ids[j] else (j, i)
        rec = pairs.setdefault((a, b), {"via": set(), "jaccard": None, "rank": {}})
        rec["via"].add(via)
        if jac is not None:
            rec["jaccard"] = jac
            rec["rank"][ids[i]] = rank

    # Identifier key: every cross-shop pair inside a key block.
    blocks: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(feats):
        if f["key"]:
            blocks[f["key"]].append(i)
    block_sizes = Counter(len(v) for v in blocks.values())
    for members in blocks.values():
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                i, j = members[x], members[y]
                if supplier[i] != supplier[j]:
                    add(i, j, "key")
    t_key = time.time() - t0

    # Title-token Jaccard top-k within the department, other shops only.
    t1 = time.time()
    index = SetIndex([set(f["tokens"]) for f in feats])
    jitter = np.random.default_rng(SEED).random(n).astype(np.float64) * 1e-6
    short_lists = Counter()
    for i in range(n):
        s = index.scores(i).astype(np.float64)
        s[supplier == supplier[i]] = -1.0  # own shop, and the listing itself
        positive = int((s > 0).sum())
        k = min(args.k, positive)
        short_lists[k] += 1
        if not k:
            continue
        ranked = s + jitter  # seeded tie-break; far below the smallest Jaccard step
        top = np.argpartition(-ranked, k - 1)[:k]
        top = top[np.argsort(-ranked[top])]
        for r, j in enumerate(top, 1):
            add(i, int(j), "jaccard", round(float(s[j]), 4), r)
    t_jac = time.time() - t1

    total = len(pairs)
    kept, dropped_pair, dropped_listing = [], 0, 0
    for (i, j), rec in pairs.items():
        a, b = ids[i], ids[j]
        if (a, b) in excluded_pairs:
            dropped_pair += 1
            continue
        if a in excluded_listings or b in excluded_listings:
            dropped_listing += 1
            continue
        kept.append((a, b, rec))
    kept.sort(key=lambda x: (x[0], x[1]))

    row_of = {lid: i for i, lid in enumerate(ids)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for a, b, rec in kept:
            jac = rec["jaccard"]
            if jac is None:  # key-only pair: its Jaccard still matters for describing it
                sa, sb = set(feats[row_of[a]]["tokens"]), set(feats[row_of[b]]["tokens"])
                jac = round(len(sa & sb) / len(sa | sb), 4) if sa | sb else 0.0
            row = {"a": a, "b": b, "via": sorted(rec["via"]), "jaccard": jac, "rank": rec["rank"]}
            f.write(json.dumps(row) + "\n")
    via = Counter("+".join(sorted(r["via"])) for _, _, r in kept)
    meta = {
        "domain": args.domain,
        "listings": n,
        "listings_with_key": sum(1 for f in feats if f["key"]),
        "key_blocks": len(blocks),
        "key_block_sizes": dict(sorted(block_sizes.items())),
        "k": args.k,
        "shortlist_length_histogram": dict(sorted(short_lists.items())),
        "pairs_before_exclusion": total,
        "excluded_phase_c_pairs": dropped_pair,
        "excluded_touching_phase_c_listing": dropped_listing,
        "phase_c_listings_in_domain": len(excluded_listings & set(ids)),
        "pairs": len(kept),
        "pairs_by_route": dict(via),
        "seconds_key": round(t_key, 1),
        "seconds_jaccard": round(t_jac, 1),
    }
    Path(str(args.out) + ".meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
