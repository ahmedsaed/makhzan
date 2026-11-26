"""pplx-decider-flash-v1.3 through llama.cpp's POST /v1/systemone: score the Phase E requests and
compare them with the validated bf16 scores (the pplx sibling of kev_gguf.py).

The GGUF is converted by our wrapper around upstream llama.cpp's pplx converter (protocol-v4
prompt, non-causal full attention), see ml/out/gguf-pplx/. llama.cpp applies pplx's own
temperature (1.3303, written from decision_config.json), which is the scale every validated
pplx score is on, so scores are compared as returned.

Every string in the request is NFC-normalised before it is sent: pplx's Hugging Face tokenizer
normalises NFC and llama.cpp's does not, so a non-NFC character (U+2126 OHM SIGN in E0013)
otherwise tokenises differently.

    python3 ml/models/pplx_gguf.py score --base http://127.0.0.1:8140 --out ml/out/gguf-pplx/x.jsonl [--n 100]
    python3 ml/models/pplx_gguf.py compare ml/out/gguf-pplx/x.jsonl
    python3 ml/models/pplx_gguf.py decisions ml/out/gguf-pplx/x.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import time
import unicodedata
from pathlib import Path

from kev_gguf import ROOT, pair_min, post, spearman

REQUESTS = ROOT / "ml/out/gguf-pplx/requests-K1-full.jsonl"
REF = ROOT / "ml/out/prompt-grid/raw/pplx-K1-full.jsonl"
KEV = ROOT / "ml/out/prompt-grid/raw/kev-K2-150.jsonl"
KEY = ROOT.parent / "makhzan-config/labels/answer-key-v2.jsonl"
KEV_MIN, PPLX_MIN = 0.80, 0.95


def nfc(v):
    if isinstance(v, str):
        return unicodedata.normalize("NFC", v)
    if isinstance(v, dict):
        return {nfc(k): nfc(x) for k, x in v.items()}
    if isinstance(v, list):
        return [nfc(x) for x in v]
    return v


def cmd_score(args) -> None:
    reqs = [json.loads(line) for line in REQUESTS.open()]
    if args.n:
        reqs = reqs[: 2 * args.n]
    done = set()
    if args.out.exists():
        rows = map(json.loads, args.out.open())
        done = {(r["pair_id"], r["order"]) for r in rows if r["score"] is not None}
    t_start, k = time.time(), 0
    with args.out.open("a") as fh:
        for r in reqs:
            if (r["pair_id"], r["order"]) in done:
                continue
            t0 = time.time()
            try:
                o = post(f"{args.base}/v1/systemone", {"model": "pplx", **nfc(r["request"])})
                s, extra = o["answers"]["same"]["noul"], {"usage": o.get("usage")}
            except Exception as e:  # noqa: BLE001 - recorded
                s, extra = None, {"error": str(e)[:300]}
            row = {"pair_id": r["pair_id"], "order": r["order"], "score": s,
                   "seconds": round(time.time() - t0, 4), **extra}  # fmt: skip
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            k += 1
    el = time.time() - t_start
    print(f"{k} requests in {el:.1f}s = {k / el:.2f} req/s" if k else "nothing to do")


def load(path: Path) -> dict:
    return {(r["pair_id"], r["order"]): r["score"] for r in map(json.loads, path.open())}


def cmd_compare(args) -> None:
    ref, new = load(REF), load(args.scores)
    errors = sum(v is None for v in new.values())
    keys = [k for k, v in new.items() if v is not None and ref.get(k) is not None]
    x, y = [ref[k] for k in keys], [new[k] for k in keys]
    d = [abs(a - b) for a, b in zip(x, y, strict=True)]
    print(f"requests {len(keys)} (errors {errors})")
    print(f"spearman {spearman(x, y):.4f}  max|dp| {max(d):.4f}  mean|dp| {sum(d) / len(d):.4f}")
    for t in (0.5, 0.95):
        flips = sum((a >= t) != (b >= t) for a, b in zip(x, y, strict=True))
        print(f"  request agree@{t}: {1 - flips / len(x):.2%} ({flips} flips)")
    pids = sorted({p for p, _ in keys if None not in (pair_min(new, p), pair_min(ref, p))})
    for t in (0.5, 0.95):
        fl = [(p, round(pair_min(ref, p), 3), round(pair_min(new, p), 3)) for p in pids
              if (pair_min(ref, p) >= t) != (pair_min(new, p) >= t)]  # fmt: skip
        print(f"  pair (min) agree@{t}: {1 - len(fl) / len(pids):.2%} ({len(fl)} of {len(pids)})"
              + (f"  {fl[:12]}" if fl else ""))  # fmt: skip
    sec = [s for s in (json.loads(line).get("seconds") for line in args.scores.open()) if s]
    print(f"latency mean {sum(sec) / len(sec):.3f}s")


def cmd_decisions(args) -> None:
    """Production rule (Kev >= 0.8 and pplx >= 0.95, pair = min of both orders) on pairs the
    vetoes pass; Kev is the stored bf16 score, pplx the reference or the variant."""
    key = {r["pair_id"]: r for r in map(json.loads, KEY.open())}
    kev = load(KEV)
    runs = {"pplx bf16 (reference)": load(REF), args.scores.name: load(args.scores)}
    ok = [p for p, k in key.items() if not any(k["veto"].values())
          and all(pair_min(r, p) is not None for r in (*runs.values(), kev))]  # fmt: skip
    decided = {}
    for name, rows in runs.items():
        merge = {p: pair_min(kev, p) >= KEV_MIN and pair_min(rows, p) >= PPLX_MIN for p in ok}
        decided[name] = merge
        wrong = sum(merge[p] and key[p]["label"] == "not" for p in ok)
        right = sum(merge[p] and key[p]["label"] == "same" for p in ok)
        print(
            f"{name}: pairs {len(ok)}  merges {sum(merge.values())} (same {right}, wrong {wrong})"
        )
    a, b = decided.values()
    changed = [(p, key[p]["label"], round(pair_min(runs["pplx bf16 (reference)"], p), 3),
                round(pair_min(runs[args.scores.name], p), 3)) for p in a if a[p] != b[p]]  # fmt: skip
    print(f"changed decisions: {len(changed)} {changed}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--base", required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--n", type=int, help="first N pairs (both orders)")
    for name in ("compare", "decisions"):
        sub.add_parser(name).add_argument("scores", type=Path)
    args = ap.parse_args()
    {"score": cmd_score, "compare": cmd_compare, "decisions": cmd_decisions}[args.cmd](args)


if __name__ == "__main__":
    _ = math  # stdlib only
    main()
