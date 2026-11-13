"""Identifier rules: what a title (or a shop) says a product *is*, as a code.

A department's `DomainProfile` lists the rules that apply to it
(`identifier_rules`, tried in order, the first that answers wins) and whether a
shop's own stated part number or model may stand in when the title says
nothing (`shop_stated_identifiers`). Grouping only ever compares identifiers
within one department.

Everything here is **evidence, not proof**. A shared identifier only makes two
listings candidates for one product; `grouping._subcluster` still requires their
titles to agree and lets any of the three vetoes (same shop, value tokens, form)
refuse the merge. A rule's job is therefore to be precise about *what kind of
code* it reads, not to decide identity.

Two kinds of code, and the difference matters:

- **Designations** name a product by a published standard: a bearing (6205-2RS),
  an O-ring by its size (10x2), an oil seal by its three dimensions. Every maker
  uses the same designation for the same thing, so it is identity by
  construction once the parts that change the product (seal, clearance, profile)
  are kept in it.
- **Model codes** are a maker's or a shop's own naming (DT-830, ASR-6014, TU-501).
  Usually one code is one product, but a code is sometimes a *family* — a
  printer model its spare parts are named after (CR-10), a motor size sold at
  several windings (A2212). These are marked `family_checked`, and grouping
  drops one whenever a single shop's catalogue shows it covering several
  different products (`grouping.assign_identifiers`). That guard needs no list:
  the shop itself is the evidence.

Measurements are never codes. "AWG-16", "NEMA-17", "IP65", "M8", "HSS-10" look like
model codes and are readings on a scale (`values.SCALE_WORDS`); "HG-2000W" ends
in a value (`values.is_value`). Both are refused by principle, so the next gauge
or frame size needs no entry anywhere.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from makhzan_schemas.values import is_scale_word, is_unit, is_value


@dataclass(frozen=True)
class Identifier:
    """One identifier read for a listing."""

    #: How it is shown ("DT-830B", "6205-2RS", "O-RING 10X2").
    value: str
    #: A model code that may turn out to name a family; grouping drops it when
    #: one shop lists several different products under it.
    family_checked: bool = False

    @property
    def key(self) -> str:
        return fold_identifier(self.value)


#: A title rule: the title in, the identifier it reads (or None).
IdentifierRule = Callable[[str], Identifier | None]

_SEPARATOR = re.compile(r"(?<!\d)[-\s./_]+|[-\s./_]+(?!\d)")
_BETWEEN_DIGITS = re.compile(r"(?<=\d)[-\s/_]+(?=\d)")


def fold_identifier(value: str) -> str:
    """What grouping compares: case, and separators that only space letters, folded.

    "DT-830", "dt830" and "DT 830" are one code; so are "HC-SR04" and "HCSR04".
    A separator between two digits is kept, because there it separates numbers:
    "AMS1117-3.3" is not "AMS1117-33", and bearing "6205-2RS" is not a "62052".
    It is written one way, a hyphen ("J58 210" is "J58-210"), except a decimal
    point, which is part of the number.
    """
    folded = _SEPARATOR.sub("", value.strip().upper())
    return _BETWEEN_DIGITS.sub("-", folded)


def identifier_pattern(value: str) -> re.Pattern[str]:
    """A case-insensitive pattern matching any spelling of `value` in a title."""
    parts = []
    for ch in fold_identifier(value):
        if ch == "-":
            parts.append(r"[-\s/_]+")
        else:
            if parts and parts[-1] != r"[-\s/_]+":
                parts.append(r"[-\s./_]?")
            parts.append(re.escape(ch))
    return re.compile("".join(parts), re.IGNORECASE)


# --------------------------------------------------------------------------- #
# References
# --------------------------------------------------------------------------- #

#: A code right after "for", "fits", "compatible with"... names what the listing
#: is *used with*, not what it is: "Extruder kit for Creality CR-10" is not a
#: CR-10. After "with" or "including" it names a part the listing comes with:
#: "Digital Logic Kit with ZY-204 Breadboard" is not the breadboard. After "for"
#: up to two words may sit between ("for Creality CR-10"); after "with" none
#: may, because "Monoblock Set with 12 Drawers ASR-6014" is the ASR-6014.
_REFERENCE = re.compile(
    r"(?:\b(?:for|fits?|to\s+suit)\s+(?:[\w&+.'’-]+\s+){0,2}"
    r"|\b(?:with|includ(?:es|ing))\s+)$",
    re.IGNORECASE,
)


def _is_reference(title: str, start: int) -> bool:
    return bool(_REFERENCE.search(title[:start]))


# --------------------------------------------------------------------------- #
# Model codes
# --------------------------------------------------------------------------- #

#: Electronics: the hobby-market model code, capitals, a hyphen, digits — DT-830,
#: DSO-153, TB-1505, KY-032, HLK-10M24. `part_number.extract_part_number` reads
#: codes written without the hyphen ("DT830") already; this is the gap it left.
#: Capitals only: "Pack-10" or "Mesh-40" in title case is a word and a count.
_HYPHEN_CODE = re.compile(
    r"(?<![A-Za-z0-9.\-/])([A-Z]{2,6})-(\d{2,}[A-Z0-9]{0,5})(?:-([A-Z0-9]{1,4}))?"
    r"(?![A-Za-z0-9]|-[A-Za-z0-9])"
)


def hyphenated_model_code(title: str) -> Identifier | None:
    """The first capitals-hyphen-digits model code that is not a reading or a reference."""
    for match in _HYPHEN_CODE.finditer(title):
        letters, tail, suffix = match.groups()
        if is_scale_word(letters) or is_value(tail) or _is_reference(title, match.start()):
            continue
        code = f"{letters}-{tail}"
        if suffix and not is_value(suffix):
            code += f"-{suffix}"
        return Identifier(code, family_checked=True)
    return None


#: Tools and chemicals: a letter-led catalogue code, with or without a separator
#: — ASR-6014, TU-501, MR818, SDL-8611, J58-210, GP999, CP-0001. Measured at about
#: 90% precise in tools (14 cross-shop codes, 12 right). Deliberately *not* the
#: broad "any letters and digits" token (about 15%: it reads "6-in-1", "No.2",
#: "6Piece"), and never a bare size ("5 inch", "3x140mm"), which is never identity.
_MODEL_CODE = re.compile(
    r"(?<![\w.\-/])([A-Za-z]{1,6})(-?)"
    r"(\d{2,}[A-Za-z0-9]{0,4}(?:[-./]\d{1,5}[A-Za-z0-9]{0,3}){0,2})(?!\w|\.\d)"
)
#: What follows a number that makes it a size, not a code: a quote or inch mark
#: (WRENCH12"), a multiplication (PLUS10*450), or a unit word (KEY13 Mm).
_SIZE_AFTER = re.compile(
    r"^(?:\s*[\"”″'’]|\s*[*×xX]\s*\d|\s*(?:mm|cm|mtr|meters?|pcs?|inch(?:es)?|ml|kg|gm)\b)",
    re.IGNORECASE,
)
#: A tail that is a number and a unit the value parser does not read ("16IN").
_UNIT_TAIL = re.compile(r"^\d+(?:IN|INCH|PCS|PC|MIC)$")
#: A trailing segment, which may be a value glued on ("WD40-330ML").
_LAST_SEGMENT = re.compile(r"[-./](\d{1,5}[A-Za-z0-9]{0,3})$")


def _sized(title: str, start: int, end: int) -> bool:
    """Whether the number ending at `end` is a size: followed by an inch mark,
    a multiplication or a unit word. A quote that closes one opened before the
    code ('"TNI-U TU-501"') is punctuation, not inches."""
    after = _SIZE_AFTER.match(title[end:])
    if not after:
        return False
    mark = after.group(0).strip()
    before = title[:start]
    if mark == '"' and before.count('"') % 2:
        return False
    if mark in "”’" and ("“" in before or "‘" in before):
        return False
    return True


def _looks_like_a_word(letters: str, glued: bool, number: str, shouting: bool) -> bool:
    """A word with a small number glued on (File10, Cutter14, WRENCH17), not a code.

    Catalogue prefixes are short (ASR, TU, HSG) or capitals in a mixed-case
    title (TIWLI20208), and carry long numbers. Four or more letters glued to a
    one- or two-digit number are a word and a size — unless written in capitals
    in a title that is otherwise not, where the capitals mark it as a code.
    """
    if not glued or len(letters) < 4 or len(number) > 2:
        return False
    return shouting or not letters.isupper()


def _code_score(letters: str, separator: str, tail: str) -> tuple[int, ...]:
    """How much a candidate looks like a catalogue code; the title's best wins.

    "ASR-2064 Power Organizer Box-13" holds two candidates and the code is the
    first only by luck; "Wrench 17mm N23-011" puts the word first. A hyphen after
    a short prefix, a long number and a further segment are what codes have.
    """
    digits = sum(ch.isdigit() for ch in tail)
    return (
        int(len(letters) <= 3) + int(bool(separator)) + int(digits >= 3) + int("-" in tail),
        digits,
    )


def model_code(title: str) -> Identifier | None:
    """The best letter-led catalogue code that is not a reading, a size, a word
    or a reference; the leftmost wins a tie."""
    best: tuple[tuple[int, ...], int, Identifier] | None = None
    shouting = not re.search(r"[a-z]", title)
    for match in _MODEL_CODE.finditer(title):
        letters, separator, tail = match.groups()
        code = match.group(0)
        while (last := _LAST_SEGMENT.search(code)) and is_value(last.group(1)):
            code = code[: last.start()]
        compact = fold_identifier(code)
        if (
            len(compact) < 4
            or sum(ch.isdigit() for ch in compact) < 2
            # "AWG-16", "M8", "HSS-10": a scale and its reading; "ml-200": a unit
            # (spelled out — a lone letter such as the "G" of G15-18-0200 is a
            # catalogue prefix far more often than grams).
            or is_scale_word(letters)
            or (len(letters) > 1 and is_unit(letters))
            # "HG-2000W": the label of a value, not a model.
            or is_value(tail)
            or _UNIT_TAIL.match(tail.upper())
            or _is_reference(title, match.start())
            or _sized(title, match.start(), match.end())
            or _looks_like_a_word(letters, not separator, re.match(r"\d+", tail).group(0), shouting)
        ):
            continue
        score = _code_score(letters, separator, code[len(letters) + len(separator) :])
        if best is None or score > best[0]:
            best = (score, match.start(), Identifier(code.upper(), family_checked=True))
    return best[2] if best else None


# --------------------------------------------------------------------------- #
# Designations
# --------------------------------------------------------------------------- #

#: Suffixes that change which bearing it is. Seals and shields first, then
#: internal clearance, then design letters (taper bore K, snap ring N/NR, cage
#: and design CC/CA/MB/E/B, lubrication groove W33, linear UU).
_BEARING_SUFFIX = r"(?:2RS[1RH]?|RS[1R]?|DDU|LLU|2Z|ZZ|Z|UU|C[2-5]|NR|N|K|E|B|CC|CA|MB|W33|TN9)"
_BEARING = re.compile(
    rf"(?<![A-Z0-9.\-/])(?:([A-Z]{{1,5}})(\d{{2,6}})|(\d{{3,6}}))((?:[- ]?{_BEARING_SUFFIX})*)"
    r"(?![A-Z0-9])"
)
_BEARING_SUFFIX_TOKEN = re.compile(_BEARING_SUFFIX)
_BEARING_WORD = re.compile(r"\bbearings?\b", re.IGNORECASE)
#: One maker's spelling of a seal -> the common one. 2RS1 (SKF), 2RSR (FAG),
#: DDU (NSK) and LLU (NTN) are all two rubber seals; 2Z (SKF) is ZZ.
_SEALS = {
    "2RS": "2RS", "2RS1": "2RS", "2RSR": "2RS", "2RSH": "2RS", "DDU": "2RS", "LLU": "2RS",
    "RS": "RS", "RS1": "RS", "RSR": "RS",
    "ZZ": "ZZ", "2Z": "ZZ", "Z": "Z",
}  # fmt: skip


def bearing_designation(title: str, *, sealed_only: bool = False) -> Identifier | None:
    """A rolling bearing's designation, with the suffixes that make it a different product.

    6205, 6205-ZZ and 6205-2RS are three products (open, shielded, sealed), and
    C3 is a different internal clearance, so all of them stay in the identifier,
    with each maker's spelling of a seal folded to one ("6205-2RS1" is
    "6205-2RS"). Only read when the title says "bearing".

    `sealed_only` reads only a designation that states its seal or shield
    (608ZZ, 625-2RS): where bearings are a side line, a bare number beside the
    word "bearing" is usually something else — "775 Motor with Ball Bearing",
    "2020 Bearing Wheel".
    """
    if not _BEARING_WORD.search(title):
        return None
    upper = title.upper()
    for match in _BEARING.finditer(upper):
        prefix, prefixed_core, core, tail = match.groups()
        if (prefix and is_scale_word(prefix)) or _is_reference(upper, match.start()):
            continue
        seal = clearance = None
        design = []
        for token in _BEARING_SUFFIX_TOKEN.findall(tail.replace("-", "").replace(" ", "")):
            if token in _SEALS:
                seal = _SEALS[token]
            elif re.fullmatch(r"C[2-5]", token):
                clearance = token
            else:
                design.append(token)
        if sealed_only and not seal:
            continue
        value = f"{prefix or ''}{prefixed_core or core}{''.join(design)}"
        value += f"-{seal}" if seal else ""
        value += f"-{clearance}" if clearance else ""
        return Identifier(value)
    return None


_SIZE = r"(\d{1,4}(?:[.,]\d{1,3})?)"
_BY = r"\s*[x×*]\s*"
_O_RING = re.compile(
    rf"(?<![A-Za-z])o[- ]?rings?(?:\s+[A-Za-z][A-Za-z.]*){{0,3}}\s*{_SIZE}{_BY}{_SIZE}"
    rf"(?!\d|{_BY}\d)",
    re.IGNORECASE,
)
_OIL_SEAL = re.compile(
    rf"oil\s*seals?\s*([A-Za-z]{{1,4}}(?:-[A-Za-z]{{1,4}})?)?[-\s]*{_SIZE}{_BY}{_SIZE}{_BY}{_SIZE}(?!\d)",
    re.IGNORECASE,
)


def _number(text: str) -> str:
    try:
        number = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return text
    return format(number.normalize(), "f")


def miniature_bearing(title: str) -> Identifier | None:
    """A bearing designation only when it states its seal (see `bearing_designation`)."""
    return bearing_designation(title, sealed_only=True)


def o_ring_size(title: str) -> Identifier | None:
    """An O-ring by its size ("O-Ring 10x2" -> "O-RING 10X2"): for an O-ring the
    size is the identity, and the material is left to the titles to agree on."""
    match = _O_RING.search(title)
    if not match:
        return None
    return Identifier(f"O-RING {_number(match.group(1))}X{_number(match.group(2))}")


def oil_seal_size(title: str) -> Identifier | None:
    """An oil seal by its dimensions and, when stated, its profile ("A", "AS",
    "TC"): "Oil seal AS52x25x7" -> "OIL SEAL AS 52X25X7". The profile is kept, so
    a seal with a dust lip never merges with one without; a title silent on it
    stays apart from one that states it — the honest under-merge."""
    match = _OIL_SEAL.search(title)
    if not match:
        return None
    profile = (match.group(1) or "").replace("-", "").upper()
    size = "X".join(_number(match.group(i)) for i in (2, 3, 4))
    return Identifier(" ".join(part for part in ("OIL SEAL", profile, size) if part))


# --------------------------------------------------------------------------- #
# What a shop states
# --------------------------------------------------------------------------- #

#: Spec rows that state the listing's own model (not "Motor Model" or
#: "Supported Models", which name a part it uses or fits).
_MODEL_ROWS = {
    "model", "model number", "model no", "model no.", "product model",
    "model / part number", "model/part number",
}  # fmt: skip
_STATED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-./_]{1,28}(?: [A-Za-z0-9\-]{1,6})?$")


def _stated(value: object) -> Identifier | None:
    """A shop-stated code, if it reads as one: letters and digits, one token
    (plus a short suffix), not a reading ("18650" is a cell size, "AWG-16" a
    gauge)."""
    if not isinstance(value, str):
        return None
    text = value.strip().strip(".-/_")
    if not _STATED.match(text) or not re.search(r"[A-Za-z]", text) or not re.search(r"\d", text):
        return None
    # A scale word and a reading is a measurement: a short number ("AWG-16",
    # "M8", "P120"), a value ("DIP-4P") or a size ("M8X1.25"). The same letter
    # leading a long number a shop states as the part number (Donaldson
    # "P551808") is not.
    reading = re.fullmatch(r"([A-Za-z]+)[-\s]?(.+)", text)
    if reading and is_scale_word(reading.group(1)):
        rest = reading.group(2)
        # A value only when short ("4P", "220V", "7R"): a long number with a
        # letter after it is a part number whose suffix merely looks like a unit
        # (PN2222A, M51231P, ER18505M).
        if (
            re.fullmatch(r"\d{1,4}", rest)
            or (re.fullmatch(r"\d{1,3}(?:\.\d+)?\s*\D.*", rest) and is_value(rest))
            or re.fullmatch(r"\d+(?:\.\d+)?\s*[xX×*]\s*\d+(?:\.\d+)?", rest)
        ):
            return None
    if is_value(text):
        return None
    return Identifier(text.upper(), family_checked=True)


def stated_identifiers(attributes: Mapping | None) -> list[Identifier]:
    """The shop's manufacturer part number, then its "Model" spec, as identifiers.

    Fallbacks only (see `DomainProfile.identifier_candidates`): a title that
    names a code wins. Both are family-checked like any model code — a "Model"
    row reading "A2212" sits on a 1000 KV and a 2200 KV motor alike.
    """
    if not isinstance(attributes, Mapping):
        return []
    found = []
    mpn = _stated(attributes.get("mfr_part_number"))
    if mpn:
        found.append(mpn)
    specs = attributes.get("specs")
    if isinstance(specs, Mapping):
        for name, value in specs.items():
            if isinstance(name, str) and name.strip().lower() in _MODEL_ROWS:
                model = _stated(value)
                if model and all(model.key != f.key for f in found):
                    found.append(model)
                break
    return found
