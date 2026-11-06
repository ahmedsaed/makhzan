"""Per-vertical strategy objects.

makhzan aggregates more than electronics, but almost every enrichment decision —
which category tree applies, what counts as a product identifier, when two
listings are "the same product", how search should rank — is vertical-specific.
A `DomainProfile` bundles those decisions behind one interface so electronics
becomes the *first* profile rather than *the* logic.

Domain is resolved **per listing**, from its category, falling back to the
supplier's default. It is deliberately not a supplier-level property: a
marketplace can span many verticals at once, so keying off the supplier would put
gaskets and microcontrollers in the same taxonomy.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field

#: (slug, name_en, name_ar, parent_slug) — parents are browse groups, leaves are
#: what the resolver assigns.
TaxonomyNode = tuple[str, str, str, str | None]
#: (leaf_slug, keywords) — ORDER IS PRIORITY, most specific first.
CategoryRule = tuple[str, list[str]]

#: Fallback domain for anything that predates the domain column.
DEFAULT_DOMAIN = "electronics"


def _no_identifier(_title: str | None) -> str | None:
    return None


@dataclass(frozen=True)
class DomainProfile:
    """Everything makhzan needs to know about one vertical."""

    slug: str
    name_en: str
    name_ar: str

    #: The category tree seeded into the Category table for this domain.
    taxonomy: list[TaxonomyNode] = field(default_factory=list)
    #: Keyword rules used when a source's own categories are not trustworthy.
    category_rules: list[CategoryRule] = field(default_factory=list)
    #: Supplier category strings too vague to resolve on (skipped before matching).
    generic_categories: frozenset[str] = frozenset()

    #: Title -> product identifier. Electronics extracts an MPN; verticals with no
    #: stable identifier return None and simply group less.
    extract_identifier: Callable[[str | None], str | None] = _no_identifier
    #: Title tokens that do not distinguish products, dropped from signatures.
    noise_tokens: frozenset[str] = frozenset()
    #: Jaccard similarity above which two listings sharing an identifier are
    #: taken to be the same product.
    cluster_threshold: float = 0.34
    #: Price ratio within which two listings sharing an identifier corroborate
    #: each other even when their wording differs. Suppliers describe the same
    #: part very differently, so price is the second opinion.
    merge_price_ratio: float = 4.0
    #: (form, pattern) pairs, highest priority first: what physical *form* a
    #: title says it is, when the noise list has stripped the words that say it.
    #: Two listings sharing an identifier but stating different forms are not
    #: merged — a bare TP4056 chip is not a TP4056 charger module. A title
    #: matching several patterns takes the first. Empty means no form check.
    form_markers: tuple[tuple[str, str], ...] = ()
    #: Forms that a title stating *no* form can never be. Ordinarily silence is
    #: not a conflict ("TP4056 Lithium Battery Charger" may well be the module),
    #: but a bracket, holder or case names the part it fits, so a title that does
    #: not say "holder" is not the holder.
    accessory_forms: frozenset[str] = frozenset()

    #: Meilisearch searchable attributes, highest-ranked first.
    search_attributes: tuple[str, ...] = ("title_en", "title_ar", "brand")
    #: What this vertical calls its identifier in the UI ("Part number", ...).
    identifier_label_en: str = "Identifier"
    identifier_label_ar: str = "المعرّف"

    def leaf_slugs(self) -> set[str]:
        return {slug for slug, *_ in self.category_rules}

    def resolve_category_slug(
        self, category_strings: list[str] | None, title: str | None
    ) -> str | None:
        """Map a listing's supplier categories / title onto a taxonomy leaf slug.

        Tries supplier category strings first (most reliable), then the title.
        Returns None when nothing matches — an explicit miss is better than a
        confident wrong answer, because a wrong category is invisible downstream.

        Only for sources whose own categories are messy. When a source is browsed
        *by* category its category is already known exactly, and it should be
        mapped through a crosswalk instead of re-inferred from words.
        """
        cats = [_normalize(c) for c in (category_strings or [])]
        meaningful = [c for c in cats if c and c not in self.generic_categories]

        for slug, pattern in _compiled_rules(self):
            if any(pattern.search(cat) for cat in meaningful):
                return slug

        if title:
            normalized_title = _normalize(title)
            for slug, pattern in _compiled_rules(self):
                if pattern.search(normalized_title):
                    return slug
        return None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip().lower()


# Compiled per profile and cached: keyword at a left word boundary (not preceded
# by a letter/digit), trailing text free. Kills matches like "led" inside
# "assembled" while still catching plurals ("resistors").
_RULE_CACHE: dict[str, list[tuple[str, re.Pattern[str]]]] = {}


def _compiled_rules(profile: DomainProfile) -> list[tuple[str, re.Pattern[str]]]:
    cached = _RULE_CACHE.get(profile.slug)
    if cached is None:
        cached = [
            (slug, re.compile("|".join(rf"(?<![a-z0-9]){re.escape(kw)}" for kw in kws)))
            for slug, kws in profile.category_rules
        ]
        _RULE_CACHE[profile.slug] = cached
    return cached


PROFILES: dict[str, DomainProfile] = {}


def register_profile(profile: DomainProfile) -> DomainProfile:
    if profile.slug in PROFILES:
        raise ValueError(f"duplicate domain profile: {profile.slug}")
    PROFILES[profile.slug] = profile
    return profile


def get_profile(domain: str | None) -> DomainProfile:
    """Profile for a domain slug, falling back to the default vertical."""
    return PROFILES.get(domain or DEFAULT_DOMAIN) or PROFILES[DEFAULT_DOMAIN]
