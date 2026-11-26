"""Kev on a llama.cpp sidecar (`backend = "llamacpp"`): the GGUF checks, the uncalibration,
the sidecar protocol, the configuration, and a whole session through the fake broker.

No model and no llama.cpp here: a small GGUF written by `write_gguf`, and a stdlib HTTP
server standing in for llama-server's /health, /props and /v1/systemone."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import struct
import threading
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


def pin_of(path: Path, **override) -> pins.Pin:
    """The real llama.cpp pin, with the sha256 of the test's GGUF."""
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    base = pins.ALTERNATIVES[("kev", "llamacpp")]
    return dataclasses.replace(base, **{"gguf_sha256": sha, **override})


class Sidecar:
    """llama-server's three endpoints. `calibrated(payload)` is the P(yes) it returns."""

    def __init__(self, *, model_path="/models/Kev-4B-Q4_K_M.gguf", build="b12767-a8ad690ca",
                 not_ready=0, calibrated=None, status=200, answer=None):  # fmt: skip
        self.model_path, self.build, self.not_ready, self.status = (
            model_path, build, not_ready, status,
        )  # fmt: skip
        self.calibrated = calibrated or (lambda payload: 0.7)
        #: The whole response body, when a test needs a malformed one.
        self.answer = answer
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
                if self.path == "/props":
                    return self._send(200, {"model_path": outer.model_path,
                                            "build_info": outer.build, "total_slots": 1})  # fmt: skip
                self._send(404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
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


def rt(url: str, gguf: Path, stop=None, device="gpu") -> judges.Runtime:
    return judges.Runtime(device, "q4_k_m", None, False, None, "llamacpp", url, gguf, stop)


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
    judge = judges._load_kev_llamacpp(rt(side.url, gguf), pin)
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
        ({"qwen35.decision.type": "laya"}, {}, "not a Kev decision model"),
        ({}, {"model_path": "/models/Kev-4B-Q8_0.gguf"}, "serves 'Kev-4B-Q8_0.gguf'"),
        ({}, {"build": "b12800-0000000"}, "pinned b12767"),
    ],
)
def test_load_refuses_a_mismatch(tmp_path, sidecar, override, sidecar_kw, match):
    gguf = kev_gguf(tmp_path, **override)
    side = sidecar(**sidecar_kw)
    with pytest.raises(judges.LoadError, match=match):
        judges._load_kev_llamacpp(rt(side.url, gguf), pin_of(gguf))


def test_load_refuses_another_file(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    pin = pin_of(gguf, gguf_sha256="0" * 64)
    with pytest.raises(judges.LoadError, match="sha256"):
        judges._load_kev_llamacpp(rt(sidecar().url, gguf), pin)
    other = write_gguf(tmp_path / "Kev-4B-Q8_0.gguf", {"qwen35.decision.type": "kev"})
    with pytest.raises(judges.LoadError, match="not the pinned"):
        judges._load_kev_llamacpp(rt(sidecar().url, other), pin_of(gguf))
    with pytest.raises(judges.LoadError, match="not a file"):
        judges._load_kev_llamacpp(rt(sidecar().url, tmp_path / "none.gguf"), pin_of(gguf))


def test_load_gives_up_on_a_sidecar_that_never_gets_ready(tmp_path, monkeypatch):
    gguf = kev_gguf(tmp_path)
    monkeypatch.setattr(judges, "LLAMACPP_READY_S", 0.0)
    with pytest.raises(judges.LoadError, match="not ready"):
        judges._load_kev_llamacpp(rt("http://127.0.0.1:9", gguf), pin_of(gguf))


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
    judge = judges._load_kev_llamacpp(rt(sidecar(answer=answer).url, gguf), pin_of(gguf))
    with pytest.raises(RuntimeError, match=match):
        judge.score(PAYLOAD)


def test_the_request_timeout_is_per_device_and_inside_the_stop_bound(tmp_path, sidecar):
    gguf = kev_gguf(tmp_path)
    for device, want in (("gpu", 60.0), ("cpu", 120.0)):
        judge = judges._load_kev_llamacpp(rt(sidecar().url, gguf, device=device), pin_of(gguf))
        assert judge.info["request_timeout_s"] == want
    # The home server's stop_grace_period (240 s) covers a request, 3 x 10 s of last posts
    # and a 10 s join (docs/ai/worker.md, "A stop sets one deadline").
    assert max(judges.LLAMACPP_REQUEST_S.values()) + 3 * 10 + 10 < 240


def test_a_stop_interrupts_the_hash_and_the_wait(tmp_path):
    gguf = kev_gguf(tmp_path)
    stop = threading.Event()
    stop.set()
    with pytest.raises(judges.LoadInterrupted, match="hashing"):
        judges._load_kev_llamacpp(rt("http://127.0.0.1:9", gguf, stop), pin_of(gguf))
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
    judge = judges._load_kev_llamacpp(rt(side.url, gguf), pin_of(gguf))
    side.status = 400
    with pytest.raises(RuntimeError, match="HTTP 400"):
        judge.score(PAYLOAD)
    with pytest.raises(ValueError):
        judge.score({"state": "x", "questions": {}})


# --- the pin and the configuration --------------------------------------------------------


def test_the_alternative_is_not_what_production_serves():
    alt = pins.pin_for("kev", "llamacpp")
    assert alt.backend == "llamacpp" and alt.temperature == 1.0
    # Its own version: the broker refuses it until the policy names it (an owner step).
    assert alt.model_version != policy.MODELS["kev"].model_version
    assert alt.code == pins.LLAMACPP_IMAGE and "@sha256:" in alt.code
    assert alt.model_version.startswith(f"kev-4b-Q4_K_M@{pins.KEV_GGUF_SHA256[:12]}+")
    assert pins.pin_for("kev") is pins.PINS["kev"]
    with pytest.raises(KeyError):
        pins.pin_for("pplx", "llamacpp")


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
    pplx = llamacpp_cfg()
    pplx["worker"]["model"] = "pplx"
    with pytest.raises(ConfigError, match="cannot serve 'pplx'"):
        parse(pplx)


def test_expect_version_is_the_backends():
    alt = pins.pin_for("kev", "llamacpp").model_version
    assert parse({**llamacpp_cfg(), "model": {"kev": {"expect_version": alt}}})
    with pytest.raises(ConfigError, match="not what this worker serves"):
        parse({**llamacpp_cfg(), "model": {"kev": {"expect_version":
                                                   pins.PINS["kev"].model_version}}})  # fmt: skip


def test_the_compose_example_parses():
    data = tomllib.loads((DEPLOY / "llamacpp-kev.toml").read_text())
    data["worker"].pop("token_file")
    data["worker"]["token"] = "example"
    cfg = parse(data)
    assert (cfg.backend, cfg.device, cfg.llamacpp_url) == (
        "llamacpp", "gpu", "http://kev-llamacpp:8080",
    )  # fmt: skip
    assert cfg.expect_versions == {"kev": pins.pin_for("kev", "llamacpp").model_version}
    # Its window is the CPU Kev worker's: it replaces it, never runs beside it.
    cpu = parse({**tomllib.loads((DEPLOY / "home-kev.toml").read_text()),
                 "worker": {**data["worker"]}})  # fmt: skip
    assert cfg.schedule.windows == cpu.schedule.windows


def test_the_sidecar_is_off_by_default_pinned_and_unreachable():
    text = (DEPLOY / "compose.yml").read_text()
    block = text[text.index("\n  kev-llamacpp:\n") : text.index("\nnetworks:")]
    assert "    profiles: [llamacpp]\n" in block
    assert f"    image: {pins.LLAMACPP_IMAGE}\n" in block
    assert "ports" not in block and "0.0.0.0:" not in block
    assert "    networks: [broker-only]\n" in block and "egress" not in block
    assert ":/models/Kev-4B-Q4_K_M.gguf:ro" in block
    for flag in ('- "512"', '- "4096"', '- "99"'):
        assert flag in block
    # Compose interpolates every service, profile or not: a required `${X:?}` here would stop
    # `docker compose up` for the running workers whenever X is unset.
    assert ":?" not in block.replace("${WEIGHTS_DIR:?", "")


# --- a whole session ----------------------------------------------------------------------


def test_a_session_on_the_sidecar_posts_raw_scores_under_the_alternative_version(
    tmp_path, sidecar, monkeypatch
):
    gguf = kev_gguf(tmp_path)
    pin = pin_of(gguf)
    monkeypatch.setitem(pins.ALTERNATIVES, ("kev", "llamacpp"), pin)
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


def test_the_production_broker_version_refuses_the_alternative(tmp_path, sidecar, monkeypatch):
    gguf = kev_gguf(tmp_path)
    monkeypatch.setitem(pins.ALTERNATIVES, ("kev", "llamacpp"), pin_of(gguf))
    with FakeBroker({"tok": ("amd-kev", ["kev"])}) as broker:  # the policy's versions
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
