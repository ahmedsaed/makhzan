"""Join the Phase E labelling run into one working file for the improvement experiments.

    python3 ml/improve/build.py --run <private>/phaseE-labels --out ml/out/improve

Reads key.jsonl (ids, Kev scores, vetoes, stratum, inclusion probability), labels/final.json
(the adjudicated label per pair) and work/catalogue.jsonl, and writes under --out (git-ignored,
it holds catalogue text):

- pairs.jsonl: one row per labelled pair, the key row plus `label` (same / not / unsure), `y`
  (1, 0 or None) and `cell` (the stratum, split by Kev band for the two-phase veto strata).
- listings.jsonl: the full catalogue row of every listing in a labelled pair.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def cell_of(row: dict) -> str:
    """The uniformly sampled cell a pair was drawn from: its stratum, or veto group x Kev band."""
    if row["stratum"].startswith("veto:"):
        return f"{row['stratum']}:{row['veto_kev_band']}"
    return row["stratum"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    labels = json.loads((args.run / "labels" / "final.json").read_text())
    pairs = []
    for line in (args.run / "key.jsonl").open():
        row = json.loads(line)
        label = labels[row["pair_id"]]
        row.update(label=label, y={"same": 1, "not": 0}.get(label), cell=cell_of(row))
        pairs.append(row)
    ids = {p["listing_a"] for p in pairs} | {p["listing_b"] for p in pairs}
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "pairs.jsonl").open("w") as f:
        for p in pairs:
            f.write(json.dumps(p) + "\n")
    n = 0
    with (args.out / "listings.jsonl").open("w") as f:
        for line in (args.run / "work" / "catalogue.jsonl").open():
            row = json.loads(line)
            if row["id"] in ids:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
    print(json.dumps({"pairs": len(pairs), "listings": n, "wanted": len(ids)}))


if __name__ == "__main__":
    main()
