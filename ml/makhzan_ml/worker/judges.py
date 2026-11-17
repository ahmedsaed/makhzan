"""Load a judge once and score one request per forward call, exactly as validated.

The scoring paths are the ones every validated score went through
(`ml/models/bench_cpu.py` on the ml-improve branch, and the compose services before it):

- **Kev**: kev-1.0's own `kev.serve.Server.answer`, which is what `POST /v1/systemone`
  calls, with `KEV_PREFIX_CACHE=0`, `KEV_TEMPERATURE=1.0` (raw P(yes)) and
  `KEV_CUDA_GRAPHS=0`. On CPU `KEV_DTYPE=fp32`; on the GPU bf16 with the fused Qwen3.5
  kernels when flash-linear-attention is installed: `kev.serve.main()`'s own serving
  defaults, as the compose `kev-4b` service ran them. The score is
  `answers[<question>]["noul"]`.
- **pplx**: the shim's `serve.build()` (the model card's `Decider`, its CPU or CUDA path,
  `BATCH_TOKENS=8192`), then `Decider.logits` for one request, divided by the
  checkpoint's temperature, through `protocol.answer`: the computation `POST /v1/decide`
  does. The score is P(true); the raw logit margin goes in `extra`.

**One request per call** (owner decision 2026-11-17; pplx is bit-stable only that way):
`score` takes one payload, and nothing here batches or reorders. Kev's model thread
batches whatever is queued at once; the worker calls it from one thread, one request at
a time, so every batch is that one request.

**No mmap on CPU** (`no_mmap`): every safetensors file is read with pread(2), tensor by
tensor, and after loading the process's mappings are checked (`mapped_weights`, which
`selfcheck` first proves can see a file mapped through a Hub-cache symlink). A weight
file still mapped is a load error.

Top level is standard library only: torch and the model code are imported by `load`,
inside the model image.
"""

from __future__ import annotations

import argparse
import atexit
import gc
import logging
import math
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from makhzan_ml.worker.pins import PINS, Pin

log = logging.getLogger("makhzan_ml.worker.judges")

WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".gguf")
#: What Kev's server is asked for (makhzan_ml.client's "kev-4b" service).
KEV_MODEL_NAME = "kev-latest"
#: Where the pplx images keep the shim (pplx/Dockerfile*: COPY serve.py /opt/pplx/serve.py).
PPLX_SHIM_DIR = os.environ.get("MAKHZAN_PPLX_SHIM", "/opt/pplx")
PPLX_BATCH_TOKENS = 8192


class LoadError(RuntimeError):
    """The model could not be loaded as pinned; nothing may be scored."""


@dataclass
class Judge:
    """A loaded model: `score(payload) -> (p, extra)`, one request per call."""

    key: str
    score_fn: Callable[[dict], tuple[float, dict]]
    info: dict = field(default_factory=dict)
    close_fn: Callable[[], None] = lambda: None

    def score(self, payload: dict) -> tuple[float, dict]:
        p, extra = self.score_fn(payload)
        p = float(p)
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError(f"{self.key} returned a score outside [0, 1]: {p!r}")
        return p, extra

    def close(self) -> None:
        self.close_fn()


def question_key(payload: dict) -> str:
    """The payload's one question (the approved prompt asks exactly one, "same")."""
    questions = payload.get("questions")
    if not isinstance(questions, dict) or len(questions) != 1:
        raise ValueError("a request must carry exactly one question")
    return next(iter(questions))


# --- memory and mappings ------------------------------------------------------------------


def proc_status(name: str) -> int | None:
    """A /proc/self/status memory field in bytes (VmRSS now, VmHWM the peak)."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(name + ":"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def cgroup_memory_max() -> int | None:
    """The container's memory limit in bytes (cgroup v2), None when unlimited or unknown."""
    try:
        text = Path("/sys/fs/cgroup/memory.max").read_text().strip()
    except OSError:
        return None
    return None if text == "max" else int(text)


def hub_cache_dirs() -> list[Path]:
    """The Hub cache this process loads from, resolved as huggingface_hub does."""
    env = os.environ
    hub = env.get("HF_HUB_CACHE") or env.get("HUGGINGFACE_HUB_CACHE")
    if not hub:
        home = env.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
        hub = os.path.join(home, "hub")
    return [Path(hub)]


def _weight_files(cache_dirs: list[Path]) -> set[str]:
    out = set()
    for d in cache_dirs:
        for f in Path(d).glob("models--*/snapshots/*/**/*"):
            if f.name.endswith(WEIGHT_SUFFIXES) and f.is_file():
                out.add(os.path.realpath(f))
    return out


def mapped_weights(maps: str | None = None, cache_dirs: list[Path] | None = None) -> list[str]:
    """Weight files this process has memory-mapped: the real path of a snapshot's weight
    file (a Hub snapshot entry is a symlink to a suffix-less blob, and /proc/self/maps
    shows the blob), anything under a Hub cache, or anything with a weight suffix."""
    cache_dirs = hub_cache_dirs() if cache_dirs is None else cache_dirs
    real = _weight_files(cache_dirs)
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
    """Prove `mapped_weights` sees a weight file mapped through Hub-style symlinks, both
    inside the cache and out of it (a shared store). A check that cannot fire would
    report "nothing mapped" whatever happened."""
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
        if mapped_weights(cache_dirs=[hub]):
            raise LoadError("mapped-weights self-check: reports a mapping before any exists")
        with std.open("rb") as f1, far.open("rb") as f2:
            m1 = mmap.mmap(f1.fileno(), 0, access=mmap.ACCESS_READ)
            m2 = mmap.mmap(f2.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                seen = mapped_weights(cache_dirs=[hub])
            finally:
                m1.close()
                m2.close()
        want = sorted({os.path.realpath(blob), os.path.realpath(outside)})
        if seen != want:
            raise LoadError(f"mapped-weights self-check missed a symlinked mapping: {seen}")


def no_mmap() -> None:
    """Read every safetensors file with pread(2), never memory-mapped. Patched before
    transformers is imported, and in any module already holding the original.

    transformers' own disable_mmap reads each shard whole before converting, which for
    pplx in fp32 does not fit in 20 GB; the pread backend (safetensors 0.8) reads each
    tensor when it is materialised, so the peak stays near the loaded model."""
    import safetensors
    import safetensors.torch  # noqa: F401  (binds the original in that module too)

    orig = safetensors.safe_open
    if getattr(orig, "_makhzan_pread", False):
        return

    def safe_open(filename, framework, device="cpu", backend=None):  # noqa: ARG001
        return orig(filename, framework=framework, device=device, backend="pread")

    safe_open._makhzan_pread = True
    for mod in list(sys.modules.values()):
        if getattr(mod, "safe_open", None) is orig:
            mod.safe_open = safe_open


# --- loading ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Runtime:
    """What `load` needs from the configuration."""

    device: str  # cpu | gpu
    dtype: str  # fp32 | bf16
    threads: int | None
    mmap: bool
    weights_cache: Path | None


def prepare_environment(rt: Runtime) -> None:
    """Environment the model code reads at import: set before torch is imported."""
    if rt.weights_cache is not None:
        os.environ["HF_HOME"] = str(rt.weights_cache)
        os.environ.pop("HF_HUB_CACHE", None)
        os.environ.pop("HUGGINGFACE_HUB_CACHE", None)
    # Offline always: weights come from the read-only cache, and the only network peer is
    # the broker.
    for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        os.environ[k] = "1"
    if rt.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    if rt.threads:
        for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ[k] = str(rt.threads)


def _check_snapshot(path: str | os.PathLike, pin: Pin) -> None:
    if Path(path).name != pin.weights_revision:
        raise LoadError(
            f"{pin.key}: loaded snapshot {Path(path).name!r}, pinned {pin.weights_revision!r}"
        )


def _check_temperature(got: float, pin: Pin) -> None:
    if round(float(got), 4) != round(pin.temperature, 4):
        raise LoadError(f"{pin.key}: scores at temperature {got}, pinned {pin.temperature}")


def _load_kev(rt: Runtime, pin: Pin) -> Judge:
    # kev.serve reads these at import (module level), so set them first.
    os.environ["KEV_PREFIX_CACHE"] = "0"
    os.environ["KEV_TEMPERATURE"] = repr(pin.temperature)
    os.environ["KEV_CUDA_GRAPHS"] = "0"
    os.environ["KEV_DTYPE"] = rt.dtype
    # The Kev code commit, when the image records it. The base images do not yet (their
    # KEV_COMMIT is a build ARG only), so today this is "unrecorded" and the check is the
    # image's pinned tarball checksum alone; set MAKHZAN_KEV_COMMIT at build time from a
    # base that records it, and a mismatch is refused here.
    code = os.environ.get("MAKHZAN_KEV_COMMIT") or None
    if code is None:
        log.warning("kev: the image does not record its Kev code commit; not checked")
    if code and code != pin.code:
        raise LoadError(f"kev: the image's Kev code is {code}, pinned {pin.code}")
    from dataclasses import replace

    import torch
    from kev import serve
    from kev.api import SystemOneRequest
    from kev.checkpoint import Checkpoint, LoadOptions

    dev = "cuda" if rt.device == "gpu" else "cpu"
    if dev == "cuda" and not torch.cuda.is_available():
        raise LoadError('kev: device = "gpu" but torch sees no CUDA device')
    opts = LoadOptions.from_env()
    if dev == "cuda" and opts.fused is None:
        # kev.serve.main()'s serving default: the fused kernels when fla is installed.
        from kev.checkpoint import fused_available

        opts = replace(opts, fused=fused_available())
    if opts.backend is None:
        opts = replace(opts, backend="auto")
    ck = Checkpoint(f"{pin.repo}@{pin.weights_revision}")
    _check_snapshot(ck.path, pin)
    tok, model = ck.load(dev, opts)
    _check_temperature(model.head.temperature, pin)
    srv = serve.Server(ck, tok, model, dev)
    if serve.PREFIX_CACHE_SIZE != 0:
        raise LoadError("kev: the prefix cache is on; validated scores were read without it")

    def score(payload: dict) -> tuple[float, dict]:
        q = question_key(payload)
        body = srv.answer(SystemOneRequest(model=KEV_MODEL_NAME, **payload))
        return body["answers"][q]["noul"], {}

    info = {
        "device": dev,
        "dtype": str(model.dtype),
        "backend": model.backend,
        "fused": bool(opts.fused),
        "temperature": model.head.temperature,
        "snapshot": Path(ck.path).name,
        "code": code or "unrecorded",
        "torch": torch.__version__,
    }

    def close() -> None:
        # Server.__post_init__ registers srv.close with atexit; that bound method would keep
        # the server, and with it the model, alive after unloading.
        srv.close()
        atexit.unregister(srv.close)
        srv.model = srv.tok = srv.prefix_cache = None

    return Judge("kev", score, info, close)


def _load_pplx(rt: Runtime, pin: Pin) -> Judge:
    if PPLX_SHIM_DIR not in sys.path:
        sys.path.insert(0, PPLX_SHIM_DIR)
    import serve  # the shim's build(): the model card's Decider
    import torch
    from huggingface_hub import snapshot_download
    from pplx_decider.protocol import answer

    dev = "cuda" if rt.device == "gpu" else "cpu"
    if dev == "cuda" and not torch.cuda.is_available():
        raise LoadError('pplx: device = "gpu" but torch sees no CUDA device')
    _check_snapshot(snapshot_download(pin.repo, revision=pin.weights_revision), pin)
    # dtype "auto" is the card's own choice: bf16 on CUDA, fp32 on CPU, the validated pair.
    args = argparse.Namespace(
        model=pin.repo,
        revision=pin.weights_revision,
        device=dev,
        dtype="auto",
        batch_tokens=PPLX_BATCH_TOKENS,
    )
    decider = serve.build(args)
    scale = decider.temperature
    _check_temperature(scale, pin)

    def score(payload: dict) -> tuple[float, dict]:
        q = question_key(payload)
        logits = decider.logits([payload])[0][q]
        p = answer(payload["questions"][q], (torch.tensor(logits) / scale).softmax(-1).tolist())
        false, true = logits  # option order: false, true (pplx_decider.protocol.options)
        return p["noul"], {"margin": true - false}

    info = {
        "device": dev,
        "dtype": str(next(decider.backbone.parameters()).dtype),
        "temperature": scale,
        "batch_tokens": PPLX_BATCH_TOKENS,
        "snapshot": pin.weights_revision,
        "torch": torch.__version__,
    }
    return Judge("pplx", score, info)


_LOADERS = {"kev": _load_kev, "pplx": _load_pplx}


def load(key: str, rt: Runtime) -> Judge:
    """Load `key`'s model once, as pinned, and check it before anything is scored."""
    pin = PINS[key]
    prepare_environment(rt)
    if not rt.mmap:
        selfcheck()
        no_mmap()
    import torch

    if rt.threads:
        torch.set_num_threads(rt.threads)
    t0 = time.monotonic()
    judge = _LOADERS[key](rt, pin)
    if rt.threads:
        torch.set_num_threads(rt.threads)  # the loaders set their own; keep the one configured
    judge.info["load_seconds"] = round(time.monotonic() - t0, 1)
    judge.info["peak_rss_bytes"] = proc_status("VmHWM")
    judge.info["threads"] = torch.get_num_threads()
    if not rt.mmap:
        mapped = mapped_weights()
        judge.info["mapped_weight_files"] = mapped
        if mapped:
            judge.close()
            raise LoadError(f"{key}: weight files are memory-mapped after loading: {mapped}")
    return judge


def unload(judge: Judge, device: str) -> None:
    """Free a judge before loading another: two 4B models do not fit side by side in 20 GB
    (or on a 12 GB card)."""
    judge.close()
    judge.score_fn = judge.close_fn = lambda *a: None  # drop the model's references
    gc.collect()
    if device == "gpu":
        import torch

        torch.cuda.empty_cache()
