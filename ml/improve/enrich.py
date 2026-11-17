"""Experiment 3: score the labelled pairs with Kev-4B on enriched listing text.

    python3 ml/improve/enrich.py --improve ml/out/improve --db-rows ml/out/improve/db_rows.jsonl \
        --variants L0,E1,E2

--db-rows holds one JSON object per listing ({id, url, attributes, description}) read from the
local `makhzan_prod` copy (README of this directory). Variants, each adding to the one before:

- L0: the title as the Phase E run sent it (contexts.clean), to re-score both orders.
- E1: + the words of the URL slug when they add a token the title lacks, and the shop's own
  category (contexts.shop_category).
- E2: + the spec table (contexts.spec_table), capped at SPEC_CHARS characters.

Question, service and settings are the Phase E run's (Kev I2, raw P(yes), 8 in flight). Every
pair is scored in both orders, (a, b) then (b, a), a < b by listing id as in key.jsonl.
Writes <improve>/kev-enrich/<variant>.json = {pair_id: [p_ab, p_ba]} and
<improve>/kev-enrich/texts.json (catalogue text: ml/out is git-ignored). Needs kev-4b running.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "bakeoff"))
from common import KEV_QUESTIONS  # noqa: E402
from contexts import clean, shop_category, spec_table  # noqa: E402
from makhzan_ml.client import Client  # noqa: E402

QUESTION = KEV_QUESTIONS["I2"]
SPEC_CHARS = 600
_WORD = re.compile(r"[a-z0-9]+")


def slug_words(url: str | None) -> str:
    """The last path segment of a product URL as words, trailing numeric ids dropped."""
    if not url:
        return ""
    path = urllib.parse.urlparse(url).path.rstrip("/")
    seg = urllib.parse.unquote(path.rsplit("/", 1)[-1])
    seg = re.sub(r"\.(?:html?|php)$", "", seg)
    seg = re.sub(r"(?:[-_]\d{3,})+$", "", seg)  # Odoo/Shopify ids appended to the handle
    return " ".join(w for w in re.split(r"[-_+\s]+", seg) if w)


def texts_for(row: dict, db: dict) -> dict[str, str]:
    title = clean(row["title_en"] or row["title_ar"])
    attrs = db.get("attributes") or {}
    have = set(_WORD.findall(title.lower()))
    slug = slug_words(db.get("url"))
    extra = []
    if slug and set(_WORD.findall(slug.lower())) - have:
        extra.append(f"URL: {slug}")
    cat = shop_category(attrs)
    if cat:
        extra.append(f"Shop category: {cat}")
    e1 = title + ("\n" + " | ".join(extra) if extra else "")
    specs = "; ".join(f"{k}: {v}" for k, v in spec_table(attrs).items())
    if len(specs) > SPEC_CHARS:
        specs = specs[:SPEC_CHARS].rsplit(";", 1)[0]
    e2 = e1 + ("\nSpecs: " + specs if specs else "")
    return {"L0": title, "E1": e1, "E2": e2}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--improve", type=Path, required=True)
    ap.add_argument("--db-rows", type=Path, required=True)
    ap.add_argument("--variants", default="L0,E1,E2")
    ap.add_argument("--in-flight", type=int, default=8)
    args = ap.parse_args()

    db = {}
    for line in args.db_rows.open():
        r = json.loads(line)
        db[r["id"]] = r
    texts = {}
    for line in (args.improve / "listings.jsonl").open():
        r = json.loads(line)
        texts[r["id"]] = texts_for(r, db.get(r["id"], {}))
    pairs = [json.loads(line) for line in (args.improve / "pairs.jsonl").open()]
    out = args.improve / "kev-enrich"
    out.mkdir(parents=True, exist_ok=True)
    (out / "texts.json").write_text(json.dumps(texts, ensure_ascii=False))
    client = Client("kev-4b", batch_size=args.in_flight)
    meta = {}
    for v in args.variants.split(","):
        batch = []
        for p in pairs:
            a, b = texts[p["listing_a"]][v], texts[p["listing_b"]][v]
            batch += [(a, b), (b, a)]
        t = time.time()
        scores = client.score(batch, QUESTION)
        seconds = time.time() - t
        res = {p["pair_id"]: [round(scores[2 * i], 6), round(scores[2 * i + 1], 6)]
               for i, p in enumerate(pairs)}  # fmt: skip
        (out / f"{v}.json").write_text(json.dumps(res))
        meta[v] = {"requests": len(batch), "seconds": round(seconds, 1),
                   "pairs_per_s": round(len(batch) / seconds, 2)}  # fmt: skip
        print(v, meta[v], flush=True)
    (out / "meta.json").write_text(json.dumps({"question": QUESTION, **meta}, indent=1))


if __name__ == "__main__":
    main()
