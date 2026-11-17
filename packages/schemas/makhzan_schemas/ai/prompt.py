"""The owner-approved judge prompt, verbatim (docs/ai/decision-review.md, sections 3 to 5).

The text and the renderer are ported unchanged from the file the owner approved
(`render_payloads.py`, kept with the labels outside the repository, and its copy
`ml/models/grid_payloads.py`). What a judge sees is therefore fixed here, and a
change to any of it is a new prompt version (`PROMPT_VERSIONS`), which the
pipeline treats as a reason to score again (decision P8 of 2026-11-17).

What each judge is shown (owner decisions, 2026-11-16):

- the rules (`RULES`) and the question (`QUESTION`);
- each listing as labelled fields, a missing field written "not stated":
  title, category, brand, part number, pack size (read from the title),
  specifications and description. **Price is never shown**;
- variant `K2-150` (Kev's): the rules in the instructions, the description
  capped at 150 words (`kev_payload`);
- variant `K1-full` (pplx's): the rules in the state, the full description
  (`pplx_payload`).

Which stage uses which variant is declared in `makhzan_schemas.ai.pipelines`.
Every pair is scored in both reading orders (`requests`), "ab" showing the
pair's `listing_a` as LISTING A, and the lower score counts
(`pipelines.decide`).

`record` turns a stored listing into the fields the renderer reads, as the
approved prompt grid did: the English title, else the Arabic one; the category's
English name; the shop's stated manufacturer part number, else the identifier
the rules assigned; the list page's specs; the English description with its
markup stripped.

The byte-identity test (`apps/ingestion/tests/test_ai_prompt.py`) holds this
module's output, on synthetic listings, to what the approved file rendered.
"""

from __future__ import annotations

import hashlib
import html
import inspect
import json
import re
from collections.abc import Mapping
from typing import Any

# --- the approved text, verbatim ------------------------------------------------------------

RULES = """You compare two product listings from different Egyptian electronics shops and decide whether a buyer could take either one and receive the identical part.

How to compare:
1. Identify what each listing is: product type, model or part number, form (bare chip, module, board, kit, cable, accessory) and pack size.
2. Compare only what both listings state. A field that one listing does not state is unknown, not different.
3. They are the same product unless a stated fact contradicts.

Same product:
- The same part, even if the brands differ or one listing names no brand.
- Drop-in revisions in the same package and pinout (IRF630 / IRF630N).
- The same model from a different factory or origin, unless a rating differs.
- Different wording, order, spelling or language.
- Sizes within about 5% of each other (rounding or typos).

Different product (only when stated):
- A different value or rating: capacitance, resistance, voltage, current, power, temperature, speed, size, length, pin count.
- NC vs NO; module vs bare IC; a different package (TO-220 vs TO-247, SMD vs through-hole); a bare standard part number implies its standard package (1N4007 vs the SMD M7).
- A different chip in the same family (MPU-6050 vs MPU-6500); a different logic family (74LS vs 74HC).
- A different stated pack size (10 pcs vs 100 pcs). A listing that states no pack size is compatible with any pack size.
- One listing includes another component the other lacks ("with I2C adapter", "with cable", "with case"), or is an accessory or part for the other.

Ignore price, shop name, stock, and marketing text in descriptions."""

QUESTION = "Could a buyer take listing A and listing B as the identical part?"

PACK = re.compile(r"\b(\d+)\s*(?:pcs|pc|pieces?|pack|units?)\b|\bpack\s+of\s+(\d+)\b", re.I)


def words(text: str, cap: int | None) -> str:
    w = text.split()
    return " ".join(w[:cap]) + (" […]" if cap and len(w) > cap else "") if w else ""


def block(name: str, r: dict, cap: int | None) -> str:
    def v(x):
        return x if x else "not stated"

    m = PACK.search(r["title"] or "")
    specs = r.get("specs") or {}
    spec_text = (
        "; ".join(f"{k}: {val}" for k, val in specs.items()) if isinstance(specs, dict) else ""
    )
    desc = words(re.sub(r"\s+", " ", r.get("description") or "").strip(), cap)
    return "\n".join(
        [
            f"[{name}]",
            f"Title: {r['title']}",
            f"Category: {v(r.get('category'))}",
            f"Brand: {v(r.get('brand'))}",
            f"Part number: {v(r.get('part_number'))}",
            f"Pack size: {m.group(1) or m.group(2) if m else 'not stated'}",
            f"Specifications: {v(spec_text)}",
            f"Description: {v(desc)}",
        ]
    )


def listings(pair: dict, cap: int | None) -> str:
    return (
        block("LISTING A", pair["listing_a"], cap)
        + "\n\n"
        + block("LISTING B", pair["listing_b"], cap)
    )


# --- the two approved layouts ---------------------------------------------------------------

#: Kev's description cap, in words (layout K2-150).
KEV_CAP = 150
#: pplx reads the full description (layout K1-full).
PPLX_CAP: int | None = None

ORDERS = ("ab", "ba")


def kev_payload(pair: dict, cap: int | None = KEV_CAP) -> dict:
    """Layout K2: the listings in the state, the rules and the question in the
    instructions. The approved file's "K2 (rules in instructions)"."""
    facts = listings(pair, cap)
    return {
        "state": facts,
        "questions": {"same": {"type": "noul", "instructions": f"{RULES}\n\n{QUESTION}"}},
    }


def pplx_payload(pair: dict, cap: int | None = PPLX_CAP) -> dict:
    """Layout K1: the rules and the listings in the state, the question in the
    instructions. The approved file's "K1 (rules in state)"."""
    facts = listings(pair, cap)
    return {
        "state": f"[RULES]\n{RULES}\n\n{facts}",
        "questions": {"same": {"type": "noul", "instructions": QUESTION}},
    }


#: The prompt variants a pipeline stage can name (`pipelines.Stage.prompt`).
#: A new variant is a new entry here, and gets its own version below.
VARIANTS = {f"K2-{KEV_CAP}": kev_payload, "K1-full": pplx_payload}


def payload(variant: str, record_a: dict, record_b: dict) -> dict:
    """One request in prompt `variant`, `record_a` shown as LISTING A."""
    if variant not in VARIANTS:
        raise ValueError(f"no prompt variant {variant!r} (known: {sorted(VARIANTS)})")
    return VARIANTS[variant]({"listing_a": record_a, "listing_b": record_b})


def requests(variant: str, record_a: dict, record_b: dict) -> dict[str, dict]:
    """Both reading orders of one pair: "ab" shows `record_a` (the pair's
    `listing_a`) as LISTING A, "ba" shows it as LISTING B."""
    return {
        "ab": payload(variant, record_a, record_b),
        "ba": payload(variant, record_b, record_a),
    }


def canonical_json(request: Any) -> str:
    """A request as one exact string: sorted keys, no spaces, unescaped text.
    What `request_sha256` is taken over, and what the broker sends."""
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_sha256(request: Any) -> bytes:
    """The request's identity (docs/ai/broker-api.md): two requests with the
    same hash showed a judge exactly the same thing, so a score stored for one
    answers the other."""
    return hashlib.sha256(canonical_json(request).encode("utf-8")).digest()


# --- what a stored listing shows ------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(text: object) -> str:
    """Markup out, entities decoded, whitespace collapsed: how the approved
    prompt grid read a description (`ml/bakeoff/contexts.clean`, verbatim)."""
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", " ", s)
    s = _TAG.sub(" ", s)
    return _WS.sub(" ", html.unescape(s)).strip()


def record(row: Mapping[str, Any]) -> dict:
    """The fields the renderer reads, from one listing's stored columns.

    `row` holds `id`, `title_en`, `title_ar`, `category` (the category's
    English name), `brand`, `part_number`, `mfr_part_number` (the shop's stated
    code, `attributes.mfr_part_number`), `specs` (`attributes.specs`) and
    `description_en`, as the approved prompt grid's `record()` read them.
    """
    specs = row.get("specs")
    return {
        "id": row["id"],
        "title": row.get("title_en") or row.get("title_ar"),
        "category": row.get("category"),
        "brand": row.get("brand"),
        "part_number": row.get("mfr_part_number") or row.get("part_number"),
        "specs": specs if isinstance(specs, dict) else None,
        "description": clean(row.get("description_en")),
    }


def listing_row(listing: Any, category: str | None) -> dict:
    """`record`'s input from a `models.Listing` and its category's English name."""
    attributes = listing.attributes if isinstance(listing.attributes, dict) else {}
    return {
        "id": str(listing.id),
        "title_en": listing.title_en,
        "title_ar": listing.title_ar,
        "category": category,
        "brand": listing.brand,
        "part_number": listing.part_number,
        "mfr_part_number": attributes.get("mfr_part_number"),
        "specs": attributes.get("specs"),
        "description_en": listing.description_en,
    }


# --- versions -------------------------------------------------------------------------------


def _renderer_sha8() -> str:
    """A hash of the rules, the question and the renderer's code: any change to
    what a judge could be shown moves it."""
    parts = [RULES, QUESTION, PACK.pattern]
    parts += [inspect.getsource(f) for f in (words, block, listings, clean, record)]
    parts += [inspect.getsource(f) for f in (kev_payload, pplx_payload)]
    digest = hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()
    return digest[:8]


#: Each variant's version: its layout and cap, and a hash of the text and the
#: renderer (P8). Pinned by a test, so a change here is a deliberate new version.
PROMPT_VERSIONS = {variant: f"{variant}@{_renderer_sha8()}" for variant in VARIANTS}
