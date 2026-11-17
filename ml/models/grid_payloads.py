"""The owner-approved judge payloads (docs/ai/decision-review.md, sections 3-4), verbatim.

Copied unchanged from ml/out/labels/render_payloads.py (git-ignored), the file the owner approved:
RULES, QUESTION, CRITERIA, PACK, words, block, listings, payloads. Do not edit the text below;
prompt_grid.py `check` asserts the rendered payloads are byte-identical to that file's for the
sample pairs (ml/out/labels/payload-sample-pairs.json). The formatter is off for that reason.
"""

# fmt: off
import re

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

CRITERIA = {
    "true": "The identical part: a buyer could take either. Differences in wording, brand, or a detail only one listing mentions do not count.",
    "false": "A different part: a stated contradiction in value, rating, size, form, package, chip or pack size, or one includes another component or is an accessory for the other.",
}

PACK = re.compile(r"\b(\d+)\s*(?:pcs|pc|pieces?|pack|units?)\b|\bpack\s+of\s+(\d+)\b", re.I)


def words(text: str, cap: int | None) -> str:
    w = text.split()
    return " ".join(w[:cap]) + (" […]" if cap and len(w) > cap else "") if w else ""


def block(name: str, r: dict, cap: int | None) -> str:
    def v(x):
        return x if x else "not stated"

    m = PACK.search(r["title"] or "")
    specs = r.get("specs") or {}
    spec_text = "; ".join(f"{k}: {val}" for k, val in specs.items()) if isinstance(specs, dict) else ""
    desc = words(re.sub(r"\s+", " ", r.get("description") or "").strip(), cap)
    return "\n".join([
        f"[{name}]",
        f"Title: {r['title']}",
        f"Category: {v(r.get('category'))}",
        f"Brand: {v(r.get('brand'))}",
        f"Part number: {v(r.get('part_number'))}",
        f"Pack size: {m.group(1) or m.group(2) if m else 'not stated'}",
        f"Specifications: {v(spec_text)}",
        f"Description: {v(desc)}",
    ])


def listings(pair: dict, cap: int | None) -> str:
    return block("LISTING A", pair["listing_a"], cap) + "\n\n" + block("LISTING B", pair["listing_b"], cap)


def payloads(pair: dict, cap: int | None) -> dict:
    facts = listings(pair, cap)
    return {
        "K1 (rules in state)": {"state": f"[RULES]\n{RULES}\n\n{facts}",
                                "questions": {"same": {"type": "noul", "instructions": QUESTION}}},
        "K2 (rules in instructions)": {"state": facts,
                                       "questions": {"same": {"type": "noul", "instructions": f"{RULES}\n\n{QUESTION}"}}},
        "K1 + criteria": {"state": f"[RULES]\n{RULES}\n\n{facts}",
                          "questions": {"same": {"type": "noul", "instructions": QUESTION, "criteria": CRITERIA}}},
        "Qwen3.5 (chat, score P(yes))": [
            {"role": "system", "content": RULES},
            {"role": "user", "content": f"{facts}\n\n[QUESTION]\n{QUESTION} Answer yes or no."},
        ],
    }


# fmt: on
