"""Parity: the worker's scores, end to end, against stored validated scores.

    python -m makhzan_ml.worker.parity --model kev --device gpu \
        --requests /req/kev-K2-150.jsonl --n 20 --out /o/parity-kev.json

`--requests` is a file in the CPU benchmark's format (one JSON object per line:
`pair_id`, `order`, `request`, the stored `gpu_score` and the setup's `threshold`;
`ml/out/bench-cpu/requests/`, git-ignored). The first `--n` requests, kept as whole
pairs, become one job per pair in a `fake_broker` on 127.0.0.1, and a real `Worker`
leases, scores and posts them through the whole protocol (hello, lease, request-hash
check, results, release) with the real model loaded by `judges.load`. So this checks
what production will run, not a shortcut around it, and it needs no network
(`docker run --network none` keeps loopback).

**llama.cpp** (`--backend llamacpp`): the worker talks to a running llama.cpp server
(`--llamacpp-url`, a loopback address) serving `--gguf-path`, which must be the pinned GGUF.
`--stored` replaces the file's `gpu_score` with scores from another file (one JSON object per
line: `pair_id`, `order`, `score`), e.g. a llama.cpp run of the same GGUF, read through
`--stored-temperature` (2.406 for scores as llama.cpp returned them, calibrated; 1 for raw):

    python -m makhzan_ml.worker.parity --model kev --backend llamacpp --device gpu \
        --llamacpp-url http://127.0.0.1:8130 --gguf-path /models/Kev-4B-Q4_K_M.gguf \
        --requests ml/out/bench-cpu/requests/kev-K2-150.jsonl --n 20 \
        --stored ml/out/gguf-kev/q4km-vulkan-3060.jsonl --stored-temperature 2.406

The report holds pair ids, orders, scores and timings, never catalogue text. Agreement
is `--tolerance` on the absolute difference (0.05, the CPU benchmark's session-chosen
value) and the count of decisions that change side of the setup's threshold.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from makhzan_ml.worker import config as config_mod
from makhzan_ml.worker import judges, run
from makhzan_ml.worker.fake_broker import FakeBroker
from makhzan_ml.worker.pins import pin_for

TOKEN = "parity-token"


def pick(lines: list[dict], n: int) -> list[list[dict]]:
    """Whole pairs, in file order, until at least `n` requests."""
    pairs: dict[str, list[dict]] = {}
    for r in lines:
        pairs.setdefault(r["pair_id"], []).append(r)
    out, count = [], 0
    for rows in pairs.values():
        if count >= n:
            break
        out.append(rows)
        count += len(rows)
    return out


def compare(rows: list[dict], tolerance: float) -> dict:
    diffs = [abs(r["worker"] - r["stored"]) for r in rows if None not in (r["worker"], r["stored"])]
    flips = [r for r in rows if None not in (r["worker"], r["stored"])
             and (r["worker"] >= r["threshold"]) != (r["stored"] >= r["threshold"])]  # fmt: skip
    return {
        "requests": len(rows),
        "compared": len(diffs),
        "missing_worker": sum(r["worker"] is None for r in rows),
        "missing_stored": sum(r["stored"] is None for r in rows),
        "max_abs_diff": max(diffs) if diffs else None,
        "mean_abs_diff": sum(diffs) / len(diffs) if diffs else None,
        "within_tolerance": sum(d <= tolerance for d in diffs),
        "tolerance": tolerance,
        "decision_flips": [(r["pair_id"], r["order"]) for r in flips],
        "agree": bool(diffs) and len(diffs) == len(rows) and max(diffs) <= tolerance and not flips,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m makhzan_ml.worker.parity")
    ap.add_argument("--model", required=True, choices=["kev", "pplx"])
    ap.add_argument("--device", default="gpu", choices=["cpu", "gpu"])
    ap.add_argument("--threads", type=int)
    ap.add_argument("--requests", type=Path, required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--tolerance", type=float, default=0.05)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--backend", default="torch", choices=["torch", "llamacpp"])
    ap.add_argument("--llamacpp-url")
    ap.add_argument("--gguf-path")
    ap.add_argument("--stored", type=Path, help="stored scores to compare with, by pair/order")
    ap.add_argument("--stored-temperature", type=float, default=1.0)
    args = ap.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    lines = [json.loads(line) for line in args.requests.open()]
    if args.stored:
        stored = {}
        for line in args.stored.open():
            r = json.loads(line)
            if r.get("score") is not None:
                stored[(r["pair_id"], r["order"])] = judges.uncalibrate(
                    r["score"], args.stored_temperature
                )
        lines = [{**r, "gpu_score": stored.get((r["pair_id"], r["order"]))} for r in lines]
    pairs = pick(lines, args.n)
    compute = {"device": args.device, **({"threads": args.threads} if args.threads else {})}
    if args.backend == "llamacpp":
        compute.update(backend="llamacpp", llamacpp_url=args.llamacpp_url,
                       gguf_path=args.gguf_path)  # fmt: skip
    pin = pin_for(args.model, args.backend)
    with FakeBroker(
        {TOKEN: ("parity", [args.model])},
        versions={args.model: pin.model_version},
        weights={args.model: pin.weights_revision},
    ) as broker:
        jobs = {}
        for rows in pairs:
            job = broker.add_job(args.model, {r["order"]: r["request"] for r in rows})
            jobs[job.job_id] = rows
        cfg = config_mod.parse(
            {
                "worker": {"name": f"parity-{args.model}", "broker_url": broker.url,
                           "token": TOKEN, "model": args.model},
                "compute": compute,
                "schedule": {"windows": "always", "on_empty": "exit"},
                "leases": {"max_jobs": 4, "lease_s": 900, "heartbeat_s": 60},
            }
        )  # fmt: skip
        t0 = time.monotonic()
        worker = run.Worker(cfg)
        code = worker.run()
        wall = time.monotonic() - t0
        rows_out = []
        for job_id, rows in jobs.items():
            got = broker.jobs[job_id].scores
            for r in rows:
                s = got.get(r["order"])
                rows_out.append(
                    {
                        "pair_id": r["pair_id"],
                        "order": r["order"],
                        "worker": s["p"] if s else None,
                        "stored": r.get("gpu_score"),
                        "threshold": r.get("threshold", 0.5),
                        "seconds": s["seconds"] if s else None,
                        "device": s["device"] if s else None,
                        "dtype": s["dtype"] if s else None,
                    }
                )
        session_end = [s["end_reason"] for s in broker.sessions.values()]
    summary = compare(rows_out, args.tolerance)
    report = {
        "model": args.model,
        "backend": args.backend,
        "model_version": pin.model_version,
        "stored": str(args.stored.name) if args.stored else "gpu_score",
        "device": args.device,
        "requests_file": args.requests.name,
        "exit_code": code,
        "wall_seconds": round(wall, 1),
        "judge_info": worker.judge_info.get(args.model),
        "session_end": session_end,
        "summary": summary,
        "rows": rows_out,
    }
    text = json.dumps(report, indent=1, default=str)
    if args.out:
        args.out.write_text(text)
    print(json.dumps(summary, indent=1))
    return 0 if code == 0 and summary["agree"] else 1


if __name__ == "__main__":
    sys.exit(main())
