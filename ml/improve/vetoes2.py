"""Experiment 1: recalibrated vetoes, beside today's, on the labelled Phase E pairs.

    $(cd apps/ingestion && poetry env info -p)/bin/python ml/improve/vetoes2.py \
        --work <private>/phaseE-labels/work --improve ml/out/improve

Today's three vetoes (ml/bakeoff/rules.py) are recomputed with makhzan_schemas, then each is
recalibrated as the experiment brief asks. Every change is a named knob, so the report can say
how many were tuned on the labelled pairs:

- **price** (`PRICE_RATIO`): veto only at a ratio of 10 or more, or above today's 4x when the
  two titles state different pack quantities (read as in `quantity` below). Today: any ratio
  above 4.
- **quantity** (`QTY_WORDS`): the values veto reads a pack quantity also from "2x AAA",
  "two / three ... batteries" and "pair", so "2xAAA" and "Pack of 2" agree. Today a title that
  states "Pack of 2" conflicts with "2xAAA", read as one unit.
- **form** (four knobs; form words must say what the listing *is*):
  - `WITH`: a marker introduced by "with", "w/", "+", "&" or "and" (within two words) describes
    something included ("with heat sink", "+ aluminium shell"), not the listing's form.
  - `HEAD`: an accessory word followed by board/shield/module ("expansion board", "adapter
    shield") names a module, not an accessory.
  - `FOR`: an accessory word states an accessory only when the title says what it is for
    ("bracket for HC-SR04", "case for Arduino"); "battery holder" or "charger adapter" is
    itself the product, so the strict accessory-vs-silent conflict no longer fires for it.
  - `SMD`: "SMD" is a mounting style (boards, LEDs and chips all say it), so it no longer
    states the chip form. Package names (SOP-8, TO-220...) still do.

Writes <improve>/vetoes2.json: pair id -> {"old": {...}, "new": {...}} (flags only).
"""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

from makhzan_schemas import grouping as g
from makhzan_schemas.domains import get_profile
from makhzan_schemas.values import value_tokens, values_conflict

DOMAIN = "electronics"
PRICE_RATIO = Decimal(10)
TODAY_RATIO = Decimal(4)

_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10, "pair": 2}
# "2xAAA", "2 x AA batteries", but not "5.5 x 2.1mm", "4X magnifier" or "x3" (a sensor count).
_QTY_X = re.compile(
    r"(?<![\w.])(\d+)\s*x\s*(?=(?:aaa?|batter\w*|pcs|pieces|cells?)\b)", re.IGNORECASE
)
_QTY_WORD = re.compile(
    r"\b(two|three|four|five|six|ten)\s+(?:batter\w*|pieces|pcs|cells?|units)\b"
    r"|\b(pair)\s+of\b",
    re.IGNORECASE,
)

_ACCESSORY = re.compile(
    r"\b(?:brackets?|holders?|mounting|cases?|covers?|enclosure|housing|stand|expansion"
    r"|heat\s?sinks?|heatsinks?|mounts?|adapters?)\b",
    re.IGNORECASE,
)
_MOUNTING_STYLES = ("pcb", "panel", "surface", "rail", "chassis", "screw", "hole")
_WITH = re.compile(r"(?:\bwith|\bw/|\+|&|\band)\s+(?:[\w.-]+\s+){0,2}$", re.IGNORECASE)
_FOR = re.compile(r"^\W*(?:(?!with\b)[\w.-]+\W+)?for\b", re.IGNORECASE)
_EXPANSION_MODULE = re.compile(r"^\s*(?:boards?|shields?|modules?)\b", re.IGNORECASE)
_MODULE = re.compile(
    r"\b(?:modules?|boards?|shields?|kits?|breakout|devkit|development)\b", re.IGNORECASE
)
_CHIP = re.compile(
    r"\b(?:ics?|chips?|p?dip|soic|sop|[st]?ssop|msop|[lt]?qfp|qfn|sot-?\d+|to-?\d+)\b",
    re.IGNORECASE,
)
_CHIP_TODAY = re.compile(
    r"\b(?:ics?|chips?|smd|p?dip|soic|sop|[st]?ssop|msop|[lt]?qfp|qfn|sot-?\d+|to-?\d+)\b",
    re.IGNORECASE,
)


def quantity(title: str) -> frozenset[Decimal]:
    """Pack quantities a title states: values.py's reading plus "2x AAA" and number words."""
    found = set(value_tokens(title).get("quantity", ()))
    for m in _QTY_X.finditer(title):
        found.add(Decimal(m.group(1)))
    for m in _QTY_WORD.finditer(title):
        found.add(Decimal(_NUMBER_WORDS[(m.group(1) or m.group(2)).lower()]))
    return frozenset(found) or frozenset({Decimal(1)})


def values_conflict_v2(ta: str, tb: str) -> bool:
    va, vb = dict(value_tokens(ta)), dict(value_tokens(tb))
    va.pop("quantity", None)
    vb.pop("quantity", None)
    return values_conflict(va, vb) or not (quantity(ta) & quantity(tb))


def _accessory_stated(text: str) -> tuple[bool, bool]:
    """(states an accessory form, mentions an expansion board i.e. a module)."""
    accessory, module = False, False
    for m in _ACCESSORY.finditer(text):
        before, after = text[: m.start()], text[m.end() :]
        word = m.group(0).lower()
        if _WITH.search(before):
            continue  # "with heat sink": an included part, not the listing's form
        if word.startswith("mount") and any(
            re.search(rf"\b{s}[\s-]$", before, re.IGNORECASE) for s in _MOUNTING_STYLES
        ):
            continue  # "PCB mount": how the part is fitted (today's rule)
        if _EXPANSION_MODULE.search(after):
            module = True  # "expansion board", "adapter shield": the listing is a module
            continue
        if _FOR.search(after):
            accessory = True
    return accessory, module


def form_v2(title: str, mpn: str | None) -> str | None:
    text = g._without_identifier(title, mpn)
    accessory, module = _accessory_stated(text)
    if accessory:
        return "accessory"
    if module or _MODULE.search(text):
        return "module"
    if _CHIP.search(text):
        return "chip"
    return None


def vetoes(ta: str, tb: str, ma, mb, pa, pb) -> dict[str, dict[str, bool]]:
    profile = get_profile(DOMAIN)
    xa, xb = g._without_identifier(ta, ma), g._without_identifier(tb, mb)
    old = {
        "values": values_conflict(value_tokens(xa), value_tokens(xb)),
        "form": g._forms_conflict(
            g._form(ta, ma, DOMAIN), g._form(tb, mb, DOMAIN), profile.accessory_forms
        ),  # fmt: skip
        "price": not g._span_ok([pa] if pa is not None else [], pb, profile.merge_price_ratio),
    }
    known = [p for p in (pa, pb) if p is not None and p > 0]
    ratio = max(known) / min(known) if len(known) == 2 else Decimal(1)
    qty_differs = not (quantity(xa) & quantity(xb))
    new = {
        "values": values_conflict_v2(xa, xb),
        "form": g._forms_conflict(form_v2(ta, ma), form_v2(tb, mb), profile.accessory_forms),
        "price": ratio >= PRICE_RATIO or (ratio > TODAY_RATIO and qty_differs),
    }
    return {"old": old, "new": new}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--improve", type=Path, required=True)
    args = ap.parse_args()

    listings = {}
    for line in (args.improve / "listings.jsonl").open():
        r = json.loads(line)
        listings[r["id"]] = r
    mpn = {}
    for line in (args.work / "listing_features.jsonl").open():
        r = json.loads(line)
        if r["id"] in listings:
            mpn[r["id"]] = r["part_number"]
    out = {}
    for line in (args.improve / "pairs.jsonl").open():
        p = json.loads(line)
        a, b = listings[p["listing_a"]], listings[p["listing_b"]]

        def price(r):
            return Decimal(str(r["price"])) if r["price"] is not None else None

        v = vetoes(a["title_en"] or a["title_ar"] or "", b["title_en"] or b["title_ar"] or "",
                   mpn[a["id"]], mpn[b["id"]], price(a), price(b))  # fmt: skip
        if v["old"] != {k: p["veto"][k] for k in ("values", "form", "price")}:
            raise SystemExit(f"{p['pair_id']}: today's vetoes do not reproduce key.jsonl")
        out[p["pair_id"]] = v
    (args.improve / "vetoes2.json").write_text(json.dumps(out))
    print(f"{len(out)} pairs; today's vetoes reproduce key.jsonl exactly")


if __name__ == "__main__":
    main()
