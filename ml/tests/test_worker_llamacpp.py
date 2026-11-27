"""Kev and pplx on a llama.cpp sidecar (`backend = "llamacpp"`): the GGUF checks, the
uncalibration (Kev) or the score as served (pplx), the sidecar protocol, the configuration, and
a whole session through the fake broker.

No model and no llama.cpp here: a small GGUF written by `write_gguf`, and a stdlib HTTP
server standing in for llama-server's /health, /props and /v1/systemone."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import struct
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from makhzan_ml.worker import judges, pins, run
from makhzan_ml.worker.config import ConfigError, parse
from makhzan_ml.worker.fake_broker import FakeBroker
from makhzan_schemas.ai import policy

T = pins.KEV_GGUF_TEMPERATURE
DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "home-server"


# --- a GGUF and a sidecar -----------------------------------------------------------------


def _s(text: str) -> bytes:
    data = text.encode()
    return struct.pack("<Q", len(data)) + data


def write_gguf(path: Path, kv: dict, *, version: int = 3) -> Path:
    """A GGUF header with `kv` (str, float, int values) plus a string array and a float
    array before them, which the reader must skip."""
    entries = [
        _s("tokenizer.ggml.tokens") + struct.pack("<IIQ", 9, 8, 3) + _s("a") + _s("bc") + _s(""),
        _s("tokenizer.ggml.scores") + struct.pack("<IIQ", 9, 6, 2) + struct.pack("<ff", 1, 2),
        _s("general.size") + struct.pack("<IQ", 10, 4),
    ]
    for k, v in kv.items():
        if isinstance(v, str):
            entries.append(_s(k) + struct.pack("<I", 8) + _s(v))
        elif isinstance(v, float):
            entries.append(_s(k) + struct.pack("<If", 6, v))
        else:
            entries.append(_s(k) + struct.pack("<Ii", 5, v))
    path.write_bytes(
        b"GGUF" + struct.pack("<IQQ", version, 0, len(entries)) + b"".join(entries) + b"\0" * 64
    )
    return path


def kev_gguf(tmp_path: Path, **override) -> Path:
    kv = {"qwen35.decision.type": "kev", "qwen35.decision.temperature.noul": T, **override}
    return write_gguf(tmp_path / pins.KEV_GGUF_FILE, kv)


def pplx_gguf(tmp_path: Path, **override) -> Path:
    kv = {"qwen35.decision.type": "pplx-decider",
          "qwen35.decision.temperature.noul": pins.PPLX_GGUF_TEMPERATURE, **override}  # fmt: skip
    return write_gguf(tmp_path / pins.PPLX_GGUF_FILE, kv)


def pin_of(path: Path, key: str = "kev", **override) -> pins.Pin:
    """The real llama.cpp pin, with the sha256 of the test's GGUF."""
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    base = pins.ALTERNATIVES[(key, "llamacpp")]
    return dataclasses.replace(base, **{"gguf_sha256": sha, **override})


class Sidecar:
    """llama-server's endpoints. `calibrated(payload)` is the P(yes) it returns.

    `router` (a {name: model path} preset) makes it a router sidecar: /models lists each with a
    status, POST /models/load loads one after `load_polls` listings (swapping the other out),
    /props?model=<name> answers for that model and /props alone for the router itself."""

    def __init__(self, *, model_path="/models/Kev-4B-Q4_K_M.gguf", build="b12767-a8ad690ca",
                 not_ready=0, calibrated=None, status=200, answer=None, router=None,
                 limit_words=None,
                 load_polls=1, initial="unloaded", busy_loads=0, models_errors=0,
                 load_fails=False):  # fmt: skip
        self.model_path, self.build, self.not_ready, self.status = (
            model_path, build, not_ready, status,
        )  # fmt: skip
        self.router = router
        self.states = {name: initial for name in (router or {})}
        self.load_polls, self.polls = load_polls, 0
        self.loads: list[str] = []
        #: Router: answer this many loads with 500 "model limit reached" (the other one busy),
        #: this many /models with 503 (restarting), and fail the load (the child exits).
        self.busy_loads, self.models_errors, self.load_fails = busy_loads, models_errors, load_fails
        self.failed: set[str] = set()
        self.calibrated = calibrated or (lambda payload: 0.7)
        #: The whole response body, when a test needs a malformed one.
        self.answer = answer
        #: A request whose state has more words than this is refused as llama.cpp b12767
        #: refuses a prompt over its batch: HTTP 500 "input (N tokens) is too large to process".
        self.limit_words = limit_words
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    if outer.not_ready > 0:
                        outer.not_ready -= 1
                        return self._send(503, {"error": {"message": "Loading model"}})
                    return self._send(200, {"status": "ok"})
                if self.path == "/models" and outer.router is not None:
                    if outer.models_errors > 0:
                        outer.models_errors -= 1
                        return self._send(503, {"error": {"message": "restarting"}})
                    for name, state in outer.states.items():
                        if state == "loading":
                            outer.polls += 1
                            if outer.load_fails:
                                outer.states[name] = "unloaded"
                                outer.failed.add(name)
                            elif outer.polls >= outer.load_polls:
                                outer.states[name] = "loaded"

                    def status(name, path):
                        st = {
                            "value": outer.states[name],
                            "args": ["/app/llama-server", "--model", path, "--port", "0"],
                        }
                        if name in outer.failed:
                            st.update(failed=True, exit_code=1)
                        return st

                    return self._send(200, {"data": [
                        {"id": name, "object": "model", "status": status(name, path)}
                        for name, path in outer.router.items()]})  # fmt: skip
                if self.path == "/models":
                    return self._send(200, {"data": [{"id": outer.model_path, "object": "model"}]})
                if self.path.startswith("/props?model=") and outer.router is not None:
                    name = self.path.split("=", 1)[1]
                    return self._send(200, {"model_path": outer.router[name],
                                            "build_info": outer.build, "total_slots": 1})  # fmt: skip
                if self.path == "/props":
                    path = "none" if outer.router is not None else outer.model_path
                    return self._send(200, {"model_path": path,
                                            "build_info": outer.build, "total_slots": 1})  # fmt: skip
                self._send(404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/models/load" and outer.router is not None:
                    name = body.get("model")
                    if name not in outer.states:
                        return self._send(404, {"error": {"message": "File Not Found"}})
                    if outer.states[name] in ("loaded", "loading", "sleeping"):
                        return self._send(400, {"error": {"message": "model is already running"}})
                    if outer.busy_loads > 0:
                        outer.busy_loads -= 1
                        return self._send(500, {"error": {
                            "message": "model limit reached, try again later"}})  # fmt: skip
                    outer.loads.append(name)
                    for other in outer.states:  # --models-max 1: swap the other out
                        outer.states[other] = "unloaded"
                    outer.states[name] = "loading"
                    outer.polls = 0
                    return self._send(200, {"success": True})
                outer.requests.append(body)
                n = len(body["state"].split())
                if outer.limit_words is not None and n > outer.limit_words:
                    return self._send(500, {"error": {"code": 500, "type": "server_error",
                        "message": f"input ({n} tokens) is too large to process. increase the "
                                   f"physical batch size (current batch size: {outer.limit_words})"}})  # fmt: skip
                if outer.status != 200:
                    return self._send(outer.status, {"error": {"message": "bad request"}})
                if outer.answer is not None:
                    return self._send(200, outer.answer(body))
                q = next(iter(body["questions"]))
                p = outer.calibrated(body)
                self._send(200, {"answers": {q: {"type": "noul", "noul": p}}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def sidecar():
    made = []

    def make(**kw):
        s = Sidecar(**kw)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def rt(url: str, gguf: Path, stop=None, device="gpu", dtype="q4_k_m") -> judges.Runtime:
    return judges.Runtime(device, dtype, None, False, None, "llamacpp", url, gguf, stop)


PAYLOAD = {"state": "Listing A ...", "questions": {"same": {"type": "noul", "instructions": "?"}}}


# --- the GGUF reader and the maths --------------------------------------------------------


def test_the_gguf_reader_finds_the_keys_and_skips_arrays(tmp_path):
    path = kev_gguf(tmp_path)
    got = judges.gguf_metadata(path, {"qwen35.decision.type", "qwen35.decision.temperature.noul"})
    assert got["qwen35.decision.type"] == "kev"
    assert got["qwen35.decision.temperature.noul"] == pytest.approx(T, rel=1e-6)
    assert judges.gguf_metadata(path, {"missing"}) == {}


def test_the_gguf_reader_refuses_what_is_not_a_gguf(tmp_path):
    (tmp_path / "x.gguf").write_bytes(b"NOPE" + b"\0" * 32)
    with pytest.raises(judges.LoadError, match="not a GGUF"):
        judges.gguf_metadata(tmp_path / "x.gguf", {"a"})
    write_gguf(tmp_path / "v1.gguf", {}, version=1)
    with pytest.raises(judges.LoadError, match="version 1"):
        judges.gguf_metadata(tmp_path / "v1.gguf", {"a"})
    (tmp_path / "short.gguf").write_bytes(b"GGUF" + struct.pack("<I", 3))
    with pytest.raises(judges.LoadError, match="ends early"):
        judges.gguf_metadata(tmp_path / "short.gguf", {"a"})


@pytest.mark.parametrize("z", [-12.0, -3.0, -0.2, 0.0, 0.4, 2.5, 9.0])
def test_uncalibrate_inverts_the_temperature(z):
    calibrated = 1 / (1 + math.exp(-z / T))
    assert judges.uncalibrate(calibrated, T) == pytest.approx(1 / (1 + math.exp(-z)), abs=1e-9)


def test_uncalibrate_keeps_order_and_bounds():
    ps = [0.0, 1e-9, 0.1, 0.5, 0.641, 0.9, 1.0 - 1e-9, 1.0]
    raw = [judges.uncalibrate(p, T) for p in ps]
    assert raw == sorted(raw) and all(0.0 <= r <= 1.0 for r in raw)
    assert judges.uncalibrate(0.5, T) == pytest.approx(0.5)
    assert judges.uncalibrate(0.3, 1.0) == pytest.approx(0.3)
    # Raw 0.8, the policy's Kev threshold, is about 0.640 on llama.cpp's calibrated scale.
    calibrated = 1 / (1 + math.exp(-math.log(4) / T))
    assert calibrated == pytest.approx(0.640, abs=1e-3)
    assert judges.uncalibrate(calibrated, T) == pytest.approx(0.8)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 1.5, -0.2, True, False, "0.5",
                                 None])  # fmt: skip
def test_uncalibrate_refuses_what_is_not_a_probability(bad):
    with pytest.raises(ValueError, match="not a probability"):
        judges.uncalibrate(bad, T)


def test_uncalibrate_takes_exact_zero_and_one():
    assert 0.0 <= judges.uncalibrate(0, T) < 1e-20
    assert 1.0 - 1e-9 < judges.uncalibrate(1.0, T) <= 1.0


# --- loading ------------------------------------------------------------------------------


def test_load_checks_everything_then_scores_raw(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar(not_ready=2, calibrated=lambda _p: 1 / (1 + math.exp(-2.0 / T)))
    pin = pin_of(gguf)
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin)
    p, extra = judge.score(PAYLOAD)
    assert p == pytest.approx(1 / (1 + math.exp(-2.0)))
    assert extra == {}
    assert side.requests == [{"model": "kev", **PAYLOAD}]
    info = judge.info
    assert info["backend"] == "llamacpp" and info["gguf_sha256"] == pin.gguf_sha256
    assert info["llamacpp_build"] == "b12767-a8ad690ca" and info["temperature"] == 1.0


def test_load_through_the_registry_needs_no_torch(tmp_path, sidecar, monkeypatch):
    gguf = kev_gguf(tmp_path)
    side = sidecar()
    monkeypatch.setitem(pins.ALTERNATIVES, ("kev", "llamacpp"), pin_of(gguf))
    import sys

    monkeypatch.setitem(sys.modules, "torch", None)  # an import of torch would now fail
    judge = judges.load("kev", rt(side.url, gguf))
    assert judge.info["backend"] == "llamacpp" and "load_seconds" in judge.info
    judges.unload(judge, "gpu")


@pytest.mark.parametrize(
    "override, sidecar_kw, match",
    [
        ({"qwen35.decision.temperature.noul": 1.0}, {}, "temperature is 1.0"),
        ({"qwen35.decision.type": "laya"}, {}, "not a kev decision model"),
        ({}, {"model_path": "/models/Kev-4B-Q8_0.gguf"}, "serves 'Kev-4B-Q8_0.gguf'"),
        ({}, {"build": "b12800-0000000"}, "pinned b12767"),
    ],
)
def test_load_refuses_a_mismatch(tmp_path, sidecar, override, sidecar_kw, match):
    gguf = kev_gguf(tmp_path, **override)
    side = sidecar(**sidecar_kw)
    with pytest.raises(judges.LoadError, match=match):
        judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))


def test_load_refuses_another_file(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    pin = pin_of(gguf, gguf_sha256="0" * 64)
    with pytest.raises(judges.LoadError, match="sha256"):
        judges._load_llamacpp("kev", rt(sidecar().url, gguf), pin)
    other = write_gguf(tmp_path / "Kev-4B-Q8_0.gguf", {"qwen35.decision.type": "kev"})
    with pytest.raises(judges.LoadError, match="not the pinned"):
        judges._load_llamacpp("kev", rt(sidecar().url, other), pin_of(gguf))
    with pytest.raises(judges.LoadError, match="not a file"):
        judges._load_llamacpp("kev", rt(sidecar().url, tmp_path / "none.gguf"), pin_of(gguf))


def test_what_is_sent_is_nfc_like_kevs_own_tokenizer_sees_it(tmp_path, sidecar):
    """llama.cpp does not NFC-normalise; Kev's Qwen tokenizer does (the ohm sign U+2126 and a
    decomposed é tokenised differently for 10 of 1,800 Phase E requests on pplx's twin)."""
    gguf = kev_gguf(tmp_path)
    side = sidecar(calibrated=lambda _p: 0.5)
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    raw = {
        "state": "47K\u2126 resistor, cafe\u0301",
        "questions": {"same": {"type": "noul", "instructions": "Ohm \u2126?",
                               "criteria": {"true": "e\u0301", "false": "no"}}},
    }  # fmt: skip
    judge.score(raw)
    [sent] = side.requests
    assert sent["state"] == "47K\u03a9 resistor, caf\u00e9"
    assert sent["questions"]["same"]["instructions"] == "Ohm \u03a9?"
    assert sent["questions"]["same"]["criteria"] == {"true": "\u00e9", "false": "no"}
    assert raw["state"] == "47K\u2126 resistor, cafe\u0301"  # the caller's payload is untouched


def test_load_gives_up_on_a_sidecar_that_never_gets_ready(tmp_path, monkeypatch):
    gguf = kev_gguf(tmp_path)
    monkeypatch.setattr(judges, "LLAMACPP_READY_S", 0.0)
    with pytest.raises(judges.LoadError, match="not ready"):
        judges._load_llamacpp("kev", rt("http://127.0.0.1:9", gguf), pin_of(gguf))


@pytest.mark.parametrize(
    "answer, match",
    [
        (lambda b: ["not", "a", "dict"], "no answers.same.noul"),
        (lambda b: {"answers": {}}, "no answers.same.noul"),
        (lambda b: {"answers": {"same": {"type": "noul"}}}, "no answers.same.noul"),
        (lambda b: {"answers": {"same": {"noul": math.nan}}}, "not a probability"),
        (lambda b: {"answers": {"same": {"noul": 1.5}}}, "not a probability"),
        (lambda b: {"answers": {"same": {"noul": -0.2}}}, "not a probability"),
        (lambda b: {"answers": {"same": {"noul": True}}}, "not a probability"),
        (lambda b: {"answers": {"same": {"noul": "0.7"}}}, "not a probability"),
    ],
)
def test_a_malformed_answer_is_an_error_never_a_score(tmp_path, sidecar, answer, match):
    gguf = kev_gguf(tmp_path)
    judge = judges._load_llamacpp("kev", rt(sidecar(answer=answer).url, gguf), pin_of(gguf))
    with pytest.raises(RuntimeError, match=match):
        judge.score(PAYLOAD)


def test_the_request_timeout_is_per_device_and_inside_the_stop_bound(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    for device, want in (("gpu", 60.0), ("cpu", 120.0)):
        judge = judges._load_llamacpp("kev", rt(sidecar().url, gguf, device=device), pin_of(gguf))
        assert judge.info["request_timeout_s"] == want
    # The compose stop_grace_period of the worker that runs each one covers a request, 3 x 10 s
    # of last posts and a 10 s join (docs/ai/worker.md, "A stop sets one deadline").
    text = (DEPLOY / "compose.yml").read_text()
    for (key, _device), timeout in judges.LLAMACPP_REQUEST_S.items():
        if f"\n  {key}:\n" not in text:
            assert key not in pins.ACTIVE_BACKEND, key  # only a rollback model has no service
            continue
        block = text[text.index(f"\n  {key}:\n") :]
        block = block[: block.index("\n\n")]
        grace = (
            int(block.split("stop_grace_period: ", 1)[1].split("s", 1)[0])
            if ("stop_grace_period" in block)
            else 240
        )  # the worker anchor's
        assert timeout + 3 * 10 + 10 < grace, (key, timeout, grace)


def test_every_llamacpp_request_fits_the_window_end_kill():
    """With outside_window = "wait" a last request may start just before the window's end; the
    supervisor kills the session KILL_AFTER_S after it. The request, 3 x 10 s of last posts and
    the 10 s join must finish first, or a score is lost without its UNDELIVERED log."""
    from makhzan_ml.worker import supervisor

    for (key, device), timeout in judges.LLAMACPP_REQUEST_S.items():
        assert timeout + 3 * 10 + 10 < supervisor.KILL_AFTER_S, (key, device, timeout)


def test_a_stop_interrupts_the_hash_and_the_wait(tmp_path):
    gguf = kev_gguf(tmp_path)
    stop = threading.Event()
    stop.set()
    with pytest.raises(judges.LoadInterrupted, match="hashing"):
        judges._load_llamacpp("kev", rt("http://127.0.0.1:9", gguf, stop), pin_of(gguf))
    with pytest.raises(judges.LoadInterrupted, match="waiting"):
        judges._wait_ready("http://127.0.0.1:9", 120.0, stop)
    # Not yet stopped, then stopped while waiting: it ends at the next check, not at 120 s.
    late = threading.Event()
    threading.Timer(0.3, late.set).start()
    import time

    t0 = time.monotonic()
    with pytest.raises(judges.LoadInterrupted):
        judges._wait_ready("http://127.0.0.1:9", 120.0, late)
    assert time.monotonic() - t0 < 5


def test_a_refused_request_is_an_error_not_a_score(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar()
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    side.status = 400
    with pytest.raises(RuntimeError, match="HTTP 400"):
        judge.score(PAYLOAD)
    with pytest.raises(ValueError):
        judge.score({"state": "x", "questions": {}})


# --- the pin and the configuration --------------------------------------------------------


def test_the_kev_llamacpp_pin_is_the_rollback_of_d25():
    alt = pins.pin_for("kev", "llamacpp")
    assert alt.backend == "llamacpp" and alt.temperature == 1.0
    # D25 (owner, 2026-11-27): H2O replaced Kev; the policy keeps Kev's version as its rollback.
    assert alt.model_version == policy.LLAMACPP_KEV.model_version
    assert "kev" not in pins.ACTIVE_BACKEND and "kev" not in policy.MODELS
    assert alt.code == pins.LLAMACPP_IMAGE and "@sha256:" in alt.code
    assert alt.model_version.startswith(f"kev-4b-Q4_K_M@{pins.KEV_GGUF_SHA256[:12]}+")
    assert pins.pin_for("kev") is pins.PINS["kev"]
    with pytest.raises(KeyError):
        pins.pin_for("kev", "onnx")


def test_the_h2o_pin_is_what_production_serves_and_reads_raw_scores():
    alt = pins.pin_for("h2o", "llamacpp")
    assert pins.production_pin("h2o") is alt
    assert alt.model_version == policy.MODELS["h2o"].model_version
    assert alt.model_version.startswith(f"h2o-lightning-4b-Q4_K_M@{pins.H2O_GGUF_SHA256[:12]}+")
    # Raw P(yes), the scale the policy's 0.578 was matched on: the GGUF's 0.8 is undone.
    assert alt.temperature == 1.0 and abs(alt.gguf_temperature - 0.8) < 1e-6
    assert judges.LLAMACPP_MODELS["h2o"] == ("h2o-lightning", "h2o")
    with pytest.raises(KeyError):
        pins.pin_for("h2o")  # no torch build


def test_the_pplx_alternative_reads_scores_as_served():
    alt = pins.pin_for("pplx", "llamacpp")
    assert alt.backend == "llamacpp" and alt.model_version == policy.MODELS["pplx"].model_version
    assert pins.production_pin("pplx") is alt
    # The scale of every validated pplx score: the checkpoint's own temperature, which the GGUF
    # carries in full and llama.cpp applies, so nothing is undone.
    assert alt.temperature == policy.MODELS["pplx"].scoring["temperature"] == 1.3303
    assert abs(alt.gguf_temperature - alt.temperature) < 1e-3
    assert alt.model_version.startswith(
        f"pplx-decider-flash-v1.3-Q4_K_S@{pins.PPLX_GGUF_SHA256[:12]}+llama.cpp-b12767-"
    )
    assert pins.pin_for("pplx") is pins.PINS["pplx"]


def llamacpp_cfg(**compute) -> dict:
    return {
        "worker": {"name": "amd-kev", "broker_url": "https://b.example.test/ai/v1",
                   "token": "t", "model": "kev"},
        "compute": {"backend": "llamacpp", "device": "gpu",
                    "llamacpp_url": "http://kev-llamacpp:8080",
                    "gguf_path": "/models/Kev-4B-Q4_K_M.gguf", **compute},
    }  # fmt: skip


def test_a_llamacpp_config_parses():
    cfg = parse(llamacpp_cfg())
    assert (cfg.backend, cfg.dtype, cfg.llamacpp_url) == (
        "llamacpp", "q4_k_m", "http://kev-llamacpp:8080",
    )  # fmt: skip
    assert cfg.pin is pins.ALTERNATIVES[("kev", "llamacpp")]
    assert parse(llamacpp_cfg(llamacpp_url="http://127.0.0.1:8130")).llamacpp_url


@pytest.mark.parametrize(
    "compute, match",
    [
        ({"backend": "onnx"}, "backend 'onnx'"),
        ({"dtype": "fp32"}, "only \\['q4_k_m'\\]"),
        ({"llamacpp_url": "https://kev-llamacpp:8080"}, "http:// to a compose service"),
        ({"llamacpp_url": "http://llama.example.com:8080"}, "http:// to a compose service"),
        ({"llamacpp_url": "http://100.101.102.103:8080"}, "http:// to a compose service"),
        ({"llamacpp_url": "http://kev-llamacpp:8080/v1"}, "no path"),
        ({"mmap": False}, "mmap is not read"),
        ({"weights_cache": "/models"}, "weights_cache is not read"),
    ],
)
def test_a_bad_llamacpp_config_is_refused(compute, match):
    with pytest.raises(ConfigError, match=match):
        parse(llamacpp_cfg(**compute))


def test_llamacpp_keys_need_the_backend_and_the_backend_needs_them():
    data = llamacpp_cfg()
    del data["compute"]["llamacpp_url"]
    with pytest.raises(ConfigError, match="needs llamacpp_url"):
        parse(data)
    torch = llamacpp_cfg()
    torch["compute"] = {"llamacpp_url": "http://kev-llamacpp:8080"}
    with pytest.raises(ConfigError, match="only read with backend"):
        parse(torch)
    pplx = llamacpp_cfg(dtype="q4_k_m")  # Kev's precision, for pplx
    pplx["worker"]["model"] = "pplx"
    with pytest.raises(ConfigError, match="only \\['q4_k_s'\\]"):
        parse(pplx)


def test_expect_version_is_the_backends():
    alt = pins.pin_for("kev", "llamacpp").model_version
    assert parse({**llamacpp_cfg(), "model": {"kev": {"expect_version": alt}}})
    with pytest.raises(ConfigError, match="not what this worker serves"):
        parse({**llamacpp_cfg(), "model": {"kev": {"expect_version":
                                                   pins.PINS["kev"].model_version}}})  # fmt: skip


def test_the_compose_example_parses():
    data = tomllib.loads((DEPLOY / "home-h2o.toml").read_text())
    data["worker"].pop("token_file")
    data["worker"]["token"] = "example"
    cfg = parse(data)
    assert (cfg.backend, cfg.device, cfg.llamacpp_url) == (
        "llamacpp", "gpu", "http://llamacpp:8080",
    )  # fmt: skip
    assert cfg.expect_versions == {"h2o": pins.pin_for("h2o", "llamacpp").model_version}
    # Its window is the torch Kev worker's (the rollback config): one replaces the other.
    cpu = parse({**tomllib.loads((DEPLOY / "torch-kev.toml").read_text()),
                 "worker": {**data["worker"], "model": "kev"}})  # fmt: skip
    assert cfg.schedule.windows == cpu.schedule.windows


def test_the_router_is_on_by_default_pinned_guarded_and_unreachable():
    """One llama.cpp router for both judges, started by a plain `docker compose up -d` (it sleeps
    when idle), refusing to start without the card's clock limit."""
    text = (DEPLOY / "compose.yml").read_text()
    block = text[text.index("\n  llamacpp:\n") : text.index("\nnetworks:")]
    # No profile (plain `up -d` starts it) and no restart override (the anchor's unless-stopped).
    assert "\n    profiles:" not in block and "\n    restart:" not in block
    assert f"    image: {pins.LLAMACPP_IMAGE}\n" in block
    assert '    entrypoint: ["/bin/sh", "/cfg/llamacpp-guard.sh"]\n' in block
    assert "ports" not in block and "0.0.0.0:" not in block
    assert "    networks: [broker-only]\n" in block and "egress" not in block
    assert "      - /dev/dri:/dev/dri\n" in block
    # Required now that the service always starts: an unset id fails `docker compose up` loudly.
    assert "${RENDER_GID:?" in block and "${VIDEO_GID:?" in block
    for mount in (
        "${WORKER_DIR:?set WORKER_DIR in .env}/models.ini:/cfg/models.ini:ro",
        "${WORKER_DIR:?set WORKER_DIR in .env}/llamacpp-guard.sh:/cfg/llamacpp-guard.sh:ro",
        f":/models/{pins.KEV_GGUF_FILE}:ro",
        f":/models/{pins.PPLX_GGUF_FILE}:ro",
    ):
        assert mount in block, mount
    for flag in (
        '- --models-max\n      - "1"',
        "- --models-preset\n      - /cfg/models.ini",
        "- -dev\n      - Vulkan0",
        '- --sleep-idle-seconds\n      - "600"',
    ):
        assert flag in block, flag
    # No host timers or scripts any more: the stack is containers only.
    assert not (DEPLOY / "sidecar-window.sh").exists()
    assert not (DEPLOY / "install-sidecar-timers.sh").exists()


def test_the_router_preset_holds_the_soaked_settings():
    import configparser

    ini = configparser.ConfigParser(inline_comment_prefixes=None)
    # llama.cpp's preset allows global keys before the first section (version = 1).
    ini.read_string("[_top]\n" + (DEPLOY / "models.ini").read_text())
    assert ini["_top"]["version"] == "1"
    assert ini["*"]["n-gpu-layers"] == "99" and ini["*"]["parallel"] == "1"
    kev, pplx = ini["kev"], ini["pplx"]
    assert kev["model"] == f"/models/{pins.KEV_GGUF_FILE}"
    assert (kev["c"], kev["b"], kev["ub"]) == ("4096", "512", "512")
    assert pplx["model"] == f"/models/{pins.PPLX_GGUF_FILE}"
    # Non-causal: the whole request in one batch (the longest Phase E request: 3,574 tokens).
    assert (pplx["c"], pplx["b"], pplx["ub"], pplx["flash-attn"]) == ("4096", "4096", "4096", "on")
    # The names the workers ask for.
    assert {"kev", "pplx"} == {judges.LLAMACPP_MODELS[k][1] for k in ("kev", "pplx")}


def _guard(tmp_path, modes):
    sysfs = tmp_path / "sys"
    for card, mode in modes.items():
        d = sysfs / "class" / "drm" / card / "device"
        d.mkdir(parents=True)
        (d / "power_dpm_force_performance_level").write_text(mode + "\n")
    server = tmp_path / "server.sh"
    server.write_text('#!/bin/sh\necho "served $*"\n')
    server.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "GUARD_SYSFS": str(sysfs), "LLAMA_SERVER": str(server)}
    import subprocess

    return subprocess.run(["sh", str(DEPLOY / "llamacpp-guard.sh"), "--models-max", "1"],
                          env=env, capture_output=True, text=True)  # fmt: skip


@pytest.mark.parametrize(
    "modes, ok",
    [
        ({"card1": "manual"}, True),
        ({"card1": "auto"}, False),  # the udev rule is not applied
        ({"card0": "manual", "card1": "auto"}, False),
        ({}, False),  # no AMD card at all
    ],
)
def test_the_guard_runs_the_server_only_with_the_clock_limit(tmp_path, modes, ok):
    r = _guard(tmp_path, modes)
    if ok:
        assert r.returncode == 0 and r.stdout.strip() == "served --models-max 1"
    else:
        assert r.returncode == 1 and "Refusing to start" in r.stderr and not r.stdout


# --- a router sidecar -----------------------------------------------------------------------

ROUTER = {"kev": f"/models/{pins.KEV_GGUF_FILE}", "pplx": f"/models/{pins.PPLX_GGUF_FILE}"}


def test_on_a_router_the_load_swaps_its_own_model_in_and_checks_its_file(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar(router=ROUTER, load_polls=3)
    side.states["pplx"] = "loaded"  # pplx held the card
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    assert side.loads == ["kev"] and side.states == {"kev": "loaded", "pplx": "unloaded"}
    assert judge.info["router"] is True and judge.info["llamacpp_build"] == "b12767-a8ad690ca"
    judge.score(PAYLOAD)
    assert side.requests[-1]["model"] == "kev"


@pytest.mark.parametrize("state", ["loaded", "sleeping"])
def test_on_a_router_a_ready_model_is_not_reloaded(tmp_path, sidecar, state):
    gguf = pplx_gguf(tmp_path)
    side = sidecar(router=ROUTER, initial=state)
    judges._load_llamacpp("pplx", rt(side.url, gguf, dtype="q4_k_s"), pin_of(gguf, "pplx"))
    assert side.loads == []


def test_on_a_router_another_file_under_the_name_is_refused(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar(router={**ROUTER, "kev": "/models/other.gguf"})
    with pytest.raises(judges.LoadError, match="other.gguf"):
        judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))


def test_on_a_router_without_the_model_the_load_fails(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar(router={"pplx": ROUTER["pplx"]})
    with pytest.raises(judges.LoadError, match="no model 'kev'"):
        judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))


def test_on_a_router_a_load_that_never_finishes_gives_up(tmp_path, sidecar, monkeypatch):
    gguf = kev_gguf(tmp_path)
    side = sidecar(router=ROUTER, load_polls=10**9)
    monkeypatch.setattr(judges, "LLAMACPP_READY_S", 2.5)
    with pytest.raises(judges.LoadError, match="did not load 'kev' \\(loading\\)"):
        judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))


def test_on_a_router_a_stop_interrupts_the_load(tmp_path, sidecar):
    import threading as _t

    gguf = kev_gguf(tmp_path)
    side = sidecar(router=ROUTER, load_polls=10**9)
    stop = _t.Event()
    _t.Timer(1.5, stop.set).start()
    with pytest.raises(judges.LoadInterrupted):
        judges._load_llamacpp("kev", rt(side.url, gguf, stop=stop), pin_of(gguf))


# --- a whole session ----------------------------------------------------------------------


def test_a_session_on_the_sidecar_posts_raw_scores_under_the_alternative_version(
    tmp_path, sidecar, monkeypatch
):
    gguf = kev_gguf(tmp_path)
    pin = pin_of(gguf)
    monkeypatch.setitem(pins.ALTERNATIVES, ("kev", "llamacpp"), pin)
    # On a GPU the config's require_clock_limit defaults on: the session's load reads it (here a
    # fake sysfs whose card is held to its clock states).
    monkeypatch.setattr(judges, "SYSFS", _sysfs(tmp_path, {"card1": "manual"}))
    side = sidecar(calibrated=lambda _p: 1 / (1 + math.exp(-1.0 / T)))
    with FakeBroker(
        {"tok": ("amd-kev", ["kev"])},
        versions={"kev": pin.model_version},
        weights={"kev": pin.weights_revision},
    ) as broker:
        job = broker.add_job("kev", {"ab": PAYLOAD, "ba": PAYLOAD})
        cfg = parse({
            "worker": {"name": "amd-kev", "broker_url": broker.url, "token": "tok",
                       "model": "kev"},
            "compute": {"backend": "llamacpp", "device": "gpu", "llamacpp_url": side.url,
                        "gguf_path": str(gguf)},
            "schedule": {"windows": "always", "on_empty": "exit"},
        })  # fmt: skip
        code = run.Worker(cfg, importable=lambda _k: False).run()
        scores = broker.jobs[job.job_id].scores
    assert code == run.EXIT_OK
    assert set(scores) == {"ab", "ba"}
    for s in scores.values():
        assert s["p"] == pytest.approx(1 / (1 + math.exp(-1.0)))
        assert (s["device"], s["dtype"]) == ("gpu", "q4_k_m")


def test_a_broker_on_the_torch_versions_refuses_the_llamacpp_worker(tmp_path, sidecar,
                                                                   monkeypatch):  # fmt: skip
    # A broker still on the torch versions (before its deploy, or after a rollback) refuses it.
    gguf = kev_gguf(tmp_path)
    monkeypatch.setitem(pins.ALTERNATIVES, ("kev", "llamacpp"), pin_of(gguf))
    with FakeBroker({"tok": ("amd-kev", ["kev"])}) as broker:  # default: the torch pins
        broker.add_job("kev", {"ab": PAYLOAD})
        cfg = parse({
            "worker": {"name": "amd-kev", "broker_url": broker.url, "token": "tok",
                       "model": "kev"},
            "compute": {"backend": "llamacpp", "device": "gpu",
                        "llamacpp_url": sidecar().url, "gguf_path": str(gguf)},
            "schedule": {"windows": "always", "on_empty": "exit"},
        })  # fmt: skip
        assert run.Worker(cfg).run() == run.EXIT_VERSION


def test_a_stop_during_the_load_hands_the_lease_back_not_a_config_error(tmp_path):
    with FakeBroker({"tok": ("amd-kev", ["kev"])},
                    versions={"kev": pins.pin_for("kev", "llamacpp").model_version},
                    weights={"kev": pins.KEV_GGUF_REVISION}) as broker:  # fmt: skip
        job = broker.add_job("kev", {"ab": PAYLOAD})
        cfg = parse({
            "worker": {"name": "amd-kev", "broker_url": broker.url, "token": "tok",
                       "model": "kev"},
            "compute": {"backend": "llamacpp", "device": "gpu",
                        "llamacpp_url": "http://127.0.0.1:9", "gguf_path": str(tmp_path / "g")},
            "schedule": {"windows": "always", "on_empty": "exit"},
        })  # fmt: skip
        worker = None

        def load(key, runtime):
            assert runtime.stop is worker.stop
            worker.request_stop("test: SIGTERM during the load")
            raise judges.LoadInterrupted("stopped while hashing")

        worker = run.Worker(cfg, load_judge=load)
        code = worker.run()
        held = broker.jobs[job.job_id]
    assert code != run.EXIT_CONFIG
    assert held.scores == {} and held.status == "queued"


# --- pplx -----------------------------------------------------------------------------------


def test_pplx_scores_are_taken_as_served_and_kevs_gguf_is_refused(tmp_path, sidecar):
    gguf = pplx_gguf(tmp_path)
    side = sidecar(model_path=f"/models/{pins.PPLX_GGUF_FILE}", calibrated=lambda _p: 0.9612)
    judge = judges._load_llamacpp("pplx", rt(side.url, gguf, dtype="q4_k_s"), pin_of(gguf, "pplx"))
    p, _ = judge.score(PAYLOAD)
    # llama.cpp applies pplx's own temperature, the scale of its validated scores: unchanged.
    assert p == 0.9612
    assert side.requests == [{"model": "pplx", **PAYLOAD}]
    assert judge.key == "pplx" and judge.info["temperature"] == 1.3303
    # A Kev GGUF under pplx's name is not a pplx-decider model.
    other = tmp_path / "kev"
    other.mkdir()
    wrong = write_gguf(other / pins.PPLX_GGUF_FILE, {
        "qwen35.decision.type": "kev",
        "qwen35.decision.temperature.noul": pins.PPLX_GGUF_TEMPERATURE})  # fmt: skip
    with pytest.raises(judges.LoadError, match="not a pplx-decider decision model"):
        judges._load_llamacpp("pplx", rt(side.url, wrong, dtype="q4_k_s"), pin_of(wrong, "pplx"))


@pytest.mark.parametrize("bad", [math.nan, 1.5, -0.1, True, "0.9"])
def test_a_bad_pplx_answer_is_an_error_never_a_score(tmp_path, sidecar, bad):
    gguf = pplx_gguf(tmp_path)
    side = sidecar(model_path=f"/models/{pins.PPLX_GGUF_FILE}", calibrated=lambda _p: bad)
    judge = judges._load_llamacpp("pplx", rt(side.url, gguf, dtype="q4_k_s"), pin_of(gguf, "pplx"))
    with pytest.raises(RuntimeError, match="noul"):
        judge.score(PAYLOAD)


def test_rescale_is_kevs_uncalibrate_and_pplxs_identity():
    assert judges.rescale(0.7, T, 1.0) == pytest.approx(judges.uncalibrate(0.7, T))
    assert judges.rescale(0.7, pins.PPLX_GGUF_TEMPERATURE, 1.3303) == 0.7
    with pytest.raises(ValueError):
        judges.rescale(math.nan, pins.PPLX_GGUF_TEMPERATURE, 1.3303)


def test_the_pplx_compose_example_parses():
    data = tomllib.loads((DEPLOY / "home-pplx.toml").read_text())
    data["worker"].pop("token_file")
    data["worker"]["token"] = "example"
    cfg = parse(data)
    assert (cfg.model, cfg.backend, cfg.device, cfg.dtype, cfg.llamacpp_url) == (
        "pplx", "llamacpp", "gpu", "q4_k_s", "http://llamacpp:8080",
    )  # fmt: skip
    assert cfg.expect_versions == {"pplx": pins.pin_for("pplx", "llamacpp").model_version}


def test_a_broker_on_the_torch_versions_refuses_the_pplx_llamacpp_worker(tmp_path, sidecar,
                                                                        monkeypatch):  # fmt: skip
    gguf = pplx_gguf(tmp_path)
    monkeypatch.setitem(pins.ALTERNATIVES, ("pplx", "llamacpp"), pin_of(gguf, "pplx"))
    with FakeBroker({"tok": ("cpu-pplx", ["pplx"])}) as broker:  # default: the torch pins
        broker.add_job("pplx", {"ab": PAYLOAD})
        cfg = parse({
            "worker": {"name": "cpu-pplx", "broker_url": broker.url, "token": "tok",
                       "model": "pplx"},
            "compute": {"backend": "llamacpp", "device": "cpu", "dtype": "q4_k_s",
                        "llamacpp_url": sidecar(model_path=f"/models/{pins.PPLX_GGUF_FILE}").url,
                        "gguf_path": str(gguf)},
            "schedule": {"windows": "always", "on_empty": "exit"},
        })  # fmt: skip
        assert run.Worker(cfg).run() == run.EXIT_VERSION


def test_a_pplx_session_posts_scores_as_served_under_its_version(tmp_path, sidecar, monkeypatch):
    gguf = pplx_gguf(tmp_path)
    pin = pin_of(gguf, "pplx")
    monkeypatch.setitem(pins.ALTERNATIVES, ("pplx", "llamacpp"), pin)
    side = sidecar(model_path=f"/models/{pins.PPLX_GGUF_FILE}", calibrated=lambda _p: 0.97)
    with FakeBroker({"tok": ("cpu-pplx", ["pplx"])}, versions={"pplx": pin.model_version},
                    weights={"pplx": pin.weights_revision}) as broker:  # fmt: skip
        job = broker.add_job("pplx", {"ab": PAYLOAD, "ba": PAYLOAD})
        cfg = parse({
            "worker": {"name": "cpu-pplx", "broker_url": broker.url, "token": "tok",
                       "model": "pplx"},
            "compute": {"backend": "llamacpp", "device": "cpu", "dtype": "q4_k_s",
                        "llamacpp_url": side.url, "gguf_path": str(gguf)},
            "schedule": {"windows": "always", "on_empty": "exit"},
        })  # fmt: skip
        code = run.Worker(cfg, importable=lambda _k: False).run()
        scores = broker.jobs[job.job_id].scores
    assert code == run.EXIT_OK
    assert {o: (s["p"], s["device"], s["dtype"]) for o, s in scores.items()} == {
        "ab": (0.97, "cpu", "q4_k_s"), "ba": (0.97, "cpu", "q4_k_s"),
    }  # fmt: skip


def test_on_a_router_a_busy_other_model_is_waited_for(tmp_path, sidecar):
    """While the model the router holds is busy it answers a load with 500 "model limit
    reached": retried until it gives way, never a load error that loses the night."""
    gguf = kev_gguf(tmp_path)
    side = sidecar(router=ROUTER, busy_loads=2)
    side.states["pplx"] = "loaded"
    judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    assert side.loads == ["kev"] and side.states["kev"] == "loaded"


def test_on_a_router_a_restarting_router_is_retried_not_read_as_single_model(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar(router=ROUTER, models_errors=2)
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    assert judge.info["router"] is True and side.loads == ["kev"]


def test_a_failing_models_endpoint_is_never_a_single_model_server(tmp_path, sidecar, monkeypatch):
    gguf = kev_gguf(tmp_path)
    side = sidecar(router=ROUTER, models_errors=10**9)
    monkeypatch.setattr(judges, "LLAMACPP_READY_S", 1.0)
    with pytest.raises(judges.LoadError, match="did not list its models"):
        judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))


def test_on_a_router_a_load_whose_child_exits_fails_at_once(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar(router=ROUTER, load_fails=True)
    t0 = time.monotonic()
    with pytest.raises(judges.LoadError, match="failed to load 'kev'"):
        judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    assert time.monotonic() - t0 < 10  # not the 180 s budget


def _sysfs(tmp_path, modes):
    root = tmp_path / "sysroot"
    for card, mode in modes.items():
        d = root / "class" / "drm" / card / "device"
        d.mkdir(parents=True)
        (d / "power_dpm_force_performance_level").write_text(mode + "\n")
    root.mkdir(exist_ok=True)
    return root


@pytest.mark.parametrize(
    "modes, ok",
    [({"card1": "manual"}, True), ({"card1": "auto"}, False),
     ({"card0": "manual", "card1": "auto"}, False), ({}, False)],
)  # fmt: skip
def test_the_worker_rechecks_the_clock_limit_at_every_load(tmp_path, sidecar, monkeypatch,
                                                         modes, ok):  # fmt: skip
    gguf = kev_gguf(tmp_path)
    monkeypatch.setattr(judges, "SYSFS", _sysfs(tmp_path, modes))
    side = sidecar(router=ROUTER)
    runtime = dataclasses.replace(rt(side.url, gguf), require_clock_limit=True)
    if ok:
        judges._load_llamacpp("kev", runtime, pin_of(gguf))
    else:
        with pytest.raises(judges.LoadError, match="manual|clock mode"):
            judges._load_llamacpp("kev", runtime, pin_of(gguf))
        assert side.loads == []  # refused before the card is touched


def test_require_clock_limit_defaults_on_for_a_gpu_and_is_llamacpp_only():
    gpu = parse(llamacpp_cfg())
    assert gpu.require_clock_limit is True
    off = llamacpp_cfg()
    off["compute"] = {**off["compute"], "require_clock_limit": False}
    assert parse(off).require_clock_limit is False
    torch = llamacpp_cfg()
    torch["compute"] = {"device": "cpu", "require_clock_limit": True}
    with pytest.raises(ConfigError, match="only read with"):
        parse(torch)
    for name in ("home-h2o", "home-pplx"):
        data = tomllib.loads((DEPLOY / f"{name}.toml").read_text())
        assert data["compute"]["require_clock_limit"] is True


# --- over-long requests: descriptions cut to fit (owner, 2026-11-27) ------------------------------

LONG_A = " ".join(f"a{i}" for i in range(300))
LONG_B = " ".join(f"b{i}" for i in range(120))


def long_payload(desc_a=LONG_A, desc_b=LONG_B):
    def blk(name, title, desc):
        return "\n".join([f"[{name}]", f"Title: {title}", "Category: not stated",
                          "Brand: not stated", "Part number: not stated", "Pack size: not stated",
                          "Specifications: Voltage: 5V; Current: 2A", f"Description: {desc}"])  # fmt: skip

    state = ("[RULES]\nCompare the two listings.\nDescription: this rules line is not a listing\n\n"
             + blk("LISTING A", "Widget A 5V", desc_a) + "\n\n" + blk("LISTING B", "Widget B 5V", desc_b))  # fmt: skip
    return {"state": state, "questions": {"same": {"type": "noul", "instructions": "Same part?"}}}


def lines(state):
    return state.split("\n")


def test_too_long_reads_both_llamacpp_messages():
    assert judges.too_long(500, "input (5469 tokens) is too large to process. increase the "
                                "physical batch size (current batch size: 4096)") == (5469, 4096)  # fmt: skip
    assert judges.too_long(400, "the request exceeds the available context size, try increasing "
                                "it") == (None, None)  # fmt: skip
    assert judges.too_long(500, "model limit reached, try again later") is None
    assert judges.too_long(503, "input (9 tokens) is too large to process") is None


def test_an_over_long_request_is_cut_from_its_longest_description_and_scored(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    payload = long_payload()
    total = len(payload["state"].split())
    side = sidecar(limit_words=total - 100)
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    p, extra = judge.score(payload)
    assert 0 <= p <= 1
    sent = side.requests[-1]["state"]
    assert len(sent.split()) <= total - 100
    cut = extra["truncated"]["words_cut"]
    assert cut.get("LISTING A", 0) >= 100 and cut.get("LISTING B", 0) == 0  # longest first
    assert extra["truncated"]["tokens_before"] == total and extra["truncated"]["attempts"] >= 1
    before, after = lines(payload["state"]), lines(sent)
    changed = [i for i, (x, y) in enumerate(zip(before, after, strict=True)) if x != y]
    assert [before[i].split(":")[0] for i in changed] == ["Description"]  # only A's description
    assert after[changed[0]].endswith(" […]") and after[changed[0]].startswith("Description: a0 a1")
    assert "Description: this rules line is not a listing" in after  # the rules are never cut
    assert payload["state"] == long_payload()["state"]  # the caller's payload is untouched


def test_the_cut_is_deterministic_and_reaches_both_descriptions_when_needed(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    payload = long_payload()
    fixed = len(payload["state"].split()) - 420  # everything but the two descriptions
    sents = []
    for _ in range(2):
        side = sidecar(limit_words=fixed + 60)
        judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
        _, extra = judge.score(payload)
        sents.append(side.requests[-1]["state"])
        assert set(extra["truncated"]["words_cut"]) == {"LISTING A", "LISTING B"}
    assert sents[0] == sents[1]


def test_a_description_the_renderer_already_capped_keeps_one_marker(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    payload = long_payload(desc_a=LONG_A + " […]")
    side = sidecar(limit_words=len(payload["state"].split()) - 100)
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    judge.score(payload)
    desc = next(x for x in lines(side.requests[-1]["state"]) if x.startswith("Description: a0"))
    assert desc.count("[…]") == 1 and desc.endswith(" […]")


def test_too_long_even_without_descriptions_fails_the_job(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar(limit_words=10)
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    with pytest.raises(RuntimeError, match="too long even with its descriptions cut"):
        judge.score(long_payload())


def test_another_server_error_is_not_retried(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    side = sidecar(status=500)
    judge = judges._load_llamacpp("kev", rt(side.url, gguf), pin_of(gguf))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        judge.score(long_payload())
    assert len(side.requests) == 1
