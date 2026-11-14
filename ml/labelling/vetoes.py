"""Today's vetoes, and today's decision, for every shortlist pair.

    $(cd apps/ingestion && poetry env info -p)/bin/python ml/labelling/vetoes.py \
        --catalogue <work>/catalogue.jsonl --candidates <work>/candidates.jsonl \
        --out <work>/vetoes.jsonl

Uses ml/bakeoff/rules.py unchanged: identifiers are re-assigned over the whole catalogue
(`grouping.assign_identifiers`), then each pair gets `rules.vetoes` (same shop, values, form,
price span, on titles with the identifier taken out), `rules.rules_pair` (today's pairwise
decision) and whether both listings already share a stored product. Writes one line per pair:
ids, the four veto flags, `any_veto`, `rules_pair`, `today_stored` (ids and flags only).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bakeoff"))
from makhzan_schemas import grouping as g  # noqa: E402
from rules import load_listings, rules_pair, vetoes  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    t0 = time.time()
    listings = load_listings(args.catalogue)
    stored = {str(x.id): x.product_id for x in listings}
    g.assign_identifiers(listings)
    by_id = {str(x.id): x for x in listings}
    counts: Counter = Counter()
    with args.out.open("w") as out:
        for line in args.candidates.open():
            p = json.loads(line)
            a, b = by_id[p["a"]], by_id[p["b"]]
            v = vetoes(a, b)
            row = {
                "a": p["a"],
                "b": p["b"],
                "veto": v,
                "any_veto": any(v.values()),
                "rules_pair": rules_pair(a, b),
                "today_stored": stored[p["a"]] is not None and stored[p["a"]] == stored[p["b"]],
            }
            counts["pairs"] += 1
            counts["any_veto"] += row["any_veto"]
            counts["rules_pair"] += row["rules_pair"]
            counts["today_stored"] += row["today_stored"]
            for k, fired in v.items():
                counts[f"veto:{k}"] += fired
            out.write(json.dumps(row) + "\n")
    counts["seconds"] = round(time.time() - t0, 1)
    Path(str(args.out) + ".meta.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
