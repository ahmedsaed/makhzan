"""Benchmark the local model services: load time, memory, throughput, and validation scores.

    python3 ml/bench.py --data <path>/validation.jsonl --out ml/out \
        --services emb-qwen3,rr-bge,rr-qwen3-0.6b

For each service, one at a time and alone on the GPU: stop every ml service, start this one,
time it to healthy (weights must already be cached; the services run offline by default, see
README "Downloading weights"), read GPU memory (nvidia-smi, used minus the idle baseline) and container RAM (docker
stats, peak while it works), score the validation pairs (saved for quant.py), then time 1,000
pairs (distinct pairs built from the validation listings, see unique_pairs) at each batch size.

"Batch size" is pairs per HTTP request with --concurrency requests in flight; for Kev, which
takes one pair (state) per request, it is the number of requests in flight. An embedder's
"pair" is two texts embedded, so its pairs/s is comparable with a judge's.

Writes <out>/<service><tag>.json (results) and <out>/scores-<service><tag>.json ({pair_id: p}).
--data must live outside the repo. --out defaults to ml/out, which git ignores; the score files
hold pair ids and probabilities only, never catalogue text.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from makhzan_ml.client import SAME_PRODUCT, SERVICES, Client  # noqa: E402

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).resolve().parent / "docker-compose.yml")]
ALL_PROFILES = [
    "--profile",
    "gpu-small",
    "--profile",
    "big",
    "--profile",
    "cpu",
    "--profile",
    "compare",
]


def listing_text(side: dict, with_specs: bool) -> str:
    t = side["title"].strip()
    if with_specs and side.get("specs"):
        t += " | " + side["specs"].strip()
    return t


def load_pairs(path: Path, with_specs: bool) -> tuple[list[str], list[tuple[str, str]]]:
    ids, pairs = [], []
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            ids.append(r["pair_id"])
            pairs.append((listing_text(r["a"], with_specs), listing_text(r["b"], with_specs)))
    return ids, pairs


def unique_pairs(pairs: list[tuple[str, str]], n: int) -> list[tuple[str, str]]:
    """n distinct pairs of the validation listings' texts, none of them a validation pair.

    Texts still recur across pairs (there are only ~500 listings), so throughput is measured
    with vLLM's prefix cache off (VLLM_EXTRA_ARGS, set by run_one): otherwise a repeated text,
    or a whole repeated prompt, is served from memory. Repeating the validation pairs verbatim
    once made the FP8 4B look 10x faster than bf16 for exactly that reason."""
    texts = list(dict.fromkeys(t for p in pairs for t in p))
    seen, out, m = set(pairs), [], len(texts)
    for shift in range(1, m):
        for i in range(m):
            pair = (texts[i], texts[(i + shift) % m])
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
                if len(out) == n:
                    assert len(set(out)) == n
                    return out
    raise ValueError(f"only {len(out)} distinct pairs available, asked for {n}")


def sh(cmd: list[str], env: dict | None = None, check: bool = True) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    if check and p.returncode:
        raise RuntimeError(f"{' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p.stdout.strip()


def gpu_used_mib() -> int | None:
    try:
        return int(
            sh(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
            ).splitlines()[0]
        )
    except Exception:
        return None


_UNITS = {"B": 1, "KiB": 2**10, "MiB": 2**20, "GiB": 2**30, "kB": 1e3, "MB": 1e6, "GB": 1e9}


def container_ram_mib(name: str) -> float | None:
    out = sh(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name], check=False)
    m = re.match(r"([\d.]+)\s*([A-Za-z]+)", out)
    return float(m.group(1)) * _UNITS.get(m.group(2), 1) / 2**20 if m else None


class Peak:
    """Samples GPU memory and container RAM in the background; keeps the maxima."""

    def __init__(self, container: str):
        self.container, self.gpu, self.ram = container, 0, 0.0
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            self.gpu = max(self.gpu, gpu_used_mib() or 0)
            self.ram = max(self.ram, container_ram_mib(self.container) or 0)
            self._stop.wait(0.5)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._t.join()


def wait_healthy(container: str, timeout: float) -> None:
    end = time.time() + timeout
    while time.time() < end:
        st = sh(
            ["docker", "inspect", "-f", "{{.State.Status}} {{.State.Health.Status}}", container],
            check=False,
        )
        if st.endswith("healthy") and not st.endswith("unhealthy"):
            return
        if st.startswith(("exited", "dead")):
            raise RuntimeError(
                f"{container} exited:\n"
                + sh(["docker", "logs", "--tail", "60", container], check=False)
            )
        time.sleep(1)
    raise TimeoutError(f"{container} not healthy after {timeout}s")


def cpu_count(cpuset: str) -> int:
    n = 0
    for part in cpuset.split(","):
        a, _, b = part.partition("-")
        n += int(b or a) - int(a) + 1
    return n


def run_one(name: str, args, ids, pairs, out: Path) -> dict:
    svc = SERVICES[name]
    container = f"makhzan-ml-{name}-1"
    is_cpu = "-cpu" in name
    env = {"CPU_SET": args.cpu_set} if is_cpu else {}
    # Prefix caching off for every vLLM server the bench starts (see unique_pairs). TEI and Kev
    # (KEV_PREFIX_CACHE=0 in compose) have none to switch off.
    env["VLLM_EXTRA_ARGS"] = "--no-enable-prefix-caching"
    env["KEV_PREFIX_CACHE"] = "0"  # explicit, so an exported shell value cannot override compose
    res_started = not args.no_lifecycle
    if not res_started:
        print(
            f"  WARNING: --no-lifecycle: {name} was not started by bench, so its prefix cache is"
            " whatever it was started with; throughput may measure the cache",
            flush=True,
        )
    res: dict = {
        "service": name,
        "model": svc.hf_id,
        "engine": svc.kind,
        "tag": args.tag,
        "text": "title+specs" if args.with_specs else "title",
        "concurrency": args.concurrency,
    }
    if is_cpu:
        res["cpuset"], res["cpus"] = args.cpu_set, cpu_count(args.cpu_set)
    res["bench_started_server"] = res_started

    if not args.no_lifecycle:
        sh(COMPOSE + ALL_PROFILES + ["down", "--remove-orphans"], check=False)
        time.sleep(2)
        base = gpu_used_mib()
        t0 = time.time()
        sh(COMPOSE + ["up", "-d", name], env=env)
        wait_healthy(container, args.health_timeout)
        res["load_s"] = round(time.time() - t0, 1)
        time.sleep(2)
        idle = gpu_used_mib()
        res["gpu_idle_baseline_mib"] = base
        res["gpu_loaded_mib"] = (
            (idle - base) if (idle is not None and base is not None and not is_cpu) else None
        )
        res["ram_loaded_mib"] = round(container_ram_mib(container) or 0)
    else:
        # The server is already up, so there is no idle baseline: GPU memory is reported as the
        # total in use (every process) under a different key, never as this service's own.
        base = None

    cli = lambda bs: Client(name, batch_size=bs, concurrency=args.concurrency)  # noqa: E731
    is_emb = svc.kind.endswith("-embed")
    instr = args.instruction

    def do(c: Client, ps):
        if is_emb:
            flat = [t for p in ps for t in p]
            v = c.embed(flat, instruction=instr if svc.takes_instruction else None)
            return [sum(x * y for x, y in zip(v[2 * i], v[2 * i + 1])) for i in range(len(ps))]
        return c.score(ps, instruction=instr)

    do(cli(8), pairs[:16])  # warm-up
    with Peak(container) as pk:
        scores = do(cli(32), pairs)
        (out / f"scores-{name}{args.tag}.json").write_text(
            json.dumps(dict(zip(ids, scores)), indent=0)
        )

        big = unique_pairs(pairs, args.n)
        res["throughput"] = []
        sizes = args.kev_inflight if svc.kind == "kev" else args.batch_sizes
        for bs in sizes:
            t = time.time()
            do(cli(bs), big)
            dt = time.time() - t
            row = {"batch": bs, "seconds": round(dt, 2), "pairs_per_s": round(args.n / dt, 1)}
            if is_cpu:
                row["pairs_per_s_per_cpu"] = round(args.n / dt / res["cpus"], 2)
            res["throughput"].append(row)
            print(f"  {name}{args.tag} batch {bs}: {row['pairs_per_s']} pairs/s", flush=True)
    if is_cpu:
        res["gpu_peak_mib"] = None
    elif base is not None:
        res["gpu_peak_mib"] = pk.gpu - base
    else:
        res["gpu_peak_total_in_use_mib"] = pk.gpu  # --no-lifecycle: not this service's alone
    res["ram_peak_mib"] = round(pk.ram)
    (out / f"{name}{args.tag}.json").write_text(json.dumps(res, indent=2))
    return res


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--services", required=True, help="comma-separated service names")
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "out")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--batch-sizes", default="1,8,32,128")
    ap.add_argument("--kev-inflight", default="1,8,32,64")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--cpu-set", default="0-11", help="cpuset for -cpu services")
    ap.add_argument("--title-only", dest="with_specs", action="store_false")
    ap.add_argument("--instruction", default=SAME_PRODUCT)
    ap.add_argument("--tag", default="", help="suffix for output files, e.g. -fp8")
    ap.add_argument(
        "--no-lifecycle", action="store_true", help="service already running; skip start/stop"
    )
    ap.add_argument("--keep", action="store_true", help="leave the last service running")
    ap.add_argument("--health-timeout", type=float, default=1800)
    args = ap.parse_args()
    args.batch_sizes = [int(x) for x in args.batch_sizes.split(",")]
    args.kev_inflight = [int(x) for x in args.kev_inflight.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    ids, pairs = load_pairs(args.data, args.with_specs)
    for name in args.services.split(","):
        print(f"== {name}{args.tag}", flush=True)
        try:
            r = run_one(name, args, ids, pairs, args.out)
            print(json.dumps({k: v for k, v in r.items() if k != "throughput"}), flush=True)
        except Exception as e:  # keep going: one broken service should not cost the others
            print(f"  FAILED: {e}", flush=True)
            (args.out / f"{name}{args.tag}.error.txt").write_text(str(e))
    if not args.keep and not args.no_lifecycle:
        sh(COMPOSE + ALL_PROFILES + ["down"], check=False)


if __name__ == "__main__":
    main()
