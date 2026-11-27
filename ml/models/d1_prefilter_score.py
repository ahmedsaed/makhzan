"""Score a d1 pre-filter sample against a llama.cpp server (docs/ai/decision-models.md, s. 7).

Each input line is {"pair": [a, b], "order": "ab"|"ba", "request": <Kev's K2 payload>}; each
output line keeps the server's calibrated P(yes) for "same" (d1_prefilter_analyse.py undoes the
baked temperature), the seconds and the input tokens. Strings are NFC-normalised first.

    python3 ml/models/d1_prefilter_score.py ml/out/models-compare/d1-prefilter/requests.jsonl \
        ml/out/models-compare/d1-prefilter/d1-uniform.jsonl [--base http://127.0.0.1:8200]

The requests and meta files (the 1,000-pair uniform backlog sample, seed 20261127, and the
500 merged pairs, seed 7, with their production Kev and pplx scores) were drawn by a one-off
that was not kept; they live in ml/out/models-compare/d1-prefilter/.
"""

from __future__ import annotations

import argparse
import json
import time
import unicodedata
import urllib.request


def nfc(v):
    if isinstance(v, str):
        return unicodedata.normalize("NFC", v)
    if isinstance(v, dict):
        return {k: nfc(x) for k, x in v.items()}
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--base", default="http://127.0.0.1:8200")
    ap.add_argument("--model", default="d1")
    args = ap.parse_args()
    t0, n, err = time.time(), 0, 0
    with open(args.dst, "w") as out:
        for line in open(args.src):
            r = json.loads(line)
            t = time.time()
            body = json.dumps({"model": args.model, **nfc(r["request"])}).encode()
            req = urllib.request.Request(
                f"{args.base}/v1/systemone", body, {"Content-Type": "application/json"}
            )
            row = {"pair": r["pair"], "order": r["order"]}
            try:
                a = json.loads(urllib.request.urlopen(req, timeout=120).read())
                row |= {
                    "score": a["answers"]["same"]["noul"],
                    "seconds": round(time.time() - t, 4),
                    "tokens": (a.get("usage") or {}).get("input_tokens"),
                }
            except Exception as e:  # noqa: BLE001 - recorded per request
                err += 1
                row |= {"score": None, "error": str(e)[:200]}
            out.write(json.dumps(row) + "\n")
            n += 1
    el = time.time() - t0
    print(f"{args.src}: {n} requests, {err} errors, {el:.0f}s, {n / el:.2f} req/s")


if __name__ == "__main__":
    main()
