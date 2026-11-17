"""A worker session against the contract-following fake broker.

The judge is fake (it records what it is given and returns a fixed score) and so is the
clock (scoring and waiting move it), so windows, crossing midnight included, run in
milliseconds. The broker client is the real one, over real HTTP on 127.0.0.1.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from makhzan_ml.worker import judges, run
from makhzan_ml.worker.broker import (
    STOP_GRACE_S,
    STOP_TIMEOUT_S,
    Broker,
    BrokerError,
    Forbidden,
)
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
        "worker": {"name": "home-kev", "broker_url": url, "token": TOKEN, "model": "kev"},
        "compute": {"threads": 6, "nice": 0},
        "schedule": {"windows": "always", "timezone": "Africa/Cairo", "on_empty": "exit"},
        "leases": {"max_jobs": 2, "lease_s": 900, "heartbeat_s": 60},
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


def make_worker(
    broker, sleeps, *, clock=None, fake=None, retry_max_s=30.0, cfg_overrides=None, **sections
):
    cfg = parse(config(broker.url, **sections))
    if cfg_overrides:  # below the configuration's floors, for tests that run in real time
        cfg = dataclasses.replace(cfg, **cfg_overrides)
    clock = clock or FakeClock(datetime(2026, 11, 17, 1, 0, tzinfo=CAIRO))
    fake = fake or FakeJudges(clock)
    elapsed = [0.0]

    def sleep(seconds):
        # A broker backoff passes the worker's time too, so windows end during retries.
        sleeps.append(seconds)
        elapsed[0] += seconds
        clock.advance(seconds)

    client = Broker(cfg.broker_url, cfg.token, retry_max_s=retry_max_s, sleep=sleep,
                    monotonic=lambda: elapsed[0])  # fmt: skip
    worker = run.Worker(cfg, client, load_judge=fake, importable=lambda k: True, clock=clock,
                        image="sha256:test")  # fmt: skip
    return worker, fake, clock


# --- the whole session ---------------------------------------------------------------------


def test_a_session_scores_every_job_in_order_and_ends_once(broker, sleeps):
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
    # No time fit: a lease asks for max_jobs and nothing else. A fresh id each lease.
    assert all(set(b) == {"session", "model", "model_version", "max_jobs", "lease_request_id"}
               for b in leases)  # fmt: skip
    ids = [b["lease_request_id"] for b in leases]
    assert len(set(ids)) == len(ids) and all(len(i) <= 64 for i in ids)
    assert len(broker.bodies("/results")) == 3  # one POST per job
    # The empty lease ended the session at the broker (P16), so no session release follows
    # to overwrite "empty" with "released".
    assert broker.paths()[-1] == "/lease" and "/release" not in broker.paths()
    assert [s["end_reason"] for s in broker.sessions.values()] == ["empty"]
    assert worker.session_closed and hello
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
    assert broker.paths() == ["/hello", "/lease"]  # the empty lease ended the session
    assert [s["end_reason"] for s in broker.sessions.values()] == ["empty"]


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
        schedule={"windows": ["23:00-00:10"]}, leases={"max_jobs": 4},
    )  # fmt: skip
    assert worker.run() == run.EXIT_OK
    # No time fit: the lease holds all four jobs. Requests run 23:50 -> 23:55 -> 00:00 ->
    # 00:05 -> 00:10, where the window ends: the rest goes back, gracefully.
    assert len(fake.scored) == 4
    assert clock.now() == datetime(2026, 11, 18, 0, 10, tzinfo=CAIRO)
    assert set(jobs[0].scores) == {"ab", "ba"} and set(jobs[1].scores) == {"ab", "ba"}
    released = [b for b in broker.bodies("/release") if b.get("job_ids")]
    assert len(released) == 1 and released[0]["reason"] == "graceful"
    assert released[0]["job_ids"] == [jobs[2].job_id, jobs[3].job_id]
    assert all(j.status == "queued" and j.attempts == 0 for j in jobs[2:])
    # The graceful release told the broker the session ended.
    assert broker.paths()[-1] == "/release"
    assert [s["end_reason"] for s in broker.sessions.values()] == ["released"]


def test_a_half_scored_job_submits_its_finished_order_then_releases(broker, sleeps):
    job = broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)
    fake.on_score = lambda i: i == 0 and worker.request_stop("SIGTERM")
    assert worker.run() == run.EXIT_OK
    assert set(job.scores) == {"ab"}  # the request in flight finished and was kept
    assert job.status == "queued" and job.attempts == 0
    with_jobs = [b for b in broker.bodies("/release") if b.get("job_ids")]
    assert with_jobs[-1]["job_ids"] == [job.job_id]
    assert with_jobs[-1]["reason"] == "graceful"


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


def test_the_window_end_drops_the_current_job(broker, sleeps):
    # A minute before the window ends, a 90 s request starts; it cannot be interrupted and
    # runs past the end. Then the job is dropped: its finished order is posted, the rest
    # goes back gracefully (no attempt), for another worker or a later window.
    job, other = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    clock = FakeClock(datetime(2026, 11, 17, 4, 29, tzinfo=CAIRO))
    fake = FakeJudges(clock, seconds=90)
    worker, fake, _ = make_worker(broker, sleeps, clock=clock, fake=fake,
                                  schedule={"windows": ["00:30-04:30"]})  # fmt: skip
    assert worker.run() == run.EXIT_OK
    assert worker.stop_reason == "the window has ended"
    assert len(fake.scored) == 1 and set(job.scores) == {"ab"}
    released = [b for b in broker.bodies("/release") if b.get("job_ids")]
    assert released == [{"session": worker.session, "lease_id": released[0]["lease_id"],
                         "job_ids": [job.job_id, other.job_id], "reason": "graceful"}]  # fmt: skip
    assert job.status == "queued" and job.attempts == 0 and other.attempts == 0
    assert fake.unloads == ["kev"]
    assert [s["end_reason"] for s in broker.sessions.values()] == ["released"]


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
    broker.fail("/hello", times=1, status=429, headers={"Retry-After": "5"})
    worker, _, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK
    assert sleeps == [5.0]  # the broker's 5 s, not the 1 s first backoff


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


def test_heartbeats_extend_the_lease_during_a_long_job(sleeps):
    # The broker's clock runs 100 times fast: its 60 s lease (the contract's minimum) is
    # 0.6 s of real time, so a 0.7 s request outlives it unless heartbeats extend it.
    with FakeBroker({TOKEN: ("home-kev", ["kev"])},
                    clock=lambda: time.monotonic() * 100) as broker:  # fmt: skip
        job = broker.add_job("kev", pair(1))
        fake = FakeJudges()

        def slow(i):
            time.sleep(0.7)
            with broker.lock:
                broker._reap()  # what another worker's lease would run

        fake.on_score = slow
        worker, fake, _ = make_worker(broker, sleeps, fake=fake, leases={"lease_s": 60, "heartbeat_s": 30},
                                      cfg_overrides={"heartbeat_s": 0.1})  # fmt: skip
        assert worker.run() == run.EXIT_OK
        # Without the heartbeats the lease would have expired mid-job and been reaped.
        assert job.status == "done" and job.attempts == 0
        beats = broker.bodies("/heartbeat")
        assert len(beats) >= 5
        assert all(b["lease_ids"] and b["session"] for b in beats)
        assert all(b["job_ids"] == [job.job_id] for b in beats)
        assert any(b.get("progress", {}).get("job_id") == job.job_id for b in beats)
        assert all(isinstance(b["rss_bytes"], int) for b in beats)


def test_no_heartbeat_without_a_lease(broker, sleeps):
    worker, _, _ = make_worker(broker, sleeps)
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
    first_lease = broker.bodies("/lease") and worker.held.lost
    assert any(j == lost.job_id for _, j in first_lease)
    # Its finished order was dropped, not posted, and its second order never scored under
    # the lost lease. The broker re-queued it, so this worker leased it again later in the
    # session (a new lease) and scored it then: being lost once does not taint the job.
    assert len(fake.scored) == 1 + 2 + 2
    assert set(kept.scores) == {"ab", "ba"}
    assert lost.status == "done" and lost.attempts == 1


def test_a_result_refused_as_lease_lost_is_logged(broker, sleeps, caplog):
    job = broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)
    fake.on_score = lambda i: i == 1 and broker.lose_lease(job.job_id)
    with caplog.at_level(logging.WARNING):
        assert worker.run() == run.EXIT_UNDELIVERED
    # The posted scores were refused: logged as undelivered, each one.
    lines = [r.getMessage() for r in caplog.records if "UNDELIVERED" in r.getMessage()]
    assert len(lines) == 2 and all("lease lost" in m for m in lines)
    # Re-queued by the broker, leased again and scored in full.
    assert job.status == "done" and job.attempts == 1


# --- versions, integrity, failures ---------------------------------------------------------


def test_version_drift_at_hello_leases_nothing(broker, sleeps):
    broker.versions["kev"] = "kev-4b@ffffffffffff+kev-0000000+T1.0"
    broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_VERSION
    assert "/lease" not in broker.paths() and fake.loads == []


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
    # The two jobs never started went back with the lease, gracefully: no attempt, not held.
    rest = [j for j in broker.jobs.values() if not j.attempts]
    assert len(rest) == 2 and all(j.status == "queued" for j in rest)


def test_a_model_that_will_not_load_hands_its_lease_back(broker, sleeps):
    job = broker.add_job("kev", pair(1))
    fake = FakeJudges()
    fake.fail_load = judges.LoadError("kev: loaded snapshot 'abc', pinned '6cfc...'")
    worker, _, _ = make_worker(broker, sleeps, fake=fake)
    assert worker.run() == run.EXIT_CONFIG
    # The worker's fault, not the job's: handed back with no attempt counted, and once.
    assert job.status == "queued" and job.attempts == 0
    assert [b["job_ids"] for b in broker.bodies("/release") if b.get("job_ids")] == [[job.job_id]]


def test_a_wrong_token_exits(broker, sleeps):
    cfg = parse(config(broker.url))
    client = Broker(cfg.broker_url, "not-the-token", sleep=sleeps.append)
    worker = run.Worker(cfg, client, load_judge=FakeJudges(), importable=lambda k: True)
    assert worker.run() == run.EXIT_AUTH


def test_a_model_key_the_broker_does_not_grant_exits():
    with FakeBroker({TOKEN: ("home-kev", ["kev"])}) as b:
        cfg = parse(config(b.url, worker={"model": "pplx"}))
        worker = run.Worker(cfg, Broker(cfg.broker_url, TOKEN), load_judge=FakeJudges(),
                            importable=lambda k: True)  # fmt: skip
        assert worker.run() == run.EXIT_AUTH


def test_too_small_a_memory_limit_stops_before_hello(broker, sleeps, monkeypatch):
    monkeypatch.setattr(judges, "cgroup_memory_max", lambda: 16 * 2**30)
    worker, fake, _ = make_worker(broker, sleeps, compute={"memory_gib": 20})
    assert worker.run() == run.EXIT_CONFIG
    assert broker.calls == []


def test_two_models_are_two_workers(broker, sleeps):
    # One model per session (the broker refuses a hello naming two): a Kev worker, then a
    # pplx worker, each its own session.
    k = broker.add_job("kev", pair(1))
    p = broker.add_job("pplx", pair(2))
    kev, kev_judges, _ = make_worker(broker, sleeps)
    pplx, pplx_judges, _ = make_worker(broker, sleeps, worker={"model": "pplx"})
    assert kev.run() == run.EXIT_OK and pplx.run() == run.EXIT_OK
    assert kev_judges.loads == ["kev"] and pplx_judges.loads == ["pplx"]
    assert [list(b["models"]) for b in broker.bodies("/hello")] == [["kev"], ["pplx"]]
    assert {b["model"] for b in broker.bodies("/lease")} == {"kev", "pplx"}
    assert k.status == "done" and p.status == "done"
    assert len(broker.sessions) == 2


# --- review regressions ---------------------------------------------------------------------


@pytest.mark.parametrize("timezone", ["UTC", "Etc/UTC", "Africa/Cairo"])
def test_a_windowed_schedule_runs_in_any_zone(broker, sleeps, timezone):
    # A fixed-offset zone (UTC) once crashed the first window check: an aware time compared
    # with the naive window bounds. (A window now requires a zone; "always" needs none.)
    broker.add_job("kev", pair(1))
    schedule = {"windows": ["00:00-23:59"], "timezone": timezone}
    clock = FakeClock(datetime(2026, 11, 17, 12, 0, tzinfo=ZoneInfo(timezone)))
    worker, fake, _ = make_worker(broker, sleeps, clock=clock, schedule=schedule)
    assert worker.run() == run.EXIT_OK
    assert len(fake.scored) == 2


def test_the_window_end_counts_real_time_across_a_dst_change(broker, sleeps):
    # Berlin's clocks went back an hour at 03:00 on 2026-10-25: 01:30 to 05:00 that night
    # is four and a half real hours, not three and a half.
    tz = ZoneInfo("Europe/Berlin")
    clock = FakeClock(datetime(2026, 10, 25, 1, 30, tzinfo=tz))
    worker, _, _ = make_worker(broker, sleeps, clock=clock,
                               schedule={"windows": ["01:00-05:00"], "timezone": "Europe/Berlin"})  # fmt: skip
    assert worker._seconds_to_window_end() == 4.5 * 3600


def test_undelivered_scores_are_logged_when_a_fatal_ends_the_session(broker, sleeps, caplog):
    for n in range(4):
        broker.add_job("kev", pair(n))
    broker.fail("/results", times=1, status=422, body={"error": "invalid", "detail": "x"})
    worker, fake, _ = make_worker(broker, sleeps, leases={"max_jobs": 4})

    def boom(i):
        if i >= 2:  # the first job scores (and is refused), then the model breaks
            raise RuntimeError("broken")

    fake.on_score = boom
    with caplog.at_level(logging.ERROR):
        assert worker.run() == run.EXIT_ERROR
    assert sum("UNDELIVERED" in r.getMessage() for r in caplog.records) == 2


def test_a_stop_cuts_the_brokers_retries_short(broker, sleeps):
    job = broker.add_job("kev", pair(1))
    broker.fail("/results", times=1000, status=503)
    worker, fake, _ = make_worker(broker, sleeps, retry_max_s=900)
    fake.on_score = lambda i: i == 1 and worker.request_stop("SIGTERM")
    assert worker.run() == run.EXIT_UNREACHABLE
    # One deadline for the rest of the session, not the 900 s budget: a docker stop would
    # kill the process first.
    assert sum(sleeps) <= STOP_GRACE_S
    assert job.scores == {}


def test_heartbeat_names_its_jobs_and_drops_a_lost_lease(broker, sleeps):
    a, b = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    worker, fake, _ = make_worker(broker, sleeps)
    seen = {}

    def first(i):
        if i == 0:
            lease_id = a.lease_id
            broker.lose_lease(a.job_id)
            broker.lose_lease(b.job_id)  # the whole lease is gone
            worker.heartbeat_once()
            seen["lost"] = set(worker.held.lost)
            seen["lease"] = lease_id

    fake.on_score = first
    assert worker.run() == run.EXIT_OK
    assert seen["lost"] == {(seen["lease"], a.job_id), (seen["lease"], b.job_id)}
    beat = broker.bodies("/heartbeat")[0]
    assert beat["job_ids"] == [a.job_id, b.job_id]
    assert a.status == "done" and b.status == "done"  # leased again later and scored


def test_the_brokers_lease_length_bounds_the_heartbeat(broker, sleeps):
    worker, _, _ = make_worker(broker, sleeps, leases={"lease_s": 90, "heartbeat_s": 45})
    worker._hello()
    assert worker.heartbeat_s == 30  # the broker answers min(60, lease_s / 3)


def test_a_job_with_no_requests_is_handed_back(broker, sleeps):
    job = broker.add_job("kev", {})
    worker, fake, _ = make_worker(broker, sleeps)
    worker.session = "s"
    worker.judge = fake("kev", judges.Runtime("cpu", "fp32", None, False, None))
    assert worker._process_job(worker.judge, "kev", "lease", {"job_id": job.job_id, "requests": []})
    body = broker.bodies("/release")[0]
    assert body["job_ids"] == [job.job_id] and body["reason"] == "error"


def test_a_redirect_is_refused_not_followed(sleeps):
    import http.server

    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.send_response(307)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()  # fmt: skip
    try:
        client = Broker(f"http://127.0.0.1:{server.server_port}/ai/v1", TOKEN, sleep=sleeps.append)
        with pytest.raises(BrokerError) as e:
            client.hello({})
        assert e.value.status == 307
    finally:
        server.shutdown()
        server.server_close()


# --- second review ------------------------------------------------------------------------


def test_the_window_end_stops_a_session_retrying_through_an_outage(broker, sleeps, caplog):
    # The broker goes down while the worker posts its last results, ten minutes before the
    # window ends. Retrying for the full 15-minute budget would keep Kev loaded past the
    # window while the next worker (pplx) loads: both in memory. The window's end stops it.
    job = broker.add_job("kev", pair(1))
    broker.fail("/results", times=1000, status=503)
    clock = FakeClock(datetime(2026, 11, 17, 4, 20, tzinfo=CAIRO))
    worker, fake, clock = make_worker(
        broker, sleeps, clock=clock, retry_max_s=900, schedule={"windows": ["00:30-04:30"]}
    )
    with caplog.at_level(logging.ERROR):
        assert worker.run() == run.EXIT_UNREACHABLE
    assert worker.stop_reason == "the window has ended"
    assert fake.unloads == ["kev"]  # unloaded on the way out
    # Stopped at 04:30, then at most the stop grace for the rest of the session.
    end = datetime(2026, 11, 17, 4, 30, tzinfo=CAIRO).timestamp() + STOP_GRACE_S
    assert clock.now().timestamp() <= end
    assert sum("UNDELIVERED" in r.getMessage() for r in caplog.records) == 2
    assert job.scores == {}


def test_a_stop_shortens_every_socket_timeout(broker, sleeps):
    worker, _, _ = make_worker(broker, sleeps)
    assert worker.broker.deadline is None
    worker.request_stop("SIGTERM")
    assert worker.broker.deadline is not None and STOP_TIMEOUT_S < worker.broker.timeout_s


def test_an_undelivered_score_is_logged_at_once(broker, sleeps, caplog):
    first, second = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    broker.fail("/results", times=1, status=422, body={"error": "invalid", "detail": "x"})
    worker, fake, _ = make_worker(broker, sleeps)
    seen = {}

    def on(i):
        if i == 2:  # scoring the second job: the first's refusal is already in the log
            seen["n"] = sum("UNDELIVERED" in r.getMessage() for r in caplog.records)

    fake.on_score = on
    with caplog.at_level(logging.ERROR):
        assert worker.run() == run.EXIT_UNDELIVERED
    assert seen["n"] == 2
    line = next(r.getMessage() for r in caplog.records if "UNDELIVERED" in r.getMessage())
    assert f"job {first.job_id}" in line and first.requests[0]["request_sha256"] in line
    assert "p=0.900000" in line
    assert set(second.scores) == {"ab", "ba"}


def test_an_unexpected_broker_answer_ends_the_session_cleanly(broker, sleeps, caplog):
    # From the review's repro: a 413 on results, then a 400 on the next lease.
    _, b = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    worker, fake, _ = make_worker(broker, sleeps, leases={"max_jobs": 1})
    lease = worker.broker.lease
    n = {"lease": 0}

    def results(body):
        raise BrokerError(413, {"error": "too large"}, "/results")

    def lease_once(body):
        n["lease"] += 1
        if n["lease"] == 2:
            raise BrokerError(400, {"error": "bad"}, "/lease")
        return lease(body)

    worker.broker.results, worker.broker.lease = results, lease_once
    with caplog.at_level(logging.ERROR):
        assert worker.run() == run.EXIT_ERROR  # no exception escapes run()
    assert sum("UNDELIVERED" in r.getMessage() for r in caplog.records) == 2
    assert b.status == "queued" and b.attempts == 0


def test_an_unexpected_error_mid_lease_hands_the_jobs_back(broker, sleeps, caplog):
    jobs = [broker.add_job("kev", pair(n)) for n in range(2)]
    worker, fake, _ = make_worker(broker, sleeps)

    def results(body):
        raise RuntimeError("something nobody planned for")

    worker.broker.results = results
    with caplog.at_level(logging.ERROR):
        assert worker.run() == run.EXIT_ERROR
    assert sum("UNDELIVERED" in r.getMessage() for r in caplog.records) == 2
    assert all(j.status == "queued" and j.attempts == 0 for j in jobs)


def test_a_malformed_hello_is_an_error_not_a_crash(broker, sleeps):
    broker.fail("/hello", status=200, body={"models": {}})
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_ERROR
    assert fake.loads == []


def test_heartbeats_never_name_a_finished_job(broker, sleeps, caplog):
    # From the review's repro, with max_jobs = 2: the first job is posted and done while
    # the second is being scored.
    _, b = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    worker, fake, _ = make_worker(broker, sleeps)
    fake.on_score = lambda i: i == 2 and worker.heartbeat_once()
    with caplog.at_level(logging.WARNING):
        assert worker.run() == run.EXIT_OK
    beat = broker.bodies("/heartbeat")[-1]
    assert beat["job_ids"] == [b.job_id]
    assert worker.held.lost == set()
    assert not any("heartbeat" in r.getMessage() for r in caplog.records)


def test_a_model_this_image_cannot_load_stops_before_hello(broker, sleeps):
    cfg = parse(config(broker.url, worker={"model": "pplx"}))  # in a Kev image
    worker = run.Worker(cfg, Broker(cfg.broker_url, TOKEN), load_judge=FakeJudges(),
                        importable=lambda k: k == "kev")  # fmt: skip
    assert worker.run() == run.EXIT_CONFIG
    assert broker.calls == []


def test_threads_default_to_the_cpu_quota_not_the_host(broker, sleeps):
    worker, _, _ = make_worker(broker, sleeps, compute={"threads": None})
    assert worker.threads == judges.default_threads()
    assert 1 <= worker.threads <= len(os.sched_getaffinity(0))


def test_proxy_settings_in_the_environment_are_ignored(broker, sleeps, monkeypatch):
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.setenv(k, "http://127.0.0.1:9")  # nothing listens there
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK
    assert len(fake.scored) == 2 and sleeps == []


# --- the final contract ---------------------------------------------------------------------


def session_releases(broker):
    return [b for b in broker.bodies("/release") if not b.get("job_ids")]


def job_releases(broker, reason="graceful"):
    return [b for b in broker.bodies("/release") if b.get("job_ids") and b["reason"] == reason]


@pytest.mark.parametrize(
    "how, end, n_session, n_jobs",
    [
        ("window", "released", 1, 0),  # stopped between leases: the session release
        ("sigterm", "released", 1, 0),  # SIGTERM after the job's last request: likewise
        ("empty", "empty", 0, 0),  # the empty lease ended it; nothing to add
        ("fatal", "released", 0, 1),  # the lease's graceful release ended it
    ],
)
def test_every_session_ends_exactly_once(broker, sleeps, how, end, n_session, n_jobs):
    jobs = [broker.add_job("kev", pair(n)) for n in range(2)]
    schedule, clock, fake = {}, None, None
    if how == "window":  # the first job (two 150 s requests) ends just as the window does
        clock = FakeClock(datetime(2026, 11, 17, 4, 25, tzinfo=CAIRO))
        schedule = {"windows": ["00:30-04:30"]}
        fake = FakeJudges(clock, seconds=150)
    worker, fake, _ = make_worker(broker, sleeps, clock=clock, schedule=schedule, fake=fake,
                                  leases={"max_jobs": 1})  # fmt: skip
    if how == "sigterm":
        fake.on_score = lambda i: i == 1 and worker.request_stop("SIGTERM")
    if how == "fatal":
        fake.fail_load = judges.LoadError("x")
    worker.run()
    assert [s["end_reason"] for s in broker.sessions.values()] == [end]
    assert len(session_releases(broker)) == n_session
    assert len(job_releases(broker)) == n_jobs
    if n_session:
        assert session_releases(broker)[0] == {"session": worker.session, "reason": "graceful"}
    assert all(j.attempts == 0 for j in jobs)


def test_no_session_release_to_a_broker_that_is_down(broker, sleeps):
    broker.add_job("kev", pair(1))
    broker.fail("/results", times=1000, status=503)
    worker, _, _ = make_worker(broker, sleeps, retry_max_s=5)
    assert worker.run() == run.EXIT_UNREACHABLE
    assert "/release" not in broker.paths()


def test_a_lease_whose_answer_was_lost_comes_back_the_same(broker, sleeps):
    jobs = [broker.add_job("kev", pair(n)) for n in range(2)]
    broker.fail("/lease", times=1, after=True)  # leased, but the answer never arrives
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.run() == run.EXIT_OK
    first, retry = broker.bodies("/lease")[:2]
    assert first["lease_request_id"] == retry["lease_request_id"]  # the retry reuses the id
    assert sleeps == [1.0]
    # The same lease came back: nothing orphaned, nothing charged, every job scored once.
    assert all(j.status == "done" and j.attempts == 0 for j in jobs)
    assert len(fake.scored) == 4
    assert list(broker.sessions.values())[0]["leases"] == 1


def test_a_heartbeat_names_each_job_as_it_starts(broker, sleeps):
    jobs = [broker.add_job("kev", pair(n)) for n in range(3)]
    worker, _, _ = make_worker(broker, sleeps, leases={"max_jobs": 3})
    assert worker.run() == run.EXIT_OK
    order = [(p, b.get("progress", {}).get("job_id") if p == "/heartbeat" else b.get("job_id"))
             for p, b in broker.calls if p in ("/heartbeat", "/results")]  # fmt: skip
    # progress.job_id is the broker's integer job id, as sent in the lease
    beats = [b for b in broker.bodies("/heartbeat") if b.get("progress")]
    assert beats and all(type(b["progress"]["job_id"]) is int for b in beats)
    for j in jobs:
        # The heartbeat naming a job comes before that job's results.
        assert order.index(("/heartbeat", j.job_id)) < order.index(("/results", j.job_id))


def test_a_crash_is_charged_to_the_job_in_hand_alone(broker, sleeps):
    done, in_hand, waiting = (broker.add_job("kev", pair(n)) for n in range(3))
    worker, fake, _ = make_worker(broker, sleeps, leases={"max_jobs": 3})
    seen = {}

    def crash(i):
        if i == 2:  # scoring the second job: the lease expires, as if the worker had died
            lease_id = in_hand.lease_id
            broker.expire(lease_id)
            with broker.lock:
                broker._reap()
            seen["attempts"] = (done.attempts, in_hand.attempts, waiting.attempts)

    fake.on_score = crash
    # The in-hand job's posted scores are refused after the expiry: undelivered, logged.
    assert worker.run() == run.EXIT_UNDELIVERED
    assert seen["attempts"] == (0, 1, 0)  # only the job its heartbeat named was charged


def test_a_prompt_version_hello_did_not_announce_is_logged(broker, sleeps, caplog):
    job = broker.add_job("kev", pair(1), prompt_version="K2-150@elsewhere")
    worker, fake, _ = make_worker(broker, sleeps)
    with caplog.at_level(logging.INFO):
        assert worker.run() == run.EXIT_OK
    assert worker.stages == {"match/kev": "K2-150@test", "audit/kev": "K2-150@test"}
    msgs = [r.getMessage() for r in caplog.records]
    assert any("K2-150@elsewhere is not one hello announced" in m for m in msgs)
    assert any("stages: audit/kev prompt K2-150@test" in m for m in msgs)
    assert job.status == "done"  # the broker renders; a mismatch is logged, not refused


def test_sigterm_mid_lease_ends_the_session_with_the_lease_release_only(broker, sleeps):
    # From the review's repro: the graceful release of the unstarted job ends the session;
    # no session release follows it.
    broker.add_job("kev", pair(1))
    second = broker.add_job("kev", pair(2))
    worker, fake, _ = make_worker(broker, sleeps)
    fake.on_score = lambda i: i == 1 and worker.request_stop("SIGTERM")
    worker.run()
    assert len(job_releases(broker)) == 1 and job_releases(broker)[0]["job_ids"] == [second.job_id]
    assert session_releases(broker) == []
    assert [s["end_reason"] for s in broker.sessions.values()] == ["released"]


def test_a_refused_model_key_at_lease_still_ends_the_session(broker, sleeps):
    broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)

    def lease(body):
        raise Forbidden(403, {"error": "model_not_allowed", "model": "kev"}, "/lease")

    worker.broker.lease = lease
    assert worker.run() == run.EXIT_AUTH
    assert len(session_releases(broker)) == 1  # the token was good: end what it opened
    assert [s["end_reason"] for s in broker.sessions.values()] == ["released"]


def test_a_refused_token_gets_no_session_release(broker, sleeps):
    cfg = parse(config(broker.url))
    worker = run.Worker(cfg, Broker(cfg.broker_url, "wrong", sleep=sleeps.append),
                        load_judge=FakeJudges(), importable=lambda k: True)  # fmt: skip
    assert worker.run() == run.EXIT_AUTH
    assert broker.calls == []  # the fake records only authorised calls; none got through


def test_a_stop_before_hello_opens_no_session(broker, sleeps):
    worker, fake, _ = make_worker(broker, sleeps)
    worker.request_stop("SIGTERM")
    assert worker.run() == run.EXIT_OK
    assert broker.calls == [] and broker.sessions == {}


def test_a_lease_retry_keeps_its_request_id(broker, sleeps):
    broker.add_job("kev", pair(1))
    broker.fail("/lease", times=3, status=503)
    worker, _, _ = make_worker(broker, sleeps, retry_max_s=600)
    seen = []
    once = worker.broker._once

    def recording(path, body):
        if path == "/lease":
            seen.append(body["lease_request_id"])
        return once(path, body)

    worker.broker._once = recording
    assert worker.run() == run.EXIT_OK
    assert len(set(seen[:4])) == 1  # three 503s, then the lease that worked: one id
    assert len(set(seen)) == len(seen) - 3  # each later lease has its own


def test_no_lost_warning_for_a_job_being_settled(broker, sleeps, caplog):
    job = broker.add_job("kev", pair(1))
    worker, _, _ = make_worker(broker, sleeps)
    results = worker.broker.results

    def results_then_heartbeat(body):
        out = results(body)  # the broker has the job done and its lease cleared ...
        worker.heartbeat_once()  # ... and a heartbeat goes out before the worker settles it
        return out

    worker.broker.results = results_then_heartbeat
    with caplog.at_level(logging.WARNING):
        assert worker.run() == run.EXIT_OK
    assert not any("heartbeat: lost" in r.getMessage() for r in caplog.records)
    assert job.status == "done"


def test_final_results_retrying_is_kept_alive_by_heartbeats(broker, sleeps, caplog):
    # The reviewer's regression: while the job's final /results retries through an outage,
    # heartbeats must keep naming it, or its lease expires and the reaper charges a job
    # that was scored in full.
    job = broker.add_job("kev", pair(1))
    broker.fail("/results", times=6, status=503)  # 1+2+4+8+16+32 = 63 s of backoff
    worker, fake, _ = make_worker(broker, sleeps, retry_max_s=900)
    beats = []
    sleep = worker.broker._sleep

    def sleep_and_beat(seconds):
        sleep(seconds)
        before = len(broker.bodies("/heartbeat"))
        worker.heartbeat_once()  # what the heartbeat thread does during the backoff
        beats.append(broker.bodies("/heartbeat")[before:])

    worker.broker._sleep = sleep_and_beat
    with caplog.at_level(logging.WARNING):
        assert worker.run() == run.EXIT_OK
    assert len(beats) == 6 and all(len(b) == 1 for b in beats)
    assert all(b[0]["job_ids"] == [job.job_id] for b in beats)  # still named while settling
    assert job.status == "done" and job.attempts == 0
    assert not any("heartbeat: lost" in r.getMessage() for r in caplog.records)


def test_a_release_never_names_a_job_found_lost(broker, sleeps):
    _, b = broker.add_job("kev", pair(1)), broker.add_job("kev", pair(2))
    worker, fake, _ = make_worker(broker, sleeps)

    def on(i):
        if i == 0:  # job b is lost (re-leased elsewhere) and the session is stopping
            broker.lose_lease(b.job_id)
            worker.heartbeat_once()
            worker.request_stop("SIGTERM")

    fake.on_score = on
    worker.run()
    with_jobs = [r for r in broker.bodies("/release") if r.get("job_ids")]
    assert all(b.job_id not in r["job_ids"] for r in with_jobs)
    assert not any(r.get("error") == "lease_lost" for r in with_jobs)
