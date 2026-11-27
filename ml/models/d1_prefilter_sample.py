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
d1_prefilter_score.py.

    python3 ml/models/d1_prefilter_sample.py
"""

from __future__ import annotations

import json
import random
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKLOG = ROOT / "ml/out/backlog-2026-11-17"
LISTINGS = ROOT / "ml/out/gain-v2/listings.json"
OUT = ROOT / "ml/out/models-compare/d1-prefilter"

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
    print(
        f"{len(kev)} backlog pairs; uniform {len(uniform)}; merged {len(merged)} of {len(merged_pool)}"
    )


if __name__ == "__main__":
    main()
