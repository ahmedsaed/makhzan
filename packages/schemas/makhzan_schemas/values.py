"""Value tokens — the number-and-unit facts in a title that make two variants differ.

A shop sells a KSD301 thermal switch at 40 °C and another at 140 °C, an ESP32
board with 30 pins and one with 38, a servo that turns 180° and one that turns
continuously. The titles share the part number and almost every word; what tells
them apart is a number next to a unit. Title-token similarity cannot see that —
it threw pure digits away, and "38" and "30" are the whole difference — so these
are pulled out of the title *before* any noise stripping and compared on their own.

Each value is reduced to (dimension, magnitude in the base unit), so "0.75kW"
and "750 W" are the same value and "12v" and "12 Volt" agree.

A single value ("12V fan", "4-channel") is what a shop picks a variant by. A
range ("9-42V", "380…500 V") is an operating envelope that two listings of the
same part describe slightly differently, so ranges are kept apart and conflict
only when unmistakable: the same floor and very different ceilings (an SSR
switching 5-60 VDC against one switching 5-200 VDC).

Two titles conflict when both state a dimension and they share no value of it.
Silence is not a conflict — "MG996R Servo" says nothing about rotation — with one
exception: a quantity. A title that says "3Pcs" is a pack, and a title that says
nothing is one unit, so they are not the same offer.
"""

from __future__ import annotations

import re
from decimal import Decimal

#: unit spelling -> (dimension, multiplier to the dimension's base unit).
#: Spellings are lowercase, matched as whole words after a number.
_UNITS: dict[str, tuple[str, Decimal]] = {}


def _unit(dimension: str, multiplier: str, *spellings: str) -> None:
    for spelling in spellings:
        _UNITS[spelling] = (dimension, Decimal(multiplier))


_unit("volt", "1", "v", "volt", "volts", "vdc", "vac")
_unit("volt", "1000", "kv")
_unit("volt", "0.001", "mv")
_unit("watt", "1", "w", "watt", "watts")
_unit("watt", "1000", "kw")
_unit("watt", "745.7", "hp")
_unit("pressure", "1", "bar")
_unit("pressure", "0.0689476", "psi")
_unit("amp", "1", "a", "amp", "amps")
_unit("amp", "0.001", "ma")
_unit("charge", "1", "mah")
_unit("charge", "1000", "ah")
_unit("pin", "1", "pin", "pins", "p")
_unit("channel", "1", "ch", "channel", "channels")
_unit("angle", "1", "°", "deg", "degree", "degrees")
_unit("temperature", "1", "°c", "℃", "c", "degc")
_unit("length", "1", "mm")
_unit("length", "10", "cm")
_unit("length", "1000", "m", "meter", "meters", "metre", "metres")
_unit("length", "25.4", "inch", "inches", '"')
# Shops spell grams "gm", "gr", "grm" and "gms" as often as "g".
_unit("mass", "1", "g", "gram", "grams", "gm", "gms", "gr", "grm", "grms")
_unit("mass", "1000", "kg", "kgs")
_unit("volume", "1", "ml", "mls")
_unit("volume", "1000", "l", "ltr", "liter", "liters", "litre", "litres")
_unit("frequency", "1", "hz")
_unit("frequency", "1000", "khz")
_unit("frequency", "1000000", "mhz")
_unit("frequency", "1000000000", "ghz")
_unit("capacitance", "0.000000000001", "pf")
_unit("capacitance", "0.000000001", "nf")
_unit("capacitance", "0.000001", "uf", "µf", "μf")
_unit("resistance", "1", "ohm", "ohms", "ω", "r")
_unit("resistance", "1000", "k", "kohm", "kω")
_unit("resistance", "1000000", "mohm", "mω")
_unit("dof", "1", "dof")
_unit("bit", "1", "bit", "bits")
_unit("quantity", "1", "pcs", "pc", "piece", "pieces", "pack")

#: Bare single-letter units are only read when glued to the number ("90C",
#: "2P", "10K", "3m"): with a space they are far more often a word or a label.
_GLUED_ONLY = {"c", "p", "k", "m", "r", "a", "g", "l", '"'}

_NUM = r"\d+(?:\.\d+)?"
_UNIT_ALT = "|".join(
    re.escape(u) for u in sorted(_UNITS, key=len, reverse=True) if u not in _GLUED_ONLY
)
_GLUED_ALT = "|".join(re.escape(u) for u in sorted(_GLUED_ONLY, key=len, reverse=True))
# A number not glued to a preceding letter or digit (so "MG996R" is not 996 Ω and
# "AMS1117" is not 1117 of anything), then a unit ending at a word boundary.
_LEFT = r"(?<![a-z0-9.])"
_RIGHT = r"(?![a-z0-9])"
_VALUE = re.compile(
    rf"{_LEFT}({_NUM})(?:\s*-?\s*({_UNIT_ALT})|({_GLUED_ALT})){_RIGHT}", re.IGNORECASE
)
# "9-42V", "380…500 V", "12/24V", "3 to 5 V", "5V~60VDC": an envelope, not a
# variant. The first number may carry the unit too, but only the same dimension's
# ("30V-5A" is two values, not a range).
_ANY_UNIT = rf"(?:{_UNIT_ALT}|{_GLUED_ALT})"
_RANGE = re.compile(
    rf"{_LEFT}({_NUM})(?:\s*-?\s*({_ANY_UNIT}))?\s*(?:-|~|–|…|\.{{2,3}}|/|to)\s*({_NUM})"
    rf"\s*-?\s*({_ANY_UNIT}){_RIGHT}",
    re.IGNORECASE,
)
# Words that state a value without a digit.
_PHRASES: list[tuple[re.Pattern[str], str, Decimal]] = [
    (re.compile(r"\bcontinu\w*\s+rotation\b"), "angle", Decimal(360)),
    (re.compile(r"\bsingle[\s-]+channel\b"), "channel", Decimal(1)),
    (re.compile(r"\bdual[\s-]+channel\b"), "channel", Decimal(2)),
    (re.compile(r"\bquad[\s-]+channel\b"), "channel", Decimal(4)),
    (re.compile(r"\bpack\s+of\s+(\d+)\b"), "quantity", Decimal(0)),
]

#: How a title that states no quantity is read: one unit.
_DEFAULT_QUANTITY = frozenset({Decimal(1)})


def _ranges(text: str, found: dict[str, set] | None = None) -> str:
    """Take the ranges out of `text`, recording each as `range:<dimension>`."""

    def take(match: re.Match[str]) -> str:
        lo, first_unit, hi, unit = match.groups()
        dimension, multiplier = _UNITS[unit.lower()]
        if first_unit and _UNITS[first_unit.lower()][0] != dimension:
            return match.group(0)
        if found is not None:
            low = Decimal(lo) * (_UNITS[first_unit.lower()][1] if first_unit else multiplier)
            span = (low.normalize(), (Decimal(hi) * multiplier).normalize())
            found.setdefault(f"range:{dimension}", set()).add(span)
        # "3.2V-35V", each end with its unit, also states its ends as values,
        # as it always has: a fixed "5V" regulator is not a "3.2V-35V" one.
        return match.group(0) if first_unit else " "

    return _RANGE.sub(take, text)


def value_tokens(title: str | None) -> dict[str, frozenset]:
    """Every value a title states: {dimension: {magnitudes}} for single values,
    and {"range:<dimension>": {(low, high)}} for envelopes."""
    found: dict[str, set] = {}
    text = _ranges((title or "").lower(), found)
    for match in _VALUE.finditer(text):
        number, unit = match.group(1), (match.group(2) or match.group(3)).lower()
        dimension, multiplier = _UNITS[unit]
        found.setdefault(dimension, set()).add((Decimal(number) * multiplier).normalize())
    for pattern, dimension, value in _PHRASES:
        for match in pattern.finditer(text):
            magnitude = Decimal(match.group(1)) if match.groups() else value
            found.setdefault(dimension, set()).add(magnitude.normalize())
    return {dimension: frozenset(values) for dimension, values in found.items()}


def _close(x: Decimal, y: Decimal, tolerance: Decimal = Decimal("0.1")) -> bool:
    return abs(x - y) <= tolerance * max(abs(x), abs(y))


def _ranges_conflict(left: frozenset, right: frozenset) -> bool:
    """Two envelopes from the same floor to very different ceilings.

    Ranges are described loosely ("9-42V" and "8-40V" are one converter), so only
    the unmistakable case conflicts: the same low end and a high end more than
    1.5x apart — an SSR switching 5-60 VDC is not one switching 5-200 VDC — and
    neither title states the other's range as well.
    """

    def matched(span, spans) -> bool:
        return any(_close(span[0], s[0]) and _close(span[1], s[1]) for s in spans)

    for a in left:
        for b in right:
            if a[0] != b[0] or not a[1] or not b[1]:
                continue
            ratio = max(a[1], b[1]) / min(a[1], b[1])
            if ratio > Decimal("1.5") and not matched(a, right) and not matched(b, left):
                return True
    return False


def values_conflict(a: dict[str, frozenset], b: dict[str, frozenset]) -> bool:
    """Whether two titles state different values of the same thing.

    Both must state the dimension and share none of its values; a title that is
    silent on it does not conflict. Quantity is the exception — silence there
    means one unit, so "3Pcs" against a plain title is a conflict. Ranges
    conflict only in the narrow case `_ranges_conflict` describes.
    """
    for dimension in a.keys() | b.keys():
        left, right = a.get(dimension), b.get(dimension)
        if dimension.startswith("range:"):
            if left and right and _ranges_conflict(left, right):
                return True
            continue
        if dimension == "quantity":
            left, right = left or _DEFAULT_QUANTITY, right or _DEFAULT_QUANTITY
        if left and right and not (left & right):
            return True
    return False


def without_values(title: str | None) -> str:
    """The title, lower-cased, with every value and range taken out: what is
    left is what a shop says about the product beyond its size or rating."""
    text = _ranges((title or "").lower())
    text = _VALUE.sub(" ", text)
    for pattern, _, _ in _PHRASES:
        text = pattern.sub(" ", text)
    return text


def is_unit(word: str | None) -> bool:
    """Whether a word is a unit this module reads ("ml", "kg", "pcs")."""
    return bool(word) and word.lower() in _UNITS


def is_value(text: str | None) -> bool:
    """Whether `text` is, in its entirety, one number and its unit ("12V", "2000W").

    The tail of something shaped like a model code ("HG-2000W", "DC-12V") is a
    reading, not a model number, when it is a value on its own.
    """
    return bool(text and _VALUE.fullmatch(text.strip().lower()))


#: Words written *before* a number to name the scale, standard or label it is
#: read on. "AWG-16" is a wire gauge, "NEMA-17" a motor frame size, "IP65" an
#: ingress rating, "M8" a thread, "DN50"/"PN16" a nominal diameter and pressure,
#: "PH2"/"PZ2" a screwdriver tip, "P120" a grit, "HSS-10" a drill steel, "CAT6" a cable
#: category, "SS304" a steel grade, "DIN-912" the standard a part follows,
#: "Size-10"/"Class-150" a label and its value. Each says *how big* or *which
#: grade*, never *which product*, so different makers' products share it.
#:
#: This is measurement vocabulary — a closed set of scales and standards bodies
#: that grows with the metrology a trade uses — not a list of product families.
#: CLAUDE.md forbids the latter: a code that turns out to cover several products
#: (CR-10, A2212) is caught by evidence from the catalogue, never by being named
#: (`makhzan_schemas.identifiers`).
SCALE_WORDS: frozenset[str] = frozenset(
    {
        # gauges, frames and ratings
        *("AWG", "SWG", "NEMA", "IP", "IK", "HRC", "GRIT", "MESH"),
        # electrical
        *("AC", "DC", "CAT", "RJ", "USB"),
        # threads and pipe sizes
        *("M", "UNC", "UNF", "NPT", "BSP", "BSPT", "BSPP", "DN", "PN", "SCH"),
        # drive and tip sizes, collet system, abrasive grit. "P" stays: of 107
        # tools and chemicals titles with a P-number, 64 are sanding grits
        # (P80, P120), shared by every brand's sheets. It costs codes such as
        # Ceta Form's P22-150 and Donaldson's P551808. "SW" does not: it named a
        # wrench size no title used, and refused SW-420 sensors.
        *("PH", "PZ", "SDS", "HEX", "TX", "TORX", "ER", "P"),
        # a count or magnification ("x250", "X10")
        "X",
        # standards bodies, and the grades and materials they number
        *("ISO", "DIN", "EN", "BS", "ASME", "ASTM", "AISI", "ANSI", "SAE", "API", "JIS"),
        *("SS", "HSS", "PVC", "PPR", "HDPE", "PE", "RAL"),
        # package outlines: a JEDEC standard for how a part is housed (TO-220,
        # DIP-16, DO-214AA), shared by thousands of different parts
        *("TO", "SOT", "SOD", "SOP", "SOIC", "SSOP", "TSSOP", "MSOP", "DIP", "PDIP"),
        *("QFP", "LQFP", "TQFP", "QFN", "DFN", "BGA", "DO", "LGA", "PLCC", "SIP"),
        # labels that precede a value
        *("NO", "SIZE", "TYPE", "STYLE", "CLASS", "GRADE", "LEVEL", "GROUP"),
    }
)


def is_scale_word(letters: str | None) -> bool:
    """Whether letters written before a number name a scale or label (see `SCALE_WORDS`)."""
    return bool(letters) and letters.upper() in SCALE_WORDS
