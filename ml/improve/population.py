"""The whole Phase E shortlist with its scores, for the per-shop and complete-link checks
(experiment 4c), plus experiment 1's recalibrated vetoes on every pair.

    $(cd apps/ingestion && poetry env info -p)/bin/python ml/improve/population.py \
        --work <private>/phaseE-labels/work --improve ml/out/improve

For each of the 231,444 candidate pairs: the two listing ids, their shops, today's vetoes and
rules_pair (work/vetoes.jsonl), the recalibrated vetoes (vetoes2.py), and Kev's score (min of
the orders scored; one order for pairs whose first order was below 0.05, an upper bound;
vetoed pairs outside the 8,000-pair veto sample have none). Writes <improve>/population.jsonl
(ids, flags and scores only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bakeoff"))
from contexts import clean  # noqa: E402
from vetoes2 import vetoes  # noqa: E402


def load_scores(directory: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in ("ab", "ba"):
        path = directory / f"{name}.jsonl"
        if not path.exists():
            continue
        for line in path.open():
            for key, p in json.loads(line).items():
                out[f"{name}:{key}"] = p
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--improve", type=Path, required=True)
    args = ap.parse_args()

    rows = {}
    for line in (args.work / "catalogue.jsonl").open():
        r = json.loads(line)
        if r["domain"] == "electronics":
            rows[r["id"]] = r
    mpn = {}
    for line in (args.work / "listing_features.jsonl").open():
        r = json.loads(line)
        if r["id"] in rows:
            mpn[r["id"]] = r["part_number"]
    scores = load_scores(args.work / "kev")
    scores.update(load_scores(args.work / "kev-vetoed"))

    def title(i: str) -> str:
        return rows[i]["title_en"] or rows[i]["title_ar"] or ""

    def price(i: str):
        p = rows[i]["price"]
        return Decimal(str(p)) if p is not None else None

    n = 0
    with (args.improve / "population.jsonl").open("w") as out:
        for line in (args.work / "vetoes.jsonl").open():
            p = json.loads(line)
            a, b = p["a"], p["b"]
            ta, tb = clean(title(a)), clean(title(b))
            h = hashlib.sha1(f"{ta}\x00{tb}".encode()).hexdigest()[:12]
            key = f"{a}|{b}|{h}"
            ab, ba = scores.get(f"ab:{key}"), scores.get(f"ba:{key}")
            kev = None if ab is None else (ab if ba is None else min(ab, ba))
            v2 = vetoes(title(a), title(b), mpn[a], mpn[b], price(a), price(b))["new"]
            row = {
                "a": a,
                "b": b,
                "shop_a": rows[a]["supplier_id"],
                "shop_b": rows[b]["supplier_id"],
                "veto_old": p["any_veto"],
                "veto_new": any(v2.values()),
                "rules_pair": p["rules_pair"],
                "kev": kev,
                "orders": (ab is not None) + (ba is not None),
            }
            out.write(json.dumps(row) + "\n")
            n += 1
    print(f"{n} pairs")


if __name__ == "__main__":
    main()
