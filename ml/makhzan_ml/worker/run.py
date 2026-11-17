"""One worker session, from hello to the last release (docs/ai/worker.md, "Lifecycle").

1. Outside every window: exit 0, nothing sent.
2. Pre-flight: the container's memory limit against `memory_gib`, then lower the
   process priority (`nice`).
3. `POST /hello` with the name, model keys and versions, device, dtype and threads. A
   key the broker answers `ok: false` for (version drift) is never leased; no `ok` key
   at all exits 3.
4. Per model key, in the configured order, until its queue is empty:
   `POST /lease` (seconds left in the window, the measured seconds per request); the
   model is loaded on the first lease that brings jobs, never on an empty night, and
   checked against its pins (`judges.load`); each job's requests are scored **in the
   order given, one per call**, each request's `request_sha256` first checked against
   its payload, and `POST /results` after each job. A background thread sends
   `/heartbeat` every `heartbeat_s` while a lease is held.
5. Graceful stop (window end, SIGTERM, SIGINT): no new request is started, the one in
   flight finishes (a forward pass cannot be interrupted), finished orders are
   submitted, the rest of the lease goes back with `/release` reason "graceful".
   Before each request the worker also checks the window: a request it does not expect
   to finish before the window ends is not started.
6. Empty queues: `on_empty = "exit"` exits; `"wait"` polls every `poll_s` until the
   window ends.
7. The broker sees a session end (P16) at a graceful `/release` of held jobs or at a
   lease that comes back empty (broker-api.md §3.1); a release naming no jobs is not
   valid, so a session that stops between leases with nothing held is not seen to end,
   and the log says so.

**Never drop a result silently.** A results POST is retried through network failures
for `retry_max_s` (`broker.Broker`); a score that still cannot be delivered, or that the
broker refuses, is logged at ERROR with its job, order, request hash and score (never
the payload), and the exit code says the session did not end clean.
"""

from __future__ import annotations

import hashlib
import json
import logging
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from makhzan_ml.worker import judges
from makhzan_ml.worker.broker import (
    Broker,
    BrokerError,
    Forbidden,
    Invalid,
    LeaseLost,
    Unauthorized,
    Unreachable,
    VersionDrift,
)
from makhzan_ml.worker.config import Config
from makhzan_ml.worker.pins import PINS

log = logging.getLogger("makhzan_ml.worker")

# Exit codes (docs/ai/worker.md).
EXIT_OK = 0
EXIT_ERROR = 1  # a model failing on 3 jobs in a row, an unexpected error
EXIT_CONFIG = 2  # configuration, memory limit, or a model that will not load as pinned
EXIT_VERSION = 3  # the broker runs another model version than this worker
EXIT_UNREACHABLE = 4  # the broker could not be reached for retry_max_s
EXIT_AUTH = 5  # 401 / 403: the token or the registration is wrong
EXIT_UNDELIVERED = 6  # the session ended, but some scores could not be delivered

#: A judge failing on this many different jobs in a row stops the session: a broken model
#: would otherwise turn the whole queue into failed attempts. One job failing again and
#: again is that job's problem: the broker makes it dead at max_attempts (a poison job).
MAX_CONSECUTIVE_ERRORS = 3
#: For lease sizing when a worker runs always: a day's worth.
ALWAYS_SECONDS_LEFT = 86_400


def canonical_json(request: object) -> str:
    """`makhzan_schemas.ai.prompt.canonical_json`, byte for byte (a test holds them equal):
    what `request_sha256` is taken over."""
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class Clock:
    """Time, injectable for tests. `now` is in the schedule's time zone."""

    def __init__(self, cfg: Config):
        self._schedule = cfg.schedule

    def now(self) -> datetime:
        return self._schedule.now()

    def monotonic(self) -> float:
        return time.monotonic()

    def wait(self, seconds: float, stop: threading.Event) -> bool:
        """Sleep up to `seconds`; True when woken by `stop`."""
        return stop.wait(max(0.0, seconds))


class _Fatal(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


@dataclass
class _Held:
    """The leases this worker holds, shared with the heartbeat thread."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    leases: dict[str, set[int]] = field(default_factory=dict)  # lease_id -> job ids
    lost: set[tuple[str, int]] = field(default_factory=set)  # (lease_id, job_id)
    progress: dict | None = None


class Worker:
    def __init__(
        self,
        cfg: Config,
        broker: Broker | None = None,
        *,
        load_judge: Callable[[str, judges.Runtime], judges.Judge] = judges.load,
        clock: Clock | None = None,
        image: str | None = None,
    ):
        self.cfg = cfg
        self.broker = broker or Broker(
            cfg.broker_url, cfg.token, ca_file=cfg.ca_file, retry_max_s=cfg.retry_max_s
        )
        self.load_judge = load_judge
        self.clock = clock or Clock(cfg)
        self.image = image
        self.stop = threading.Event()
        # A stop cuts the broker's retries short, so a SIGTERM's grace period is enough.
        self.broker.stop_event = self.stop
        self.stop_reason: str | None = None
        self.session: str | None = None
        self.heartbeat_s = cfg.heartbeat_s
        self.judge: judges.Judge | None = None
        self.held = _Held()
        self.spr = {k: cfg.seconds_per_request for k in cfg.models}  # measured, per model
        self._measured: set[str] = set()
        self.judge_info: dict[str, dict] = {}  # what each load reported, kept after unloading
        self.undelivered: list[dict] = []
        self.session_closed = False  # the broker saw the session end (P16)
        self.failed_jobs: set[int] = set()  # distinct jobs failed since the last success
        self.scored = 0
        self._hb_thread: threading.Thread | None = None
        self._hb_stop = threading.Event()

    # -- control ---------------------------------------------------------------------------

    def request_stop(self, reason: str = "stop requested") -> None:
        if not self.stop.is_set():
            self.stop_reason = reason
            log.info("stopping: %s", reason)
            self.stop.set()

    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            self.request_stop(signal.Signals(signum).name)

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    def _closes_at(self) -> datetime | None:
        return self.cfg.schedule.closes_at(self.clock.now())

    def _seconds_left(self) -> float:
        closes = self._closes_at()
        if closes is None:
            return ALWAYS_SECONDS_LEFT
        return max(0.0, closes.timestamp() - self.clock.now().timestamp())

    def _window_open(self) -> bool:
        if self.cfg.schedule.is_open(self.clock.now()):
            return True
        self.request_stop("the window has ended")
        return False

    def _may_continue(self) -> bool:
        return not self.stop.is_set() and self._window_open()

    # -- the session -----------------------------------------------------------------------

    def run(self) -> int:
        cfg = self.cfg
        if not cfg.schedule.is_open(self.clock.now()):
            log.info("outside the window (%s); nothing to do", cfg.schedule.describe())
            return EXIT_OK
        code = self._session()
        # Every exit path, whatever ended the session, says which scores did not arrive.
        if self._report_undelivered() and code == EXIT_OK:
            code = EXIT_UNDELIVERED
        log.info(
            "session ended (%s), exit %d: %d requests scored",
            self.stop_reason or "done",
            code,
            self.scored,
        )
        if self.session and not self.session_closed:
            log.info(
                "the broker was not told this session ended: it stopped between leases "
                "with nothing held (no release was due)"
            )
        return code

    def _session(self) -> int:
        try:
            self._preflight()
            ok = self._hello()
            self._start_heartbeat()
            try:
                self._serve(ok)
            finally:
                self._stop_heartbeat()
                self._unload()
        except _Fatal as e:
            log.error("%s", e)
            return e.code
        except Unauthorized as e:
            log.error("the broker refused the token: %s", e)
            return EXIT_AUTH
        except Forbidden as e:
            log.error("the broker refused a model key: %s", e)
            return EXIT_AUTH
        except Unreachable as e:
            log.error("the broker is unreachable: %s", e)
            return EXIT_UNREACHABLE
        return EXIT_OK

    def _preflight(self) -> None:
        cfg = self.cfg
        limit = judges.cgroup_memory_max()
        if cfg.memory_gib and limit is not None and limit < cfg.memory_gib * 2**30:
            raise _Fatal(
                EXIT_CONFIG,
                f"the container may use {limit / 2**30:.1f} GiB, the model is expected to need "
                f"{cfg.memory_gib} GiB: it would be killed mid-job (raise --memory or lower "
                "memory_gib)",
            )
        if cfg.nice:
            import os

            try:
                os.nice(cfg.nice)
            except OSError as e:  # never fatal: the container's cpu-shares still apply
                log.warning("could not lower the priority by %d: %s", cfg.nice, e)
        if cfg.weights_cache is not None:
            import os

            if not cfg.weights_cache.is_dir():
                raise _Fatal(EXIT_CONFIG, f"weights_cache {cfg.weights_cache} does not exist")
            if os.access(cfg.weights_cache, os.W_OK):
                log.warning("weights_cache %s is writable; mount it read-only", cfg.weights_cache)

    def _hello(self) -> list[str]:
        cfg = self.cfg
        body = {
            "worker": cfg.name,
            "models": {
                k: {
                    "model_version": PINS[k].model_version,
                    "weights_revision": PINS[k].weights_revision,
                }
                for k in cfg.models
            },
            "image": self.image,
            "device": cfg.device,
            "dtype": cfg.dtype,
            "threads": cfg.threads,
            "config": cfg.hello_config(),
        }
        resp = self.broker.hello(body)
        self.session = resp["session"]
        if resp.get("heartbeat_s"):
            self.heartbeat_s = min(self.heartbeat_s, float(resp["heartbeat_s"]))
        if resp.get("lease_s"):  # the broker's lease length is the one that applies
            self.heartbeat_s = min(self.heartbeat_s, float(resp["lease_s"]) / 2)
        ok = []
        for key in cfg.models:
            answer = (resp.get("models") or {}).get(key) or {}
            if answer.get("ok"):
                ok.append(key)
                log.info(
                    "hello: %s %s ok, %s requests queued",
                    key,
                    PINS[key].model_version,
                    answer.get("queued_requests"),
                )
            else:
                log.error(
                    "hello: %s is not ok: this worker serves %s, the broker's registry %s; "
                    "it will not be leased",
                    key,
                    PINS[key].model_version,
                    answer.get("model_version"),
                )
        log.info(
            "session %s: worker %s, %s on %s %s, threads %s, window %s",
            self.session,
            cfg.name,
            ",".join(cfg.models),
            cfg.device,
            cfg.dtype,
            cfg.threads,
            cfg.schedule.describe(),
        )
        if not ok:
            raise _Fatal(EXIT_VERSION, "no model key this worker serves is the broker's version")
        return ok

    def _serve(self, ok: list[str]) -> None:
        while self._may_continue():
            empty = 0
            for key in ok:
                if not self._may_continue():
                    return
                if self._drain(key) == "empty":
                    empty += 1
            if empty < len(ok):
                continue  # stopped, or the window is ending: the loop condition decides
            if self.cfg.schedule.on_empty == "exit":
                self.stop_reason = "the queue is empty"
                log.info("the queue is empty; exiting (on_empty = exit)")
                return
            wait = self.cfg.schedule.poll_s
            if self._closes_at() is not None:
                wait = min(wait, self._seconds_left())
            log.info("the queue is empty; polling again in %.0f s", wait)
            if self.clock.wait(wait, self.stop):
                return

    def _drain(self, key: str) -> str:
        """Lease and score `key`'s jobs until its queue is empty ("empty") or the session
        must stop ("stop")."""
        while self._may_continue():
            left = self._seconds_left()
            if left < self.spr[key]:
                self.request_stop("too little of the window is left for one request")
                return "stop"
            try:
                lease = self.broker.lease(
                    {
                        "session": self.session,
                        "model": key,
                        "model_version": PINS[key].model_version,
                        "max_jobs": self.cfg.max_jobs,
                        "seconds_left": int(left),
                        "seconds_per_request": max(1, round(self.spr[key])),
                    }
                )
            except VersionDrift as e:
                raise _Fatal(
                    EXIT_VERSION,
                    f"lease {key}: the broker's version is {e.body.get('current')!r}, this "
                    f"worker serves {PINS[key].model_version!r}",
                ) from None
            jobs = lease.get("jobs") or []
            if not lease.get("lease_id") or not jobs:
                self.session_closed = True  # an empty lease ends the session at the broker
                return "empty"
            self.session_closed = False  # a lease with jobs reopens it
            self._process_lease(key, lease["lease_id"], jobs)
        return "stop"

    # -- one lease -------------------------------------------------------------------------

    def _process_lease(self, key: str, lease_id: str, jobs: list[dict]) -> None:
        with self.held.lock:
            self.held.leases[lease_id] = {j["job_id"] for j in jobs}
        started: set[int] = set()
        try:
            if not self._may_continue():  # stopped while leasing: no load, nothing scored
                self._release(lease_id, [j["job_id"] for j in jobs], "graceful")
                return
            judge = self._ensure_loaded(key, lease_id, jobs)
            unfinished: list[int] = []
            for job in jobs:
                if unfinished or not self._may_continue():
                    unfinished.append(job["job_id"])
                    continue
                started.add(job["job_id"])
                if not self._process_job(judge, key, lease_id, job):
                    unfinished.append(job["job_id"])
            if unfinished:
                self._release(lease_id, unfinished, "graceful")
        except _Fatal:
            # The jobs never started go back with no attempt counted; the one that failed
            # was already released as an error.
            rest = [j["job_id"] for j in jobs if j["job_id"] not in started]
            if rest:
                self._release(lease_id, rest, "graceful")
            raise
        finally:
            with self.held.lock:
                self.held.leases.pop(lease_id, None)
                self.held.progress = None

    def _ensure_loaded(self, key: str, lease_id: str, jobs: list[dict]) -> judges.Judge:
        if self.judge is not None and self.judge.key == key:
            return self.judge
        self._unload()
        cfg = self.cfg
        rt = judges.Runtime(cfg.device, cfg.dtype, cfg.threads, cfg.mmap, cfg.weights_cache)
        log.info("loading %s (%s, %s) for lease %s", key, cfg.device, cfg.dtype, lease_id)
        try:
            self.judge = self.load_judge(key, rt)
        except Exception as e:  # noqa: BLE001 - every load failure ends the session the same way
            # The jobs are not at fault, so no attempt is counted: a misconfigured worker
            # restarted by a timer must not turn healthy jobs dead. Exit 2 carries the error.
            msg = f"{type(e).__name__}: {str(e)[:400]}"
            self._release(lease_id, [j["job_id"] for j in jobs], "graceful")
            raise _Fatal(EXIT_CONFIG, f"could not load {key}: {msg}") from None
        info = self.judge.info
        self.judge_info[key] = info
        log.info("loaded %s: %s", key, json.dumps(info, default=str))
        peak = info.get("peak_rss_bytes")
        if cfg.memory_gib and peak and peak > cfg.memory_gib * 2**30:
            log.warning(
                "%s peaked at %.1f GiB, above memory_gib = %s", key, peak / 2**30, cfg.memory_gib
            )
        return self.judge

    def _unload(self) -> None:
        if self.judge is not None:
            log.info("unloading %s", self.judge.key)
            judges.unload(self.judge, self.cfg.device)
            self.judge = None

    def _process_job(self, judge: judges.Judge, key: str, lease_id: str, job: dict) -> bool:
        """Score one job's requests in the order the broker sent them, then submit.
        True when the job needs nothing more from this worker."""
        job_id = job["job_id"]
        requests = job.get("requests") or []
        if not requests:  # the contract says a job never carries zero orders; never hold one
            self._release(lease_id, [job_id], "error", "the job carried no requests")
            return True
        scores: list[dict] = []
        complete = True
        for req in requests:
            if (lease_id, job_id) in self.held.lost:
                break
            if not self._may_continue():
                complete = False
                break
            closes = self._closes_at()
            if closes is not None and self._seconds_left() < self.spr[key]:
                self.request_stop("the next request would not finish inside the window")
                complete = False
                break
            payload = req.get("payload")
            if request_sha256(payload) != req.get("request_sha256"):
                # Never score something other than what the broker rendered and hashed.
                self._submit(lease_id, job_id, scores)
                self._release(lease_id, [job_id], "error", "request_sha256 does not match payload")
                return True
            with self.held.lock:
                self.held.progress = {"job_id": job_id, "order": req.get("order")}
            t0 = self.clock.monotonic()
            try:
                p, extra = judge.score(payload)
            except Exception as e:  # noqa: BLE001 - recorded on the job, never swallowed
                self._submit(lease_id, job_id, scores)
                self._release(lease_id, [job_id], "error", f"{type(e).__name__}: {str(e)[:400]}")
                self.failed_jobs.add(job_id)
                log.error("job %s %s failed: %s", job_id, req.get("order"), type(e).__name__)
                if len(self.failed_jobs) >= MAX_CONSECUTIVE_ERRORS:
                    raise _Fatal(
                        EXIT_ERROR, f"{key} failed on {len(self.failed_jobs)} jobs in a row"
                    ) from None
                return True
            seconds = self.clock.monotonic() - t0
            self.failed_jobs.clear()
            self.scored += 1
            # Seconds per request, for lease sizing and the window check: a moving average.
            if key in self._measured:
                self.spr[key] = 0.7 * self.spr[key] + 0.3 * seconds
            else:
                self.spr[key] = seconds
                self._measured.add(key)
            scores.append(
                {
                    "order": req.get("order"),
                    "request_sha256": req["request_sha256"],
                    "p": p,
                    "seconds": round(seconds, 3),
                    "extra": extra,
                }
            )
            log.info("job %s %s: %.4f in %.1f s", job_id, req.get("order"), p, seconds)
        if (lease_id, job_id) in self.held.lost:
            for s in scores:
                log.warning(
                    "job %s: lease lost; dropping %s %s p=%.4f (another worker holds the job)",
                    job_id,
                    s["order"],
                    s["request_sha256"],
                    s["p"],
                )
            return True
        self._submit(lease_id, job_id, scores)
        return complete

    def _submit(self, lease_id: str, job_id: int, scores: list[dict]) -> None:
        if not scores:
            return
        cfg = self.cfg
        body = {
            "session": self.session,
            "lease_id": lease_id,
            "job_id": job_id,
            "scores": scores,
            "device": cfg.device,
            "dtype": cfg.dtype,
            "threads": cfg.threads,
        }
        try:
            resp = self.broker.results(body)
        except Unreachable:
            self.undelivered.extend({"job_id": job_id, **s} for s in scores)
            raise
        except LeaseLost:
            log.warning(
                "job %s: results refused, lease lost (%s); the job's new holder scores it",
                job_id,
                ", ".join(f"{s['order']} {s['request_sha256']} p={s['p']:.4f}" for s in scores),
            )
            return
        except (Invalid, BrokerError) as e:
            self.undelivered.extend({"job_id": job_id, "refused": str(e), **s} for s in scores)
            log.error("job %s: results refused: %s", job_id, e)
            return
        log.info(
            "job %s: %s accepted, %s duplicate, job %s",
            job_id,
            resp.get("accepted"),
            resp.get("duplicate"),
            resp.get("job"),
        )

    def _release(self, lease_id: str, job_ids: list[int], reason: str, error=None) -> None:
        body = {"session": self.session, "lease_id": lease_id, "job_ids": job_ids, "reason": reason}
        if error:
            body["error"] = error
        try:
            resp = self.broker.release(body)
            log.info("released %s (%s): %s", job_ids, reason, resp)
            if reason == "graceful":
                self.session_closed = True  # a graceful release ends the session at the broker
        except LeaseLost as e:
            log.warning("release of %s: lease already lost (%s)", job_ids, e.job_ids)
        except BrokerError as e:
            log.warning("release of %s refused: %s", job_ids, e)

    def _report_undelivered(self) -> bool:
        for s in self.undelivered:
            log.error(
                "UNDELIVERED score: job %s %s %s p=%.6f%s",
                s["job_id"],
                s["order"],
                s["request_sha256"],
                s["p"],
                f" ({s['refused']})" if s.get("refused") else "",
            )
        return bool(self.undelivered)

    # -- heartbeat -------------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        self._hb_stop.clear()
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, name="heartbeat", daemon=True
        )
        self._hb_thread.start()

    def _stop_heartbeat(self) -> None:
        self._hb_stop.set()
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=10)

    def _heartbeat_loop(self) -> None:
        while not self._hb_stop.wait(self.heartbeat_s):
            try:
                self.heartbeat_once()
            except Exception:  # noqa: BLE001 - a dead heartbeat thread would lose every lease
                log.exception("heartbeat failed unexpectedly")

    def heartbeat_once(self) -> None:
        with self.held.lock:
            lease_ids = sorted(self.held.leases)
            job_ids = sorted(
                j
                for lid in lease_ids
                for j in self.held.leases[lid]
                if (lid, j) not in self.held.lost
            )
            progress = dict(self.held.progress) if self.held.progress else None
        if not lease_ids:
            return
        body = {
            "session": self.session,
            "lease_ids": lease_ids,
            "job_ids": job_ids,
            "rss_bytes": judges.proc_status("VmRSS"),
        }
        if progress:
            body["progress"] = progress
        try:
            self.broker.heartbeat(body)
        except LeaseLost as e:
            # The live leases were extended all the same; drop only what was lost, and only
            # jobs still held under the leases this heartbeat named (one released or
            # finished meanwhile is not this worker's to drop).
            lost_jobs = set(e.job_ids)
            lost_leases = set(e.body.get("lease_ids") or [])
            with self.held.lock:
                marked = {
                    (lid, j)
                    for lid in lease_ids
                    for j in self.held.leases.get(lid, ())
                    if j in lost_jobs or lid in lost_leases
                }
                self.held.lost.update(marked)
            log.warning("heartbeat: lost %s; dropping them", sorted(j for _, j in marked))
        except (BrokerError, Unreachable) as e:
            log.warning("heartbeat failed: %s", e)
