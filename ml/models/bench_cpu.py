"""CPU benchmark of the owner's chosen judge setup, rendered on the desktop, run on the CPU worker.

The setup (decided): Kev-4B, layout K2 (rules in the instructions), description capped at 150
words, accept at >= 0.8; and pplx-decider-flash-v1.3, layout K1 (rules in the state), full
description, accept at >= 0.95. Each pair is scored in both reading orders, one request per call,
and the pair score is the lower one. No two-stage. Requests are rendered by prompt_grid.py's
`payload` (the approved grid_payloads.py, unchanged) from listings built by its `record()`.

    # 1. desktop: draw the pairs, check the database against the grid's listings.json, render
    #    (stdlib; reads the local `makhzan_prod` through `docker exec psql`, read-only SELECT)
    python3 ml/models/bench_cpu.py render --key ml/out/labels/answer-key-v2.jsonl \
        --grid ml/out/prompt-grid --out ml/out/bench-cpu
    # 2. in the lean CPU image, with --network none: load the model in this process (no mmap)
    #    and score the requests one per call (ml/out/bench-cpu/RUNBOOK.md has the full commands)
    python /bench/bench_cpu.py run --model kev --requests /req/kev-K2-150.jsonl --out /o/kev.json
    # 3. compare with the desktop GPU scores (stdlib)
    python3 ml/models/bench_cpu.py parity --result ml/out/bench-cpu/results/kev.json \
        --requests ml/out/bench-cpu/requests/kev-K2-150.jsonl

`run` keeps each service's own scoring path and settings: Kev through kev.serve's Server.answer
(what POST /v1/systemone calls) with KEV_DTYPE=fp32, KEV_PREFIX_CACHE=0, KEV_TEMPERATURE=1.0, as
compose's kev-4b-cpu; pplx through serve.py's build() and the same logits -> answer computation
as POST /v1/decide, fp32 (the card's CPU choice), BATCH_TOKENS=8192. The only change is how the
weights are read: every safetensors file is read with pread(2) rather than memory-mapped
(no_mmap), and the result records any weight file mapped after loading (mapped_weights: the real
paths of the Hub cache's weight files, which are symlinks to suffix-less blobs, and anything under
the cache; `selfcheck` proves it sees a file mapped through such a symlink, and `run` runs that
check first). Its top level is standard library only, so it runs in either image.

Session-chosen measurement parameters, not owner decisions (docs/ai/decision-review.md, D23):
N_PAIRS = 60 pairs drawn for the benchmark and parity's --tolerance 0.05. They decide how much is
measured and what counts as CPU/GPU agreement, not what merges.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import resource
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261116
N_PAIRS = 60  # session default, awaiting owner review (decision-review.md, D23)
# (model, prompt_grid variant, cap) -> threshold of the chosen setup
SETUP = {"kev-K2-150": ("kev", "K2", "150", 0.8), "pplx-K1-full": ("pplx", "K1", "full", 0.95)}
# Pinned to the cached snapshot's commit (kev.checkpoint.resolve_run takes `repo@revision`); its
# head.pt pins the base itself (Qwen/Qwen3.5-4B-Base@1001bb4d826a52d1f399e183466143f4da7b741b).
KEV_REVISION = "6cfce5c2fa4b4bd64026336ab649c5ca78857d52"
KEV_RUN = f"jaredpalmer/kev-4b@{KEV_REVISION}"
KEV_MODEL_NAME = "kev-latest"  # what makhzan_ml.client sends as `model` (Service "kev-4b")
PPLX_REPO = "perplexity-ai/pplx-decider-flash-v1.3"
PPLX_REVISION = "d06fb3f2d97e0a52325a0d463c450cf0338f44fe"
WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".gguf")

SQL = """
SELECT json_build_object(
  'id', l.id, 'title_en', l.title_en, 'title_ar', l.title_ar, 'category', c.name_en,
  'brand', l.brand, 'part_number', l.part_number,
  'mfr_part_number', l.attributes->>'mfr_part_number', 'specs', l.attributes->'specs',
  'description_en', l.description_en)
FROM listings l LEFT JOIN categories c ON c.id = l.category_id
WHERE l.id IN ({ids}) ORDER BY l.id
"""


# --- 1. render (desktop) -------------------------------------------------------------------------
def db_rows(ids: list[str], container: str, user: str, db: str) -> list[dict]:
    in_list = ",".join(f"'{i}'" for i in ids if all(c in "0123456789abcdef-" for c in i))
    cmd = ["docker", "exec", "-i", container, "psql", "-U", user, "-d", db, "-v",
           "ON_ERROR_STOP=1", "-At", "-c", SQL.format(ids=in_list)]  # fmt: skip
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cmd_render(args) -> None:
    sys.path.insert(0, str(HERE))
    import prompt_grid as pg  # the grid's record() and payload(), unchanged

    pairs = pg.key_pairs(args.key)
    sample = sorted(random.Random(args.seed).sample(pairs, args.n), key=lambda p: p["pair_id"])
    ids = sorted({p[k] for p in sample for k in ("listing_a", "listing_b")})
    grid = json.loads((args.grid / "listings.json").read_text())
    rows = {r["id"]: r for r in db_rows(ids, args.container, args.db_user, args.db)}
    fresh = {i: pg.record(rows[i]) for i in ids if i in rows}
    same = [i for i in ids if i in fresh and json.dumps(fresh[i], ensure_ascii=False)
            == json.dumps(grid[i], ensure_ascii=False)]  # fmt: skip
    differ = {i: sorted(k for k in grid[i] if fresh.get(i, {}).get(k) != grid[i][k])
              for i in ids if i not in same}  # fmt: skip
    # The GPU scores were made from listings.json, so it is what is rendered either way; the
    # database check says whether a fresh render from the database would have been the same.
    listings = {i: grid[i] for i in ids}

    req_dir = args.out / "requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for cfg, (model, variant, cap, threshold) in SETUP.items():
        gpu = {}
        for line in (args.grid / "raw" / f"{cfg}.jsonl").open():
            r = json.loads(line)
            gpu[(r["pair_id"], r["order"])] = r["score"]
        path = req_dir / f"{cfg}.jsonl"
        with path.open("w") as fh:
            for p in sample:
                for order in ("ab", "ba"):
                    a, b = p["listing_a"], p["listing_b"]
                    if order == "ba":
                        a, b = b, a
                    pl = pg.payload(listings, a, b, variant, pg.CAPS[cap])
                    fh.write(json.dumps({"pair_id": p["pair_id"], "order": order, "config": cfg,
                                         "threshold": threshold, "request": pl,
                                         "gpu_score": gpu.get((p["pair_id"], order))},
                                        ensure_ascii=False) + "\n")  # fmt: skip
        files[path.name] = {"requests": 2 * len(sample), "sha256": sha256(path)}
    strata: dict[str, int] = {}
    for p in sample:
        strata[p["stratum"]] = strata.get(p["stratum"], 0) + 1
    manifest = {
        "setup": {cfg: {"model": m, "variant": v, "cap": c, "threshold": t}
                  for cfg, (m, v, c, t) in SETUP.items()},
        "seed": args.seed, "pairs": len(sample), "drawn_from": str(args.key), "of": len(pairs),
        "pair_ids": [p["pair_id"] for p in sample], "strata": strata,
        "listings": len(ids),
        "db_check": {"database": args.db, "matched_listings_json": len(same),
                     "missing_in_db": [i for i in ids if i not in rows], "differ": differ,
                     "rendered_from": "listings.json"},
        "gpu_scores_from": {cfg: str(args.grid / "raw" / f"{cfg}.jsonl") for cfg in SETUP},
        "files": files,
    }  # fmt: skip
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{len(sample)} pairs, {len(ids)} listings: {len(same)} match listings.json, "
          f"{len(differ)} differ {sorted(differ.values())[:3] if differ else ''}")  # fmt: skip
    for name, f in files.items():
        print(f"  {name}: {f['requests']} requests")


# --- 2. run (in the container) -------------------------------------------------------------------
def proc_status(field: str) -> int | None:
    """A /proc/self/status memory field in bytes (VmHWM = peak RSS, VmRSS = current)."""
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1]) * 1024
    return None


def cgroup(name: str) -> str | None:
    p = Path("/sys/fs/cgroup") / name
    return p.read_text().strip() if p.exists() else None


def hub_cache_dirs() -> list[Path]:
    """The Hub cache this process loads from, resolved as huggingface_hub does."""
    env = os.environ
    hub = env.get("HF_HUB_CACHE") or env.get("HUGGINGFACE_HUB_CACHE")
    if not hub:
        home = env.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
        hub = os.path.join(home, "hub")
    return [Path(hub)]


def weight_files(cache_dirs: list[Path]) -> set[str]:
    """Real paths of every weight file in the caches' snapshots. In a standard Hub cache each
    snapshots/<rev>/<name> is a symlink to a suffix-less blobs/<sha> file (or further, into a
    shared store), and /proc/self/maps lists that target, never the snapshot name."""
    out = set()
    for d in cache_dirs:
        for f in Path(d).glob("models--*/snapshots/*/**/*"):
            if f.name.endswith(WEIGHT_SUFFIXES) and f.is_file():
                out.add(os.path.realpath(f))
    return out


def mapped_weights(maps: str | None = None, cache_dirs: list[Path] | None = None) -> list[str]:
    """Weight files memory-mapped by this process: a mapping that is the real path of a snapshot's
    weight file, lies anywhere under a Hub cache directory, or carries a weight suffix.

    The suffix alone (the first version) can never fire on a standard cache, where the mapped
    path is the blob; it only worked on copies with symlinks resolved (rsync -L)."""
    cache_dirs = hub_cache_dirs() if cache_dirs is None else cache_dirs
    real = weight_files(cache_dirs)
    roots = tuple(os.path.realpath(d) + os.sep for d in cache_dirs)
    text = Path("/proc/self/maps").read_text() if maps is None else maps
    out = set()
    for line in text.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 6:
            continue
        path = parts[5].removesuffix(" (deleted)")
        if path in real or path.startswith(roots) or path.endswith(WEIGHT_SUFFIXES):
            out.add(path)
    return sorted(out)


def selfcheck() -> None:
    """Map weight files through Hub-style symlinks and confirm mapped_weights reports them.

    Two layouts: the standard one (snapshot symlink -> suffix-less blob in the same cache) and a
    snapshot whose symlink leads out of the cache (a shared store), which only the real-path
    match catches. Raises AssertionError on a miss; stdlib only, needs a writable temp dir."""
    import mmap
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        hub = Path(tmp) / "hub"
        repo = hub / "models--org--name"
        snap = repo / "snapshots" / ("1" * 40)
        blob = repo / "blobs" / ("0" * 64)
        outside = Path(tmp) / "store" / ("2" * 64)
        for d in (snap, blob.parent, outside.parent):
            d.mkdir(parents=True)
        blob.write_bytes(b"\0" * mmap.PAGESIZE)
        outside.write_bytes(b"\0" * mmap.PAGESIZE)
        std = snap / "model-00001-of-00002.safetensors"
        std.symlink_to(os.path.relpath(blob, snap))
        far = snap / "model-00002-of-00002.safetensors"
        far.symlink_to(outside)
        assert not os.path.realpath(std).endswith(WEIGHT_SUFFIXES)  # what the suffix check missed
        assert mapped_weights(cache_dirs=[hub]) == [], "nothing mapped yet"
        with std.open("rb") as f1, far.open("rb") as f2:
            m1 = mmap.mmap(f1.fileno(), 0, access=mmap.ACCESS_READ)
            m2 = mmap.mmap(f2.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                seen = mapped_weights(cache_dirs=[hub])
            finally:
                m1.close()
                m2.close()
        want = sorted({os.path.realpath(blob), os.path.realpath(outside)})
        assert seen == want, f"mapped_weights missed a symlinked mapping: {seen} != {want}"
        assert mapped_weights(cache_dirs=[hub]) == [], "unmapped files still reported"


def no_mmap() -> None:
    """Every safetensors file is read with pread(2), tensor by tensor, never memory-mapped.

    transformers' own disable_mmap reads every shard whole into memory before converting, which
    for pplx in fp32 (9 GB of bf16 bytes plus 18 GB of fp32 weights) does not fit in 20 GB; the
    pread backend (safetensors 0.8, what transformers itself uses on Windows and MPS) reads each
    tensor when it is materialised, so the peak stays near the loaded model. Patched before
    transformers is imported, so its `from safetensors import safe_open` binds this, and in any
    module already holding the original."""
    import safetensors
    import safetensors.torch

    orig = safetensors.safe_open

    def safe_open(filename, framework, device="cpu", backend=None):  # noqa: ARG001
        return orig(filename, framework=framework, device=device, backend="pread")

    for mod in list(sys.modules.values()):
        if getattr(mod, "safe_open", None) is orig:
            mod.safe_open = safe_open


def load_kev():
    # compose's kev-4b-cpu settings; module-level in kev.serve, so set before importing it
    os.environ.setdefault("KEV_DTYPE", "fp32")
    os.environ.setdefault("KEV_PREFIX_CACHE", "0")
    os.environ.setdefault("KEV_TEMPERATURE", "1.0")
    from dataclasses import replace

    from kev import serve
    from kev.api import SystemOneRequest
    from kev.checkpoint import Checkpoint, LoadOptions
    from kev.device import default_device

    dev = default_device()
    opts = LoadOptions.from_env()
    if opts.backend is None:
        opts = replace(opts, backend="auto")
    ck = Checkpoint(KEV_RUN)
    tok, model = ck.load(dev, opts)
    srv = serve.Server(ck, tok, model, dev)

    def score(pl: dict) -> tuple[float, dict]:
        body = srv.answer(SystemOneRequest(model=KEV_MODEL_NAME, **pl))
        return body["answers"]["same"]["noul"], {"usage": body.get("usage")}

    info = {"device": str(dev), "dtype": str(model.dtype), "backend": model.backend,
            "prefix_cache": serve.PREFIX_CACHE_SIZE, "temperature": model.head.temperature}  # fmt: skip
    return score, info, srv.close


def load_pplx():
    sys.path.insert(0, "/opt/pplx")
    import serve  # the shim's build(): the card's Decider, its CPU path
    import torch
    from pplx_decider.protocol import answer

    a = argparse.Namespace(model=PPLX_REPO, revision=PPLX_REVISION, device="cpu",
                           dtype=os.environ.get("DTYPE", "auto"),
                           batch_tokens=int(os.environ.get("BATCH_TOKENS", 8192)))  # fmt: skip
    decider = serve.build(a)
    scale = decider.temperature

    def score(pl: dict) -> tuple[float, dict]:
        lg = decider.logits([pl])[0]
        q = pl["questions"]["same"]
        p = answer(q, (torch.tensor(lg["same"]) / scale).softmax(-1).tolist())["noul"]
        f, t = lg["same"]  # option order: false, true
        return p, {"margin": t - f}

    info = {"device": "cpu", "dtype": str(next(decider.backbone.parameters()).dtype),
            "temperature": scale, "batch_tokens": a.batch_tokens}  # fmt: skip
    return score, info, lambda: None


def cmd_run(args) -> None:
    t_start = time.perf_counter()
    selfcheck()  # a check that cannot fire would report "no weights mapped" whatever happened
    reqs = [json.loads(line) for line in args.requests.open()]
    if args.limit:
        reqs = reqs[: args.limit]
    env_keys = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "ATEN_CPU_CAPABILITY", "ONEDNN_MAX_CPU_ISA",
                "MKL_ENABLE_INSTRUCTIONS", "HF_HUB_OFFLINE", "KEV_DTYPE", "DTYPE", "BATCH_TOKENS")  # fmt: skip
    res: dict = {"model": args.model, "requests_file": args.requests.name,
                 "requests_sha256": sha256(args.requests), "n": len(reqs),
                 "no_mmap": not args.mmap, "mapped_check": "selfcheck passed",
                 "hub_cache": [str(d) for d in hub_cache_dirs()], "env": {k: os.environ.get(k) for k in env_keys},
                 "affinity_cpus": len(os.sched_getaffinity(0)), "cpu_count": os.cpu_count(),
                 "cgroup_cpu_max": cgroup("cpu.max"), "cgroup_memory_max": cgroup("memory.max"),
                 "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}  # fmt: skip
    import torch

    torch.set_num_threads(args.threads)
    if not args.mmap:
        no_mmap()
    res["torch"] = {"version": torch.__version__, "threads": torch.get_num_threads(),
                    "cpu_capability": torch.backends.cpu.get_cpu_capability(),
                    "cuda": torch.cuda.is_available()}  # fmt: skip
    t0 = time.perf_counter()
    score, info, close = (load_kev if args.model == "kev" else load_pplx)()
    torch.set_num_threads(args.threads)  # the loaders set their own count; keep the one asked for
    res["load_seconds"] = round(time.perf_counter() - t0, 2)
    res["import_seconds"] = round(t0 - t_start, 2)
    res["model_info"] = info
    res["peak_rss_after_load_bytes"] = proc_status("VmHWM")
    res["rss_after_load_bytes"] = proc_status("VmRSS")
    res["mapped_weight_files_after_load"] = mapped_weights()
    print(f"loaded in {res['load_seconds']} s, peak RSS {res['peak_rss_after_load_bytes'] / 2**30:.2f}"
          f" GiB, mapped weight files: {len(res['mapped_weight_files_after_load'])}", flush=True)  # fmt: skip
    out = []
    res["results"] = out
    for i, r in enumerate(reqs):
        t = time.perf_counter()
        try:
            s, extra = score(r["request"])
        except Exception as e:  # noqa: BLE001 - recorded; parity counts them
            s, extra = None, {"error": f"{type(e).__name__}: {str(e)[:300]}"}
        out.append({"pair_id": r["pair_id"], "order": r["order"], "score": s,
                    "seconds": round(time.perf_counter() - t, 3), "gpu_score": r.get("gpu_score"),
                    **extra})  # fmt: skip
        print(f"[{i + 1}/{len(reqs)}] {r['pair_id']} {r['order']} {s} {out[-1]['seconds']} s",
              flush=True)  # fmt: skip
        if args.out:
            write(args.out, res)
    close()
    secs = sorted(x["seconds"] for x in out if x["score"] is not None)
    res["summary"] = {
        "scored": len(secs), "failed": len(out) - len(secs),
        "seconds_total": round(sum(secs), 1),
        "seconds_mean": round(sum(secs) / len(secs), 3) if secs else None,
        "seconds_median": secs[len(secs) // 2] if secs else None,
        "seconds_mean_after_first": round(sum(x["seconds"] for x in out[1:] if x["score"]
                                              is not None) / max(1, len(secs) - 1), 3),
        "req_per_s": round(len(secs) / sum(secs), 4) if secs else None,
        "peak_rss_bytes": proc_status("VmHWM"),
        "peak_rss_gib": round(proc_status("VmHWM") / 2**30, 2),
        "max_rss_getrusage_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "cgroup_memory_peak": cgroup("memory.peak"),
        "wall_seconds": round(time.perf_counter() - t_start, 1),
    }  # fmt: skip
    res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if args.out:
        write(args.out, res)
    print(json.dumps(res["summary"]), flush=True)


def write(path: Path, res: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(res, indent=1))
    tmp.replace(path)


# --- 3. parity (desktop, or anywhere with Python) ------------------------------------------------
def cmd_parity(args) -> None:
    res = json.loads(args.result.read_text())
    reqs = {(r["pair_id"], r["order"]): r for r in map(json.loads, args.requests.open())}
    t = args.threshold if args.threshold is not None else next(iter(reqs.values()))["threshold"]
    # a GPU score can be missing (a failed GPU request, or a request not in this file): such a
    # request is counted, never compared
    rows = [(x, reqs.get((x["pair_id"], x["order"]), {}).get("gpu_score")) for x in res["results"]]
    no_gpu = [(x["pair_id"], x["order"]) for x, g in rows if g is None]
    ok = [(x["score"], g) for x, g in rows if x["score"] is not None and g is not None]
    d = [abs(c - g) for c, g in ok]
    by_pair: dict[str, dict] = {}
    for x, g in rows:
        by_pair.setdefault(x["pair_id"], {})[x["order"]] = (x["score"], g)
    pairs = {k: v for k, v in by_pair.items()
             if len(v) == 2 and all(c is not None and g is not None for c, g in v.values())}  # fmt: skip
    pmin = {k: (min(c for c, _ in v.values()), min(g for _, g in v.values()))
            for k, v in pairs.items()}  # fmt: skip
    flips_req = [(x["pair_id"], x["order"], round(g, 4), round(x["score"], 4)) for x, g in rows
                 if x["score"] is not None and g is not None
                 and (x["score"] >= t) != (g >= t)]  # fmt: skip
    flips_pair = [
        (k, round(g, 4), round(c, 4)) for k, (c, g) in pmin.items() if (c >= t) != (g >= t)
    ]
    out = {"result": args.result.name, "threshold": t, "requests": len(rows),
           "scored": sum(x["score"] is not None for x, _ in rows), "compared": len(ok),
           "missing_gpu_score": no_gpu,
           "max_abs_diff": round(max(d), 4) if d else None,
           "mean_abs_diff": round(sum(d) / len(d), 4) if d else None,
           "agree_requests": f"{len(ok) - len(flips_req)}/{len(ok)}",
           "agree_pairs_min": f"{len(pmin) - len(flips_pair)}/{len(pmin)}",
           "flips_requests": flips_req, "flips_pairs_min": flips_pair,
           # every request must have been compared: a failed CPU score or a missing GPU score
           # is a request the verdict cannot vouch for
           "not_compared": len(rows) - len(ok),
           "within_tolerance": bool(d) and max(d) <= args.tolerance and not flips_pair
           and len(ok) == len(rows),
           "within_tolerance_why_not": [
               why for why, bad in (
                   ("nothing compared", not d),
                   (f"max |CPU - GPU| over {args.tolerance}", bool(d) and max(d) > args.tolerance),
                   ("a pair flips at the threshold", bool(flips_pair)),
                   (f"{len(rows) - len(ok)} request(s) not compared (failed CPU score or "
                    "missing GPU score)", len(ok) < len(rows)),
               ) if bad],
           "tolerance": args.tolerance,
           "seconds_mean": res.get("summary", {}).get("seconds_mean"),
           "load_seconds": res.get("load_seconds"),
           "peak_rss_gib": res.get("summary", {}).get("peak_rss_gib"),
           "mapped_weight_files_after_load": res.get("mapped_weight_files_after_load")}  # fmt: skip
    print(json.dumps(out, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--key", type=Path, required=True)
    r.add_argument(
        "--grid", type=Path, required=True, help="prompt_grid --out (listings.json, raw/)"
    )
    r.add_argument("--out", type=Path, required=True)
    r.add_argument(
        "--n",
        type=int,
        default=N_PAIRS,
        help="pairs to draw (default 60: a session choice awaiting owner review)",
    )
    r.add_argument("--seed", type=int, default=SEED)
    r.add_argument("--container", default="makhzan-db-1")
    r.add_argument("--db-user", default="makhzan")
    r.add_argument("--db", default="makhzan_prod")
    u = sub.add_parser("run")
    u.add_argument("--model", choices=("kev", "pplx"), required=True)
    u.add_argument("--requests", type=Path, required=True)
    u.add_argument("--out", type=Path)
    u.add_argument("--limit", type=int)
    u.add_argument("--threads", type=int, default=int(os.environ.get("OMP_NUM_THREADS") or 6))
    u.add_argument("--mmap", action="store_true", help="let transformers memory-map the weights")
    p = sub.add_parser("parity")
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--requests", type=Path, required=True)
    p.add_argument("--threshold", type=float, help="default: the setup's, from the requests file")
    p.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="max |CPU - GPU| per request (default 0.05: a session choice awaiting "
        "owner review; a measurement parameter, not a merge rule)",
    )
    sub.add_parser("selfcheck", help="prove the mapped-weights check sees a symlinked blob")
    args = ap.parse_args()
    if args.cmd == "selfcheck":
        selfcheck()
        print("selfcheck: mapped_weights sees files mapped through Hub symlinks")
        return
    {"render": cmd_render, "run": cmd_run, "parity": cmd_parity}[args.cmd](args)


if __name__ == "__main__":
    main()
