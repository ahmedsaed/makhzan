"""What a spare part fits, as the shop states it.

A spare-parts buyer searches by machine: "neptune 4 nozzle", "k2 plus fan". Shops
say what a part fits in two ways — in the title ("Extruder Kit for Neptune 4
Plus / 4 Max") and as a product option ("Printer Model: Anycubic Photon M3").
Both are read here into display strings.

**Display only. Never evidence that two listings are the same product.** A title
naming a machine is exactly the "bracket for SG90" case in CLAUDE.md: two parts
for the same printer are different parts.

Titles are noisy ("for Casting jewelry 500g", "for 1.75mm", "for Arduino"), so a
"for …" phrase is kept only when it names a machine family from `_FAMILIES`. A
fit missed is a line the buyer can still read in the title; a fit invented is a
wrong fact on the product page.
"""

from __future__ import annotations

import re

#: Option names whose values are the machines a part fits.
COMPATIBILITY_OPTIONS = {
    "printer model",
    "printer",
    "compatibility",
    "compatible with",
    "compatible model",
    "compatible models",
    "fits",
}

#: 3D printer and CNC families a spare-part title names. Lowercase words; a
#: phrase is kept when one of its words is one of these.
_FAMILIES = {
    "anycubic", "kobra", "photon", "bambu", "bambulab", "a1", "x1", "x1c", "x1e",
    "p1", "p1p", "p1s", "h2d", "h2s", "x2d", "p2s", "elegoo", "neptune", "centauri",
    "orangestorm", "mars", "saturn", "jupiter", "creality", "ender", "cr10", "cr-10",
    "cr10s", "k1", "k1c", "k2", "prusa", "voron", "phrozen", "flashforge", "artillery",
    "sidewinder", "qidi", "sovol", "tronxy", "ams",
}  # fmt: skip

_FOR = re.compile(r"\bfor\b", re.I)
#: Where a "for …" phrase stops being about the machine.
_TAIL = re.compile(
    r"\s+(?:[–—-]\s+(?=upgrade|replacement|original)|\(\s*\d+\s*(?:pcs?|v)\b|3d\s*printers?\b"
    r"|upgrade\b|replacement\b|with\b|hardened\b|stainless\b).*$",
    re.I,
)
_MAX_LEN = 80
_MAX_ITEMS = 20


def _words(text: str) -> set[str]:
    """Words of `text`, with hyphenated ones also split: "cr-10" gives cr-10, cr, 10."""
    words = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower()))
    return words | {piece for word in words for piece in word.split("-")}


def from_title(title: str | None) -> list[str]:
    """The machine a title says the part is for, if it names one we recognise."""
    if not title:
        return []
    # The last "for" is the one about the machine: "Mount for E3D Hotends for
    # CR10S" mounts a hotend, and the hotend is what fits the CR10S.
    for match in reversed(list(_FOR.finditer(title))):
        phrase = _TAIL.sub("", title[match.end() :]).strip(" -–—|,.:;")
        phrase = " ".join(phrase.split())
        if phrase and len(phrase) <= _MAX_LEN and _words(phrase) & _FAMILIES:
            return [phrase]
    return []


def from_options(options: dict[str, list[str]]) -> list[str]:
    """Values of the options that name what the part fits ("Printer Model")."""
    out: list[str] = []
    for name, values in options.items():
        if name.strip().lower() in COMPATIBILITY_OPTIONS:
            out.extend(v for v in values if v and len(v) <= _MAX_LEN)
    return out


def merge(*lists: list[str]) -> list[str]:
    """Every fit once, in the order first stated, capped."""
    seen: set[str] = set()
    out: list[str] = []
    for value in (v for values in lists for v in values):
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out[:_MAX_ITEMS]
