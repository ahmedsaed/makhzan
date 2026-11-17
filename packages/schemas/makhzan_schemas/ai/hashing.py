"""A listing's content hash: what decides that its text changed (decision P5, 2026-11-17).

Taken over every field that can reach a judge's prompt (`makhzan_schemas.ai.prompt`):

- the title in both languages (the prompt shows the English one, else the Arabic);
- the brand;
- the part number: the identifier the rules assigned and the shop's stated
  manufacturer part number (`attributes.mfr_part_number`), which the prompt
  prefers;
- the category, by its English name, which is what the prompt shows;
- the specs (`attributes.specs`);
- the description (the English one: the prompt shows no other).

**Never price**, nor stock, photos, the shop or anything else the prompt does
not show: a price change must not make a decision look out of date.

A changed hash, or a new model or prompt version, is what makes a pair due to be
scored again; the hash is stored with each score and decision, so a score says
which text it was about. It is deterministic: strings have their whitespace
collapsed and an empty one counts as absent, and the canonical JSON sorts its
keys, so the same content gives the same hash whatever order a shop or a query
gave it in. Changing what goes in is a new `HASH_VERSION`, and makes every
listing due again.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

#: Bumped when the fields or their normalisation change.
HASH_VERSION = 1

_WS = re.compile(r"\s+")


def _norm(value: Any) -> Any:
    """Strings with whitespace collapsed (empty is None); tables and lists
    normalised all the way down. Key order is left to the canonical JSON."""
    if value is None:
        return None
    if isinstance(value, str):
        return _WS.sub(" ", value).strip() or None
    if isinstance(value, dict):
        return {str(_norm(str(k)) or ""): _norm(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, bool | int | float):
        return value
    return _norm(str(value))


def content_fields(
    *,
    title_en: str | None,
    title_ar: str | None,
    brand: str | None,
    part_number: str | None,
    mfr_part_number: Any,
    category: str | None,
    specs: Any,
    description: str | None,
) -> dict:
    """The hashed fields, normalised. Specs that are not a table count as none,
    as the prompt reads them."""
    return {
        "v": HASH_VERSION,
        "title_en": _norm(title_en),
        "title_ar": _norm(title_ar),
        "brand": _norm(brand),
        "part_number": _norm(part_number),
        "mfr_part_number": _norm(mfr_part_number),
        "category": _norm(category),
        "specs": _norm(specs) if isinstance(specs, dict) and specs else None,
        "description": _norm(description),
    }


def listing_fields(listing: Any, category: str | None) -> dict:
    """`content_fields` of a `models.Listing`, given its category's English name."""
    attributes = listing.attributes if isinstance(listing.attributes, dict) else {}
    return content_fields(
        title_en=listing.title_en,
        title_ar=listing.title_ar,
        brand=listing.brand,
        part_number=listing.part_number,
        mfr_part_number=attributes.get("mfr_part_number"),
        category=category,
        specs=attributes.get("specs"),
        description=listing.description_en,
    )


def content_hash(fields: dict) -> bytes:
    """sha256 of the fields' canonical JSON (sorted keys, no spaces)."""
    text = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).digest()


def listing_hash(listing: Any, category: str | None) -> bytes:
    """The content hash of one stored listing."""
    return content_hash(listing_fields(listing, category))
