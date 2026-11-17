"""A worker session against the contract-following fake broker.

The judge is fake (it records what it is given and returns a fixed score) and so is the
clock (scoring and waiting move it), so windows, crossing midnight included, run in
milliseconds. The broker client is the real one, over real HTTP on 127.0.0.1.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from makhzan_ml.worker import judges, run
from makhzan_ml.worker.broker import Broker
from makhzan_ml.worker.config import parse
from makhzan_ml.worker.fake_broker import FakeBroker
from makhzan_ml.worker.pins import PINS

CAIRO = ZoneInfo("Africa/Cairo")
TOKEN = "test-token"


class FakeClock:
    def __init__(self, start: datetime):
        self.t = start
        self.mono = 0.0
        self.waits: list[float] = []

    def now(self) -> datetime:
        return self.t

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)
        self.mono += seconds

    def wait(self, seconds: float, stop: threading.Event) -> bool:
        if stop.is_set():
            return True
        self.waits.append(seconds)
        self.advance(seconds)
        return stop.is_set()


class FakeJudges:
    """`load_judge` for the worker: records loads and every payload scored, in order."""

    def __init__(self, clock: FakeClock | None = None, seconds: float = 10.0, p: float = 0.9):
        self.clock, self.seconds, self.p = clock, seconds, p
        self.loads: list[str] = []
        self.unloads: list[str] = []
        self.scored: list[tuple[str, dict]] = []
        self.calls = 0
        self.on_score = None  # called with the call index before scoring
        self.fail_load: Exception | None = None

    def __call__(self, key: str, rt: judges.Runtime) -> judges.Judge:
        if self.fail_load:
            raise self.fail_load
        self.loads.append(key)

        def score(payload: dict):
            i, self.calls = self.calls, self.calls + 1
            if self.on_score:
                self.on_score(i)
            self.scored.append((key, payload))
            if self.clock:
                self.clock.advance(self.seconds)
            return self.p, {"margin": 1.5} if key == "pplx" else {}

        return judges.Judge(key, score, {"device": rt.device}, lambda: self.unloads.append(key))


def payload(text: str) -> dict:
    return {
        "state": f"[LISTING A]\nTitle: {text}\n\n[LISTING B]\nTitle: {text} (other shop)",
        "questions": {"same": {"type": "noul", "instructions": "Could a buyer ...?"}},
    }


def pair(n: int) -> dict:
    return {"ab": payload(f"part {n} ab"), "ba": payload(f"part {n} ba")}


def config(url: str, **sections) -> dict:
    data = {
        "worker": {"name": "home-kev", "broker_url": url, "token": TOKEN, "models": ["kev"]},
        "compute": {"threads": 6, "nice": 0},
        "schedule": {"windows": "always", "on_empty": "exit"},
        "leases": {"max_jobs": 2, "lease_s": 900, "heartbeat_s": 60, "seconds_per_request": 10},
    }
    for name, values in sections.items():
        data.setdefault(name, {}).update(values)
    return data


@pytest.fixture
def broker():
    with FakeBroker({TOKEN: ("home-kev", ["kev", "pplx"])}) as b:
        yield b


@pytest.fixture
def sleeps():
    return []


def make_worker(broker, sleeps, *, clock=None, fake=None, retry_max_s=30.0, **sections):
    cfg = parse(config(broker.url, **sections))
    clock = clock or FakeClock(datetime(2026, 11, 17, 1, 0, tzinfo=CAIRO))
    fake = fake or FakeJudges(clock)
    elapsed = [0.0]

    def sleep(seconds):
        sleeps.append(seconds)
        elapsed[0] += seconds

    client = Broker(cfg.broker_url, cfg.token, retry_max_s=retry_max_s, sleep=sleep,
                    monotonic=lambda: elapsed[0])  # fmt: skip
    worker = run.Worker(cfg, client, load_judge=fake, clock=clock, image="sha256:test")
    return worker, fake, clock


# --- the whole session ---------------------------------------------------------------------


def test_a_session_scores_every_job_in_order_and_ends_with_a_release(broker, sleeps):
    jobs = [broker.add_job("kev", pair(n)) for n in range(3)]
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK

    hello = broker.bodies("/hello")[0]
    assert hello["worker"] == "home-kev"
    assert hello["models"] == {"kev": {"model_version": PINS["kev"].model_version,
                                       "weights_revision": PINS["kev"].weights_revision}}  # fmt: skip
    assert (hello["device"], hello["dtype"], hello["threads"]) == ("cpu", "fp32", 6)
    assert hello["image"] == "sha256:test"
    assert hello["config"]["window"] == "always"

    assert fake.loads == ["kev"] and fake.unloads == ["kev"]  # loaded once, freed at the end
    # Exactly the payloads the broker sent, one per call, in the order it sent them.
    sent = [r["payload"] for j in jobs for r in j.requests]
    assert [p for _, p in fake.scored] == sent
    assert all(j.status == "done" for j in broker.jobs.values())
    for j in jobs:
        assert set(j.scores) == {"ab", "ba"}
        assert j.scores["ab"]["device"] == "cpu" and j.scores["ab"]["dtype"] == "fp32"

    leases = broker.bodies("/lease")
    assert leases[0]["max_jobs"] == 2 and leases[0]["model"] == "kev"
    assert leases[0]["model_version"] == PINS["kev"].model_version
    assert leases[1]["seconds_per_request"] == 10  # measured by now
    assert len(broker.bodies("/results")) == 3  # one POST per job
    assert broker.paths()[-1] == "/release"
    assert broker.bodies("/release")[-1] == {"session": hello and broker.bodies("/release")[-1]
                                             ["session"], "lease_id": None, "job_ids": [],
                                             "reason": "graceful"}  # fmt: skip
    assert [s["ended"] for s in broker.sessions.values()] == ["graceful"]
    assert sleeps == []


def test_a_job_carrying_one_order_is_scored_as_sent(broker, sleeps):
    job = broker.add_job("kev", pair(1))
    job.scores["ab"] = {"p": 0.5}  # scored earlier: the lease carries "ba" only
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK
    assert [p for _, p in fake.scored] == [job.requests[1]["payload"]]
    assert job.status == "done"


def test_an_empty_queue_loads_nothing_and_exits(broker, sleeps):
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK
    assert fake.loads == []
    assert broker.paths() == ["/hello", "/lease", "/release"]


def test_on_empty_wait_polls_until_the_window_ends(broker, sleeps):
    clock = FakeClock(datetime(2026, 11, 17, 3, 55, tzinfo=CAIRO))
    worker, fake, clock = make_worker(
        broker,
        sleeps,
        clock=clock,
        schedule={"windows": ["00:30-04:30"], "on_empty": "wait", "poll_s": 600},
    )
    assert worker.run() == run.EXIT_OK
    assert fake.loads == []
    assert clock.waits == [600, 600, 600, 300]  # the last capped at the window's end
    assert broker.paths().count("/lease") == 4
    assert clock.now() == datetime(2026, 11, 17, 4, 30, tzinfo=CAIRO)


def test_on_empty_wait_picks_up_work_that_arrives(broker, sleeps):
    clock = FakeClock(datetime(2026, 11, 17, 1, 0, tzinfo=CAIRO))
    worker, fake, clock = make_worker(
        broker, sleeps, clock=clock,
        schedule={"windows": ["00:30-04:30"], "on_empty": "wait", "poll_s": 600},
    )  # fmt: skip
    original = clock.wait

    def wait(seconds, stop):
        if not broker.jobs:
            broker.add_job("kev", pair(1))
        return original(seconds, stop)

    clock.wait = wait
    assert worker.run() == run.EXIT_OK
    assert fake.loads == ["kev"]
    assert all(j.status == "done" for j in broker.jobs.values())


def test_outside_every_window_nothing_is_sent(broker, sleeps):
    clock = FakeClock(datetime(2026, 11, 17, 12, 0, tzinfo=CAIRO))
    worker, fake, _ = make_worker(broker, sleeps, clock=clock,
                                  schedule={"windows": ["00:30-04:30"]})  # fmt: skip
    assert worker.run() == run.EXIT_OK
    assert broker.calls == [] and fake.loads == []


# --- stopping ------------------------------------------------------------------------------


def test_the_window_closing_across_midnight_releases_the_rest_gracefully(broker, sleeps):
    jobs = [broker.add_job("kev", pair(n)) for n in range(4)]
    clock = FakeClock(datetime(2026, 11, 17, 23, 50, tzinfo=CAIRO))
    fake = FakeJudges(clock, seconds=300)  # five minutes a request
    worker, fake, clock = make_worker(
        broker, sleeps, clock=clock, fake=fake,
        schedule={"windows": ["23:00-00:10"]}, leases={"max_jobs": 4, "seconds_per_request": 60},
    )  # fmt: skip
    assert worker.run() == run.EXIT_OK
    # The lease was sized on the 60 s estimate, so it holds all four jobs. Measured at 300 s,
    # requests run 23:50 -> 23:55 -> 00:00 -> 00:05 -> 00:10; a fifth would not fit and is
    # never started.
    assert len(fake.scored) == 4
    assert clock.now() == datetime(2026, 11, 18, 0, 10, tzinfo=CAIRO)
    assert set(jobs[0].scores) == {"ab", "ba"} and set(jobs[1].scores) == {"ab", "ba"}
    released = [b for b in broker.bodies("/release") if b["job_ids"]]
    assert len(released) == 1 and released[0]["reason"] == "graceful"
    assert released[0]["job_ids"] == [jobs[2].job_id, jobs[3].job_id]
    assert all(j.status == "queued" and j.attempts == 0 for j in jobs[2:])
    # The graceful release with jobs already told the broker the session ended.
    assert broker.paths()[-1] == "/release"


def test_a_half_scored_job_submits_its_finished_order_then_releases(broker, sleeps):
    job = broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)
    fake.on_score = lambda i: i == 0 and worker.request_stop("SIGTERM")
    assert worker.run() == run.EXIT_OK
    assert set(job.scores) == {"ab"}  # the request in flight finished and was kept
    assert job.status == "queued" and job.attempts == 0
    assert broker.bodies("/release")[-1]["job_ids"] == [job.job_id]
    assert broker.bodies("/release")[-1]["reason"] == "graceful"


def test_sigterm_stops_after_the_request_in_flight(broker, sleeps):
    jobs = [broker.add_job("kev", pair(n)) for n in range(2)]
    worker, fake, _ = make_worker(broker, sleeps)
    worker.install_signal_handlers()
    try:
        fake.on_score = lambda i: i == 1 and os.kill(os.getpid(), signal.SIGTERM)
        assert worker.run() == run.EXIT_OK
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.default_int_handler)
    assert worker.stop_reason == "SIGTERM"
    assert len(fake.scored) == 2 and set(jobs[0].scores) == {"ab", "ba"}
    assert jobs[1].status == "queued" and jobs[1].attempts == 0


def test_a_request_that_would_overrun_the_window_is_not_started(broker, sleeps):
    broker.add_job("kev", pair(1))
    clock = FakeClock(datetime(2026, 11, 17, 4, 29, tzinfo=CAIRO))
    worker, fake, _ = make_worker(broker, sleeps, clock=clock,
                                  schedule={"windows": ["00:30-04:30"]},
                                  leases={"seconds_per_request": 90})  # fmt: skip
    assert worker.run() == run.EXIT_OK
    assert fake.scored == [] and "/lease" not in broker.paths()


# --- retries -------------------------------------------------------------------------------


def test_network_failures_are_retried_with_backoff_and_nothing_is_lost(broker, sleeps):
    job = broker.add_job("kev", pair(1))
    broker.fail("/results", times=2)  # connection dropped, twice
    broker.fail("/lease", times=1, status=503)
    worker, _, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK
    assert set(job.scores) == {"ab", "ba"} and job.status == "done"
    assert sleeps == [1.0, 1.0, 2.0]  # lease 503 once; results dropped twice (1 s, then 2 s)


def test_retry_after_is_honoured(broker, sleeps):
    broker.add_job("kev", pair(1))
    broker.fail("/hello", times=1, status=429)
    worker, _, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK
    assert sleeps == [1.0]


def test_a_broker_that_stays_down_ends_the_session_and_logs_every_score(broker, sleeps, caplog):
    job = broker.add_job("kev", pair(1))
    broker.fail("/results", times=100, status=502)
    worker, _, _ = make_worker(broker, sleeps, retry_max_s=10)
    with caplog.at_level(logging.ERROR):
        assert worker.run() == run.EXIT_UNREACHABLE
    lines = [r.getMessage() for r in caplog.records if "UNDELIVERED" in r.getMessage()]
    assert len(lines) == 2
    assert job.requests[0]["request_sha256"] in lines[0]
    assert "p=0.900000" in lines[0]
    assert sum(sleeps) <= 10


def test_a_refused_result_is_reported_not_swallowed(broker, sleeps, caplog):
    broker.add_job("kev", pair(1))
    broker.fail("/results", times=1, status=422, body={"error": "invalid", "detail": "x"})
    worker, _, _ = make_worker(broker, sleeps)
    with caplog.at_level(logging.ERROR):
        assert worker.run() == run.EXIT_UNDELIVERED
    assert sum("UNDELIVERED" in r.getMessage() for r in caplog.records) == 2


# --- heartbeats and lost leases ------------------------------------------------------------


def test_heartbeats_extend_the_lease_during_a_long_job(broker, sleeps):
    job = broker.add_job("kev", pair(1))
    fake = FakeJudges()
    fake.on_score = lambda i: time.sleep(0.35)  # real time: the heartbeat thread runs on it
    worker, fake, _ = make_worker(broker, sleeps, fake=fake,
                                  leases={"heartbeat_s": 0.05, "lease_s": 900})  # fmt: skip
    assert worker.run() == run.EXIT_OK
    beats = broker.bodies("/heartbeat")
    assert len(beats) >= 3
    assert all(b["lease_ids"] and b["session"] for b in beats)
    assert any(b.get("progress", {}).get("job_id") == job.job_id for b in beats)
    assert all(isinstance(b["rss_bytes"], int) for b in beats)


def test_no_heartbeat_without_a_lease(broker, sleeps):
    worker, _, _ = make_worker(broker, sleeps, leases={"heartbeat_s": 0.01, "lease_s": 900})
    worker.session = "s"
    worker.heartbeat_once()
    assert broker.bodies("/heartbeat") == []


def test_a_lease_lost_at_heartbeat_drops_that_job_and_goes_on(broker, sleeps):
    lost, kept = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    worker, fake, _ = make_worker(broker, sleeps)

    def first(i):
        if i == 0:  # while scoring the first request, the broker re-leases that job elsewhere
            broker.lose_lease(lost.job_id)
            worker.heartbeat_once()

    fake.on_score = first
    assert worker.run() == run.EXIT_OK
    assert lost.job_id in worker.held.lost
    assert lost.scores == {}  # its finished order was dropped, not posted
    assert len(fake.scored) == 3  # the lost job's second order was never scored
    assert set(kept.scores) == {"ab", "ba"}


def test_a_result_refused_as_lease_lost_is_logged(broker, sleeps, caplog):
    job = broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)
    fake.on_score = lambda i: i == 1 and broker.lose_lease(job.job_id)
    with caplog.at_level(logging.WARNING):
        assert worker.run() == run.EXIT_OK
    assert any("lease lost" in r.getMessage() for r in caplog.records)
    assert job.scores == {}


# --- versions, integrity, failures ---------------------------------------------------------


def test_version_drift_at_hello_leases_nothing(broker, sleeps):
    broker.versions["kev"] = "kev-4b@ffffffffffff+kev-0000000+T1.0"
    broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_VERSION
    assert "/lease" not in broker.paths() and fake.loads == []


def test_version_drift_on_one_key_serves_the_others(broker, sleeps):
    broker.versions["kev"] = "kev-4b@ffffffffffff+kev-0000000+T1.0"
    job = broker.add_job("pplx", pair(1))
    worker, fake, _ = make_worker(broker, sleeps, worker={"models": ["kev", "pplx"]})
    assert worker.run() == run.EXIT_OK
    assert [b["model"] for b in broker.bodies("/lease")] == ["pplx", "pplx"]
    assert fake.loads == ["pplx"] and job.status == "done"
    assert job.scores["ab"]["extra"] == {"margin": 1.5}


def test_version_drift_at_lease_exits(broker, sleeps):
    broker.add_job("kev", pair(1))
    broker.fail("/lease", status=409,
                body={"error": "version", "model": "kev", "current": "kev-4b@new"})  # fmt: skip
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_VERSION
    assert fake.loads == []


def test_a_payload_that_does_not_match_its_hash_is_never_scored(broker, sleeps):
    bad, good = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    bad.requests[0]["payload"] = payload("tampered")  # the hash still names the original
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK
    assert payload("tampered") not in [p for _, p in fake.scored]
    # Every lease of it fails the same way, so it reaches max_attempts and is dead (a poison
    # job, for status); a hash mismatch is not the model failing, so the worker carries on.
    assert bad.status == "dead" and "request_sha256" in bad.last_error
    assert set(good.scores) == {"ab", "ba"}


def test_a_failing_request_is_released_as_an_error(broker, sleeps):
    bad, good = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    worker, fake, _ = make_worker(broker, sleeps)

    def boom(i):
        if i == 0:
            raise RuntimeError("CUDA out of memory")

    fake.on_score = boom
    assert worker.run() == run.EXIT_OK
    assert bad.attempts == 1 and bad.last_error == "RuntimeError: CUDA out of memory"
    assert set(good.scores) == {"ab", "ba"}
    # Re-leased later in the session and scored: one failure costs one attempt, no more.
    assert bad.status == "done"


def test_one_poison_job_does_not_stop_the_session(broker, sleeps):
    bad, good = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    worker, fake, _ = make_worker(broker, sleeps, leases={"max_jobs": 1})

    def boom(i):
        if i < 3:  # the first job fails on each of its three leases
            raise RuntimeError("bad input")

    fake.on_score = boom
    assert worker.run() == run.EXIT_OK
    assert bad.status == "dead" and bad.attempts == 3
    assert good.status == "done"


def test_a_model_that_keeps_failing_stops_the_session(broker, sleeps):
    for n in range(5):
        broker.add_job("kev", pair(n))
    worker, fake, _ = make_worker(broker, sleeps, leases={"max_jobs": 5})

    def boom(i):
        raise RuntimeError("broken")

    fake.on_score = boom
    assert worker.run() == run.EXIT_ERROR
    failed = [j for j in broker.jobs.values() if j.attempts]
    assert len(failed) == run.MAX_CONSECUTIVE_ERRORS and all(j.attempts == 1 for j in failed)


def test_a_model_that_will_not_load_hands_its_lease_back(broker, sleeps):
    job = broker.add_job("kev", pair(1))
    fake = FakeJudges()
    fake.fail_load = judges.LoadError("kev: loaded snapshot 'abc', pinned '6cfc...'")
    worker, _, _ = make_worker(broker, sleeps, fake=fake)
    assert worker.run() == run.EXIT_CONFIG
    assert job.status == "queued" and job.attempts == 1
    assert "LoadError" in job.last_error


def test_a_wrong_token_exits(broker, sleeps):
    cfg = parse(config(broker.url))
    client = Broker(cfg.broker_url, "not-the-token", sleep=sleeps.append)
    worker = run.Worker(cfg, client, load_judge=FakeJudges())
    assert worker.run() == run.EXIT_AUTH


def test_a_model_key_the_broker_does_not_grant_exits():
    with FakeBroker({TOKEN: ("home-kev", ["kev"])}) as b:
        cfg = parse(config(b.url, worker={"models": ["pplx"]}))
        worker = run.Worker(cfg, Broker(cfg.broker_url, TOKEN), load_judge=FakeJudges())
        assert worker.run() == run.EXIT_AUTH


def test_too_small_a_memory_limit_stops_before_hello(broker, sleeps, monkeypatch):
    monkeypatch.setattr(judges, "cgroup_memory_max", lambda: 16 * 2**30)
    worker, fake, _ = make_worker(broker, sleeps, compute={"memory_gib": 20})
    assert worker.run() == run.EXIT_CONFIG
    assert broker.calls == []


def test_two_models_are_drained_one_after_the_other(broker, sleeps):
    k = broker.add_job("kev", pair(1))
    p = broker.add_job("pplx", pair(2))
    worker, fake, _ = make_worker(broker, sleeps, worker={"models": ["kev", "pplx"]})
    assert worker.run() == run.EXIT_OK
    assert fake.loads == ["kev", "pplx"]
    assert fake.unloads == ["kev", "pplx"]  # kev freed before pplx was loaded
    assert k.status == "done" and p.status == "done"
