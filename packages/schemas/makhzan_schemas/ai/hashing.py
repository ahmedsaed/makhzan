"""A listing's content hash: what decides that its text changed (decision P5, 2026-11-17).

Taken over exactly what a judge could be shown of the listing: the renderer's own
block for it (`prompt.block`) at full length, built from `prompt.record`, so
every field that can reach a prompt is in it, normalised exactly as the prompt
normalises it:

- the title (the English one, else the Arabic), as written;
- category (its English name), brand, part number (the shop's stated code,
  else the identifier the rules assigned), pack size;
- the specs, as the prompt writes them;
- the description, markup stripped and whitespace collapsed.

Plus the Arabic title as written, so a listing whose Arabic title changes
under an English one is due again too (P5 names both languages).

**Never price**, nor stock, photos, the shop or anything else the prompt does
not show: a price change must not make a decision look out of date. Kev's
capped block is a prefix of the full one, so any change Kev could see moves
this hash; an edit past Kev's 150th description word moves it too (pplx reads
the whole description).

A changed hash, or a new model or prompt version, is what makes a pair due to
be scored again (the re-score trigger); with each score it records which text
the score was about. Whether a score already exists for what would be sent is
answered by the request hash (`prompt.request_sha256`), never by this one.
Changing what goes in is a new `HASH_VERSION`, and makes every listing due
again.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from makhzan_schemas.ai.prompt import block, listing_row, record

#: Bumped when what goes in changes.
HASH_VERSION = 2


def content_text(rec: dict, title_ar: str | None) -> str:
    """The canonical text hashed: the renderer's full block and the Arabic title."""
    shown = block("LISTING", rec, None)
    return json.dumps(
        {"v": HASH_VERSION, "shown": shown, "title_ar": title_ar or None},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_hash(rec: dict, title_ar: str | None = None) -> bytes:
    """sha256 of `content_text`."""
    return hashlib.sha256(content_text(rec, title_ar).encode("utf-8")).digest()


def listing_hash(listing: Any, category: str | None) -> bytes:
    """The content hash of one stored listing, given its category's English name."""
    return content_hash(record(listing_row(listing, category)), listing.title_ar)
