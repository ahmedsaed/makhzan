"""Phase E judge bake-off: score pairs with one candidate judge, both orders.

    python3 ml/models/judge.py --improve ml/out/improve --judge kev-rules --out ml/out/models
    python3 ml/models/judge.py --improve ml/out/improve --judge pplx --out ml/out/models \
        --edges ml/out/models/edges1.jsonl --texts ml/out/models/edge-texts.json --tag edges1 \
        --two-pass

Judges (each needs its service running alone on the GPU, ml/README.md):

- kev-rules: Kev-4B (kev-4b), the Phase E setup (title as contexts.clean, raw P(yes), 8 in
  flight) with RULES_QUESTION instead of I2: the same question plus the error classes found in
  the labelled data, named as rules.
- pplx: perplexity-ai/pplx-decider-flash-v1.3 (pplx-decider), a `noul` question, the I2
  question verbatim and Kev's state layout. Records P(true) at the checkpoint's saved
  temperature and the raw logit margin.
- qwen35: Qwen/Qwen3.5-4B (gen-qwen3.5-4b), thinking off, QWEN_PROMPT; records the margin
  log P(yes) - log P(no) at the first answer token (temperature is fitted later, score.py).
- qwen35-think: qwen35 with thinking on (up to 2,048 tokens), only on the labelled pairs
  whose Phase E Kev score is in THINK_BAND; the margin is read at the answer after </think>.
  Piloted on 16 pairs only (every answer "no", 7 unfinished at 2,048 tokens); not run in full.

The labelled pairs come from <improve>/pairs.jsonl and their texts from
<improve>/kev-enrich/texts.json (variant L0, exactly what Kev was scored on). --edges/--texts
score other pairs instead ({"pair_id", "a", "b"} per line; {listing id: title}; edges.py
writes them). Every pair is scored as (a, b) and (b, a); with --two-pass, (b, a) only where
(a, b) >= 0.05, which changes no decision (min <= 0.05 is below every threshold and below
complete-link's 0.0772 "confidently different" line either way). Writes <out>/<judge>[-<tag>].json = {pair_id: [ab, ba]} (scores)
and, for pplx and qwen35, <out>/<judge>[-<tag>].margin.json (logit margins), plus
<out>/<judge>[-<tag>].meta.json (question, requests, seconds, pairs/s, peak GPU MiB sampled by
nvidia-smi). ml/out is git-ignored; nothing here holds catalogue text.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "bakeoff"))
from common import KEV_QUESTIONS  # noqa: E402
from makhzan_ml.client import Client  # noqa: E402

I2 = KEV_QUESTIONS["I2"]
RULES_QUESTION = (
    I2 + " They are different products if they differ in package or package suffix (e.g. TO-220 "
    "vs TO-247, SMD vs through-hole, IRF vs IRFP), NC vs NO, standard vs long/short versions, "
    "module/board vs bare IC, a model-number digit or suffix that denotes a different chip "
    "(MPU-6050 vs MPU-6500), or a stated range/rating; the same part number written "
    "differently (74HC164 vs 74164 only if the family matches; TEC1-12706 vs TEC-12706) is the "
    "same product."
)
QWEN_PROMPT = (
    "Two product listings from electronics shops.\n"
    "Listing A: {a}\nListing B: {b}\n\n"
    "{question} Answer only yes or no."
)
SERVICE = {
    "kev-rules": "kev-4b",
    "pplx": "pplx-decider",
    "qwen35": "gen-qwen3.5-4b",
    "qwen35-think": "gen-qwen3.5-4b",
}
THINK_BAND = (0.3, 0.9)  # qwen35-think scores only pairs whose Phase E Kev score is in here


class GpuPeak:
    """Peak total GPU memory in use (MiB) while the block runs, sampled every 0.5 s."""

    def __enter__(self):
        self.peak, self._stop = 0, threading.Event()

        def run():
            while not self._stop.is_set():
                try:
                    out = subprocess.run(
                        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=5,
                    ).stdout  # fmt: skip
                    self.peak = max(self.peak, int(out.split()[0]))
                except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                    pass
                self._stop.wait(0.5)

        self._t = threading.Thread(target=run, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join()


def load(args) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    if args.edges:
        texts = json.loads(args.texts.read_text())
        items = [json.loads(line) for line in args.edges.open()]
        return [(e["pair_id"], e["a"], e["b"]) for e in items], texts
    texts = {k: v["L0"] for k, v in
             json.loads((args.improve / "kev-enrich" / "texts.json").read_text()).items()}  # fmt: skip
    pairs = [json.loads(line) for line in (args.improve / "pairs.jsonl").open()]
    if args.judge == "qwen35-think":
        lo, hi = THINK_BAND
        pairs = [p for p in pairs if lo <= p.get("kev_raw", p["kev"]) < hi]
    return [(p["pair_id"], p["listing_a"], p["listing_b"]) for p in pairs], texts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--improve", type=Path, required=True)
    ap.add_argument("--judge", choices=sorted(SERVICE), required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--edges", type=Path)
    ap.add_argument("--texts", type=Path)
    ap.add_argument("--tag", default="")
    ap.add_argument("--in-flight", type=int, default=8)
    ap.add_argument(
        "--two-pass",
        action="store_true",
        help="score (b, a) only where (a, b) >= 0.05 (not for qwen35's raw margins)",
    )
    args = ap.parse_args()
    if args.two_pass and args.judge.startswith("qwen35"):
        ap.error("--two-pass needs a probability; qwen35 returns an uncalibrated margin")

    items, texts = load(args)
    name = args.judge + (f"-{args.tag}" if args.tag else "")
    args.out.mkdir(parents=True, exist_ok=True)
    question = {
        "kev-rules": RULES_QUESTION,
        "pplx": I2,
        "qwen35": QWEN_PROMPT.format(a="<A>", b="<B>", question=I2),
    }.get(args.judge)
    question = question or QWEN_PROMPT.format(a="<A>", b="<B>", question=I2)
    tokens: list[int] = []  # fmt: skip

    def run(batch: list[tuple[str, str]]) -> tuple[list[float], list[float] | None]:
        if not batch:
            return [], None
        if args.judge == "kev-rules":
            return Client("kev-4b", batch_size=args.in_flight).score(batch, question), None
        if args.judge == "pplx":
            res = Client("pplx-decider", batch_size=32, concurrency=1).decide_noul(batch, I2)
            return [r[0] for r in res], [r[1] for r in res]
        prompts = [QWEN_PROMPT.format(a=a, b=b, question=I2) for a, b in batch]
        if args.judge == "qwen35-think":
            res = Client("gen-qwen3.5-4b", batch_size=args.in_flight * 4).think_yes_no_margin(
                prompts
            )
            tokens.extend(n for _, n in res)
            z = [0.0 if m is None else m for m, _ in res]  # unfinished thinking: undecided
            return z, z
        z = Client("gen-qwen3.5-4b", batch_size=args.in_flight * 4).yes_no_margin(prompts)
        return z, z  # calibrated later (score.py fits a temperature by 2-fold)

    fwd = [(texts[a], texts[b]) for _, a, b in items]
    with GpuPeak() as gpu:
        t0 = time.time()
        s_ab, m_ab = run(fwd)
        second = [i for i in range(len(items)) if not args.two_pass or s_ab[i] >= 0.05]
        s_ba, m_ba = run([(fwd[i][1], fwd[i][0]) for i in second])
        seconds = time.time() - t0
    requests = len(fwd) + len(second)

    def pairs_of(ab, ba):
        out = {pid: [round(ab[i], 6)] for i, (pid, _, _) in enumerate(items)}
        for j, i in enumerate(second):
            out[items[i][0]].append(round(ba[j], 6))
        return out

    (args.out / f"{name}.json").write_text(json.dumps(pairs_of(s_ab, s_ba)))
    if m_ab is not None:
        (args.out / f"{name}.margin.json").write_text(json.dumps(pairs_of(m_ab, m_ba or [])))
    meta = {"judge": args.judge, "service": SERVICE[args.judge], "question": question,
            "pairs": len(items), "requests": requests, "two_pass": args.two_pass,
            "seconds": round(seconds, 1), "pairs_per_s": round(requests / seconds, 2),
            "gpu_peak_mib_total": gpu.peak}  # fmt: skip
    if tokens:
        meta["completion_tokens"] = {"total": sum(tokens), "mean": round(sum(tokens) / len(tokens)),
                                     "max": max(tokens)}  # fmt: skip
    (args.out / f"{name}.meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta), flush=True)


if __name__ == "__main__":
    main()
