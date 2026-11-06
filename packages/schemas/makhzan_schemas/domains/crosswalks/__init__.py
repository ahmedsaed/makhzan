"""Supplier category crosswalks, and the name normalization they are keyed on.

A crosswalk maps a supplier's own category name to ours. The tables themselves
are data, not code — one TOML file per supplier in `crosswalk_dir()`, loaded by
`load_crosswalk`. They are hand-authored and change under review, so they are
files rather than database rows; and they are kept out of this package because
they describe particular suppliers, while the code here describes none.

The keys are exact
strings, which makes them quietly fragile: a shop that re-types "Diodes - General
Purpose" with an en-dash, or "0603x4" with a multiplication sign, keeps the same
category and the same products but stops matching. The mapping does not error —
those listings simply lose their category, which looks identical to the supplier
discontinuing them.

That is not hypothetical. Comparing the crosswalks authored from a July snapshot
against the live shops found six keys already dead this way:

    shop 1  'Diodes - General Purpose'      live 'Diodes – General Purpose'
            'Diodes - Fast Recovery Rectifiers'
            'SMD Diodes - General Purpose'
            '0603x4 Resistor'               live '0603×4 Resistor'
    shop 2  "X - power batteries"           live 'X – power batteries'
            "ADC & DAC Converters IC's"     live 'ADC & DAC Converters IC’s'

So lookups go through `normalize_category_name`, which folds the punctuation a
CMS rewrites on its own — dashes, quotes, the multiplication sign, whitespace and
case. It deliberately does **not** touch words: a crosswalk still has to name the
category the supplier actually publishes. Real renames stay the drift report's
job (see `make status`), because only a human can tell a rename from a retirement.
"""

from __future__ import annotations

import html
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from makhzan_schemas.config import crosswalk_dir

#: Characters a CMS or an editor's keyboard swaps in without meaning to change
#: anything: dash variants, smart quotes, and the multiplication sign that Word
#: substitutes into "0603x4".
_CONFUSABLES = str.maketrans(
    {
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "‒": "-",  # figure dash
        "–": "-",  # en dash
        "—": "-",  # em dash
        "―": "-",  # horizontal bar
        "−": "-",  # minus sign
        "×": "x",  # multiplication sign
        "‘": "'",  # left single quote
        "’": "'",  # right single quote
        "‛": "'",
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        " ": " ",  # non-breaking space
    }
)


def normalize_category_name(name: str | None) -> str:
    """Canonical form of a supplier category name, for crosswalk lookup.

    HTML-unescapes (the WooCommerce Store API sends "&amp;"), applies NFKC,
    folds the confusable punctuation above, collapses whitespace and case.
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", html.unescape(name))
    text = text.translate(_CONFUSABLES)
    return re.sub(r"\s+", " ", text).strip().casefold()


def fold_crosswalk(table: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """Index a crosswalk by normalized name, for lookup.

    Raises on a collision rather than letting one entry silently shadow another:
    two keys that normalize to the same string are a mistake in the table, and
    which of them wins would otherwise depend on dict order.
    """
    folded: dict[str, tuple[str, str]] = {}
    for name, target in table.items():
        key = normalize_category_name(name)
        if key in folded and folded[key] != target:
            raise ValueError(
                f"crosswalk keys collide after normalization: {key!r} "
                f"maps to both {folded[key]} and {target}"
            )
        folded[key] = target
    return folded


@dataclass(frozen=True)
class Crosswalk:
    """One supplier's category table, as loaded from `<name>.toml`.

    The file maps each source category to a `domain:slug` ref — the same
    identifier categories carry everywhere else, because a slug alone is
    ambiguous across domains:

        [categories]
        "Ceramic Capacitors" = "electronics:capacitors"
    """

    name: str
    #: Source category -> (domain, taxonomy leaf slug), in file order.
    categories: dict[str, tuple[str, str]]
    #: For a source browsed *by* category: the categories to sweep. Deliberately
    #: wider than `categories` — an unmapped category still has to be visited, or
    #: its listings are never seen again and a completed cycle archives them.
    #: Empty for sources whose categories are read off the listing instead.
    partitions: tuple[str, ...] = ()


def load_crosswalk(name: str, directory: Path | None = None) -> Crosswalk:
    """Load and validate `<directory>/<name>.toml` (default: `crosswalk_dir()`).

    Every malformed entry is a ValueError naming the file, not a silently dead
    mapping: a ref without a domain, an unknown top-level key (a typo'd
    `[categorise]` would otherwise load as an empty crosswalk), or two keys
    that collide once normalized.
    """
    path = (directory or crosswalk_dir()) / f"{name}.toml"
    with path.open("rb") as f:
        data = tomllib.load(f)

    unknown = set(data) - {"categories", "partitions"}
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")

    categories: dict[str, tuple[str, str]] = {}
    for source_name, ref in data.get("categories", {}).items():
        domain, sep, slug = ref.partition(":") if isinstance(ref, str) else ("", "", "")
        if not (sep and domain and slug) or ":" in slug:
            raise ValueError(f"{path}: {source_name!r} must map to 'domain:slug', got {ref!r}")
        categories[source_name] = (domain, slug)
    fold_crosswalk(categories)

    partitions = data.get("partitions", [])
    if not all(isinstance(p, str) for p in partitions):
        raise ValueError(f"{path}: partitions must be a list of strings")
    return Crosswalk(name=name, categories=categories, partitions=tuple(partitions))


def list_crosswalks(directory: Path | None = None) -> list[str]:
    """Names of every crosswalk file present, for checks that cover them all."""
    return sorted(p.stem for p in (directory or crosswalk_dir()).glob("*.toml"))
