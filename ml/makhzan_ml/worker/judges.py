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

- **Kev on llama.cpp** (`backend = "llamacpp"`, `pins.ALTERNATIVES`): a llama.cpp server
  beside the worker (a compose sidecar) does the compute; the worker posts the same payload
  to its `POST /v1/systemone`, one request per call, and undoes the GGUF's built-in
  decision temperature, so the score is raw P(yes) like every validated Kev score. Before
  anything is scored it checks the GGUF it was given (mounted read-only into the worker
  too) by sha256 and by its own metadata (decision type, temperature), and the sidecar's
  `/props` (that file's name, the pinned llama.cpp build). No torch on this path.

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
import hashlib
import json
import os
import struct
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from makhzan_ml.worker.pins import Pin, pin_for

log = logging.getLogger("makhzan_ml.worker.judges")

WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".gguf")
#: What Kev's server is asked for (makhzan_ml.client's "kev-4b" service).
KEV_MODEL_NAME = "kev-latest"
#: Where the pplx images keep the shim (pplx/Dockerfile*: COPY serve.py /opt/pplx/serve.py).
PPLX_SHIM_DIR = os.environ.get("MAKHZAN_PPLX_SHIM", "/opt/pplx")
PPLX_BATCH_TOKENS = 8192


class LoadError(RuntimeError):
    """The model could not be loaded as pinned; nothing may be scored."""


class LoadInterrupted(LoadError):
    """A stop came during an interruptible load (the llama.cpp backend's hash and wait)."""


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


def default_threads() -> int:
    """The CPU threads this process may really use: the container's CPU quota (cgroup v2
    `cpu.max`, so `--cpus=6` gives 6), else the CPUs it may run on. Never the host's core
    count, which torch would otherwise take and oversubscribe a capped container with."""
    cpus = len(os.sched_getaffinity(0))
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            cpus = min(cpus, max(1, math.ceil(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return cpus


def importable(key: str) -> bool:
    """Whether this image can load `key` at all. Each model image holds one model's code:
    the Kev images have `kev`, the pplx images the card's `pplx_decider` and the shim."""
    import importlib.util

    if key == "kev":
        return importlib.util.find_spec("kev") is not None
    if key == "pplx":
        shim = Path(PPLX_SHIM_DIR) / "serve.py"
        return importlib.util.find_spec("pplx_decider") is not None and shim.is_file()
    return False


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
    backend: str = "torch"
    llamacpp_url: str | None = None
    gguf_path: Path | None = None
    #: The worker's stop event (a threading.Event): the llama.cpp load checks it while it
    #: hashes the GGUF and waits for the sidecar, so a stop never waits on either.
    stop: object = None


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
    # The Kev code commit the image records: the Kev base images set MAKHZAN_KEV_COMMIT
    # beside the source they built from (ml/kev/Dockerfile*), whose tarball checksum pins it.
    # A mismatch is refused here; a base image built before it recorded one only logs it.
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


# --- llama.cpp sidecar ------------------------------------------------------------------------

#: How long a load waits for the sidecar to answer /health ok (it loads the GGUF when it
#: starts, normally long before a window opens; a 3 GB file from an HDD takes tens of
#: seconds). Interruptible by a stop, as is the hash before it.
LLAMACPP_READY_S = 120.0
#: One scoring request's timeout, per model and device. A request is the one part of a session
#: a stop cannot interrupt, so each stays inside its worker's stop bound (docs/ai/worker.md, "A
#: stop sets one deadline"; the compose stop_grace_period of the worker that runs it).
#: - Kev: about 0.5 s on the 3060, 4.4-6.1 s on the home server's AMD card; on the i7-3770's CPU
#:   about 95 s for its longest request (1,625 tokens at ~17 tokens/s).
#: - pplx (non-causal, its K1 prompt with the full description, so longer): the longest Phase E
#:   request, 3,574 tokens, took 48.9 s on the desktop's CPU (4 threads, 73 tokens/s); scaled by
#:   Kev Q4's measured i7-3770/desktop ratio (17.1 / 67.5 tokens/s), about 193 s on the home
#:   server. Not measured there yet. Its timeout, 225 s, covers that with margin and keeps the
#:   whole stop (request, 3 x 10 s of last posts, 10 s join: 265 s) under the supervisor's
#:   window-end kill (supervisor.KILL_AFTER_S, 270 s) and the pplx worker's 300 s
#:   stop_grace_period.
LLAMACPP_REQUEST_S = {
    ("kev", "gpu"): 60.0,
    ("kev", "cpu"): 120.0,
    ("pplx", "gpu"): 60.0,
    ("pplx", "cpu"): 225.0,
}

_GGUF_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?",
                 10: "<Q", 11: "<q", 12: "<d"}  # fmt: skip
_GGUF_STRING, _GGUF_ARRAY = 8, 9


def gguf_metadata(path: Path, keys: set[str]) -> dict:
    """The values of `keys` in a GGUF file's key-value header (format v2/v3), read with the
    standard library. Arrays (the tokenizer's) are skipped, never loaded."""

    def read(f, fmt):
        size = struct.calcsize(fmt)
        data = f.read(size)
        if len(data) != size:
            raise LoadError(f"{path}: the GGUF header ends early")
        return struct.unpack(fmt, data)[0]

    def string(f) -> bytes:
        n = read(f, "<Q")
        data = f.read(n)
        if len(data) != n:
            raise LoadError(f"{path}: the GGUF header ends early")
        return data

    def skip(f, kind):
        if kind in _GGUF_SCALARS:
            f.seek(struct.calcsize(_GGUF_SCALARS[kind]), 1)
        elif kind == _GGUF_STRING:
            f.seek(read(f, "<Q"), 1)
        elif kind == _GGUF_ARRAY:
            inner, n = read(f, "<I"), read(f, "<Q")
            if inner in _GGUF_SCALARS:
                f.seek(struct.calcsize(_GGUF_SCALARS[inner]) * n, 1)
            else:
                for _ in range(n):
                    skip(f, inner)
        else:
            raise LoadError(f"{path}: unknown GGUF value type {kind}")

    found: dict = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise LoadError(f"{path} is not a GGUF file")
        version = read(f, "<I")
        if version not in (2, 3):
            raise LoadError(f"{path}: GGUF version {version} is not read here")
        read(f, "<Q")  # tensor count
        for _ in range(read(f, "<Q")):
            name = string(f).decode("utf-8", "replace")
            kind = read(f, "<I")
            if name in keys and kind in _GGUF_SCALARS:
                found[name] = read(f, _GGUF_SCALARS[kind])
            elif name in keys and kind == _GGUF_STRING:
                found[name] = string(f).decode("utf-8")
            else:
                skip(f, kind)
            if len(found) == len(keys):
                break
    return found


def _stopped(stop) -> bool:
    return stop is not None and stop.is_set()


def sha256_file(path: Path, chunk: int = 1 << 20, stop=None) -> str:
    """The file's sha256; a set `stop` event ends it between chunks (LoadInterrupted)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            if _stopped(stop):
                raise LoadInterrupted(f"stopped while hashing {path.name}")
            h.update(block)
    return h.hexdigest()


def uncalibrate(p: float, temperature: float) -> float:
    """llama.cpp's calibrated P(yes) = sigmoid(logit / T) back to the raw sigmoid(logit).

    `p` must be a real probability: a bool, a string, NaN, an infinity or anything outside
    [0, 1] is a ValueError, never clamped into a score. Only exactly 0 and 1 are nudged
    inward, so their logit is finite."""
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        raise ValueError(f"not a probability: {p!r}")
    p = float(p)
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise ValueError(f"not a probability: {p!r}")
    if p == 0.0:
        p = 1e-12
    elif p == 1.0:
        p = 1.0 - 1e-12
    z = temperature * math.log(p / (1.0 - p))
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


def _http_json(url: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - checked URL
        return json.loads(r.read())


def _wait_ready(base: str, budget_s: float, stop=None, clock=time.monotonic) -> None:
    deadline = clock() + budget_s
    last = "no answer"
    while True:
        if _stopped(stop):
            raise LoadInterrupted("stopped while waiting for the llama.cpp sidecar")
        try:
            if _http_json(f"{base}/health", timeout=10).get("status") == "ok":
                return
            last = "not ok"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"  # 503 while the model is loading
        except (OSError, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
        if clock() >= deadline:
            raise LoadError(f"the llama.cpp sidecar at {base} is not ready ({last})")
        if stop is not None:
            stop.wait(2.0)
        else:
            time.sleep(2.0)


def nfc(value):
    """Every string in a payload in Unicode NFC, as Kev's own tokenizer normalises it.

    The Qwen tokenizer Kev's server uses applies NFC before tokenising; llama.cpp's does not,
    although the GGUF records it (`tokenizer.ggml.normalizer`). Without this, text such as the
    ohm sign U+2126 tokenises differently from the validated scores (10 of the 1,800 Phase E
    requests did, for pplx's identical tokenizer). Only what is sent changes: the broker's
    request hashes are computed on the payload as rendered."""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {k: nfc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [nfc(v) for v in value]
    return value


def rescale(p: float, served: float, wanted: float) -> float:
    """A probability llama.cpp served at temperature `served` (its softmax(logit / served)) on
    the scale of temperature `wanted`: sigmoid(logit · served / wanted).

    Validated as `uncalibrate` does (a bool, a string, NaN, an infinity or anything outside
    [0, 1] is a ValueError). When the two temperatures agree to 1e-3, as pplx's do (the GGUF
    carries 1.3302961587905884, the scores and the pin 1.3303), `p` is returned unchanged."""
    if abs(served - wanted) < 1e-3:
        uncalibrate(p, 1.0)  # validation only
        return float(p)
    return uncalibrate(p, served / wanted)


#: Per model: the GGUF's `qwen35.decision.type`, and the `model` name sent with a request.
LLAMACPP_MODELS = {"kev": ("kev", "kev"), "pplx": ("pplx-decider", "pplx")}


def _load_llamacpp(key: str, rt: Runtime, pin: Pin) -> Judge:
    who = f"{key} (llamacpp)"
    decision_type, request_model = LLAMACPP_MODELS[key]
    if not rt.llamacpp_url or rt.gguf_path is None:
        raise LoadError(f"{who}: llamacpp_url and gguf_path are required")
    path = Path(rt.gguf_path)
    if not path.is_file():
        raise LoadError(f"{who}: gguf_path {path} is not a file")
    if path.name != pin.gguf_file:
        raise LoadError(f"{who}: {path.name!r} is not the pinned {pin.gguf_file!r}")
    meta = gguf_metadata(path, {"qwen35.decision.type", "qwen35.decision.temperature.noul"})
    if meta.get("qwen35.decision.type") != decision_type:
        raise LoadError(f"{who}: {path.name} is not a {decision_type} decision model: {meta}")
    temperature = meta.get("qwen35.decision.temperature.noul")
    if temperature is None or abs(float(temperature) - pin.gguf_temperature) > 1e-6:
        raise LoadError(
            f"{who}: the GGUF's temperature is {temperature}, pinned {pin.gguf_temperature}"
        )
    digest = sha256_file(path, stop=rt.stop)
    if digest != pin.gguf_sha256:
        raise LoadError(f"{who}: {path.name} sha256 {digest}, pinned {pin.gguf_sha256}")
    base = rt.llamacpp_url.rstrip("/")
    _wait_ready(base, LLAMACPP_READY_S, rt.stop)
    request_timeout = LLAMACPP_REQUEST_S[(key, rt.device)]
    props = _http_json(f"{base}/props")
    served = Path(str(props.get("model_path") or "")).name
    if served != pin.gguf_file:
        raise LoadError(f"{who}: the sidecar serves {served!r}, pinned {pin.gguf_file!r}")
    build = str(props.get("build_info") or "")
    want_build = pin.model_version.split("+llama.cpp-", 1)[1].split("-", 1)[0]
    if not build.startswith(want_build + "-"):
        raise LoadError(f"{who}: the sidecar is llama.cpp {build!r}, pinned {want_build}")

    def score(payload: dict) -> tuple[float, dict]:
        q = question_key(payload)
        try:
            body = _http_json(f"{base}/v1/systemone", {"model": request_model, **nfc(payload)},
                              timeout=request_timeout)  # fmt: skip
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            raise RuntimeError(f"llama.cpp answered HTTP {e.code}: {detail}") from None
        try:
            calibrated = body["answers"][q]["noul"]
        except (KeyError, TypeError):
            raise RuntimeError(
                f"llama.cpp's answer has no answers.{q}.noul: {str(body)[:300]}"
            ) from None
        try:
            return rescale(calibrated, pin.gguf_temperature, pin.temperature), {}
        except ValueError as e:
            raise RuntimeError(f"llama.cpp answered {q}.noul = {calibrated!r}: {e}") from None

    info = {
        "backend": "llamacpp",
        "device": rt.device,
        "dtype": rt.dtype,
        "gguf": pin.gguf_file,
        "gguf_sha256": digest,
        "gguf_temperature": float(temperature),
        "temperature": pin.temperature,
        "llamacpp_build": build,
        "slots": props.get("total_slots"),
        "request_timeout_s": request_timeout,
        "image": pin.code,
    }
    return Judge(key, score, info)


def _load_kev_llamacpp(rt: Runtime, pin: Pin) -> Judge:
    return _load_llamacpp("kev", rt, pin)


def _load_pplx_llamacpp(rt: Runtime, pin: Pin) -> Judge:
    return _load_llamacpp("pplx", rt, pin)


def load(key: str, rt: Runtime) -> Judge:
    """Load `key`'s model once, as pinned, and check it before anything is scored."""
    pin = pin_for(key, rt.backend)
    if rt.backend == "llamacpp":
        # The sidecar does the compute: no torch, no weights in this process.
        t0 = time.monotonic()
        judge = _load_llamacpp(key, rt, pin)
        judge.info["load_seconds"] = round(time.monotonic() - t0, 1)
        judge.info["peak_rss_bytes"] = proc_status("VmHWM")
        return judge
    prepare_environment(rt)
    if not rt.mmap:
        selfcheck()
        no_mmap()
    import torch

    if rt.threads:
        torch.set_num_threads(rt.threads)
        try:
            # Inter-op parallelism too, or torch sizes that pool to the host's cores. It can
            # be set once per process, before any parallel work: a second load keeps it.
            torch.set_num_interop_threads(rt.threads)
        except RuntimeError:
            pass
    t0 = time.monotonic()
    judge = _LOADERS[key](rt, pin)
    if rt.threads:
        torch.set_num_threads(rt.threads)  # the loaders set their own; keep the one configured
    judge.info["load_seconds"] = round(time.monotonic() - t0, 1)
    judge.info["peak_rss_bytes"] = proc_status("VmHWM")
    judge.info["threads"] = torch.get_num_threads()
    judge.info["interop_threads"] = torch.get_num_interop_threads()
    if not rt.mmap:
        mapped = mapped_weights()
        judge.info["mapped_weight_files"] = mapped
        if mapped:
            judge.close()
            raise LoadError(f"{key}: weight files are memory-mapped after loading: {mapped}")
    return judge


def unload(judge: Judge, device: str) -> None:
    """Free a judge at the end of a session, so its memory goes back before the process
    exits (and before another worker's window on the same machine)."""
    judge.close()
    judge.score_fn = judge.close_fn = lambda *a: None  # drop the model's references
    gc.collect()
    if device == "gpu" and judge.info.get("backend") != "llamacpp":
        import torch

        torch.cuda.empty_cache()
    release_freed_memory()


def release_freed_memory() -> None:
    """Ask glibc to hand freed heap pages back to the system (`malloc_trim(0)`), as the
    ingestion worker does. Best effort: a worker that waits between windows does not rely
    on it, since each window's session runs in a child process that exits (supervisor.py)."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass
