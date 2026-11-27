"""Render two pairs' Intern-Decision prompts, string state vs structured state; scores nothing.

The draft the owner approved before the structured run (docs/ai/decision-models.md, section 8):
each pair rendered with Intern's own inference.compile_row and chat template
(enable_thinking=False), once as sent on 2026-11-26 (Kev's K2 text block as one string, which
json.dumps turns into one quoted line of \\n escapes) and once with the same fields as an object.

    python3 ml/models/intern_struct_draft.py <intern snapshot dir> E0098 E0639
    # -> ml/out/models-compare/intern-structured-draft.md

Runs where the snapshot's inference.py and transformers import (the reference container).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from intern_struct_requests import KEY, LISTINGS, OUT, prompt, structured_listing  # noqa: E402


def main() -> None:
    snapshot, pair_ids = Path(sys.argv[1]), sys.argv[2:]
    sys.path.insert(0, str(snapshot))
    import inference  # Intern's own code: compile_row, SYSTEM_PROMPT
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(snapshot))
    listings = json.loads(LISTINGS.read_text())
    key = {r["pair_id"]: r for r in map(json.loads, KEY.open())}
    orig = {
        (r["pair_id"], r["order"]): r["payload"]
        for r in map(json.loads, (OUT / "requests.jsonl").open())
        if r["variant"] == "K2"
    }

    def text_of(payload):
        c = inference.compile_row(payload)
        t = tok.apply_chat_template(
            c.messages,
            tokenize=False,
            add_generation_prompt=False,
            enable_thinking=False,
            add_vision_id=True,
        )
        return t, len(tok(t, add_special_tokens=False)["input_ids"])

    out = [
        "# Intern-Decision-4B: structured state — DRAFT (nothing scored)",
        "",
        "Rendered with Intern's own `inference.compile_row` and its chat template.",
        "Original = the 2026-11-26 run's state (Kev's K2 text block, one string).",
        "Structured = the same K2 fields, labels, order and values as a JSON object;",
        "instructions (RULES + QUESTION) unchanged.",
        "",
    ]
    for pid in pair_ids:
        k = key[pid]
        a, b = listings[k["listing_a"]], listings[k["listing_b"]]
        structured = {
            "state": {
                "Listing A": structured_listing(a, prompt.KEV_CAP),
                "Listing B": structured_listing(b, prompt.KEV_CAP),
            },
            "questions": prompt.payload("K2-150", a, b)["questions"],
        }
        o_text, o_n = text_of(orig[(pid, "ab")])
        s_text, s_n = text_of(structured)
        out += [f"## {pid} — label: {k['label']}", "", f"### Original ({o_n} tokens)", ""]
        out += ["```", o_text, "```", "", f"### Structured ({s_n} tokens)", ""]
        out += ["```", s_text, "```", ""]
    (OUT / "intern-structured-draft.md").write_text("\n".join(out))
    print("ok", pair_ids)


if __name__ == "__main__":
    main()
