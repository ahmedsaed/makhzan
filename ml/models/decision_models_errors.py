"""H2O against Kev as the first judge: their errors, and the two-judge rule (section 5).

On the Phase E pairs that pass the vetoes (label not "unsure") and that every run below scored
in both orders. A pair's score is the lower of its two orders, on the raw scale:
Kev BF16 as stored (raw already), H2O sigmoid(0.8 * logit p).

    python3 ml/models/decision_models_errors.py [--q4] [--titles]

Prints, for Kev >= 0.8 and H2O >= 0.578 each alone: false merges and misses, and which of them
the other judge shares; with --titles, each pair's two listing titles. Then the production rule
(first stage, then pplx >= 0.95) for Kev, H2O, Kev OR H2O and Kev AND H2O, twice: Kev BF16 with
pplx BF16, and the production quantisations, Kev Q4_K_M (its GGUF temperature 2.406 undone) with
pplx Q4_K_S: merges / correct / wrong, and the wrong pair ids. --q4 reads H2O Q4_K_M
(h2o-q4-K2.jsonl) instead of Q8_0 (h2o-K2.jsonl); at 0.578 the two make the same merges.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import compare_models as cm  # noqa: E402

OUT = ROOT / "ml/out/models-compare"
PPLX_Q4 = ROOT / "ml/out/gguf-pplx/Q4_K_S.jsonl"
KEV_Q4 = ROOT / "ml/out/gguf-kev/q4km-vulkan-3060.jsonl"
KEV_GGUF_T = 2.406049966812134  # baked into every Kev GGUF; undone like the worker does
KEV_T, H2O_T, PPLX_T = 0.8, 0.578, 0.95


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q4", action="store_true", help="H2O Q4_K_M instead of Q8_0")
    ap.add_argument("--titles", action="store_true", help="print each pair's listing titles")
    args = ap.parse_args()
    key = {r["pair_id"]: r for r in map(json.loads, cm.KEY.open())}
    listings = json.loads(cm.LISTINGS.read_text())
    runs = {
        "kev": cm.load(cm.KEV),
        "h2o": cm.load(OUT / ("h2o-q4-K2.jsonl" if args.q4 else "h2o-K2.jsonl"), 0.8),
        "pplx bf16": cm.load(cm.PPLX),
        "pplx Q4": cm.load(PPLX_Q4),
        "kev Q4": cm.load(KEV_Q4, KEV_GGUF_T),
    }
    pairs = sorted(
        p
        for p, k in key.items()
        if not any(k["veto"].values())
        and k["label"] != "unsure"
        and all(cm.pmin(d, p) is not None for d in runs.values())
    )
    s = {name: {p: cm.pmin(d, p) for p in pairs} for name, d in runs.items()}
    same = {p: key[p]["label"] == "same" for p in pairs}
    print(f"{len(pairs)} pairs, {sum(same.values())} same; H2O {'Q4_K_M' if args.q4 else 'Q8_0'}")

    def titles(p):
        a, b = listings[key[p]["listing_a"]], listings[key[p]["listing_b"]]
        return f"{a['title'][:70]} || {b['title'][:70]}"

    kev_m = {p for p in pairs if s["kev"][p] >= KEV_T}
    h2o_m = {p for p in pairs if s["h2o"][p] >= H2O_T}
    for name, mine, other, oname in (("H2O", h2o_m, kev_m, "Kev"), ("Kev", kev_m, h2o_m, "H2O")):
        fm = sorted(p for p in mine if not same[p])
        miss = sorted(p for p in pairs if same[p] and p not in mine)
        only = sorted(p for p in mine if same[p] and p not in other)
        print(
            f"\n== {name} alone: {len(fm)} false merges, {len(miss)} missed, {len(only)} found only by it"
        )
        for p in fm:
            shared = "shared" if p in other else f"{oname} avoids"
            line = (
                f"   {p} {name.lower()} {s[name.lower()][p]:.3f} kev {s['kev'][p]:.3f} ({shared})"
            )
            print(line + (f" | {titles(p)}" if args.titles else ""))

    for kev, pplx in (("kev", "pplx bf16"), ("kev Q4", "pplx Q4")):
        k_m = {p for p in pairs if s[kev][p] >= KEV_T}
        stages = {"Kev": k_m, "H2O": h2o_m, "Kev OR H2O": k_m | h2o_m, "Kev AND H2O": k_m & h2o_m}
        label = "Kev BF16" if kev == "kev" else "Kev Q4_K_M"
        print(f"\n== {label} / H2O, then {pplx} >= {PPLX_T}: merges / correct / wrong")
        for name, first in stages.items():
            m = [p for p in pairs if p in first and s[pplx][p] >= PPLX_T]
            wrong = [p for p in m if not same[p]]
            print(
                f"   {name:12} {len(m)} / {len(m) - len(wrong)} / {len(wrong)}  {' '.join(wrong)}"
            )


if __name__ == "__main__":
    main()
