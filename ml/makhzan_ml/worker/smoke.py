"""`python -m makhzan_ml.worker.smoke --model kev|pplx`: check a built worker image, no weights.

What CI runs on each CPU worker image before it is pushed (.github/workflows/ai-worker-images.yml),
and what can be run on the home server before a first real session. It loads no model and needs
no network beyond loopback (run it with `--network none`):

1. the image is CPU-only: torch sees no CUDA device and flash-linear-attention is not installed;
2. the image holds the model's code (`judges.importable`) and, for Kev, records the Kev code
   commit the worker is pinned to (`MAKHZAN_KEV_COMMIT`, from the base image);
3. the image holds no model weights: the Hub cache is empty and no weight-sized file is on disk;
4. the entrypoint's own `--check` accepts a configuration for the model;
5. a whole worker session runs against `fake_broker` with a fake judge: hello, a lease, the
   payloads scored in order, the results posted, the empty lease ending the session;
6. the same through the supervisor (`outside_window = "wait"`): the session runs in a forked
   child, which loads and frees the model, under the container's restrictions;
7. the broker proxy (`python -m makhzan_ml.worker.proxy`) forwards to a local listener, sends
   a request naming another host to that same listener, and refuses a name as its target;
8. with `--expect-revision`, the image records that commit (`MAKHZAN_IMAGE_REVISION`), which
   the worker reports at hello.

It says nothing about the model's scores: parity with the validated scores needs the weights and
is the supervised first run (docs/ai/worker.md, "Parity with the validated scores").
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from makhzan_ml.worker import judges, run
from makhzan_ml.worker.broker import Broker
from makhzan_ml.worker.config import parse
from makhzan_ml.worker.fake_broker import FakeBroker
from makhzan_ml.worker.pins import PINS

log = logging.getLogger("makhzan_ml.worker.smoke")

TOKEN = "smoke-token"
# Files named like weights, at a size no source or config file reaches. torch's own wheel ships
# no such file; a checkpoint shard is gigabytes.
WEIGHT_SUFFIXES = (".safetensors", ".gguf", ".pt", ".pth", ".bin", ".ckpt", ".onnx")
WEIGHT_MIN_BYTES = 1 << 20
SKIP_DIRS = ("/proc", "/sys", "/dev", "/tmp", "/run")


def check_cpu_only() -> None:
    import torch

    assert not torch.cuda.is_available(), "torch sees a CUDA device"
    assert importlib.util.find_spec("fla") is None, "flash-linear-attention (fla) is installed"
    log.info("cpu only: torch %s, cuda unavailable, no fla", torch.__version__)


def check_model_code(model: str) -> None:
    assert judges.importable(model), f"this image cannot load {model!r}"
    if model == "kev":
        got = os.environ.get("MAKHZAN_KEV_COMMIT")
        assert got == PINS["kev"].code, f"MAKHZAN_KEV_COMMIT {got!r}, pinned {PINS['kev'].code}"
        log.info("model code: kev importable, Kev commit %s recorded", got)
    else:
        log.info("model code: %s importable", model)


def weight_files(root: str = "/") -> list[str]:
    found = []
    for top, dirs, files in os.walk(root):
        if top in SKIP_DIRS:
            dirs[:] = []
            continue
        for name in files:
            if not name.endswith(WEIGHT_SUFFIXES):
                continue
            path = os.path.join(top, name)
            try:
                if os.lstat(path).st_size >= WEIGHT_MIN_BYTES:
                    found.append(path)
            except OSError:
                pass
    return found


def check_no_weights() -> None:
    for d in judges.hub_cache_dirs():
        if d.is_dir():
            held = [p for p in d.rglob("*") if p.is_file()]
            assert not held, f"the Hub cache {d} holds {len(held)} files, e.g. {held[0]}"
    found = weight_files()
    assert not found, f"weight files in the image: {found[:5]}"
    log.info("no weights: Hub cache empty, no weight-sized file on disk")


def config(model: str, url: str) -> dict:
    return {
        "worker": {"name": f"smoke-{model}", "broker_url": url, "token": TOKEN, "model": model},
        "compute": {"threads": 1, "nice": 0},
        "schedule": {"windows": "always", "timezone": "UTC", "on_empty": "exit"},
        "leases": {"max_jobs": 2, "lease_s": 900, "heartbeat_s": 60},
    }


def check_entrypoint(model: str) -> None:
    """`python -m makhzan_ml.worker --config ... --check`, the image's ENTRYPOINT plus --check."""
    text = (
        "[worker]\n"
        f'name = "smoke-{model}"\nbroker_url = "http://127.0.0.1:9"\n'
        f'token = "{TOKEN}"\nmodel = "{model}"\n'
        '[schedule]\nwindows = "always"\ntimezone = "UTC"\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "worker.toml"
        path.write_text(text)
        cmd = [sys.executable, "-m", "makhzan_ml.worker", "--config", str(path), "--check"]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert done.returncode == run.EXIT_OK, f"--check exited {done.returncode}: {done.stderr}"
    log.info("entrypoint --check: %s", done.stderr.strip().splitlines()[-1])


class FakeJudge:
    def __init__(self) -> None:
        self.scored: list[dict] = []
        self.loads = self.unloads = 0

    def __call__(self, key: str, rt: judges.Runtime) -> judges.Judge:
        self.loads += 1

        def score(payload: dict):
            self.scored.append(payload)
            return 0.9, ({"margin": 1.5} if key == "pplx" else {})

        def unload() -> None:
            self.unloads += 1

        return judges.Judge(key, score, {"device": rt.device}, unload)


def payload(text: str) -> dict:
    return {
        "state": f"[LISTING A]\nTitle: {text}\n\n[LISTING B]\nTitle: {text} (other shop)",
        "questions": {"same": {"type": "noul", "instructions": "Could a buyer ...?"}},
    }


def check_session(model: str, importable=judges.importable) -> None:
    """A whole session; `importable` is the worker's own check (a test outside an image stubs
    it, since the host holds neither model's code)."""
    with FakeBroker({TOKEN: (f"smoke-{model}", [model])}) as broker:
        jobs = [
            broker.add_job(model, {"ab": payload(f"part {n} ab"), "ba": payload(f"part {n} ba")})
            for n in range(3)
        ]
        cfg = parse(config(model, broker.url))
        fake = FakeJudge()
        client = Broker(cfg.broker_url, cfg.token, retry_max_s=5.0)
        worker = run.Worker(cfg, client, load_judge=fake, importable=importable, image="smoke")
        code = worker.run()
        assert code == run.EXIT_OK, f"the session exited {code}"
        sent = [r["payload"] for j in jobs for r in j.requests]
        assert fake.scored == sent, "the payloads scored are not the ones sent, in order"
        assert all(j.status == "done" for j in broker.jobs.values()), "a job is not done"
        assert (fake.loads, fake.unloads) == (1, 1), "the model was not loaded once and freed"
        ends = [s["end_reason"] for s in broker.sessions.values()]
        assert ends == ["empty"], f"sessions ended {ends}"
    log.info("session: %d jobs scored against the fake broker, ended once", len(jobs))


def check_supervisor(model: str, importable=judges.importable) -> None:
    """One window through the supervisor: a forked child runs the session and exits."""
    from makhzan_ml.worker import supervisor

    with FakeBroker({TOKEN: (f"smoke-{model}", [model])}) as broker:
        jobs = [broker.add_job(model, {"ab": payload(f"sup {n} ab")}) for n in range(2)]
        data = config(model, broker.url)
        data["schedule"]["outside_window"] = "wait"
        cfg = parse(data)
        with tempfile.TemporaryDirectory() as tmp:
            marks = Path(tmp) / "pids"

            class ChildJudge(FakeJudge):
                def __call__(self, key, rt):
                    marks.open("a").write(f"load {os.getpid()}\n")
                    judge = super().__call__(key, rt)
                    judge.close_fn = lambda: marks.open("a").write(f"unload {os.getpid()}\n")
                    return judge

            fake = ChildJudge()

            def make_worker():
                client = Broker(cfg.broker_url, cfg.token, retry_max_s=5.0)
                return run.Worker(cfg, client, load_judge=fake, importable=importable)

            sup = supervisor.Supervisor(cfg, supervisor.ForkedSession(make_worker))
            inner = sup.session.run

            def once() -> int:
                code = inner()
                sup.request_stop("smoke done")
                return code

            sup.session.run = once
            code = sup.run()
            lines = marks.read_text().split() if marks.exists() else []
        assert code == run.EXIT_OK, f"the supervised session exited {code}"
        assert all(j.status == "done" for j in jobs), "a job is not done"
        assert lines[0::2] == ["load", "unload"], f"load/unload in the child: {lines}"
        assert int(lines[1]) != os.getpid(), "the model was loaded in the supervisor itself"
    log.info("supervisor: one window in a forked child, model loaded and freed there")


def check_proxy() -> None:
    """The proxy, as its own process, over loopback (no network needed)."""
    import socket
    import threading
    import time

    received: list[bytes] = []
    target = socket.create_server(("127.0.0.1", 0))
    tport = target.getsockname()[1]

    def serve() -> None:
        while True:
            try:
                conn, _ = target.accept()
            except OSError:
                return
            with conn:
                data = b""
                while chunk := conn.recv(65536):
                    data += chunk
                received.append(data)
                conn.sendall(b"broker:" + data)

    threading.Thread(target=serve, daemon=True).start()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        pport = s.getsockname()[1]
    cmd = [sys.executable, "-m", "makhzan_ml.worker.proxy", "--listen", f"127.0.0.1:{pport}",
           "--to", f"127.0.0.1:{tport}"]  # fmt: skip
    # The package's own root on the path, as the image's PYTHONPATH has it (and a test has not).
    root = str(Path(__file__).resolve().parents[2])
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, [root, os.environ.get("PYTHONPATH")])),
    }
    proc = subprocess.Popen(cmd, env=env)

    def exchange(data: bytes) -> bytes:
        deadline = time.monotonic() + 20
        while True:
            try:
                c = socket.create_connection(("127.0.0.1", pport), timeout=5)
                break
            except OSError:
                assert time.monotonic() < deadline, "the proxy never listened"
                time.sleep(0.1)
        with c:
            c.sendall(data)
            c.shutdown(socket.SHUT_WR)
            out = b""
            while chunk := c.recv(65536):
                out += chunk
        return out

    try:
        hello = b"POST /ai/v1/hello HTTP/1.1\r\nHost: broker-proxy\r\n\r\n{}"
        assert exchange(hello) == b"broker:" + hello, "the proxy did not forward the bytes"
        other = b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n"
        assert exchange(other) == b"broker:" + other, "a CONNECT went somewhere else"
        assert received == [hello, other], "the target did not get exactly what was sent"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        target.close()
    bad = subprocess.run(
        [sys.executable, "-m", "makhzan_ml.worker.proxy", "--listen", "127.0.0.1:8100",
         "--to", "broker.example.test:8100"],
        capture_output=True, text=True, timeout=60, env=env,
    )  # fmt: skip
    assert bad.returncode == 2 and "IP address" in bad.stderr, "a name was accepted as target"
    log.info("proxy: forwards to its one target, CONNECT included; a name as target refused")


def check_revision(expected: str) -> None:
    got = os.environ.get("MAKHZAN_IMAGE_REVISION")
    assert got == expected, f"MAKHZAN_IMAGE_REVISION {got!r}, expected {expected!r}"
    log.info("revision: %s, reported at hello as %s", got, run.image_reference())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m makhzan_ml.worker.smoke", description=__doc__)
    ap.add_argument("--model", required=True, choices=sorted(PINS))
    ap.add_argument("--expect-revision", help="the commit the image must record")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )
    try:
        check_cpu_only()
        check_model_code(args.model)
        check_no_weights()
        check_entrypoint(args.model)
        check_session(args.model)
        check_supervisor(args.model)
        check_proxy()
        if args.expect_revision:
            check_revision(args.expect_revision)
    except AssertionError as e:
        log.error("smoke test failed: %s", e)
        return 1
    log.info("smoke test passed for %s", args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
