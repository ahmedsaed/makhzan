"""The judge prompt is the owner-approved one, byte for byte.

`fixtures/ai_prompt_golden.json` holds synthetic listings (no real catalogue
text: the repository is public) and the payloads the approved renderer produced
for them, Kev in layout K2 with the description capped at 150 words and pplx in
layout K1 with the full description, both reading orders. The port must
reproduce them exactly; any change to the text or the renderer is a new prompt
version, and `PROMPT_VERSIONS` is pinned here so that one is never made by
accident.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from makhzan_schemas.ai import prompt
from makhzan_schemas.ai.prompt import (
    PROMPT_VERSIONS,
    QUESTION,
    RULES,
    canonical_json,
    kev_payload,
    listing_row,
    pplx_payload,
    record,
    request_sha256,
    requests,
)

#: Each judge's approved layout, as the golden file names them.
VARIANT = {"kev": "K2-150", "pplx": "K1-full"}
GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "ai_prompt_golden.json").read_text())


def _pairs():
    for entry in GOLDEN["pairs"]:
        yield entry, GOLDEN["listings"][entry["a"]], GOLDEN["listings"][entry["b"]]


@pytest.mark.parametrize("stage", ["kev", "pplx"])
def test_both_orders_render_byte_for_byte_what_the_approved_renderer_did(stage):
    for entry, a, b in _pairs():
        got = requests(VARIANT[stage], a, b)
        for order in ("ab", "ba"):
            want = json.dumps(entry[stage][order], ensure_ascii=False)
            assert json.dumps(got[order], ensure_ascii=False) == want, (entry["a"], order)


def test_ab_shows_listing_a_first_and_ba_the_other_way_round():
    a, b = GOLDEN["listings"]["full"], GOLDEN["listings"]["bare"]
    both = requests("K2-150", a, b)
    assert both["ab"]["state"].index(a["title"]) < both["ab"]["state"].index(b["title"])
    assert both["ba"]["state"].index(b["title"]) < both["ba"]["state"].index(a["title"])


def test_kev_has_the_rules_in_its_instructions_and_pplx_in_its_state():
    a, b = GOLDEN["listings"]["full"], GOLDEN["listings"]["bare"]
    kev = kev_payload({"listing_a": a, "listing_b": b})
    pplx = pplx_payload({"listing_a": a, "listing_b": b})
    assert kev["questions"]["same"]["instructions"] == f"{RULES}\n\n{QUESTION}"
    assert RULES not in kev["state"]
    assert pplx["state"].startswith(f"[RULES]\n{RULES}\n\n[LISTING A]\n")
    assert pplx["questions"]["same"] == {"type": "noul", "instructions": QUESTION}


def test_kev_caps_the_description_at_150_words_and_pplx_reads_it_whole():
    long = GOLDEN["listings"]["long"]
    bare = GOLDEN["listings"]["bare"]
    kev = kev_payload({"listing_a": long, "listing_b": bare})["state"]
    pplx = pplx_payload({"listing_a": long, "listing_b": bare})["state"]
    assert "word150 […]" in kev and "word151" not in kev
    assert "word170" in pplx and "[…]" not in pplx
    # Exactly 150 words is not cut, so no ellipsis.
    exact = GOLDEN["listings"]["exact_cap"]
    assert "w149\n" in kev_payload({"listing_a": exact, "listing_b": bare})["state"]


def test_a_missing_field_is_written_not_stated_and_price_is_never_shown():
    bare = dict(GOLDEN["listings"]["bare"], price="999.00")
    text = kev_payload({"listing_a": bare, "listing_b": bare})["state"]
    for label in ("Category", "Brand", "Part number", "Pack size", "Specifications", "Description"):
        assert f"{label}: not stated" in text
    assert "999" not in text and "rice" not in text


def test_pack_size_is_read_from_the_title():
    assert (
        "Pack size: 10\n"
        in kev_payload(
            {"listing_a": GOLDEN["listings"]["full"], "listing_b": GOLDEN["listings"]["bare"]}
        )["state"]
    )
    assert (
        "Pack size: 5\n"
        in kev_payload(
            {"listing_a": GOLDEN["listings"]["long"], "listing_b": GOLDEN["listings"]["bare"]}
        )["state"]
    )


def test_record_reads_a_stored_listing_as_the_approved_grid_did():
    listing = SimpleNamespace(
        id=uuid.UUID("00000000-0000-4000-8000-0000000000aa"),
        title_en=None,
        title_ar="عنوان تجريبي",
        brand="Examplebrand",
        part_number="RULE-1",
        description_en="<p>First&nbsp;line</p><br/>second\n\n  line",
        attributes={"mfr_part_number": "SHOP-9", "specs": {"Voltage": "5V"}, "price": 3},
        price=3,
    )
    got = record(listing_row(listing, "Example category"))
    assert got == {
        "id": "00000000-0000-4000-8000-0000000000aa",
        "title": "عنوان تجريبي",  # no English title: the Arabic one
        "category": "Example category",
        "brand": "Examplebrand",
        "part_number": "SHOP-9",  # the shop's stated code wins over the rules'
        "specs": {"Voltage": "5V"},
        "description": "First line second line",
    }
    listing.attributes = {"specs": ["not", "a", "table"]}
    assert record(listing_row(listing, None))["part_number"] == "RULE-1"
    assert record(listing_row(listing, None))["specs"] is None


def test_the_request_hash_is_over_the_exact_canonical_request():
    a, b = GOLDEN["listings"]["full"], GOLDEN["listings"]["bare"]
    both = requests("K2-150", a, b)
    assert request_sha256(both["ab"]) != request_sha256(both["ba"])
    reordered = json.loads(json.dumps(both["ab"]), object_pairs_hook=lambda kv: dict(kv[::-1]))
    assert request_sha256(reordered) == request_sha256(both["ab"])
    assert canonical_json({"b": "é", "a": 1}) == '{"a":1,"b":"é"}'


def test_prompt_versions_are_pinned():
    # A change to the rules, the question or the renderer moves these: that
    # is a new prompt version, which makes every pair due to be scored again.
    # Update them only on purpose, with the owner's approval of the new text.
    assert PROMPT_VERSIONS == {"K2-150": "K2-150@6aef2c6c", "K1-full": "K1-full@6aef2c6c"}


def test_an_unknown_variant_is_refused():
    with pytest.raises(ValueError):
        prompt.payload("qwen", {}, {})
