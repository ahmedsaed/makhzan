"""The owner-approved prompt grid for the merge judges (docs/ai/decision-review.md, section 4).

    # 1. listing records from `makhzan_prod` (one JSON object per line: id, title_en, title_ar,
    #    category = categories.name_en, brand, part_number, mfr_part_number = attributes->
    #    'mfr_part_number', specs = attributes->'specs', description_en):
    python3 ml/models/prompt_grid.py rows --db-rows <db_rows.jsonl> --out ml/out/prompt-grid
    # 2. the rendered payloads are the approved file's, byte for byte (sample pairs):
    python3 ml/models/prompt_grid.py check --out ml/out/prompt-grid \
        --approved ml/out/labels/render_payloads.py --sample ml/out/labels/payload-sample-pairs.json
    # 3. token counts per request and context-limit check, in an image with transformers:
    docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 -e HF_HUB_OFFLINE=1 \
      -v "$PWD/ml/.cache/huggingface:/hf:z" -v "$PWD/ml:/ml:ro" -v "$PWD/ml/out:/o:z" \
      makhzan-ml/kev:1.0 /ml/models/prompt_grid.py tokens --out /o/prompt-grid --hub /hf/hub \
      --key /o/labels/answer-key-v2.jsonl --improve /o/improve
    # 4. score, one service alone on the GPU (ml/README.md), one request per call:
    python3 ml/models/prompt_grid.py score --model kev --cap 150 --out ml/out/prompt-grid \
        --key ml/out/labels/answer-key-v2.jsonl
    # 5. compare (stdlib):
    python3 ml/models/prompt_grid.py report --out ml/out/prompt-grid --improve ml/out/improve \
        --key ml/out/labels/answer-key-v2.jsonl --models ml/out/models

The grid (14 configurations): Kev-4B and pplx-decider-flash-v1.3 each with K1 (rules in the
state), K2 (rules in the instructions) and K1 + criteria; Qwen3.5-4B with the chat messages
(system = RULES, user = listings + question), scored as P(yes) / (P(yes) + P(no)) at the first
answer token (the client's yes_no_margin path, thinking off, greedy). Each with the description
capped at 150 words or full. Payloads come from grid_payloads.py, unchanged. Every pair is
scored as (A, B) and (B, A), one request per HTTP call and one call in flight (bit-stable for
pplx, the owner's protocol); the pair score is the lower one. Kev runs at the service's settings
(KEV_TEMPERATURE=1.0, raw P(yes)); pplx at its checkpoint temperature.

Outputs under --out (git-ignored; listings.json holds catalogue text): raw/<config>.jsonl (one
line per request, resumable), scores/<config>.json ({pair_id: [ab, ba]}), noise/<config>.json
(NOISE pairs re-scored twice), meta/<config>.json (requests, seconds, req/s, GPU peak),
tokens.json, results.json.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "bakeoff"))
sys.path.insert(0, str(HERE.parent / "improve"))
sys.path.insert(0, str(HERE))

import grid_payloads as gp  # noqa: E402

VARIANTS = {
    "K1": "K1 (rules in state)",
    "K2": "K2 (rules in instructions)",
    "K1c": "K1 + criteria",
    "chat": "Qwen3.5 (chat, score P(yes))",
}
MODELS = {"kev": ("K1", "K2", "K1c"), "pplx": ("K1", "K2", "K1c"), "qwen": ("chat",)}
SERVICE = {"kev": "kev-4b", "pplx": "pplx-decider", "qwen": "gen-qwen3.5-4b"}
CAPS = {"150": 150, "full": None}
NOISE = 50
# Context limits (tokens): Kev's server refuses a state over 65,536 (kev.model.SERVE_MAX_STATE)
# and a question row over state + 8,192; pplx refuses a question over 32,768 (DEFAULT_MAX_LENGTH);
# Qwen3.5-4B is served with --max-model-len QWEN35_MAX_LEN.
LIMITS = {"kev": 65536, "pplx": 32768}
TITLE_ONLY_CPU_RATE = 0.117  # Kev-4B, title-only, home server, req/s (measured)
SEED = 20261116
KNOWN = {
    "KSD301 NC/NO": "E0337", "IRF250/IRFP250": "E0446", "ATmega328/328P": "E0098",
    "MPU-6500/6050": "E0711", "1N5819/SS14": "E0581", "HX711 module/IC": "E0362",
    "33 pF capacitor": "E0149", "1602 LCD bundle": "E0579",
}  # fmt: skip


def configs() -> list[str]:
    return [f"{m}-{v}-{c}" for m, vs in MODELS.items() for v in vs for c in CAPS]


def key_pairs(key: Path) -> list[dict]:
    return [json.loads(line) for line in key.open()]


def payload(listings: dict, a: str, b: str, variant: str, cap: int | None):
    return gp.payloads({"listing_a": listings[a], "listing_b": listings[b]}, cap)[VARIANTS[variant]]


# --- 1. listing records ------------------------------------------------------------------------
def record(row: dict) -> dict:
    from contexts import clean  # tags out, entities decoded, whitespace collapsed

    specs = row.get("specs")
    return {
        "id": row["id"],
        "title": row.get("title_en") or row.get("title_ar"),
        "category": row.get("category"),
        "brand": row.get("brand"),
        "part_number": row.get("mfr_part_number") or row.get("part_number"),
        "specs": specs if isinstance(specs, dict) else None,
        "description": clean(row.get("description_en")),
    }


def cmd_rows(args) -> None:
    rows = [json.loads(line) for line in args.db_rows.open() if line.startswith("{")]
    out = {r["id"]: record(r) for r in rows}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "listings.json").write_text(json.dumps(out, ensure_ascii=False))
    print(f"{len(out)} listings")


# --- 2. byte-identity check ------------------------------------------------------------------
def cmd_check(args) -> None:
    spec = importlib.util.spec_from_file_location("approved", args.approved)
    approved = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(approved)
    for name in ("RULES", "QUESTION", "CRITERIA"):
        assert getattr(approved, name) == getattr(gp, name), name
    listings = json.loads((args.out / "listings.json").read_text())
    sample = json.loads(args.sample.read_text())
    n = 0
    for pid, pair in sample.items():
        ours = {"listing_a": listings[pair["listing_a"]["id"]],
                "listing_b": listings[pair["listing_b"]["id"]]}  # fmt: skip
        for cap in CAPS.values():
            for a, b in (("listing_a", "listing_b"), ("listing_b", "listing_a")):
                want = json.dumps(approved.payloads({"listing_a": pair[a], "listing_b": pair[b]},
                                                    cap), ensure_ascii=False)  # fmt: skip
                got = json.dumps(gp.payloads({"listing_a": ours[a], "listing_b": ours[b]}, cap),
                                 ensure_ascii=False)  # fmt: skip
                assert want == got, (pid, cap, a)
                n += 1
    print(f"byte-identical: {n} renderings ({len(sample)} sample pairs x 2 caps x 2 orders)")


# --- 3. tokens -------------------------------------------------------------------------------
def flat_text(variant: str, p) -> tuple[str, str]:
    """(state text, question text) as the model reads them, without the server's template."""
    if variant == "chat":
        return p[0]["content"], p[1]["content"]
    q = p["questions"]["same"]
    crit = q.get("criteria") or {}
    return p["state"], "\n".join([q["instructions"], *crit.values()])


def cmd_tokens(args) -> None:
    from transformers import AutoTokenizer

    def snap(name: str) -> str:
        d = args.hub / f"models--{name.replace('/', '--')}" / "snapshots"
        return str(next(d.iterdir()))

    toks = {
        "kev": AutoTokenizer.from_pretrained(snap("Qwen/Qwen3.5-4B-Base")),
        "pplx": AutoTokenizer.from_pretrained(snap("perplexity-ai/pplx-decider-flash-v1.3")),
        "qwen": AutoTokenizer.from_pretrained(snap("Qwen/Qwen3.5-4B")),
    }
    listings = json.loads((args.out / "listings.json").read_text())
    pairs = key_pairs(args.key)
    res: dict = {}
    for cfg in configs():
        model, variant, cap = cfg.split("-")
        tok = toks[model]
        n_state, n_total, over = [], [], 0
        for p in pairs:
            for a, b in ((p["listing_a"], p["listing_b"]), (p["listing_b"], p["listing_a"])):
                pl = payload(listings, a, b, variant, CAPS[cap])
                if model == "qwen":
                    text = tok.apply_chat_template(pl, add_generation_prompt=True, tokenize=False,
                                                   enable_thinking=False)  # fmt: skip
                    s = t = len(tok(text, add_special_tokens=False)["input_ids"])
                else:
                    st, q = flat_text(variant, pl)
                    s = len(tok(st)["input_ids"])
                    t = s + len(tok(q)["input_ids"])
                n_state.append(s)
                n_total.append(t)
                over += model in LIMITS and t > LIMITS[model]
        st = sorted(n_total)
        res[cfg] = {"requests": len(n_total), "mean_tokens": round(sum(st) / len(st), 1),
                    "p95": st[int(0.95 * len(st))], "max": st[-1], "over_limit": over,
                    "limit": LIMITS.get(model)}  # fmt: skip
        print(cfg, res[cfg], flush=True)
    # title-only Kev requests (the Phase E layout: I2 question, titles as Kev saw them)
    titles = {k: v["L0"] for k, v in
              json.loads((args.improve / "kev-enrich" / "texts.json").read_text()).items()}  # fmt: skip
    from common import KEV_QUESTIONS

    q = len(toks["kev"](KEV_QUESTIONS["I2"])["input_ids"])
    n = [len(toks["kev"](f"Listing A: {titles[p['listing_a']]}\nListing B: {titles[p['listing_b']]}"
                         )["input_ids"]) + q for p in pairs]  # fmt: skip
    res["kev-title-only"] = {"requests": len(n), "mean_tokens": round(sum(n) / len(n), 1)}
    print("kev-title-only", res["kev-title-only"])
    (args.out / "tokens.json").write_text(json.dumps(res, indent=1))


# --- 4. score --------------------------------------------------------------------------------
def scorer(model: str):
    from makhzan_ml.client import Client, _post

    if model == "kev":
        c = Client("kev-4b")

        def kev(pl):
            out = _post(f"{c.base}/v1/systemone", {"model": c.svc.model, **pl}, c.timeout)
            return out["answers"]["same"]["noul"], {"usage": out.get("usage")}

        return kev
    if model == "pplx":
        c = Client("pplx-decider")

        def pplx(pl):
            out = _post(f"{c.base}/v1/decide", {"requests": [pl]}, c.timeout)
            f, t = out["logits"][0]["same"]  # option order: false, true
            return out["responses"][0]["answers"]["same"]["noul"], {"margin": t - f}

        return pplx
    c = Client("gen-qwen3.5-4b", batch_size=1)

    def qwen(pl):
        usage: list = []
        z = c.yes_no_margin([pl], usage=usage)[0]
        p = 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))
        return p, {"margin": z, "usage": usage[0]}

    return qwen


def cmd_score(args) -> None:
    from judge import GpuPeak

    listings = json.loads((args.out / "listings.json").read_text())
    pairs = key_pairs(args.key)
    one = scorer(args.model)
    for d in ("raw", "scores", "noise", "meta"):
        (args.out / d).mkdir(parents=True, exist_ok=True)
    for variant in MODELS[args.model]:
        if args.variants and variant not in args.variants:
            continue
        cfg = f"{args.model}-{variant}-{args.cap}"
        cap = CAPS[args.cap]
        raw = args.out / "raw" / f"{cfg}.jsonl"
        done = {}
        if raw.exists():
            for line in raw.open():
                r = json.loads(line)
                done[(r["pair_id"], r["order"])] = r
        todo = [(p, o) for p in pairs for o in ("ab", "ba") if (p["pair_id"], o) not in done]
        t_start = time.time()
        failed = 0
        with GpuPeak() as gpu, raw.open("a") as fh:
            for p, o in todo:
                a, b = p["listing_a"], p["listing_b"]
                if o == "ba":
                    a, b = b, a
                t0 = time.time()
                try:
                    s, extra = one(payload(listings, a, b, variant, cap))
                except Exception as e:  # noqa: BLE001 - recorded, the report counts them
                    s, extra = None, {"error": str(e)[:300]}
                    failed += 1
                r = {"pair_id": p["pair_id"], "order": o, "score": s,
                     "seconds": round(time.time() - t0, 4), **extra}  # fmt: skip
                done[(p["pair_id"], o)] = r
                fh.write(json.dumps(r) + "\n")
                fh.flush()
        seconds = time.time() - t_start
        scores = {p["pair_id"]: [done[(p["pair_id"], "ab")]["score"],
                                 done[(p["pair_id"], "ba")]["score"]] for p in pairs}  # fmt: skip
        (args.out / "scores" / f"{cfg}.json").write_text(json.dumps(scores))
        # noise: every 18th pair (stratum-mixed), (A, B) re-scored twice
        npairs = pairs[:: len(pairs) // NOISE][:NOISE]
        rep = {}

        def again(pl):  # a failed repeat is recorded as None, as a failed request is
            try:
                return one(pl)[0]
            except Exception:  # noqa: BLE001
                return None

        for p in npairs:
            pl = payload(listings, p["listing_a"], p["listing_b"], variant, cap)
            rep[p["pair_id"]] = [done[(p["pair_id"], "ab")]["score"], again(pl), again(pl)]
        (args.out / "noise" / f"{cfg}.json").write_text(json.dumps(rep))
        sec_req = [r["seconds"] for r in done.values() if r["score"] is not None]
        meta = {"config": cfg, "service": SERVICE[args.model], "requests": len(todo),
                "failed": failed, "seconds": round(seconds, 1),
                "req_per_s": round(len(todo) / seconds, 3) if todo else None,
                # None when every request failed (nothing timed) rather than a ZeroDivisionError
                "req_per_s_from_latency": round(len(sec_req) / sum(sec_req), 3)
                if sec_req and sum(sec_req) > 0 else None,
                "gpu_peak_mib_total": gpu.peak}  # fmt: skip
        (args.out / "meta" / f"{cfg}.json").write_text(json.dumps(meta, indent=1))
        print(json.dumps(meta), flush=True)


# --- 5. report -------------------------------------------------------------------------------
CURVE = [round(0.05 * i, 2) for i in range(1, 20)] + [0.97, 0.98, 0.99, 0.995]
SWEEP = sorted(set(CURVE + [round(0.5 + i * 0.005, 3) for i in range(100)] + [0.9975, 0.999]))
FIXED = {"kev": 0.9, "pplx": 0.5, "qwen": 0.5}


def cmd_report(args) -> None:
    from metric import cp_lower, evaluate, sweep

    key = {p["pair_id"]: p for p in key_pairs(args.key)}
    cells = {json.loads(line)["pair_id"]: json.loads(line)["cell"]
             for line in (args.improve / "pairs.jsonl").open()}  # fmt: skip
    y = {"same": 1, "not": 0}
    pairs = [{**p, "cell": cells[p["pair_id"]], "y": y.get(p["label"])} for p in key.values()]
    listings = json.loads((args.out / "listings.json").read_text())
    title = {k: v["title"] for k, v in listings.items()}
    tokens = json.loads((args.out / "tokens.json").read_text())

    def pair_min(v) -> float:
        # a pair with no score in either order is never accepted (0.0); `missing` counts them
        return min((x for x in v if x is not None), default=0.0)

    def mins(d: dict) -> dict:
        return {k: pair_min(v) for k, v in d.items()}

    sig = lambda z: 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))  # noqa: E731
    s: dict[str, dict[str, float]] = {
        # the key's `kev` is 0 where today's vetoes fire; the judge's own score is the min of
        # its orders ((B, A) was skipped where (A, B) < 0.05, the Phase E two-pass)
        "baseline:kev-title": {p["pair_id"]: pair_min((p["kev_ab"], p["kev_ba"]))
                               for p in key.values()},
        "baseline:pplx-title": mins(json.loads((args.models / "pplx.json").read_text())),
        "baseline:qwen-title": {k: sig(min(v)) for k, v in
                                json.loads((args.models / "qwen35.json").read_text()).items()},
    }  # fmt: skip
    missing = {}
    for cfg in configs():
        f = args.out / "scores" / f"{cfg}.json"
        if f.exists():
            d = json.loads(f.read_text())
            missing[cfg] = sum(None in v for v in d.values())
            s[cfg] = mins(d)
    veto_old = {p["pair_id"]: p["vetoed"] for p in key.values()}

    def judge(name: str) -> str:
        return (
            name.split(":")[1].split("-")[0] if name.startswith("baseline") else name.split("-")[0]
        )

    def errors(accept) -> list[dict]:
        return [{"pair_id": p["pair_id"], "cell": p["cell"], "soft": p["soft"],
                 "a": title.get(p["listing_a"]), "b": title.get(p["listing_b"])}
                for p in pairs if p["y"] == 0 and accept(p)]  # fmt: skip

    def summary(accept, veto: bool = False) -> dict:
        acc = (lambda p: accept(p) and not veto_old[p["pair_id"]]) if veto else accept
        r = evaluate(pairs, acc)
        n_same = sum(1 for p in pairs if p["y"] == 1)
        tp = sum(1 for p in pairs if p["y"] == 1 and acc(p))
        err = errors(acc)
        return {"accepted": r["used"], "same": r["same"], "errors": r["errors"],
                "soft_errors": sum(e["soft"] for e in err),
                "precision_raw": round(r["precision_raw"], 4) if r["used"] else None,
                "precision_w": round(r["precision_weighted"], 4) if r["used"] else None,
                "bound_w": round(r["bound"], 4) if r["used"] else None,
                "cp_raw": round(cp_lower(r["same"], r["used"]), 4) if r["used"] else None,
                "recall_raw": round(tp / n_same, 4),
                "recall_w": None, "est_matches": r["est_matches"], "error_pairs": err}  # fmt: skip

    from metric import cell_sizes

    size, dec = cell_sizes(pairs)
    tot_same = sum(size[p["cell"]] / dec[p["cell"]] for p in pairs if p["y"] == 1)

    def with_recall(r: dict) -> dict:
        r["recall_w"] = round(r["est_matches"] / tot_same, 4)
        return r

    res: dict = {"labelled": {"same": sum(p["y"] == 1 for p in pairs),
                              "not": sum(p["y"] == 0 for p in pairs),
                              "unsure_excluded": sum(p["y"] is None for p in pairs),
                              "soft": sum(p["soft"] for p in pairs)},
                 "missing_scores": missing, "single": {}, "curves": {}, "rule": {}}  # fmt: skip
    for name, sc in s.items():
        t = FIXED[judge(name)]
        res["single"][name] = with_recall(summary(lambda p, sc=sc, t=t: sc[p["pair_id"]] >= t))
        res["single"][name]["threshold"] = t
        res["curves"][name] = [
            {"t": th, **{k: v for k, v in with_recall(
                summary(lambda p, sc=sc, th=th: sc[p["pair_id"]] >= th)).items()
                if k != "error_pairs"}} for th in CURVE]  # fmt: skip
    rules = {"title": ("baseline:kev-title", "baseline:pplx-title")}
    for v in ("K1", "K2", "K1c"):
        for c in CAPS:
            if f"kev-{v}-{c}" in s and f"pplx-{v}-{c}" in s:
                rules[f"{v}-{c}"] = (f"kev-{v}-{c}", f"pplx-{v}-{c}")
    for name, (k, q) in rules.items():
        acc = lambda p, k=s[k], q=s[q]: k[p["pair_id"]] >= 0.9 and q[p["pair_id"]] >= 0.5  # noqa: E731
        res["rule"][name] = {"no_veto": with_recall(summary(acc)),
                             "behind_today_vetoes": with_recall(summary(acc, veto=True))}  # fmt: skip

    # known hard pairs
    res["known"] = {}
    for label, pid in KNOWN.items():
        p = next(x for x in pairs if x["pair_id"] == pid)
        res["known"][label] = {"pair_id": pid, "label": p["label"], "soft": p["soft"],
                               "a": title[p["listing_a"]], "b": title[p["listing_b"]],
                               "scores": {n: round(sc[pid], 4) for n, sc in s.items()},
                               "rule": {n: s[k][pid] >= 0.9 and s[q][pid] >= 0.5
                                        for n, (k, q) in rules.items()}}  # fmt: skip

    # noise
    res["noise"] = {}
    for cfg in configs():
        f = args.out / "noise" / f"{cfg}.json"
        if f.exists():
            d = json.loads(f.read_text())
            d = {k: [x for x in v if x is not None] for k, v in d.items()}  # failed repeats
            diffs = [abs(x - v[0]) for v in d.values() for x in v[1:]]
            t = FIXED[cfg.split("-")[0]]
            flips = sum(len({x >= t for x in v}) > 1 for v in d.values())
            res["noise"][cfg] = {"pairs": len(d), "max_abs_diff": max(diffs, default=None),
                                 "identical": sum(x == 0 for x in diffs), "of": len(diffs),
                                 "flips_at_fixed_threshold": flips}  # fmt: skip

    # cost
    title_tok = tokens["kev-title-only"]["mean_tokens"]
    res["cost"] = {}
    for cfg in configs():
        f = args.out / "meta" / f"{cfg}.json"
        if f.exists() and cfg in tokens:
            m = json.loads(f.read_text())
            tk = tokens[cfg]["mean_tokens"]
            served = []
            for line in (args.out / "raw" / f"{cfg}.jsonl").open():
                u = json.loads(line).get("usage") or {}
                n = u.get("input_tokens") or u.get("prompt_tokens")
                if n:
                    served.append(n)
            res["cost"][cfg] = {"gpu_req_per_s": m["req_per_s_from_latency"],
                                "gpu_peak_mib": m["gpu_peak_mib_total"],
                                "mean_tokens": tk, "max_tokens": tokens[cfg]["max"],
                                "mean_tokens_served": round(sum(served) / len(served), 1)
                                if served else None,
                                "over_limit": tokens[cfg].get("over_limit"),
                                "cpu_req_per_s_implied": round(TITLE_ONLY_CPU_RATE * title_tok / tk, 4)}  # fmt: skip
    res["cost_title_only_kev_tokens"] = title_tok

    # held-out: rank in-sample by the metric (largest certified estimate, else highest bound)
    def single_rule(sc):
        return lambda t: lambda p: sc[p["pair_id"]] >= t

    cands = {n: ("single", sc) for n, sc in s.items() if not n.startswith("baseline")}
    for n, (k, q) in rules.items():
        if n != "title":
            cands[f"rule:{n}"] = ("rule", (s[k], s[q]))

    def best_of(kind, obj, subset=None):
        if kind == "single":
            t, r, _ = sweep(pairs, single_rule(obj), SWEEP, subset)
            return t, r
        k, q = obj
        best = None
        for tq in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
            t, r, _ = sweep(pairs, lambda tk, tq=tq: (lambda p: k[p["pair_id"]] >= tk and
                                                     q[p["pair_id"]] >= tq), SWEEP, subset)  # fmt: skip
            key_ = (r["certified"], r["metric"] if r["certified"] else r["bound"])
            if best is None or key_ > best[0]:
                best = (key_, (t, tq), r)
        return best[1], best[2]

    insample = {}
    for n, (kind, obj) in cands.items():
        t, r = best_of(kind, obj)
        insample[n] = {"threshold": t, "certified": r["certified"], "est_matches": r["est_matches"],
                       "bound": round(r["bound"], 4), "errors": r["errors"], "used": r["used"]}  # fmt: skip
    res["insample_tuned"] = insample
    rank = sorted(insample, key=lambda n: (insample[n]["certified"],
                  insample[n]["est_matches"] if insample[n]["certified"] else insample[n]["bound"]),
                  reverse=True)  # fmt: skip
    fold = {}
    by = defaultdict(list)
    for p in pairs:
        by[(p["cell"], p["label"])].append(p["pair_id"])
    rng = random.Random(SEED)
    for k_ in sorted(by):
        ids = sorted(by[k_])
        rng.shuffle(ids)
        for i, pid in enumerate(ids):
            fold[pid] = i % 2
    res["heldout"] = {}
    for n in rank[:3]:
        kind, obj = cands[n]
        out = []
        for f in (0, 1):
            tune = {pid for pid, x in fold.items() if x == f}
            test = {pid for pid, x in fold.items() if x != f}
            t, r_tune = best_of(kind, obj, tune)
            if kind == "single":
                acc = single_rule(obj)(t)
            else:

                def acc(p, k=obj[0], q=obj[1], t=t):
                    return k[p["pair_id"]] >= t[0] and q[p["pair_id"]] >= t[1]

            r = evaluate(pairs, acc, test)
            out.append({"tuned_on_fold": f, "threshold": t,
                        "tune": {"bound": round(r_tune["bound"], 4), "errors": r_tune["errors"],
                                 "used": r_tune["used"]},
                        "test": {"used": r["used"], "errors": r["errors"],
                                 "precision_w": round(r["precision_weighted"], 4) if r["used"] else None,
                                 "bound": round(r["bound"], 4) if r["used"] else None,
                                 "est_matches_half": r["est_matches"],
                                 "error_pairs": errors(lambda p, acc=acc, test=test:
                                                       p["pair_id"] in test and acc(p))}})  # fmt: skip
        res["heldout"][n] = out
    (args.out / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    for n, r in res["single"].items():
        print(
            f"{n:24s} t={r['threshold']} acc={r['accepted']} err={r['errors']} "
            f"Pw={r['precision_w']} bound={r['bound_w']} Rw={r['recall_w']}"
        )
    for n, r in res["rule"].items():
        for vv, x in r.items():
            print(
                f"rule {n:12s} {vv:20s} acc={x['accepted']} err={x['errors']} "
                f"Pw={x['precision_w']} bound={x['bound_w']} Rw={x['recall_w']}"
            )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rows")
    r.add_argument("--db-rows", type=Path, required=True)
    r.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--approved", type=Path, required=True)
    c.add_argument("--sample", type=Path, required=True)
    t = sub.add_parser("tokens")
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--hub", type=Path, required=True)
    t.add_argument("--key", type=Path, required=True)
    t.add_argument("--improve", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--model", choices=sorted(MODELS), required=True)
    s.add_argument("--cap", choices=sorted(CAPS), required=True)
    s.add_argument("--variants", nargs="*")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--key", type=Path, required=True)
    p = sub.add_parser("report")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--improve", type=Path, required=True)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--models", type=Path, required=True)
    args = ap.parse_args()
    {"rows": cmd_rows, "check": cmd_check, "tokens": cmd_tokens, "score": cmd_score,
     "report": cmd_report}[args.cmd](args)  # fmt: skip


if __name__ == "__main__":
    main()
