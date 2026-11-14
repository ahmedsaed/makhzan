"""Today's grouping rules as a pair judge and as a candidate finder, from makhzan_schemas itself.

Run with the ingestion virtualenv (it has makhzan_schemas and SQLAlchemy):

    $(cd apps/ingestion && poetry env info -p)/bin/python ml/bakeoff/rules.py \
        --catalogue <private>/catalogue.jsonl --pairs <private>/pairs.jsonl \
        --out ml/out/bakeoff --work <private>

Nothing here re-implements a rule. Every active listing becomes a transient `Listing`, then:

1. `grouping.assign_identifiers(listings)`: the current identifier rules and family guard over
   the whole catalogue, exactly what `rebuild_products(reidentify=True)` runs first.
2. **rules_pair** (the pairwise decision): the two listings merge only if both have an
   identifier, `grouping.base_key` gives them the same key, and `grouping._subcluster(key,
   [a, b], domain, current={})` puts them in one cluster (title agreement plus every veto:
   same shop, values, form, price span).
3. **rules_full** (what a regroup would do): `grouping._group_listings(listings, current)`
   over the whole catalogue with each listing's stored product as incumbent, as
   `rebuild_products` calls it; same group or not. This includes chaining through third
   listings and incumbency, so it can differ from rules_pair.
4. **today_stored**: both listings point at the same stored product in the snapshot.
5. **vetoes** for the combination judge, computed with grouping's own helpers on each
   listing's title with its identifier taken out, as `_subcluster` builds its evidence:
   same supplier, `values.values_conflict`, `grouping._forms_conflict` (with the profile's
   strict forms) and `grouping._span_ok` (the profile's `merge_price_ratio`).

Writes <out>/rules.json (pair id -> decisions and vetoes; no text) and, under --work,
listing_features.jsonl (listing id, domain, supplier, assigned identifier key, grouping's
title tokens with the identifier kept) for the candidate-finding script. --work holds
catalogue text: keep it outside the repo.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from makhzan_schemas import grouping as g
from makhzan_schemas.domains import get_profile
from makhzan_schemas.models import Listing
from makhzan_schemas.values import value_tokens, values_conflict

_TOKEN = re.compile(r"[a-z0-9]+")


def load_listings(path: Path) -> list[Listing]:
    out = []
    for line in path.open():
        r = json.loads(line)
        out.append(
            Listing(
                id=uuid.UUID(r["id"]),
                supplier_id=uuid.UUID(r["supplier_id"]),
                source=r["source"],
                external_id=r["external_id"],
                domain=r["domain"],
                title_en=r["title_en"],
                title_ar=r["title_ar"],
                part_number=r["part_number"],
                brand=r["brand"],
                price=Decimal(str(r["price"])) if r["price"] is not None else None,
                product_id=uuid.UUID(r["product_id"]) if r["product_id"] else None,
                first_seen_at=datetime.fromisoformat(r["first_seen_at"]),
                attributes=r["attributes"] or {},
                images=[],
            )
        )
    return out


def title_of(listing: Listing) -> str:
    return listing.title_en or listing.title_ar or ""


def evidence(listing: Listing, domain: str) -> g._Evidence:
    title, mpn = title_of(listing), listing.part_number
    return g._Evidence(
        tokens=g._sig_tokens(title, mpn, domain),
        values=value_tokens(g._without_identifier(title, mpn)),
        form=g._form(title, mpn, domain),
    )


def key_of(listing: Listing) -> str:
    return g.base_key(
        listing.part_number, listing.source, listing.external_id, listing.id, listing.domain
    )


def rules_pair(a: Listing, b: Listing) -> bool:
    if not a.part_number or not b.part_number or key_of(a) != key_of(b):
        return False
    groups = g._subcluster(key_of(a), [a, b], a.domain, current={})
    return any(a in members and b in members for members in groups.values())


def vetoes(a: Listing, b: Listing) -> dict[str, bool]:
    domain = a.domain
    profile = get_profile(domain)
    ea, eb = evidence(a, domain), evidence(b, domain)
    prices = [a.price] if a.price is not None else []
    return {
        "same_shop": a.supplier_id == b.supplier_id,
        "values": values_conflict(ea.values, eb.values),
        "form": g._forms_conflict(ea.form, eb.form, profile.accessory_forms),
        "price": not g._span_ok(prices, b.price, profile.merge_price_ratio),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()

    t0 = time.time()
    listings = load_listings(args.catalogue)
    by_id = {str(x.id): x for x in listings}
    stored = {x.id: x.product_id for x in listings}
    changed = g.assign_identifiers(listings)
    t_ident = time.time() - t0
    t1 = time.time()
    groups = g._group_listings(listings, stored)
    t_group = time.time() - t1
    group_of = {x.id: key for key, members in groups.items() for x in members}

    pairs = [json.loads(line) for line in args.pairs.open()]
    result = {}
    for p in pairs:
        a, b = by_id[p["a"]["listing_id"]], by_id[p["b"]["listing_id"]]
        v = vetoes(a, b)
        result[p["pair_id"]] = {
            "rules_pair": rules_pair(a, b),
            "rules_full": group_of[a.id] == group_of[b.id],
            "today_stored": stored[a.id] is not None and stored[a.id] == stored[b.id],
            "shared_key": bool(a.part_number and b.part_number and key_of(a) == key_of(b)),
            "has_identifier": [bool(a.part_number), bool(b.part_number)],
            "veto": v,
            "any_veto": any(v.values()),
        }
    args.out.mkdir(parents=True, exist_ok=True)
    meta = {
        "listings": len(listings),
        "identifiers_changed_by_current_rules": changed,
        "listings_with_identifier": sum(1 for x in listings if x.part_number),
        "groups": len(groups),
        "seconds_assign_identifiers": round(t_ident, 1),
        "seconds_group_listings": round(t_group, 1),
    }
    (args.out / "rules.json").write_text(json.dumps({"meta": meta, "pairs": result}, indent=1))

    args.work.mkdir(parents=True, exist_ok=True)
    with (args.work / "listing_features.jsonl").open("w") as f:
        for x in listings:
            noise = get_profile(x.domain).noise_tokens
            words = _TOKEN.findall(title_of(x).lower())
            tokens = sorted({t for t in words if t not in noise and len(t) >= 2})
            row = {
                "id": str(x.id),
                "domain": x.domain,
                "supplier_id": str(x.supplier_id),
                "part_number": x.part_number,
                "key": key_of(x) if x.part_number else None,
                "tokens": tokens,
            }
            f.write(json.dumps(row) + "\n")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
