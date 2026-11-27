"""Score the compare_models requests with Intern-Decision-4B's own reference code (inference.py,
HF transformers, BF16, SDPA, use_cache=False), raw P(yes) at temperature 1.

Runs inside the reference container (torch 2.9.1, transformers 5.14.1):

    python intern_runner.py --checkpoint <snapshot> --requests requests.jsonl --variant K2 \
        --out intern-K2.jsonl [--n N]

Our state string and instructions (and criteria in K2c) go into its own template unchanged
(inference.compile_row); nothing here writes prompt text.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--requests", type=Path, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int)
    args = ap.parse_args()
    sys.path.insert(0, args.checkpoint)
    import torch
    from inference import DecisionEngine

    rows = [r for r in map(json.loads, args.requests.open()) if r["variant"] == args.variant]
    if args.n:
        keep = sorted({r["pair_id"] for r in rows})[: args.n]
        rows = [r for r in rows if r["pair_id"] in keep]
    done = set()
    if args.out.exists():
        for r in map(json.loads, args.out.open()):
            if r.get("score") is not None:
                done.add((r["pair_id"], r["order"]))
    engine = DecisionEngine(args.checkpoint, temperature=1.0)
    print("loaded; peak MiB", torch.cuda.max_memory_allocated() // 2**20, flush=True)
    t0, k = time.time(), 0
    with args.out.open("a") as fh:
        for r in rows:
            if (r["pair_id"], r["order"]) in done:
                continue
            t = time.time()
            try:
                res = engine.predict(r["payload"])
                ans = res["answers"]["same"]
                s, extra = ans["noul"], {"usage": {"input_tokens": res["usage"]["input_tokens"]}}
            except Exception as e:  # noqa: BLE001 - recorded
                s, extra = None, {"error": str(e)[:300]}
            out = {"pair_id": r["pair_id"], "order": r["order"], "score": s,
                   "seconds": round(time.time() - t, 4), **extra}  # fmt: skip
            fh.write(json.dumps(out) + "\n")
            fh.flush()
            k += 1
    el = time.time() - t0
    print(f"{k} requests in {el:.1f}s; peak MiB {torch.cuda.max_memory_allocated() // 2**20}")


if __name__ == "__main__":
    main()
