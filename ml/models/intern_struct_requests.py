"""Build the Intern-Decision structured-state requests (docs/ai/decision-models.md, section 8).

Reads compare_models.py's requests.jsonl and replaces each request's state, which was Kev's K2
text block (one string), with the same fields as a JSON object: "Listing A" / "Listing B", one
key per field, specifications as an object. The questions (K2 / K2c) are unchanged.

    python3 ml/models/intern_struct_requests.py
    # -> ml/out/models-compare/intern-struct-requests.jsonl, then score it with intern_runner.py

Needs ml/out/models-compare/requests.jsonl (compare_models.py render), the Phase E listings
(ml/out/prompt-grid/listings.json) and the private answer key beside this repository.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ml/out/models-compare"
KEY = ROOT.parent / "makhzan-config/labels/answer-key-v2.jsonl"
LISTINGS = ROOT / "ml/out/prompt-grid/listings.json"

# Import makhzan_schemas.ai.prompt without the package's __init__ (no database dependencies).
_stub = types.ModuleType("makhzan_schemas")
_stub.__path__ = [str(ROOT / "packages/schemas/makhzan_schemas")]
sys.modules.setdefault("makhzan_schemas", _stub)
from makhzan_schemas.ai import prompt  # noqa: E402


def structured_listing(r: dict, cap: int) -> dict:
    """The fields, labels, order and values of prompt.block(), as an object instead of text."""

    def v(x):
        return x if x else "not stated"

    m = prompt.PACK.search(r["title"] or "")
    specs = r.get("specs") if isinstance(r.get("specs"), dict) and r.get("specs") else "not stated"
    desc = prompt.words(re.sub(r"\s+", " ", r.get("description") or "").strip(), cap)
    return {
        "Title": r["title"],
        "Category": v(r.get("category")),
        "Brand": v(r.get("brand")),
        "Part number": v(r.get("part_number")),
        "Pack size": (m.group(1) or m.group(2)) if m else "not stated",
        "Specifications": specs,
        "Description": v(desc),
    }


def main() -> None:
    listings = json.loads(LISTINGS.read_text())
    key = {r["pair_id"]: r for r in map(json.loads, KEY.open())}
    n = 0
    with (OUT / "intern-struct-requests.jsonl").open("w") as out:
        for r in map(json.loads, (OUT / "requests.jsonl").open()):
            k = key[r["pair_id"]]
            a, b = listings[k["listing_a"]], listings[k["listing_b"]]
            if r["order"] == "ba":
                a, b = b, a
            state = {
                "Listing A": structured_listing(a, prompt.KEV_CAP),
                "Listing B": structured_listing(b, prompt.KEV_CAP),
            }
            payload = {"state": state, "questions": r["payload"]["questions"]}
            out.write(json.dumps({**r, "payload": payload}, ensure_ascii=False) + "\n")
            n += 1
    print("wrote", n)


if __name__ == "__main__":
    main()
