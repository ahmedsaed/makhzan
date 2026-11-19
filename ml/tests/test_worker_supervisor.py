"""`outside_window = "wait"`: the supervisor that sleeps between windows and runs one session
per window.

Most tests run each window's session in-process (`InProcessSession`) so the fake clock and
the fake judge are shared with the supervisor, and days of windows pass in milliseconds.
The last ones fork for real (`ForkedSession`, what the image runs), against the fake broker
over HTTP, to show the model is loaded in the child and a SIGTERM reaches it.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from makhzan_ml.worker import __main__ as entry
from makhzan_ml.worker import run, supervisor
from makhzan_ml.worker.broker import Broker
from makhzan_ml.worker.config import parse
from test_worker_lifecycle import CAIRO, TOKEN, FakeClock, FakeJudges, config, pair

# A fork from a test process that runs the fake broker's threads: fine for these tests (the
# child only uses urllib); the image's supervisor forks with no other thread running.
pytestmark = pytest.mark.filterwarnings("ignore:This process .* is multi-threaded")


@pytest.fixture
def broker():
    from makhzan_ml.worker.fake_broker import FakeBroker

    with FakeBroker({TOKEN: ("home-kev", ["kev", "pplx"])}) as b:
        yield b


class Judges(FakeJudges):
    """Also records when (on the fake clock) each load and unload happened."""

    def __init__(self, clock: FakeClock, **kw):
        super().__init__(clock, **kw)
        self.events: list[tuple[str, datetime]] = []

    def __call__(self, key, rt):
        judge = super().__call__(key, rt)
        self.events.append(("load", self.clock.now()))
        inner = judge.close_fn

        def close():
            inner()
            self.events.append(("unload", self.clock.now()))

        judge.close_fn = close
        return judge


def build(broker, clock, fake, **schedule):
    sched = {"windows": ["01:00-05:00"], "outside_window": "wait", "on_empty": "wait"}
    sched.update(schedule)
    cfg = parse(config(broker.url, schedule=sched))

    def make_worker():
        client = Broker(cfg.broker_url, cfg.token, retry_max_s=30.0,
                        sleep=clock.advance, monotonic=lambda: clock.mono)  # fmt: skip
        return run.Worker(cfg, client, load_judge=fake, importable=lambda k: True, clock=clock)

    sup = supervisor.Supervisor(cfg, supervisor.InProcessSession(make_worker), clock=clock)
    return sup, cfg


def stop_after(sup, clock, sessions: int, hook=None):
    """Stop the supervisor in the first sleep after `sessions` sessions; `hook(seconds)` runs
    on every wait first."""
    original = clock.wait

    def wait(seconds, stop):
        if hook:
            hook(seconds)
        if sup.windows >= sessions and not sup.session.worker:
            sup.request_stop("SIGTERM")
        return original(seconds, stop)

    clock.wait = wait


def test_three_windows_load_only_inside_and_unload_after_each(broker, caplog):
    caplog.set_level(logging.INFO)
    clock = FakeClock(datetime(2026, 11, 17, 12, 0, tzinfo=CAIRO))
    fake = Judges(clock)
    sup, cfg = build(broker, clock, fake, poll_s=600)
    # Work arrives each afternoon; the window drains it, then polls until 05:00.
    loaded_while_asleep = []

    def hook(seconds):
        if sup.session.worker is None:  # asleep: the supervisor's own wait
            loaded_while_asleep.append(len(fake.loads) - len(fake.unloads))
            now = clock.now()
            arrives = now.hour == 12 or (now.hour, now.minute) == (5, 0)
            if arrives and sup.windows < 3:
                broker.add_job("kev", pair(len(broker.jobs)))

    broker.add_job("kev", pair(0))
    stop_after(sup, clock, 3, hook)
    assert sup.run() == run.EXIT_OK  # stopped while asleep

    assert sup.windows == 3 and sup.codes == [0, 0, 0]
    assert fake.loads == ["kev"] * 3 and fake.unloads == ["kev"] * 3
    window = cfg.schedule.windows[0]
    for kind, at in fake.events:
        if kind == "load":
            assert window.contains(at.time()), f"loaded at {at}, outside the window"
        else:  # by the window's end at the latest (the graceful stop runs at 05:00)
            assert window.contains(at.time()) or at.time() == window.end, f"unloaded at {at}"
    # Load, unload, load, unload ...: never two loads without an unload between.
    assert [k for k, _ in fake.events] == ["load", "unload"] * 3
    assert set(loaded_while_asleep) == {0}  # nothing held while sleeping
    # One session per window, each ended once at the broker.
    assert len(broker.sessions) == 3
    assert all(s["end_reason"] for s in broker.sessions.values())
    assert all(j.status == "done" for j in broker.jobs.values())
    # The days: 17th 01:00 is past at noon, so the first window is the 18th.
    starts = sorted({at.date() for _, at in fake.events})
    assert [d.day for d in starts] == [18, 19, 20]
    text = caplog.text
    assert "sleeping until Wed 01:00 (Africa/Cairo)" in text  # from Tuesday noon
    assert text.count("window open") == 3
    assert text.count("window closed; model unloaded") == 3


def test_sleep_messages_name_the_time_and_zone(broker, caplog):
    caplog.set_level(logging.INFO)
    clock = FakeClock(datetime(2026, 11, 17, 0, 10, tzinfo=CAIRO))  # same day: HH:MM only
    sup, _ = build(broker, clock, Judges(clock))
    stop_after(sup, clock, 1)
    sup.run()
    assert "sleeping until 01:00 (Africa/Cairo)" in caplog.text
    # After the 17th's window, the next is tomorrow: the day is named.
    assert "sleeping until Wed 01:00 (Africa/Cairo)" in caplog.text


def test_sleeps_are_chunked_and_land_on_the_window_start(broker):
    clock = FakeClock(datetime(2026, 11, 17, 12, 0, tzinfo=CAIRO))
    sup, _ = build(broker, clock, Judges(clock))
    starts = []
    original = sup.session.run

    def session_run():
        starts.append(clock.now())
        return original()

    sup.session.run = session_run
    stop_after(sup, clock, 1)
    sup.run()
    assert starts == [datetime(2026, 11, 18, 1, 0, tzinfo=CAIRO)]
    assert max(clock.waits) <= supervisor.SLEEP_CHUNK_S


def test_on_empty_exit_ends_the_window_early_and_sleeps_until_the_next(broker, caplog):
    caplog.set_level(logging.INFO)
    clock = FakeClock(datetime(2026, 11, 17, 0, 59, tzinfo=CAIRO))
    fake = Judges(clock)
    sup, _ = build(broker, clock, fake, on_empty="exit")
    broker.add_job("kev", pair(1))
    starts = []
    original = sup.session.run

    def session_run():
        starts.append(clock.now())
        return original()

    sup.session.run = session_run
    stop_after(sup, clock, 2)
    assert sup.run() == run.EXIT_OK
    # One session per window, not one per poll: the second window is the next day's.
    assert [s.day for s in starts] == [17, 18]
    assert all(s.hour == 1 and s.minute == 0 for s in starts)
    assert fake.loads == ["kev"]  # the second night's queue was empty: nothing loaded
    assert [s["end_reason"] for s in broker.sessions.values()] == ["empty", "empty"]
    assert "session ended before the window's end" in caplog.text


def test_touching_windows_are_one_run_and_the_next_is_after_both(broker):
    clock = FakeClock(datetime(2026, 11, 17, 0, 0, tzinfo=CAIRO))
    sup, _ = build(broker, clock, Judges(clock), windows=["01:00-03:00", "03:00-05:00"],
                   on_empty="exit")  # fmt: skip
    starts = []
    original = sup.session.run

    def session_run():
        starts.append(clock.now())
        return original()

    sup.session.run = session_run
    stop_after(sup, clock, 2)
    sup.run()
    # Ended early at 01:00 (empty): the 03:00 window is the same run, so not reopened.
    assert [(s.day, s.hour) for s in starts] == [(17, 1), (18, 1)]


def test_a_stop_during_a_session_is_graceful_and_ends_the_supervisor(broker):
    clock = FakeClock(datetime(2026, 11, 17, 1, 0, tzinfo=CAIRO))
    fake = Judges(clock)
    sup, _ = build(broker, clock, fake)
    jobs = [broker.add_job("kev", pair(n)) for n in range(3)]
    fake.on_score = lambda i: i == 1 and sup.request_stop("SIGTERM")
    assert sup.run() == run.EXIT_OK
    assert sup.windows == 1
    assert fake.loads == fake.unloads == ["kev"]
    assert jobs[0].scores and all(j.attempts == 0 for j in jobs)  # nothing charged
    assert [s["end_reason"] for s in broker.sessions.values()] == ["released"]


def test_an_unreachable_broker_is_retried_inside_the_window(broker):
    clock = FakeClock(datetime(2026, 11, 17, 1, 0, tzinfo=CAIRO))
    sup, _ = build(broker, clock, Judges(clock), poll_s=600)
    codes = iter([run.EXIT_UNREACHABLE, run.EXIT_UNREACHABLE])
    starts = []

    def session_run():
        starts.append(clock.now())
        return next(codes, run.EXIT_OK)

    sup.session.run = session_run
    stop_after(sup, clock, 3)
    sup.run()
    assert [s.strftime("%H:%M") for s in starts[:3]] == ["01:00", "01:10", "01:20"]


@pytest.mark.parametrize("code", [run.EXIT_CONFIG, run.EXIT_VERSION, run.EXIT_AUTH, -9])
def test_a_failed_session_waits_for_the_next_window(broker, caplog, code):
    clock = FakeClock(datetime(2026, 11, 17, 1, 0, tzinfo=CAIRO))
    sup, _ = build(broker, clock, Judges(clock))
    starts = []

    def session_run():
        starts.append(clock.now())
        return code

    sup.session.run = session_run
    stop_after(sup, clock, 2)
    assert sup.run() == run.EXIT_OK
    assert [(s.day, s.hour) for s in starts] == [(17, 1), (18, 1)]
    assert ("killed by SIGKILL" if code < 0 else f"failed (exit {code})") in caplog.text


def test_always_with_wait_restarts_a_finished_session_after_poll_s(broker):
    clock = FakeClock(datetime(2026, 11, 17, 1, 0, tzinfo=CAIRO))
    sup, _ = build(broker, clock, Judges(clock), windows="always", on_empty="exit", poll_s=300)
    stop_after(sup, clock, 3)
    sup.run()
    assert sup.windows == 3 and clock.waits[:2] == [300, 300]


def test_sigterm_while_asleep_exits_at_once_with_0(broker):
    """Real time, a real signal: the window is hours away."""
    now = datetime.now(UTC)
    start, end = now + timedelta(hours=2), now + timedelta(hours=3)
    cfg = parse(config(broker.url, schedule={
        "windows": [f"{start:%H:%M}-{end:%H:%M}"], "timezone": "UTC", "outside_window": "wait",
    }))  # fmt: skip
    ran = []
    sup = supervisor.Supervisor(cfg, supervisor.InProcessSession(lambda: ran.append(1)))
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        sup.install_signal_handlers()
        threading.Timer(0.2, os.kill, args=(os.getpid(), signal.SIGTERM)).start()
        t0 = time.monotonic()
        assert sup.run() == 0
        assert time.monotonic() - t0 < 2.0
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    assert ran == [] and broker.calls == []  # nothing loaded, nothing sent


# --- the real thing: a forked child per window ----------------------------------------------


class PidJudges(FakeJudges):
    """Writes the pid that loaded and unloaded the model to a file: the child's, not ours."""

    def __init__(self, path, seconds: float = 0.0):
        super().__init__(None)
        self.path, self.delay = path, seconds

    def __call__(self, key, rt):
        with open(self.path, "a") as f:
            f.write(f"load {os.getpid()}\n")
        judge = super().__call__(key, rt)

        def score(payload):
            time.sleep(self.delay)
            return 0.9, {}

        judge.score_fn = score

        def close():
            with open(self.path, "a") as f:
                f.write(f"unload {os.getpid()}\n")

        judge.close_fn = close
        return judge


def forked(broker, tmp_path, *, seconds=0.0, **schedule):
    sched = {"windows": "always", "outside_window": "wait", "on_empty": "exit"}
    sched.update(schedule)
    cfg = parse(config(broker.url, schedule=sched))
    fake = PidJudges(tmp_path / "pids", seconds)

    def make_worker():
        client = Broker(cfg.broker_url, cfg.token, retry_max_s=5.0)
        return run.Worker(cfg, client, load_judge=fake, importable=lambda k: True)

    return supervisor.Supervisor(cfg, supervisor.ForkedSession(make_worker)), fake


def test_each_window_runs_in_a_child_that_loads_and_frees_the_model(broker, tmp_path):
    jobs = [broker.add_job("kev", pair(n)) for n in range(2)]
    sup, fake = forked(broker, tmp_path)
    original = sup.session.run

    def once():
        code = original()
        sup.request_stop("test done")
        return code

    sup.session.run = once
    assert sup.run() == run.EXIT_OK
    assert all(j.status == "done" for j in jobs)
    assert [s["end_reason"] for s in broker.sessions.values()] == ["empty"]
    lines = (tmp_path / "pids").read_text().split()
    assert lines[0::2] == ["load", "unload"]
    child = int(lines[1])
    assert child != os.getpid() and int(lines[3]) == child
    assert sup.session.pid is None  # reaped


def test_sigterm_during_a_window_is_forwarded_to_the_child(broker, tmp_path):
    jobs = [broker.add_job("kev", pair(n)) for n in range(5)]
    sup, _ = forked(broker, tmp_path, seconds=0.3, on_empty="wait")
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        sup.install_signal_handlers()
        threading.Timer(1.0, os.kill, args=(os.getpid(), signal.SIGTERM)).start()
        t0 = time.monotonic()
        assert sup.run() == run.EXIT_OK  # the child's own graceful exit code
        assert time.monotonic() - t0 < 10
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    assert sup.windows == 1
    done = [j for j in jobs if j.status == "done"]
    assert 0 < len(done) < len(jobs)
    assert all(j.attempts == 0 for j in jobs)  # the rest went back gracefully
    assert [s["end_reason"] for s in broker.sessions.values()] == ["released"]
    assert (tmp_path / "pids").read_text().split()[0::2] == ["load", "unload"]


def test_a_child_killed_by_a_signal_is_reported_and_waited_out(broker, tmp_path):
    sup, _ = forked(broker, tmp_path)

    class Dies:
        pid = None

        def run(self):
            pid = os.fork()
            if pid == 0:
                os.kill(os.getpid(), signal.SIGKILL)
            _, status = os.waitpid(pid, 0)
            sup.request_stop("test done")
            return os.waitstatus_to_exitcode(status)

        def stop(self, reason):
            pass

    sup.session = Dies()
    sup.run()
    assert sup.codes == [-signal.SIGKILL]


# --- the entrypoint picks the mode ----------------------------------------------------------


@pytest.mark.parametrize("mode", ["exit", "wait"])
def test_the_entrypoint_runs_a_supervisor_only_for_wait(tmp_path, monkeypatch, mode):
    path = tmp_path / "w.toml"
    path.write_text(
        '[worker]\nname = "home-kev"\nbroker_url = "http://127.0.0.1:9/ai/v1"\n'
        'token = "t"\nmodel = "kev"\n'
        f'[schedule]\nwindows = "always"\ntimezone = "UTC"\noutside_window = "{mode}"\n'
    )
    seen = []

    class FakeWorker:
        def __init__(self, cfg, image=None):
            seen.append(("worker", image))

        def install_signal_handlers(self):
            pass

        def run(self):
            return 0

    class FakeSupervisor(FakeWorker):
        def __init__(self, cfg, image=None):
            seen.append(("supervisor", image))

    monkeypatch.setattr(run, "Worker", FakeWorker)
    monkeypatch.setattr(supervisor, "Supervisor", FakeSupervisor)
    monkeypatch.setenv("MAKHZAN_IMAGE_REVISION", "abc123")
    monkeypatch.setenv("MAKHZAN_IMAGE_REPO", "ghcr.io/example/kev-worker-cpu")
    monkeypatch.delenv("MAKHZAN_IMAGE", raising=False)
    assert entry.main(["--config", str(path)]) == 0
    kind = "worker" if mode == "exit" else "supervisor"
    assert seen == [(kind, "ghcr.io/example/kev-worker-cpu:sha-abc123")]


def test_the_supervisor_imports_no_model_code():
    """The parent forks each window's child: it must hold no torch (nor any thread) itself."""
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import sys, threading, makhzan_ml.worker.__main__, makhzan_ml.worker.supervisor; "
        "assert 'torch' not in sys.modules, 'torch imported'; "
        "assert threading.active_count() == 1, threading.enumerate()"
    )
    ml = Path(supervisor.__file__).resolve().parents[2]
    done = subprocess.run([sys.executable, "-c", code], cwd=ml, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ml)})  # fmt: skip
    assert done.returncode == 0, done.stderr
