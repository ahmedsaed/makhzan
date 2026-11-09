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


def fold_crosswalk(
    table: dict[str, tuple[str, str]], ignore: tuple[str, ...] | list[str] = ()
) -> dict[str, tuple[str, str]]:
    """Index a crosswalk by normalized name, for lookup.

    Raises on a collision rather than letting one entry silently shadow another:
    two keys that normalize to the same string are a mistake in the table, and
    which of them wins would otherwise depend on dict order. Likewise a name in
    `ignore` (left unmapped on purpose) that is also mapped: the table cannot
    both map a category and say it deliberately does not.
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
    both = sorted(name for name in ignore if normalize_category_name(name) in folded)
    if both:
        raise ValueError(f"crosswalk both maps and ignores {both}")
    return folded


def fold_names(names) -> set[str]:
    """Normalized forms of category names, for comparing what a sweep saw."""
    return {normalize_category_name(name) for name in names}


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
    #: For a source that tags a listing with several categories at once: the
    #: mapped names that win when a listing carries more than one, most preferred
    #: first. A tag listed here beats any tag that is not; between unlisted tags
    #: the source's own order decides. Every name must also be mapped.
    prefer: tuple[str, ...] = ()
    #: Source categories left unmapped on purpose: brand tags, generic buckets,
    #: anything whose name says nothing about type. Not mapped, never guessed
    #: from; listed only so the drift report (`make status`) stops raising them
    #: as new on every sweep. Optional: a crosswalk without the key ignores
    #: nothing. A crosswalk that uses it needs an image that reads it.
    ignore: tuple[str, ...] = ()


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

    unknown = set(data) - {"categories", "partitions", "prefer", "ignore"}
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")

    categories: dict[str, tuple[str, str]] = {}
    for source_name, ref in data.get("categories", {}).items():
        domain, sep, slug = ref.partition(":") if isinstance(ref, str) else ("", "", "")
        if not (sep and domain and slug) or ":" in slug:
            raise ValueError(f"{path}: {source_name!r} must map to 'domain:slug', got {ref!r}")
        categories[source_name] = (domain, slug)

    ignore = data.get("ignore", [])
    if not isinstance(ignore, list) or not all(isinstance(n, str) for n in ignore):
        raise ValueError(f"{path}: ignore must be a list of strings")
    try:
        fold_crosswalk(categories, ignore)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None

    partitions = data.get("partitions", [])
    if not all(isinstance(p, str) for p in partitions):
        raise ValueError(f"{path}: partitions must be a list of strings")

    prefer = data.get("prefer", [])
    if not isinstance(prefer, list) or not all(isinstance(p, str) for p in prefer):
        raise ValueError(f"{path}: prefer must be a list of strings")
    mapped = {normalize_category_name(n) for n in categories}
    folded_prefer = [normalize_category_name(p) for p in prefer]
    # A preference for a name that is not mapped can never fire — most likely a
    # typo, or a mapping since removed — so it is refused rather than kept dead.
    unmapped = [p for p, key in zip(prefer, folded_prefer) if key not in mapped]
    if unmapped:
        raise ValueError(f"{path}: prefer names categories that are not mapped: {unmapped}")
    if len(set(folded_prefer)) != len(folded_prefer):
        raise ValueError(f"{path}: prefer lists a category twice")
    return Crosswalk(
        name=name,
        categories=categories,
        partitions=tuple(partitions),
        prefer=tuple(prefer),
        ignore=tuple(ignore),
    )


def list_crosswalks(directory: Path | None = None) -> list[str]:
    """Names of every crosswalk file present, for checks that cover them all."""
    return sorted(p.stem for p in (directory or crosswalk_dir()).glob("*.toml"))
