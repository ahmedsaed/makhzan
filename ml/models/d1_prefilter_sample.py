"""Draw the d1 pre-filter's backlog samples and render their requests (section 7).

The backlog is the 2026-11-17 production backlog as the BF16 judges scored it
(ml/out/backlog-2026-11-17/scores-kev.jsonl and scores-pplx.jsonl, one line per order). A
pair's Kev and pplx scores are the lower of its orders; pairs are keyed by their two listing
ids sorted, in the order the Kev file first names them.

- uniform: random.Random(20261127).sample(every Kev-scored pair, 1000);
- merged: random.Random(7).sample(the pairs both judges merged, Kev >= 0.8 and pplx >= 0.95,
  minus the uniform sample, 500).

Each pair is rendered both ways with Kev's K2 payload (prompt.payload("K2-150", ...)) from
ml/out/gain-v2/listings.json, A,B first. Writes meta.json, meta-merged.json, requests.jsonl and
requests-merged.jsonl to ml/out/models-compare/d1-prefilter/; score them with
d1_prefilter_score.py. Exits non-zero unless the four files come out byte-identical to the ones
the scoring runs used.

    python3 ml/models/d1_prefilter_sample.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKLOG = ROOT / "ml/out/backlog-2026-11-17"
LISTINGS = ROOT / "ml/out/gain-v2/listings.json"
OUT = ROOT / "ml/out/models-compare/d1-prefilter"
# The files the scoring runs used, as sha256; the script exits non-zero unless it rewrites them
# byte for byte (and the sample sizes the doc states).
EXPECTED_SHA256 = {
    "meta.json": "138d6ce927eb8ae7e5a875811c89cd14baebd55ff37a4a04326fce7908d1d8cf",
    "meta-merged.json": "6c4a9700eba20437d081503c76be3facc3d722d8cb9fab3d37118557f5816f19",
    "requests.jsonl": "307f6ac4e88635507eb8184f1e5daac4a8f1a58873730d2a0efb030880334dfd",
    "requests-merged.jsonl": "96a71d7016315837bb01bb3261b794bdf73397b00a0b469327bc8a47d61b388a",
}
EXPECTED_COUNTS = (92833, 1000, 500, 6236)

_stub = types.ModuleType("makhzan_schemas")
_stub.__path__ = [str(ROOT / "packages/schemas/makhzan_schemas")]
sys.modules.setdefault("makhzan_schemas", _stub)
from makhzan_schemas.ai import prompt  # noqa: E402


def pair_scores(path: Path) -> dict[tuple[str, str], float]:
    orders: dict[tuple[str, str], dict[str, float]] = {}
    for r in map(json.loads, path.open()):
        k = tuple(sorted((r["listing_a"], r["listing_b"])))
        orders.setdefault(k, {})[r["order"]] = r["p"]
    return {k: min(v.values()) for k, v in orders.items()}


def write(name: str, pairs, kev, pplx, listings) -> None:
    meta = [{"pair": list(p), "kev": kev[p], "pplx": pplx.get(p)} for p in pairs]
    (OUT / f"{name}.json").write_text(json.dumps(meta))
    reqs = "requests" if name == "meta" else "requests-merged"
    with (OUT / f"{reqs}.jsonl").open("w") as fh:
        for a, b in pairs:
            for order, (x, y) in (("ab", (a, b)), ("ba", (b, a))):
                request = prompt.payload("K2-150", listings[x], listings[y])
                fh.write(json.dumps({"pair": [a, b], "order": order, "request": request}) + "\n")


def main() -> None:
    kev = pair_scores(BACKLOG / "scores-kev.jsonl")
    pplx = pair_scores(BACKLOG / "scores-pplx.jsonl")
    listings = json.loads(LISTINGS.read_text())
    uniform = random.Random(20261127).sample(list(kev), 1000)
    taken = set(uniform)
    merged_pool = [
        k for k in kev if k in pplx and kev[k] >= 0.8 and pplx[k] >= 0.95 and k not in taken
    ]
    merged = random.Random(7).sample(merged_pool, 500)
    OUT.mkdir(parents=True, exist_ok=True)
    write("meta", uniform, kev, pplx, listings)
    write("meta-merged", merged, kev, pplx, listings)
    counts = (len(kev), len(uniform), len(merged), len(merged_pool))
    print(f"{counts[0]} backlog pairs; uniform {counts[1]}; merged {counts[2]} of {counts[3]}")
    bad = [] if counts == EXPECTED_COUNTS else [f"counts: expected {EXPECTED_COUNTS}"]
    for name, want in EXPECTED_SHA256.items():
        if hashlib.sha256((OUT / name).read_bytes()).hexdigest() != want:
            bad.append(f"{name}: not byte-identical to the file the runs scored")
    print("\n".join(bad) if bad else "check: all four files byte-identical to the scored ones")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
