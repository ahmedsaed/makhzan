"""Value tokens — the number-and-unit facts in a title that make two variants differ.

A shop sells a KSD301 thermal switch at 40 °C and another at 140 °C, an ESP32
board with 30 pins and one with 38, a servo that turns 180° and one that turns
continuously. The titles share the part number and almost every word; what tells
them apart is a number next to a unit. Title-token similarity cannot see that —
it threw pure digits away, and "38" and "30" are the whole difference — so these
are pulled out of the title *before* any noise stripping and compared on their own.

Each value is reduced to (dimension, magnitude in the base unit), so "0.75kW"
and "750 W" are the same value and "12v" and "12 Volt" agree.

Only **single** values are kept. A range ("9-42V", "380…500 V") is an operating
envelope that two listings of the same part describe slightly differently; a
single value ("12V fan", "4-channel") is what a shop picks a variant by.

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
_unit("amp", "1", "a", "amp", "amps")
_unit("amp", "0.001", "ma")
_unit("charge", "1", "mah")
_unit("pin", "1", "pin", "pins", "p")
_unit("channel", "1", "ch", "channel", "channels")
_unit("angle", "1", "°", "deg", "degree", "degrees")
_unit("temperature", "1", "°c", "℃", "c", "degc")
_unit("length", "1", "mm")
_unit("length", "10", "cm")
_unit("length", "1000", "m", "meter", "meters", "metre", "metres")
_unit("length", "25.4", "inch", "inches", '"')
_unit("mass", "1", "g", "gram", "grams")
_unit("mass", "1000", "kg")
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
_GLUED_ONLY = {"c", "p", "k", "m", "r", "a", "g", '"'}

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
# "9-42V", "380…500 V", "12/24V", "3 to 5 V": an envelope, not a variant.
_RANGE = re.compile(
    rf"{_LEFT}{_NUM}\s*(?:-|~|–|…|\.{{2,3}}|/|to)\s*{_NUM}\s*-?\s*(?:{_UNIT_ALT}|{_GLUED_ALT}){_RIGHT}",
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


def value_tokens(title: str | None) -> dict[str, frozenset[Decimal]]:
    """Every single value a title states, as {dimension: {magnitudes}}."""
    text = (title or "").lower()
    text = _RANGE.sub(" ", text)
    found: dict[str, set[Decimal]] = {}
    for match in _VALUE.finditer(text):
        number, unit = match.group(1), (match.group(2) or match.group(3)).lower()
        dimension, multiplier = _UNITS[unit]
        found.setdefault(dimension, set()).add((Decimal(number) * multiplier).normalize())
    for pattern, dimension, value in _PHRASES:
        for match in pattern.finditer(text):
            magnitude = Decimal(match.group(1)) if match.groups() else value
            found.setdefault(dimension, set()).add(magnitude.normalize())
    return {dimension: frozenset(values) for dimension, values in found.items()}


def values_conflict(a: dict[str, frozenset[Decimal]], b: dict[str, frozenset[Decimal]]) -> bool:
    """Whether two titles state different values of the same thing.

    Both must state the dimension and share none of its values; a title that is
    silent on it does not conflict. Quantity is the exception — silence there
    means one unit, so "3Pcs" against a plain title is a conflict.
    """
    for dimension in a.keys() | b.keys():
        left, right = a.get(dimension), b.get(dimension)
        if dimension == "quantity":
            left, right = left or _DEFAULT_QUANTITY, right or _DEFAULT_QUANTITY
        if left and right and not (left & right):
            return True
    return False
