"""Compare other decision models with Kev and pplx on the Phase E labels (owner, 2026-11-26).

Two prompts, no new wording: "K2" is Kev's approved payload (prompt_grid.payload, K2, cap 150);
"K2c" adds the approved CRITERIA (grid_payloads.CRITERIA) to the question, unchanged.

    python3 ml/models/compare_models.py render                       # requests.jsonl
    python3 ml/models/compare_models.py score --base URL --model NAME --variant K2 \
        --out ml/out/models-compare/<name>-K2.jsonl [--nfc] [--n N]   # /v1/systemone
    python3 ml/models/compare_models.py analyse    # exits non-zero unless the doc's numbers hold

Score files keep the server's calibrated P(yes); `analyse` converts to raw with each model's
temperature where one is baked in (raw = sigmoid(T * logit p)).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
OUT = ROOT / "ml/out/models-compare"
KEY = ROOT.parent / "makhzan-config/labels/answer-key-v2.jsonl"
LISTINGS = ROOT / "ml/out/prompt-grid/listings.json"
KEV = ROOT / "ml/out/prompt-grid/raw/kev-K2-150.jsonl"
PPLX = ROOT / "ml/out/prompt-grid/raw/pplx-K1-full.jsonl"
REQUESTS = OUT / "requests.jsonl"
# The temperature each llama.cpp server applies to noul answers (read from the GGUF), undone in
# `analyse`. Intern-Decision is scored raw already (DecisionEngine(temperature=1)); its own
# calibration temperature is 1.99241824.
TEMPERATURES = {"h2o": 0.8, "d1": 1.3374}


def cmd_render(_args) -> None:
    import grid_payloads as gp
    import prompt_grid as pg

    listings = json.loads(LISTINGS.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    with REQUESTS.open("w") as fh:
        for p in pg.key_pairs(KEY):
            for o in ("ab", "ba"):
                a, b = (p["listing_a"], p["listing_b"])[:: 1 if o == "ab" else -1]
                k2 = pg.payload(listings, a, b, "K2", pg.CAPS["150"])
                k2c = json.loads(json.dumps(k2))
                k2c["questions"]["same"]["criteria"] = dict(gp.CRITERIA)
                for v, pl in (("K2", k2), ("K2c", k2c)):
                    row = {"pair_id": p["pair_id"], "order": o, "variant": v, "payload": pl}
                    fh.write(json.dumps(row) + "\n")
    print(sum(1 for _ in REQUESTS.open()), "requests")


def nfc(v):
    if isinstance(v, str):
        return unicodedata.normalize("NFC", v)
    if isinstance(v, dict):
        return {k: nfc(x) for k, x in v.items()}
    if isinstance(v, list):
        return [nfc(x) for x in v]
    return v


def post(url: str, body: dict, timeout: float = 300) -> dict:
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def cmd_score(args) -> None:
    rows = [r for r in map(json.loads, REQUESTS.open()) if r["variant"] == args.variant]
    if args.n:
        keep = sorted({r["pair_id"] for r in rows})[: args.n]
        rows = [r for r in rows if r["pair_id"] in keep]
    done = set()
    if args.out.exists():
        for r in map(json.loads, args.out.open()):
            if r.get("score") is not None:
                done.add((r["pair_id"], r["order"]))
    t0, k = time.time(), 0
    with args.out.open("a") as fh:
        for r in rows:
            if (r["pair_id"], r["order"]) in done:
                continue
            pl = nfc(r["payload"]) if args.nfc else r["payload"]
            t = time.time()
            try:
                body = post(f"{args.base}/v1/systemone", {"model": args.model, **pl})
                s, extra = body["answers"]["same"]["noul"], {"usage": body.get("usage")}
                if isinstance(s, bool) or not (0.0 <= float(s) <= 1.0):
                    raise ValueError(f"bad score {s!r}")
            except Exception as e:  # noqa: BLE001 - recorded
                s, extra = None, {"error": str(e)[:300]}
            out = {"pair_id": r["pair_id"], "order": r["order"], "score": s,
                   "seconds": round(time.time() - t, 4), **extra}  # fmt: skip
            fh.write(json.dumps(out) + "\n")
            fh.flush()
            k += 1
    el = time.time() - t0
    print(f"{k} requests in {el:.1f}s = {k / el:.2f} req/s" if k else "nothing to do")


# --- analysis ----------------------------------------------------------------------------------
def raw(p: float, t: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    return 1 / (1 + math.exp(-t * math.log(p / (1 - p))))


def load(path: Path, t: float = 1.0) -> dict:
    d = {}
    for r in map(json.loads, path.open()):
        if r.get("score") is not None:
            d[(r["pair_id"], r["order"])] = raw(r["score"], t) if t != 1.0 else r["score"]
    return d


def pmin(d: dict, p: str):
    a, b = d.get((p, "ab")), d.get((p, "ba"))
    return None if a is None or b is None else min(a, b)


def auc(pos: list[float], neg: list[float]) -> float:
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    i = 0
    r = [0.0] * len(allv)
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for q in range(i, j + 1):
            r[q] = (i + j) / 2 + 1
        i = j + 1
    rp = sum(rk for rk, (_, y) in zip(r, allv, strict=True) if y)
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def avg_precision(scored: list[tuple[float, bool]]) -> float:
    scored = sorted(scored, key=lambda x: -x[0])
    tp, ap, npos = 0, 0.0, sum(y for _, y in scored)
    for i, (_, y) in enumerate(scored, 1):
        if y:
            tp += 1
            ap += tp / i
    return ap / npos


def pr_at(scored, t):
    tp = sum(s >= t and y for s, y in scored)
    fp = sum(s >= t and not y for s, y in scored)
    npos = sum(y for _, y in scored)
    return (tp / (tp + fp) if tp + fp else float("nan")), tp / npos, tp, fp


def matched_threshold(scored, target_precision):
    """Lowest threshold whose precision is >= target (most recall at that precision)."""
    best = None
    for t in sorted({s for s, _ in scored}):
        p, r, tp, fp = pr_at(scored, t)
        if tp + fp and p >= target_precision:
            best = (t, p, r) if best is None or r > best[2] else best
    return best


# The runs docs/ai/decision-models.md section 4 reports from analysis.json, in its order. Other
# runs in OUT (H2O Q4, Intern structured) are analysed by intern_struct_analyse.py.
ANALYSED = ("d1-K2", "d1-K2c", "h2o-K2", "h2o-K2c", "intern-K2", "intern-K2c")

# What the doc states, checked after every analyse: (auc, ap, recall at Kev's precision,
# recall at pplx's precision, (merges, correct, wrong) replacing Kev, the same replacing pplx,
# mean |ab - ba|).
EXPECTED = {
    "kev-bf16": (0.942, 0.9619, 0.7221, 0.3974, None, None, 0.1058),
    "pplx-bf16": (0.9563, 0.9727, 0.7429, 0.587, None, None, 0.0471),
    "d1-K2": (0.9207, 0.9473, 0.6545, 0.2883, (196, 196, 0), (102, 102, 0), 0.0664),
    "d1-K2c": (0.9228, 0.95, 0.6701, 0.3117, (196, 195, 1), (113, 113, 0), 0.0536),
    "h2o-K2": (0.9499, 0.9696, 0.7688, 0.5688, (217, 216, 1), (211, 210, 1), 0.0747),
    "h2o-K2c": (0.9508, 0.97, 0.7636, 0.5818, (215, 214, 1), (213, 211, 2), 0.0774),
    "intern-K2": (0.932, 0.9522, 0.6104, 0.3688, (184, 183, 1), (143, 142, 1), 0.1188),
    "intern-K2c": (0.9332, 0.9514, 0.5818, 0.0909, (178, 178, 0), (35, 35, 0), 0.1048),
}


def check_expected(rep: dict) -> None:
    """Exit non-zero unless the analysis matches the numbers the doc states."""

    def mwc(r):
        return None if r is None else (r["merges"], r["correct"], r["wrong"])

    bad = []
    for name, want in EXPECTED.items():
        m = rep["models"].get(name)
        got = m and (
            m["auc"],
            m["ap"],
            m["threshold_at_kev_precision"][2],
            m["threshold_at_pplx_precision"][2],
            mwc(m.get("as_kev")),
            mwc(m.get("as_pplx")),
            m["order_mean_abs_diff"],
        )
        if got != want:
            bad.append(f"{name}: expected {want}, got {got}")
    print("\n".join(bad) if bad else "check: every documented number reproduced")
    if bad:
        sys.exit(1)


def cmd_analyse(args) -> None:
    key = {r["pair_id"]: r for r in map(json.loads, KEY.open())}
    kev, pplx = load(KEV), load(PPLX)
    runs = {"kev-bf16": (kev, 1.0), "pplx-bf16": (pplx, 1.0)}
    for name in ANALYSED:
        t = TEMPERATURES.get(name.split("-")[0], 1.0)
        runs[name] = (load(OUT / f"{name}.jsonl", t), t)
    base = [p for p, k in key.items() if not any(k["veto"].values()) and k["label"] != "unsure"
            and pmin(kev, p) is not None and pmin(pplx, p) is not None]  # fmt: skip
    rep = {"pairs_base": len(base), "models": {}}
    kev_scored = [(pmin(kev, p), key[p]["label"] == "same") for p in base]
    kev_prec = pr_at(kev_scored, 0.8)[0]
    pplx_scored = [(pmin(pplx, p), key[p]["label"] == "same") for p in base]
    pplx_prec = pr_at(pplx_scored, 0.95)[0]
    for name, (d, _t) in runs.items():
        ps = [p for p in base if pmin(d, p) is not None]
        if len(ps) < 50:
            continue  # a run still in progress
        sc = [(pmin(d, p), key[p]["label"] == "same") for p in ps]
        pos = [s for s, y in sc if y]
        neg = [s for s, y in sc if not y]
        m = {"pairs": len(ps), "auc": round(auc(pos, neg), 4), "ap": round(avg_precision(sc), 4)}
        m["at"] = {str(t): [round(x, 3) for x in pr_at(sc, t)[:2]] for t in
                   (0.5, 0.7, 0.8, 0.9, 0.95, 0.98)}  # fmt: skip
        for label, target in (("kev_precision", kev_prec), ("pplx_precision", pplx_prec)):
            mt = matched_threshold(sc, target)
            m[f"threshold_at_{label}"] = None if mt is None else [round(x, 4) for x in mt]
        # Replacements in the production rule, at the Kev-precision-matched threshold.
        diffs = [abs(d[(p, "ab")] - d[(p, "ba")]) for p in ps]
        m["order_mean_abs_diff"] = round(sum(diffs) / len(diffs), 4)
        mt = m["threshold_at_kev_precision"]
        if mt and name not in ("kev-bf16", "pplx-bf16"):
            t = mt[0]
            mp = m["threshold_at_pplx_precision"]
            roles = {"as_kev": [p for p in ps if pmin(d, p) >= t and pmin(pplx, p) >= 0.95]}
            if mp:
                roles["as_pplx"] = [p for p in ps if pmin(kev, p) >= 0.8 and pmin(d, p) >= mp[0]]
            for role, merged in roles.items():
                m[role] = {"merges": len(merged),
                           "correct": sum(key[p]["label"] == "same" for p in merged),
                           "wrong": sum(key[p]["label"] == "not" for p in merged)}  # fmt: skip
            ref = [p for p in ps if pmin(kev, p) >= 0.8 and pmin(pplx, p) >= 0.95]
            m["production_bf16_same_pairs"] = {
                "merges": len(ref),
                "correct": sum(key[p]["label"] == "same" for p in ref),
            }
            m["agree_with_kev_at_matched"] = round(
                sum((pmin(d, p) >= t) == (pmin(kev, p) >= 0.8) for p in ps) / len(ps), 4
            )
            vals = [pmin(d, p) for p in ps]
            m["score_spread"] = [round(min(vals), 4), round(sorted(vals)[len(vals) // 2], 4),
                                 round(max(vals), 4)]  # fmt: skip
        rep["models"][name] = m
    rep["kev_precision_at_0.8"] = round(kev_prec, 4)
    rep["pplx_precision_at_0.95"] = round(pplx_prec, 4)
    (OUT / "analysis.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    check_expected(rep)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("render")
    s = sub.add_parser("score")
    s.add_argument("--base", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--variant", choices=["K2", "K2c"], required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--nfc", action="store_true")
    s.add_argument("--n", type=int)
    sub.add_parser("analyse")
    args = ap.parse_args()
    {"render": cmd_render, "score": cmd_score, "analyse": cmd_analyse}[args.cmd](args)


if __name__ == "__main__":
    main()
