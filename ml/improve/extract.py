"""Experiment 2: extract a small attribute schema per listing with a local generative model,
then compare two listings by code. A stated contradiction is a veto; silence is compatible.

    python3 ml/improve/extract.py run --improve ml/out/improve      # needs gen-qwen3-4b up
    python3 ml/improve/extract.py compare --improve ml/out/improve

`run` sends each listing in a labelled pair (title and the shop's category) to
`gen-qwen3-4b` (Qwen/Qwen3-4B-Instruct-2507, bf16, vLLM), greedy, with the output constrained
to SCHEMA by vLLM's structured outputs. Writes <improve>/attributes.jsonl ({id, attrs}; text
derived from titles, so it stays in git-ignored ml/out).

`compare` applies `contradictions(a, b)` to every labelled pair and writes
<improve>/attr_veto.json = {pair_id: [reason, ...]} (empty list = no contradiction).

The comparison is deliberately narrow, from the owner's labelling rulings: different part
numbers (neither a prefix of the other), different forms (bare component / module-or-board /
kit / accessory / cable), different pack quantities (unstated = 1), NO vs NC, different USB
connector, different package (or SMD vs through-hole), a different pin count, and a different
key value of one dimension (resistance, capacitance, voltage, current, power, temperature,
length, angle, frequency, charge) with no value in common within 2%. Product type is not
compared: free text differs in wording far more often than in meaning.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "bakeoff"))
from contexts import clean, shop_category  # noqa: E402

MODEL_SERVICE = "gen-qwen3-4b"
SYSTEM = (
    "You read one product listing from an Egyptian electronics shop and extract what the "
    "listing itself states, as JSON. Never guess: use null (or an empty list) for anything the "
    "listing does not state. Keep part numbers exactly as written, with their suffixes."
)
PROMPT = """Listing title: {title}
Shop category: {category}

Fields:
- product_type: what the item is, 1-4 words (e.g. "trimmer potentiometer", "MOSFET",
  "motor driver module", "battery holder").
- part_numbers: every manufacturer part number or model code stated (e.g. "IRF630N",
  "ATmega328P-PU", "3296W-1-504", "GP2Y0A21YK"); not sizes, not values, not shop SKUs.
- form: "bare_component" (a chip, transistor, diode, resistor, connector, switch...),
  "module" (a small PCB carrying a component: sensor module, breakout, driver board),
  "board" (a development or controller board such as Arduino, ESP32 dev board),
  "kit", "accessory" (a holder, case, bracket, mount, cover or spare part made FOR another
  item), "cable", or "other" (tools, devices, materials); null if unclear.
- pack_quantity: how many units the listing sells (e.g. "10pcs" = 10, "pack of 2" = 2,
  "2x AAA batteries" = 2); null if not stated. Pin, channel or cell counts are not packs.
- values: key ratings stated, each {{"name", "value", "unit"}} with a plain number (e.g.
  {{"name": "resistance", "value": 500000, "unit": "ohm"}} for "500K" or code "504";
  {{"name": "voltage", "value": 12, "unit": "V"}}). Skip ranges.
- contact: "NO", "NC", "NO/NC" for a switch, relay or sensor contact; else null.
- connector: the main connector stated (e.g. "Micro-USB", "Type-C", "Mini-USB", "USB-A",
  "DC 5.5x2.1mm", "JST-XH"); else null.
- package: the component package stated (e.g. "DIP-28", "TO-220", "TO-247", "SOP-8", "SMD",
  "through-hole", "SOD-80"); else null.
- pins: the pin count stated; else null."""

SCHEMA = {
    "type": "object",
    "properties": {
        "product_type": {"type": ["string", "null"]},
        "part_numbers": {"type": "array", "items": {"type": "string"}},
        "form": {
            "enum": [
                "bare_component",
                "module",
                "board",
                "kit",
                "accessory",
                "cable",
                "other",
                None,
            ]
        },  # fmt: skip
        "pack_quantity": {"type": ["integer", "null"]},
        "values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                },
                "required": ["name", "value", "unit"],
            },
        },
        "contact": {"enum": ["NO", "NC", "NO/NC", None]},
        "connector": {"type": ["string", "null"]},
        "package": {"type": ["string", "null"]},
        "pins": {"type": ["integer", "null"]},
    },
    "required": [
        "product_type",
        "part_numbers",
        "form",
        "pack_quantity",
        "values",
        "contact",
        "connector",
        "package",
        "pins",
    ],  # fmt: skip
}


# --- comparison --------------------------------------------------------------------------------

_FORM_GROUP = {"bare_component": "bare", "module": "module", "board": "module", "kit": "kit",
               "accessory": "accessory", "cable": "cable"}  # fmt: skip
_UNIT_DIM = {
    "ohm": ("resistance", 1), "ω": ("resistance", 1), "kohm": ("resistance", 1e3),
    "kω": ("resistance", 1e3), "k": ("resistance", 1e3), "mohm": ("resistance", 1e6),
    "f": ("capacitance", 1), "uf": ("capacitance", 1e-6), "µf": ("capacitance", 1e-6),
    "μf": ("capacitance", 1e-6), "nf": ("capacitance", 1e-9), "pf": ("capacitance", 1e-12),
    "v": ("voltage", 1), "vdc": ("voltage", 1), "vac": ("voltage", 1), "mv": ("voltage", 1e-3),
    "kv": ("voltage", 1e3), "a": ("current", 1), "ma": ("current", 1e-3),
    "w": ("power", 1), "mw": ("power", 1e-3), "kw": ("power", 1e3),
    "°c": ("temperature", 1), "c": ("temperature", 1), "℃": ("temperature", 1),
    "mm": ("length", 1), "cm": ("length", 10), "m": ("length", 1000),
    "°": ("angle", 1), "deg": ("angle", 1), "degree": ("angle", 1), "degrees": ("angle", 1),
    "hz": ("frequency", 1), "khz": ("frequency", 1e3), "mhz": ("frequency", 1e6),
    "ghz": ("frequency", 1e9), "mah": ("charge", 1), "ah": ("charge", 1e3),
}  # fmt: skip
_THT = re.compile(r"dip|to-?92|to-?220|to-?247|to-?3p?\b|axial|do-?35|do-?41|through", re.I)
_SMD = re.compile(r"smd|sop|soic|ssop|qfn|qfp|sot|sod|sma\b|smb\b|smc\b|0[468]0[0-9]|1206", re.I)


def _norm_pn(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _pn_compatible(a: str, b: str) -> bool:
    x, y = _norm_pn(a), _norm_pn(b)
    return bool(x and y) and (x.startswith(y) or y.startswith(x) or x in y or y in x)


def _usb(c: str | None) -> str | None:
    if not c:
        return None
    c = c.lower()
    if re.search(r"type[\s-]?c|usb[\s-]?c\b", c):
        return "type-c"
    if "micro" in c:
        return "micro"
    if "mini" in c:
        return "mini"
    return None


def _package(p: str | None) -> tuple[str | None, str | None]:
    """(specific package such as 'TO220', class 'smd' / 'tht')."""
    if not p:
        return None, None
    cls = "smd" if _SMD.search(p) else "tht" if _THT.search(p) else None
    m = re.search(r"\b(to|sot|sod|dip|sop|soic|qfn|qfp)[\s-]?(\d+)", p, re.I)
    spec = (m.group(1).upper().replace("SOIC", "SOP") + m.group(2)) if m else None
    return spec, cls


def _values(attrs: dict) -> dict[str, set[float]]:
    out: dict[str, set[float]] = {}
    for v in attrs.get("values") or []:
        unit = str(v.get("unit", "")).strip().lower().replace(" ", "")
        if unit not in _UNIT_DIM or not isinstance(v.get("value"), int | float):
            continue
        dim, mult = _UNIT_DIM[unit]
        out.setdefault(dim, set()).add(float(v["value"]) * mult)
    return out


def contradictions(a: dict, b: dict) -> list[str]:
    why = []
    pa, pb = a.get("part_numbers") or [], b.get("part_numbers") or []
    if pa and pb and not any(_pn_compatible(x, y) for x in pa for y in pb):
        why.append("part_number")
    fa, fb = _FORM_GROUP.get(a.get("form")), _FORM_GROUP.get(b.get("form"))
    if fa and fb and fa != fb:
        why.append("form")
    if (a.get("pack_quantity") or 1) != (b.get("pack_quantity") or 1):
        why.append("pack")
    if {a.get("contact"), b.get("contact")} == {"NO", "NC"}:
        why.append("contact")
    ua, ub = _usb(a.get("connector")), _usb(b.get("connector"))
    if ua and ub and ua != ub:
        why.append("connector")
    (sa, ca), (sb, cb) = _package(a.get("package")), _package(b.get("package"))
    if (sa and sb and sa != sb) or (ca and cb and ca != cb):
        why.append("package")
    if a.get("pins") and b.get("pins") and a["pins"] != b["pins"]:
        why.append("pins")
    va, vb = _values(a), _values(b)
    for dim in va.keys() & vb.keys():
        if not any(abs(x - y) <= 0.02 * max(abs(x), abs(y)) for x in va[dim] for y in vb[dim]):
            why.append(f"value:{dim}")
    return why


def run(improve: Path, in_flight: int) -> None:
    from makhzan_ml.client import Client

    rows = [json.loads(line) for line in (improve / "listings.jsonl").open()]
    prompts = [
        PROMPT.format(
            title=clean(r["title_en"] or r["title_ar"]),
            category=shop_category(r.get("attributes") or {}) or "(none)",
        )
        for r in rows
    ]
    client = Client(MODEL_SERVICE, batch_size=in_flight)
    t = time.time()
    out = client.chat_json(prompts, SCHEMA, system=SYSTEM)
    seconds = time.time() - t
    with (improve / "attributes.jsonl").open("w") as f:
        for r, attrs in zip(rows, out, strict=True):
            f.write(json.dumps({"id": r["id"], "attrs": attrs}, ensure_ascii=False) + "\n")
    meta = {"model": "Qwen/Qwen3-4B-Instruct-2507", "service": MODEL_SERVICE,
            "listings": len(rows), "seconds": round(seconds, 1), "in_flight": in_flight}  # fmt: skip
    (improve / "attributes.meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


def compare(improve: Path) -> None:
    attrs = {}
    for line in (improve / "attributes.jsonl").open():
        r = json.loads(line)
        attrs[r["id"]] = r["attrs"]
    out = {}
    for line in (improve / "pairs.jsonl").open():
        p = json.loads(line)
        out[p["pair_id"]] = contradictions(attrs[p["listing_a"]], attrs[p["listing_b"]])
    (improve / "attr_veto.json").write_text(json.dumps(out))
    print(f"{sum(bool(v) for v in out.values())} of {len(out)} pairs contradict")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("step", choices=["run", "compare"])
    ap.add_argument("--improve", type=Path, required=True)
    ap.add_argument("--in-flight", type=int, default=16)
    args = ap.parse_args()
    run(args.improve, args.in_flight) if args.step == "run" else compare(args.improve)


if __name__ == "__main__":
    main()
