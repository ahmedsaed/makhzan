"""Kev-4B through llama.cpp's POST /v1/systemone: score the Phase E requests and compare them
with the validated bf16 scores (docs/ai/kev-llamacpp.md).

The requests are the chosen setup's (K2 layout, description capped at 150 words), rendered by
prompt_grid.py's payload() from ml/out/prompt-grid/listings.json, one request per call, both
orders of each Phase E pair. The reference is ml/out/prompt-grid/raw/kev-K2-150.jsonl: Kev's own
server, bf16, raw P(yes) (KEV_TEMPERATURE=1.0).

ggml-org's Kev GGUF carries Kev's calibration temperature (qwen35.decision.temperature.noul =
2.406) and llama.cpp always applies it, so `compare` and `decisions` first undo it:
p_raw = sigmoid(T * logit(p)). Pass --temperature 1 for a file whose metadata was set to 1.0.

    # a llama.cpp server with the GGUF loaded, e.g.
    #   docker run --gpus all -p 127.0.0.1:8130:8080 ghcr.io/ggml-org/llama.cpp:server-vulkan \
    #     -m /models/Kev-4B-Q8_0.gguf -ngl 99 -np 1 -c 4096 -b 2048 -ub 2048
    python3 ml/models/kev_gguf.py score --base http://127.0.0.1:8130 \
        --out ml/out/gguf-kev/q8.jsonl [--n 100]          # resumes; --n = first N pairs
    python3 ml/models/kev_gguf.py compare ml/out/gguf-kev/q8.jsonl     # D20's numbers
    python3 ml/models/kev_gguf.py decisions ml/out/gguf-kev/q8.jsonl   # production rule, labels
    python3 ml/models/kev_gguf.py diff ml/out/gguf-kev/a.jsonl ml/out/gguf-kev/b.jsonl

A rerun of `score` retries requests that failed (the newer row wins when a file is read).

Standard library only, apart from prompt_grid's renderer for `score`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
REF = ROOT / "ml/out/prompt-grid/raw/kev-K2-150.jsonl"
PPLX = ROOT / "ml/out/prompt-grid/raw/pplx-K1-full.jsonl"
LISTINGS = ROOT / "ml/out/prompt-grid/listings.json"
KEY = ROOT.parent / "makhzan-config/labels/answer-key-v2.jsonl"
GGUF_TEMPERATURE = 2.406049966812134  # ggml-org/Kev-4B-GGUF metadata, every quantisation
KEV_MIN, PPLX_MIN = 0.80, 0.95  # policy p1 (makhzan_schemas.ai.policy)


def post(url: str, body: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def cmd_score(args) -> None:
    import prompt_grid as pg

    listings = json.loads(LISTINGS.read_text())
    pairs = pg.key_pairs(KEY)[: args.n] if args.n else pg.key_pairs(KEY)
    done = set()
    if args.out.exists():
        rows = map(json.loads, args.out.open())
        done = {(r["pair_id"], r["order"]) for r in rows if r["score"] is not None}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    t_start, k = time.time(), 0
    with args.out.open("a") as fh:
        for p in pairs:
            for o in ("ab", "ba"):
                if (p["pair_id"], o) in done:
                    continue
                a, b = (p["listing_a"], p["listing_b"])[:: 1 if o == "ab" else -1]
                pl = pg.payload(listings, a, b, "K2", pg.CAPS["150"])
                t0 = time.time()
                try:
                    r = post(f"{args.base}/v1/systemone", {"model": "kev", **pl})
                    s, extra = r["answers"]["same"]["noul"], {"usage": r.get("usage")}
                except Exception as e:  # noqa: BLE001 - recorded; compare counts them
                    s, extra = None, {"error": str(e)[:300]}
                row = {"pair_id": p["pair_id"], "order": o, "score": s,
                       "seconds": round(time.time() - t0, 4), **extra}  # fmt: skip
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                k += 1
    el = time.time() - t_start
    print(f"{k} requests in {el:.1f}s = {k / el:.2f} req/s" if k else "nothing to do")


def uncalibrate(p: float, t: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return 1 / (1 + math.exp(-t * math.log(p / (1 - p))))


def load(path: Path, t: float = 1.0) -> dict:
    rows = {}
    for r in map(json.loads, path.open()):
        s = r["score"]
        rows[(r["pair_id"], r["order"])] = None if s is None else uncalibrate(s, t)
    return rows


def spearman(x: list[float], y: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=v.__getitem__)
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for q in range(i, j + 1):
                r[order[q]] = (i + j) / 2
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return sxy / math.sqrt(sxx * syy)


def pair_min(rows: dict, pid: str) -> float | None:
    a, b = rows.get((pid, "ab")), rows.get((pid, "ba"))
    return None if a is None or b is None else min(a, b)


def cmd_compare(args) -> None:
    ref, new = load(REF), load(args.scores, args.temperature)
    errors = sum(v is None for v in new.values())
    keys = [k for k, v in new.items() if v is not None and ref.get(k) is not None]
    x, y = [ref[k] for k in keys], [new[k] for k in keys]
    d = [abs(a - b) for a, b in zip(x, y, strict=True)]
    print(f"requests {len(keys)} (errors {errors})")
    print(f"spearman {spearman(x, y):.4f}  max|dp| {max(d):.4f}  mean|dp| {sum(d) / len(d):.4f}")
    for t in (0.5, 0.8, 0.9):
        flips = sum((a >= t) != (b >= t) for a, b in zip(x, y, strict=True))
        print(f"  request agree@{t}: {1 - flips / len(x):.2%} ({flips} flips)")
    pids = sorted({p for p, _ in keys if None not in (pair_min(new, p), pair_min(ref, p))})
    for t in (0.5, 0.8, 0.9):
        fl = [(p, round(pair_min(ref, p), 3), round(pair_min(new, p), 3)) for p in pids
              if (pair_min(ref, p) >= t) != (pair_min(new, p) >= t)]  # fmt: skip
        print(f"  pair (min) agree@{t}: {1 - len(fl) / len(pids):.2%} ({len(fl)} of {len(pids)})"
              + (f"  {fl[:12]}" if fl else ""))  # fmt: skip


def cmd_decisions(args) -> None:
    """The production rule (Kev >= 0.8 and pplx >= 0.95, pair = min of both orders) on pairs
    today's vetoes pass, for the reference and the variant, against the labels."""
    key = {r["pair_id"]: r for r in map(json.loads, KEY.open())}
    pplx = load(PPLX)
    runs = {"bf16 (reference)": load(REF), args.scores.name: load(args.scores, args.temperature)}
    # Only pairs every run scored (both orders), so a partial run is compared like for like.
    ok = [p for p, k in key.items() if not any(k["veto"].values())
          and all(pair_min(r, p) is not None for r in (*runs.values(), pplx))]  # fmt: skip
    decided = {}
    for name, rows in runs.items():
        merge = {p: pair_min(rows, p) >= KEV_MIN and pair_min(pplx, p) >= PPLX_MIN for p in ok}
        decided[name] = merge
        wrong = sum(merge[p] and key[p]["label"] == "not" for p in ok)
        kev = [(pair_min(rows, p) >= KEV_MIN, key[p]["label"] == "same") for p in ok
               if key[p]["label"] != "unsure"]  # fmt: skip
        tp = sum(a and b for a, b in kev)
        print(f"{name}: pairs {len(ok)}  merges {sum(merge.values())}  wrong merges {wrong}  "
              f"Kev-only precision {tp / max(1, sum(a for a, _ in kev)):.3f} "
              f"recall {tp / max(1, sum(b for _, b in kev)):.3f}")  # fmt: skip
    a, b = decided.values()
    changed = [(p, key[p]["label"]) for p in a if p in b and a[p] != b[p]]
    print(f"changed decisions: {len(changed)} {changed}")


def cmd_diff(args) -> None:
    """Two llama.cpp runs against each other (e.g. two batch sizes, two machines), on the raw
    scale the accuracy tables use and on llama.cpp's calibrated scale."""
    for label, t in (("raw", args.temperature), ("calibrated", 1.0)):
        a, b = load(args.a, t), load(args.b, t)
        keys = [k for k in a if a[k] is not None and b.get(k) is not None]
        d = [abs(a[k] - b[k]) for k in keys]
        print(
            f"{label}: requests {len(keys)}  max|dp| {max(d):.4f}  mean|dp| {sum(d) / len(d):.5f}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--base", required=True, help="llama.cpp server, e.g. http://127.0.0.1:8130")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--n", type=int, help="first N pairs of the answer key (both orders)")
    for name in ("compare", "decisions", "diff"):
        c = sub.add_parser(name)
        if name == "diff":
            c.add_argument("a", type=Path)
            c.add_argument("b", type=Path)
        else:
            c.add_argument("scores", type=Path)
        c.add_argument("--temperature", type=float, default=GGUF_TEMPERATURE,
                       help="the GGUF's decision temperature, undone before comparing")  # fmt: skip
    args = ap.parse_args()
    cmds = {
        "score": cmd_score,
        "compare": cmd_compare,
        "decisions": cmd_decisions,
        "diff": cmd_diff,
    }
    cmds[args.cmd](args)


if __name__ == "__main__":
    main()
