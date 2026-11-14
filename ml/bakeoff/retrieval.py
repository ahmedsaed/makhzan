"""Candidate finding: is a labelled `same` pair's partner in each listing's top-k?

    <python with numpy> ml/bakeoff/retrieval.py --split validation \
        --pairs <private>/pairs.jsonl --features <private>/listing_features.jsonl \
        --texts <private>/texts.jsonl --emb <private>/emb --out ml/out/bakeoff

Methods, each ranking the whole catalogue (61k active listings) for a query listing:

- `token-jaccard`: Jaccard over grouping's title tokens (makhzan_schemas' tokeniser and the
  department's noise list, as `grouping._sig_tokens`, but with the identifier and numbers
  kept: grouping strips the identifier because it has already blocked on it).
- `trigram-jaccard`: character-trigram Jaccard of the lower-cased alphanumeric title (the
  Phase C `similarity`).
- `<embedder>.<rung>`: cosine of the embeddings from embed.py.
- `identifier-key` (no k): whether today's identifier rules give both listings the same key,
  the only way today's grouping ever compares two listings.

The pool excludes the query itself and every listing of the query's own shop (same-shop
listings never merge). "within" restricts it to the query's department; "across" uses all.
Ties are scored at their expectation under random tie-breaking: with g listings strictly
above the partner and e others tied with it, the hit at k counts min(1, max(0, (k-g)/(e+1))).

A pair counts as found at k when either listing has the other in its top k ("pair"); the
per-direction rate is reported too. Writes <out>/retrieval.<split>.json (counts and rates
only). Search timings are recorded; embedding cost is in <out>/embed/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_pairs  # noqa: E402

KS = (5, 10, 20, 50)
_ALNUM = re.compile(r"[^a-z0-9]+")


def trigrams(title: str) -> set[str]:
    s = _ALNUM.sub("", title.lower())
    return {s[i : i + 3] for i in range(len(s) - 2)} if len(s) >= 3 else {s}


class SetIndex:
    """Jaccard of each query's set against every listing's set, via postings."""

    def __init__(self, sets: list[set[str]]):
        self.n = len(sets)
        self.size = np.array([len(s) for s in sets], dtype=np.float32)
        postings: dict[str, list[int]] = defaultdict(list)
        for i, s in enumerate(sets):
            for t in s:
                postings[t].append(i)
        self.postings = {t: np.array(v, dtype=np.int32) for t, v in postings.items()}
        self.sets = sets

    def scores(self, i: int) -> np.ndarray:
        inter = np.zeros(self.n, dtype=np.float32)
        for t in self.sets[i]:
            inter[self.postings[t]] += 1
        union = self.size + self.size[i] - inter
        return np.where(union > 0, inter / np.maximum(union, 1), 0.0)


def expected_hits(scores: np.ndarray, pool: np.ndarray, partner: int) -> dict[int, float]:
    s = scores[pool]
    sp = scores[partner]
    greater = int((s > sp).sum())
    ties = int((s == sp).sum()) - 1  # the partner itself is in the pool
    return {k: min(1.0, max(0.0, (k - greater) / (ties + 1))) for k in KS}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--split", required=True)
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--features", type=Path, required=True)
    ap.add_argument("--texts", type=Path, required=True)
    ap.add_argument("--emb", type=Path, required=True)
    ap.add_argument(
        "--embeddings", default="emb-harrier.L0,emb-harrier.L1,emb-qwen3.L0,emb-qwen3.L1"
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    feats = [json.loads(line) for line in args.features.open()]
    ids = json.loads((args.emb / "ids.json").read_text())
    assert ids == [f["id"] for f in feats], "embedding rows and features must share one order"
    row = {lid: i for i, lid in enumerate(ids)}
    titles = {}
    for line in args.texts.open():
        r = json.loads(line)
        titles[r["id"]] = r["L0"]
    domain = np.array([f["domain"] for f in feats])
    supplier = np.array([f["supplier_id"] for f in feats])
    keys = [f["key"] for f in feats]

    pairs = [p for p in load_pairs(args.pairs) if p["split"] == args.split and p["label"] == "same"]
    queries = sorted({row[p[s]["listing_id"]] for p in pairs for s in ("a", "b")})

    methods: dict[str, callable] = {}
    timing: dict[str, float] = {}
    t0 = time.time()
    tok = SetIndex([set(f["tokens"]) for f in feats])
    timing["token-jaccard.index_s"] = round(time.time() - t0, 1)
    methods["token-jaccard"] = tok.scores
    t0 = time.time()
    tri = SetIndex([trigrams(titles[lid]) for lid in ids])
    timing["trigram-jaccard.index_s"] = round(time.time() - t0, 1)
    methods["trigram-jaccard"] = tri.scores
    for name in args.embeddings.split(","):
        path = args.emb / f"{name}.npy"
        if not path.exists():
            print(f"skipping {name}: no {path}")
            continue
        mat = np.load(path).astype(np.float32)
        t0 = time.time()
        sims = mat[queries] @ mat.T
        timing[f"{name}.search_s"] = round(time.time() - t0, 2)
        cache = {q: sims[j] for j, q in enumerate(queries)}
        methods[name] = cache.__getitem__

    everyone = np.arange(len(ids))
    result: dict = {"split": args.split, "pairs": len(pairs), "timing": timing, "methods": {}}
    for name, fn in methods.items():
        t0 = time.time()
        rows = []
        cache: dict[int, np.ndarray] = {}
        for p in pairs:
            ia, ib = row[p["a"]["listing_id"]], row[p["b"]["listing_id"]]
            rec = {"domain": p["domain"], "stratum": p["stratum"]}
            for scope in ("within", "across"):
                hits = []
                for q, partner in ((ia, ib), (ib, ia)):
                    if q not in cache:
                        cache[q] = fn(q)
                    keep = (everyone != q) & (supplier != supplier[q])
                    if scope == "within":
                        keep &= domain == domain[q]
                    if not keep[partner]:
                        hits.append(dict.fromkeys(KS, 0.0))
                        continue
                    hits.append(expected_hits(cache[q], np.flatnonzero(keep), partner))
                for k in KS:
                    rec[f"{scope}.dir@{k}"] = (hits[0][k] + hits[1][k]) / 2
                    # Either side finding the other; tie expectations combined as independent.
                    rec[f"{scope}.pair@{k}"] = 1 - (1 - hits[0][k]) * (1 - hits[1][k])
            rows.append(rec)
        timing[f"{name}.rank_s"] = round(time.time() - t0, 1)
        result["methods"][name] = summarise(rows)
    key_rows = [
        {"domain": p["domain"], "hit": float(
            keys[row[p["a"]["listing_id"]]] is not None
            and keys[row[p["a"]["listing_id"]]] == keys[row[p["b"]["listing_id"]]]
        )}
        for p in pairs
    ]  # fmt: skip
    result["identifier_key"] = {
        "all": {"n": len(key_rows), "rate": sum(r["hit"] for r in key_rows) / len(key_rows)},
        **{
            d: {"n": len(v), "rate": sum(r["hit"] for r in v) / len(v)}
            for d, v in group(key_rows).items()
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"retrieval.{args.split}.json").write_text(json.dumps(result, indent=1))
    for name, s in result["methods"].items():
        a = s["all"]
        print(name, {k: round(a[k], 3) for k in a if "pair@" in k})


def group(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["domain"]].append(r)
    return out


def summarise(rows: list[dict]) -> dict:
    def mean(rs: list[dict]) -> dict:
        keys = [k for k in rs[0] if k not in ("domain", "stratum")]
        return {"n": len(rs), **{k: sum(r[k] for r in rs) / len(rs) for k in keys}}

    strata: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        strata[f"stratum:{r['stratum']}"].append(r)
    return {
        "all": mean(rows),
        **{d: mean(v) for d, v in sorted(group(rows).items())},
        **{s: mean(v) for s, v in sorted(strata.items())},
    }


if __name__ == "__main__":
    main()
