"""The context ladder: what a judge or embedder is shown about one listing, rung by rung.

    python3 ml/bakeoff/contexts.py --catalogue <private>/catalogue.jsonl \
        --features <private>/listing_features.jsonl --pairs <private>/pairs.jsonl \
        --texts <private>/texts.jsonl --coverage ml/out/bakeoff/coverage.json

Rungs (each adds to the one before; a field the listing lacks is left out, never "unknown"):

- L0 title only.
- L1 + structured fields: department, category (makhzan's), shop category, brand, part number
  (the shop's stated manufacturer part number, else the identifier today's rules assign), and
  price in EGP.
- L2 + the full spec table (the list page's specs merged with the product page's, as
  worker/details.py does) and the shop's selectable options.
- L3 + the full description (the stored description, else the product page's), HTML stripped
  to text, entities decoded, whitespace collapsed; units are kept as written.

No truncation here: fit.py cuts each model's prompt to its documented length. --texts holds
catalogue text, so keep it outside the repo; --coverage (and pair_fields.json beside it: which
pairs have a spec table / description on both sides) holds counts and flags only. Standard library.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

RUNGS = ("L0", "L1", "L2", "L3")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(text: object) -> str:
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", " ", s)
    s = _TAG.sub(" ", s)
    return _WS.sub(" ", html.unescape(s)).strip()


def shop_category(attrs: dict) -> str:
    for key in ("shop_category_path", "categories"):
        v = attrs.get(key)
        if isinstance(v, list) and v:
            return " / ".join(clean(x) for x in v if clean(x))
    for key in ("category", "product_type"):
        if isinstance(attrs.get(key), str) and attrs[key].strip():
            return clean(attrs[key])
    return ""


def spec_table(attrs: dict) -> dict[str, str]:
    specs: dict[str, str] = {}
    for source in (attrs.get("specs"), (attrs.get("details") or {}).get("specs")):
        if isinstance(source, dict):
            for k, v in source.items():
                k, v = clean(k), clean(v)
                if k and v and k.lower() not in {s.lower() for s in specs}:
                    specs[k] = v
    return specs


def options_text(attrs: dict) -> str:
    opts = attrs.get("options")
    if not isinstance(opts, dict):
        return ""
    parts = []
    for name, values in opts.items():
        vals = values if isinstance(values, list) else [values]
        parts.append(f"{clean(name)}: {', '.join(clean(v) for v in vals)}")
    return "; ".join(parts)


def description(row: dict) -> str:
    d = clean(row.get("description"))
    if not d:
        d = clean(((row.get("attributes") or {}).get("details") or {}).get("description"))
    return d


def fields(row: dict, feature: dict) -> dict[str, str]:
    attrs = row.get("attributes") or {}
    mpn = clean(attrs.get("mfr_part_number")) or (feature.get("part_number") or "")
    price = row.get("price")
    specs = spec_table(attrs)
    return {
        "title": clean(row.get("title_en") or row.get("title_ar")),
        "department": row.get("domain") or "",
        "category": clean(row.get("category")),
        "shop_category": shop_category(attrs),
        "brand": clean(row.get("brand")),
        "part_number": mpn,
        "price": f"{float(price):g} EGP" if price is not None else "",
        "specs": "; ".join(f"{k}: {v}" for k, v in specs.items()),
        "options": options_text(attrs),
        "description": description(row),
    }


def rungs(f: dict[str, str]) -> dict[str, str]:
    l0 = f["title"]
    structured = [
        ("Department", f["department"]),
        ("Category", f["category"]),
        ("Shop category", f["shop_category"]),
        ("Brand", f["brand"]),
        ("Part number", f["part_number"]),
        ("Price", f["price"]),
    ]
    l1 = l0 + "\n" + " | ".join(f"{k}: {v}" for k, v in structured if v)
    l2 = l1
    if f["specs"]:
        l2 += "\nSpecs: " + f["specs"]
    if f["options"]:
        l2 += "\nOptions: " + f["options"]
    l3 = l2 + ("\nDescription: " + f["description"] if f["description"] else "")
    return {"L0": l0, "L1": l1, "L2": l2, "L3": l3}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--features", type=Path, required=True)
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--texts", type=Path, required=True)
    ap.add_argument("--coverage", type=Path, required=True)
    args = ap.parse_args()

    features = {}
    for line in args.features.open():
        r = json.loads(line)
        features[r["id"]] = r
    have: dict[str, dict[str, bool]] = {}
    with args.texts.open("w") as out:
        for line in args.catalogue.open():
            row = json.loads(line)
            f = fields(row, features[row["id"]])
            have[row["id"]] = {k: bool(v) for k, v in f.items()}
            out.write(json.dumps({"id": row["id"], **rungs(f)}) + "\n")

    # Coverage: per split, per field, how many pairs have it on one side / both sides.
    names = ["category", "shop_category", "brand", "part_number", "price", "specs",
             "options", "description"]  # fmt: skip
    cov: dict = defaultdict(lambda: defaultdict(Counter))
    both: dict[str, dict[str, bool]] = {}
    for line in args.pairs.open():
        p = json.loads(line)
        a, b = have[p["a"]["listing_id"]], have[p["b"]["listing_id"]]
        both[p["pair_id"]] = {n: a[n] and b[n] for n in ("specs", "description")}
        for scope in ("all", p["domain"]):
            c = cov[p["split"]][scope]
            c["pairs"] += 1
            for n in names:
                c[f"{n}:both"] += a[n] and b[n]
                c[f"{n}:either"] += a[n] or b[n]
    listing_cov = Counter()
    for h in have.values():
        listing_cov["listings"] += 1
        for n in names:
            listing_cov[n] += h[n]
    args.coverage.parent.mkdir(parents=True, exist_ok=True)
    args.coverage.write_text(
        json.dumps({"catalogue": listing_cov, "pairs": cov}, indent=1, sort_keys=True)
    )
    (args.coverage.parent / "pair_fields.json").write_text(json.dumps(both))
    print(json.dumps(listing_cov))


if __name__ == "__main__":
    main()
