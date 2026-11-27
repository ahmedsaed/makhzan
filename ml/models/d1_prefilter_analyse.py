"""How much of the backlog a d1 pre-filter would drop, and which merges it would lose.

docs/ai/decision-models.md, section 7. Reads d1_prefilter_score.py's outputs and the sample
metadata (production Kev and pplx scores per pair) in ml/out/models-compare/d1-prefilter/;
a pair's d1 score is the lower of its two orders, on the raw scale (the GGUF's baked
temperature undone). A merge is Kev >= 0.8 and pplx >= 0.95, the rule the sample was decided by.

    python3 ml/models/d1_prefilter_analyse.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "ml/out/models-compare/d1-prefilter"
LISTINGS = ROOT / "ml/out/gain-v2/listings.json"
T = 1.3374  # d1's baked calibration temperature
THRESHOLDS = (0.05, 0.10, 0.20, 0.30, 0.50)


def raw(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return 1 / (1 + math.exp(-T * math.log(p / (1 - p))))


def load(f: str) -> dict:
    d: dict = {}
    for r in map(json.loads, (DIR / f).open()):
        if r.get("score") is not None:
            d.setdefault(tuple(r["pair"]), {})[r["order"]] = raw(r["score"])
    return {k: min(v.values()) for k, v in d.items() if len(v) == 2}


def speed(f: str):
    rows = [json.loads(x) for x in (DIR / f).open()]
    ok = [r for r in rows if r.get("score") is not None]
    s = sum(r["seconds"] for r in ok)
    t = sum(r.get("tokens") or 0 for r in ok)
    return len(rows), len(rows) - len(ok), len(ok) / s, t / s


def main() -> None:
    listings = json.loads(LISTINGS.read_text())
    samples = (
        ("uniform sample", "d1-uniform.jsonl", "meta.json"),
        ("merged sample", "d1-merged.jsonl", "meta-merged.json"),
    )
    for name, f, mf in samples:
        d1 = load(f)
        meta = {tuple(m["pair"]): m for m in json.loads((DIR / mf).read_text())}
        n, err, rps, tps = speed(f)
        v = sorted(d1.values())

        def q(x, v=v):
            return v[min(len(v) - 1, int(x * len(v)))]

        print(
            f"== {name}: {len(d1)} pairs, {n} requests, {err} errors, {rps:.2f} req/s, {tps:.0f} tok/s"
        )
        print(
            f"   d1 pair score p05 {q(0.05):.3f} p25 {q(0.25):.3f} p50 {q(0.5):.3f}"
            f" p75 {q(0.75):.3f} p95 {q(0.95):.3f}"
        )
        merged = {k for k, m in meta.items() if m["kev"] >= 0.8 and (m["pplx"] or 0) >= 0.95}
        kevpass = {k for k, m in meta.items() if m["kev"] >= 0.8}
        for t in THRESHOLDS:
            below = {k for k, s in d1.items() if s < t}
            killed = below & merged
            print(
                f"   d1 < {t:.2f}: {len(below)}/{len(d1)} pairs ({len(below) / len(d1):.1%});"
                f" of Kev>=0.8 pairs: {len(below & kevpass)}/{len(kevpass)};"
                f" merges lost: {len(killed)}/{len(merged)}"
            )
            for k in sorted(killed, key=lambda k: d1[k]):
                a, b = listings[k[0]], listings[k[1]]
                print(
                    f"      d1 {d1[k]:.3f} kev {meta[k]['kev']:.3f} pplx {meta[k]['pplx']:.3f}"
                    f" | {a['title'][:70]} || {b['title'][:70]}"
                )


if __name__ == "__main__":
    main()
