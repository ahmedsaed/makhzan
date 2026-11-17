"""No AI decisions, no change: grouping is byte for byte what it was before AI matching.

Synthetic catalogues (seeded, so the same every run) cover identifier families,
variants, values, forms, prices, stated-only identifiers, two departments,
existing products (incumbency, both as random stored product ids and, in a
half of the catalogues, as the realistic `current` a first pass stored before
some listings were reworded and new ones arrived) and a person's rulings
(never_merge, must_merge, forced). `fixtures/grouping_golden.json` holds, per catalogue, the sha256 of
the groups the grouping code produced **before** AI matching existed (origin's
main at the merge of #56), keyed and membered by each listing's natural key.
This test regroups each catalogue with today's code, with no AI argument, with
an empty `AiSame` and with Kev "no" pairs alone, and requires the same hash.
AI cases are tested in `test_grouping_ai.py`, never here.

To regenerate (only after a deliberate change to the rules, never to make
this pass), run this file as a script against the grouping code to freeze:
``python tests/test_grouping_differential.py --write tests/fixtures/grouping_golden.json``.
The catalogues are fictional.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
import uuid
from decimal import Decimal
from pathlib import Path

from makhzan_schemas.enums import SourceType
from makhzan_schemas.grouping import _group_listings
from makhzan_schemas.models import Listing
from makhzan_schemas.overrides import Overrides, pair

SEEDS = 300
GOLDEN = Path(__file__).parent / "fixtures" / "grouping_golden.json"

_WORDS = (
    "board module 30 pin 38 sensor ultrasonic bracket for servo 9g relay 5V 12V 10uF 22uF "
    "capacitor pack 10 pcs with cable kit chip ic dip smd 1 channel 2 channel heat sink "
    "development micro motor driver 180 360 degree red blue"
).split()
_CODES = [None, None, None, "ESP32", "HCSR04", "SG90", "LM7805", "NE555", "DT-830", "TMC2208"]
_TOOL_CODES = [None, "ASR-6014", "DT-830"]
_VALUES = [
    "5V",
    "12V",
    "10uF",
    "22uF",
    "30 pin",
    "38 pin",
    "180 degree",
    "360 degree",
    "40C",
    "90C",
]


def catalogue(seed: int):
    """One seeded catalogue: listings and, half the time, some rulings."""
    rng = random.Random(seed)

    def uid() -> uuid.UUID:
        return uuid.UUID(int=rng.getrandbits(128))

    shops = {f"shop-{c}": uid() for c in "abcdef"}
    products = [uid() for _ in range(8)] + [None] * 5
    listings = []
    for i in range(rng.randint(6, 40)):
        source = rng.choice(list(shops))
        domain = "electronics" if rng.random() < 0.85 else "tools"
        code = rng.choice(_CODES if domain == "electronics" else _TOOL_CODES)
        if listings and rng.random() < 0.4:
            # Another shop's wording of an earlier listing, sometimes with a
            # variant word: what makes real merges, splits and vetoes common.
            earlier = rng.choice(listings)
            domain, code, title = earlier.domain, earlier.part_number, earlier.title_en
            if rng.random() < 0.3:
                title = f"{title} {rng.choice(_WORDS)}"
        else:
            title = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(2, 7)))
            if code and rng.random() < 0.8:
                title = f"{code} {title}" if rng.random() < 0.7 else f"{title} {code}"
        listings.append(
            Listing(
                id=uid(),
                supplier_id=shops[source],
                source=source,
                source_type=SourceType.SCRAPED,
                external_id=f"{seed}-{i}",
                domain=domain,
                title_en=title,
                part_number=code,
                price=Decimal(rng.choice([1, 10, 50, 60, 70, 300, 320, 1500])),
                images=[],
                attributes={},
                product_id=rng.choice(products),
            )
        )
    overrides = None
    if rng.random() < 0.5 and len(listings) >= 6:
        a, b, c, d, e, f = rng.sample(listings, 6)
        must = frozenset({pair(a.id, b.id), pair(e.id, f.id)})
        overrides = Overrides(
            never=frozenset({pair(c.id, d.id)}),
            must=must,
            forced=frozenset({pair(a.id, b.id)}) if rng.random() < 0.5 else frozenset(),
        )
    return listings, overrides


def regroup(seed: int, ai=None):
    """The catalogue's groups as the regroup would make them: from its stored
    product ids or, in half of the catalogues, from the `current` a first
    pass stored, after some listings changed and new ones arrived."""
    listings, overrides = catalogue(seed)
    extra = () if ai is None else (ai,)
    if seed % 2:
        return _group_listings(listings, None, overrides, *extra)
    rng = random.Random(seed * 7919)
    first = _group_listings(listings, None, overrides)
    current = {
        member.id: uuid.uuid5(uuid.NAMESPACE_URL, f"{seed}:{key}")
        for key, members in first.items()
        for member in members
    }
    for listing in listings:
        roll = rng.random()
        if roll < 0.1:  # reworded: another listing's title
            listing.title_en = rng.choice(listings).title_en
        elif roll < 0.25:  # a value now stated
            listing.title_en = f"{listing.title_en} {rng.choice(_VALUES)}"
    # Newcomers since the first pass: other shops' copies of a settled
    # product's wording, some stating a value that contradicts it, sorting
    # ahead of it (the case incumbency exists for).
    settled = [members for members in first.values() if len(members) > 1]
    for i in range(rng.randint(2, 6)):
        model = rng.choice(rng.choice(settled) if settled else listings)
        title = model.title_en
        if rng.random() < 0.9:
            title = f"{title} {rng.choice(_VALUES)}"
        listings.append(
            Listing(
                id=uuid.UUID(int=rng.getrandbits(128)),
                supplier_id=uuid.UUID(int=rng.getrandbits(128)),
                source=f"new-{i}",
                source_type=SourceType.SCRAPED,
                external_id=f"0-{seed}-{i}",
                domain=model.domain,
                title_en=title,
                part_number=model.part_number,
                price=model.price,
                images=[],
                attributes={},
                product_id=None,
            )
        )
    return _group_listings(listings, current, overrides, *extra)


def shape_hash(groups) -> str:
    """The groups by natural key, canonical, hashed."""
    shape = {
        key: sorted(f"{m.source}:{m.external_id}" for m in members)
        for key, members in groups.items()
    }
    text = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def test_with_no_ai_decision_grouping_matches_the_frozen_output_of_before():
    from makhzan_schemas.ai.decisions import AiSame

    golden = json.loads(GOLDEN.read_text())
    assert len(golden) == SEEDS
    for seed in range(SEEDS):
        want = golden[str(seed)]
        assert shape_hash(regroup(seed)) == want, seed
        assert shape_hash(regroup(seed, AiSame())) == want, seed
        # Kev "no" pairs with no "same" pair can block nothing.
        listings, _ = catalogue(seed)
        no = frozenset(pair(a.id, b.id) for a, b in zip(listings, listings[1:]))
        assert shape_hash(regroup(seed, AiSame(no=no))) == want, seed


if __name__ == "__main__" and sys.argv[1:2] == ["--write"]:
    out = {str(seed): shape_hash(regroup(seed)) for seed in range(SEEDS)}
    Path(sys.argv[2]).write_text(json.dumps(out, indent=0, sort_keys=True) + "\n")
    print(f"wrote {len(out)} catalogue hashes")
