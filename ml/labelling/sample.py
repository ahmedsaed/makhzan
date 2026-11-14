"""Draw the stratified labelling sample from the scored shortlist, and write the blind files.

    python3 ml/labelling/sample.py --catalogue <work>/catalogue.jsonl \
        --candidates <work>/candidates.jsonl --vetoes <work>/vetoes.jsonl --kev <work>/kev \
        --frozen ml/out/bakeoff/frozen.json --db makhzan_prod --out <private dir>

Strata over the Kev + vetoes score s (a vetoed pair scores 0), thresholds from frozen.json's
`combination` (t_p98, t_f1):

- `kev_positive`: not vetoed, s >= t_p98: what an automatic merge would accept (the gate).
- `borderline`: not vetoed, t_f1 <= s < t_p98.
- `confident_no`: not vetoed, s < t_f1 (estimates matches Kev misses).
- `vetoed`: any of today's vetoes fired (estimates matches the vetoes block).

Each stratum is a seeded simple random sample without replacement (all of it if smaller), so a
pair's inclusion probability is n_h / N_h and Horvitz-Thompson weights N_h / n_h give
population estimates. Writes:

- to_label.jsonl: shuffled; pair id and, per side, title, shop, price, department, category,
  shop category, brand, part number, stock, URL. Nothing about Kev, strata, vetoes, Jaccard,
  the route that found the pair, or today's grouping. A/B order is a seeded coin flip.
- key.jsonl: pair id -> listing ids, Kev score (and how many orders it covers), veto flags,
  stratum, inclusion probability, route, Jaccard, today's decisions. Keep it from labellers.
- population.json: counts per stratum and the score distribution.

Reads URLs and shop names with `docker exec <container> psql` (read-only SELECT). Standard
library only. Every output holds catalogue text: write it outside the repo.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "bakeoff"))
sys.path.insert(0, str(HERE))
from common import SEED  # noqa: E402
from contexts import clean, shop_category  # noqa: E402
from score import load_done, pair_key  # noqa: E402

STRATA = ("kev_positive", "borderline", "confident_no", "vetoed")
SQL = r"""
COPY (
  SELECT json_build_object('id', l.id, 'url', l.source_url, 'shop', s.name, 'currency', l.currency)
  FROM listings l JOIN suppliers s ON s.id = l.supplier_id
  WHERE l.status = 'ACTIVE' AND l.domain = 'electronics'
) TO STDOUT
"""


def psql_rows(container: str, db: str) -> dict[str, dict]:
    cmd = ["docker", "exec", "-i", container, "psql", "-U", "makhzan", "-d", db,
           "-v", "ON_ERROR_STOP=1", "-At", "-c", SQL]  # fmt: skip
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    rows = [json.loads(line.replace("\\\\", "\\")) for line in out.splitlines() if line.strip()]
    return {r["id"]: r for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--vetoes", type=Path, required=True)
    ap.add_argument("--kev", type=Path, required=True)
    ap.add_argument("--frozen", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--db", default="makhzan_prod")
    ap.add_argument("--container", default="makhzan-db-1")
    ap.add_argument("--n", default="kev_positive=400,borderline=150,confident_no=150,vetoed=60")
    args = ap.parse_args()

    frozen = json.loads(args.frozen.read_text())["combination"]
    t_p98, t_f1 = frozen["threshold_p98"], frozen["threshold_best_f1"]
    sizes = {k: int(v) for k, v in (x.split("=") for x in args.n.split(","))}

    cat = {}
    for line in args.catalogue.open():
        r = json.loads(line)
        cat[r["id"]] = r
    titles = {lid: clean(r["title_en"] or r["title_ar"]) for lid, r in cat.items()}
    cand = {(c["a"], c["b"]): c for c in map(json.loads, args.candidates.open())}
    ab, ba = load_done(args.kev / "ab.jsonl"), load_done(args.kev / "ba.jsonl")

    pop: dict[str, list[dict]] = {s: [] for s in STRATA}
    missing = 0
    for v in map(json.loads, args.vetoes.open()):
        c = cand[(v["a"], v["b"])]
        rec = {
            "a": v["a"], "b": v["b"], "veto": v["veto"], "vetoed": v["any_veto"],
            "via": c["via"], "jaccard": c["jaccard"], "rules_pair": v["rules_pair"],
            "today_stored": v["today_stored"],
        }  # fmt: skip
        if v["any_veto"]:
            rec.update(kev=0.0, kev_orders=0, stratum="vetoed")
        else:
            k = pair_key(v["a"], v["b"], titles[v["a"]], titles[v["b"]])
            if k not in ab:
                missing += 1
                continue
            s, orders = (min(ab[k], ba[k]), 2) if k in ba else (ab[k], 1)
            rec.update(kev_ab=ab[k], kev_ba=ba.get(k), kev=s, kev_orders=orders)
            rec["stratum"] = (
                "kev_positive" if s >= t_p98 else "borderline" if s >= t_f1 else "confident_no"
            )
        pop[rec["stratum"]].append(rec)
    if missing:
        sys.exit(f"{missing} open pairs have no Kev score: finish score.py first")

    rng = random.Random(SEED + 5)
    chosen = []
    for s in STRATA:
        members = sorted(pop[s], key=lambda r: (r["a"], r["b"]))
        n = min(sizes[s], len(members))
        for r in rng.sample(members, n):
            r["inclusion_prob"] = n / len(members)
            chosen.append(r)
    rng.shuffle(chosen)

    extra = psql_rows(args.container, args.db)

    def side(lid: str) -> dict:
        r, e = cat[lid], extra[lid]
        attrs = r.get("attributes") or {}
        price = r.get("price")
        return {
            "title": titles[lid],
            "shop": e["shop"],
            "price": f"{float(price):g} {e['currency'] or 'EGP'}" if price is not None else None,
            "department": r["domain"],
            "category": r.get("category"),
            "shop_category": shop_category(attrs) or None,
            "brand": clean(r.get("brand")) or None,
            "part_number": clean(attrs.get("mfr_part_number")) or r.get("part_number"),
            "stock": r.get("stock_signal"),
            "url": e["url"],
        }

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "to_label.jsonl").open("w") as tl, (args.out / "key.jsonl").open("w") as kf:
        for i, r in enumerate(chosen, 1):
            pid = f"E{i:04d}"
            first, second = (r["a"], r["b"]) if rng.random() < 0.5 else (r["b"], r["a"])
            tl.write(json.dumps({"pair_id": pid, "a": side(first), "b": side(second)},
                                ensure_ascii=False) + "\n")  # fmt: skip
            kf.write(json.dumps({"pair_id": pid, "listing_a": first, "listing_b": second,
                                 **{k: v for k, v in r.items() if k not in ("a", "b")}}) + "\n")  # fmt: skip

    def hist(rs: list[dict]) -> dict:
        edges = [0, 0.01, 0.05, t_f1, 0.2, 0.4, t_p98, 0.8, 0.9, 0.95, 0.99, 1.01]
        out = Counter()
        for r in rs:
            for lo, hi in zip(edges, edges[1:], strict=False):
                if lo <= r["kev"] < hi:
                    out[f"[{lo:.4g},{hi:.4g})"] += 1
                    break
        return dict(out)

    everyone = [r for s in STRATA for r in pop[s]]
    summary = {
        "thresholds": {"p98": t_p98, "best_f1": t_f1},
        "population": {s: len(pop[s]) for s in STRATA},
        "sample": {s: sum(1 for r in chosen if r["stratum"] == s) for s in STRATA},
        "today_stored_by_stratum": {s: sum(r["today_stored"] for r in pop[s]) for s in STRATA},
        "rules_pair_by_stratum": {s: sum(r["rules_pair"] for r in pop[s]) for s in STRATA},
        "via_key_by_stratum": {s: sum("key" in r["via"] for r in pop[s]) for s in STRATA},
        "open_score_histogram": hist([r for r in everyone if not r["vetoed"]]),
        "open_pairs_one_order_only": sum(1 for r in everyone if r["kev_orders"] == 1),
    }
    (args.out / "population.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
