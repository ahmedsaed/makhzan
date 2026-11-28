"""One worker session, from hello to the last release (docs/ai/worker.md, "Lifecycle").

1. Outside every window: exit 0, nothing sent.
A worker serves exactly one model key (`cfg.model`): the broker takes one model per
session, so two models are two workers.

2. Pre-flight: the model key must be loadable in this image; the container's memory
   limit against `memory_gib`; then lower the process priority (`nice`).
3. `POST /hello` with the name, the model key and its versions, device, dtype and
   threads. If the broker answers `ok: false` (version drift), nothing is leased: exit 3.
4. Until the queue is empty or the window ends:
   `POST /lease` for up to `max_jobs` jobs (no time is sent: the worker takes what it is
   given and drops what the window's end interrupts); the
   model is loaded on the first lease that brings jobs, never on an empty night, and
   checked against its pins (`judges.load`); each job's requests are scored **in the
   order given, one per call**, each request's `request_sha256` first checked against
   its payload, and `POST /results` after each job. Each lease carries a fresh
   `lease_request_id` (the same on a retry of that call, so a lost answer gives the same
   lease back).
   A heartbeat goes out as each job starts, naming it in hand (so an expiry is charged to
   it alone), and a background thread sends one every `heartbeat_s` naming the jobs still
   held. Each job's prompt version is compared with the stages hello announced.
5. Stop (the window's end, SIGTERM, SIGINT): the current job is dropped. No new request
   is started, the one in flight finishes (a forward pass cannot be interrupted), the
   finished orders are submitted, the rest of the lease (the current job's unscored
   orders included) goes back with `/release` reason "graceful", no attempt charged, for
   another worker or a later window, and the model is unloaded. The window's end is enforced by a timer and checked between
   retries, so a call retrying through a broker outage cannot keep the model loaded past
   the window. A stop sets one deadline for the rest of the session (`broker.STOP_GRACE_S`,
   short socket timeouts), so all of this fits a `docker stop` grace period.
6. Empty queues: `on_empty = "exit"` exits; `"wait"` polls every `poll_s` until the
   window ends.
7. Every session that said hello is ended at the broker exactly once (P16): by an empty
   lease, by a graceful release of held jobs, or else by `POST /release {"session"}`, a
   graceful release naming no jobs (broker-api.md §3.5), however it stopped. A session
   release is not sent after the broker already recorded the end (it would overwrite
   "empty" with "released"), nor to a broker that is unreachable or refused the token. A
   stop that comes before hello opens no session at all.

**Never drop a result silently.** A score is logged at ERROR as `UNDELIVERED`, with its
job, order, request hash and score (never the payload), the moment it is known not to
have arrived: the broker unreachable past the retry budget or the stop deadline, or the
broker refusing it. The exit code says the session did not end clean. Any unexpected
error is caught, logged, and the jobs still held are handed back.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from makhzan_ml.worker import judges
from makhzan_ml.worker.broker import (
    Broker,
    BrokerError,
    Forbidden,
    LeaseLost,
    Unauthorized,
    Unreachable,
    VersionDrift,
)
from makhzan_ml.worker.config import Config

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
#: max_vddgfx_mv: how often a worker waiting for the card's voltage reads it (often enough that a
#: busy spell rarely falls between two readings), how long after a reading above the limit the
#: second, confirming one is taken, and the retries of a failed read before it is fatal.
CARD_SAMPLE_S = 5.0
CARD_CONFIRM_S = 0.5
CARD_READ_TRIES = 3
CARD_RETRY_S = 1.0


def canonical_json(request: object) -> str:
    """`makhzan_schemas.ai.prompt.canonical_json`, byte for byte (a test holds them equal):
    what `request_sha256` is taken over."""
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def image_reference(env: dict[str, str] | None = None) -> str | None:
    """What hello reports as `image` (the broker keeps it as given, in the session's hello).

    `MAKHZAN_IMAGE` when set (a digest the host resolved, or a local build's id). Else what
    the image says of itself, from the build: `MAKHZAN_IMAGE_REPO` and
    `MAKHZAN_IMAGE_REVISION` (ml/worker.Dockerfile), the commit CI built it from, given as
    `<repo>:sha-<commit>`, the tag CI puts on exactly that tested build; a local build
    without a revision is `<repo>:local`. None when the image records neither."""
    env = os.environ if env is None else env
    explicit = (env.get("MAKHZAN_IMAGE") or "").strip()
    if explicit:
        return explicit
    revision = (env.get("MAKHZAN_IMAGE_REVISION") or "").strip()
    if not revision:
        return None
    repo = (env.get("MAKHZAN_IMAGE_REPO") or "").strip() or "unnamed"
    return f"{repo}:local" if revision == "local" else f"{repo}:sha-{revision}"


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
    """The jobs this worker holds, by lease, shared with the heartbeat thread. A job leaves
    when it is submitted in full, released, or found lost."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    leases: dict[str, set[int]] = field(default_factory=dict)  # lease_id -> job ids
    lost: set[tuple[str, int]] = field(default_factory=set)  # (lease_id, job_id)
    #: Being submitted in full or released right now: no longer named, never marked lost.
    settling: set[tuple[str, int]] = field(default_factory=set)
    progress: dict | None = None


class Worker:
    def __init__(
        self,
        cfg: Config,
        broker: Broker | None = None,
        *,
        load_judge: Callable[[str, judges.Runtime], judges.Judge] = judges.load,
        importable: Callable[[str], bool] = judges.importable,
        clock: Clock | None = None,
        image: str | None = None,
    ):
        self.cfg = cfg
        self.broker = broker or Broker(
            cfg.broker_url, cfg.token, ca_file=cfg.ca_file, retry_max_s=cfg.retry_max_s
        )
        self.load_judge = load_judge
        self.importable = importable
        self.clock = clock or Clock(cfg)
        self.image = image
        self.stop = threading.Event()
        # A stop wakes the broker's backoff and sets its deadline; between retries the
        # broker asks whether the window has ended.
        self.broker.stop_event = self.stop
        self.broker.cutoff = self._window_open
        self.broker.until_cutoff = self._seconds_to_window_end
        self.stop_reason: str | None = None
        self.session: str | None = None
        self.heartbeat_s = cfg.heartbeat_s
        # Threads: as configured, else the container's CPU quota (never the host's cores).
        self.threads = cfg.threads or (judges.default_threads() if cfg.device == "cpu" else None)
        self.judge: judges.Judge | None = None
        self.held = _Held()
        self.key = cfg.model  # the one model this worker serves
        self.pin = cfg.pin  # what it serves it as: the key's pin on the configured backend
        self.judge_info: dict[str, dict] = {}  # what each load reported, kept after unloading
        self.undelivered: list[dict] = []
        self.session_closed = False  # the broker has recorded the session's end (P16)
        self.token_refused = False  # a 401: the broker will hear nothing more from us
        self.stages: dict[str, str] = {}  # "pipeline/stage" -> prompt version, from hello
        self.failed_jobs: set[int] = set()  # distinct jobs failed since the last success
        self.scored = 0
        self.card_wait_s = 0.0  # time spent waiting for the card's voltage (max_vddgfx_mv)
        self._card_high_at: float | None = None  # monotonic time of the last reading above it
        self._hb_thread: threading.Thread | None = None
        self._hb_stop = threading.Event()
        self._window_timer: threading.Timer | None = None

    # -- control ---------------------------------------------------------------------------

    def request_stop(self, reason: str = "stop requested") -> None:
        if not self.stop.is_set():
            self.stop_reason = reason
            log.info("stopping: %s", reason)
            self.broker.stopping()
            self.stop.set()

    def install_signal_handlers(self) -> None:
        """SIGTERM and SIGINT stop the session, signal-safely: the handler itself does
        nothing (a `threading.Event.set` there could deadlock on a lock the interrupted code
        holds). Python writes each signal's number to a wakeup pipe, and a watcher thread
        reading it calls `request_stop`, at once, even while the main thread is inside a
        forward pass."""
        r, w = os.pipe()
        os.set_blocking(w, False)
        signal.set_wakeup_fd(w, warn_on_full_buffer=False)

        def watch() -> None:
            while True:
                try:
                    data = os.read(r, 64)
                except OSError:
                    return
                if not data:
                    return
                for signum in data:
                    if signum in (signal.SIGTERM, signal.SIGINT):
                        self.request_stop(signal.Signals(signum).name)

        threading.Thread(target=watch, name="signals", daemon=True).start()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda _signum, _frame: None)  # the wakeup fd does the work

    def _closes_at(self) -> datetime | None:
        return self.cfg.schedule.closes_at(self.clock.now())

    def _seconds_to_window_end(self) -> float | None:
        """Real seconds until the window ends (None: always open). Real elapsed time, not a
        wall-clock difference, so a DST change inside the window does not move it."""
        closes = self._closes_at()
        if closes is None:
            return None
        return max(0.0, closes.timestamp() - self.clock.now().timestamp())

    def _window_open(self) -> bool:
        if self.cfg.schedule.is_open(self.clock.now()):
            return True
        self.request_stop("the window has ended")
        return False

    def _may_continue(self) -> bool:
        return not self.stop.is_set() and self._window_open()

    def _too_late(self) -> bool:
        """Inside the window's last `no_new_lease_s`: no new lease, no model load, so
        neither can keep a model in memory past the window (one model at a time)."""
        left = self._seconds_to_window_end()
        return left is not None and left <= self.cfg.schedule.no_new_lease_s

    def _start_window_timer(self) -> None:
        """Stop at the window's end even while blocked in a broker call's backoff."""
        if self._closes_at() is None:
            return
        self._window_timer = threading.Timer(
            self._seconds_to_window_end(), self.request_stop, args=("the window has ended",)
        )
        self._window_timer.daemon = True
        self._window_timer.start()

    # -- the session -----------------------------------------------------------------------

    def run(self) -> int:
        if not self.cfg.schedule.is_open(self.clock.now()):
            log.info("outside the window (%s); nothing to do", self.cfg.schedule.describe())
            return EXIT_OK
        if self._too_late():
            log.info(
                "the window ends in %.0f s, inside no_new_lease_s = %.0f; nothing to do",
                self._seconds_to_window_end(),
                self.cfg.schedule.no_new_lease_s,
            )
            return EXIT_OK
        code = EXIT_ERROR
        try:
            code = self._session()
        finally:
            if self._window_timer is not None:
                self._window_timer.cancel()
            # Every exit path, whatever ended the session, says which scores did not arrive.
            if self.undelivered:
                log.error(
                    "%d score(s) were not delivered; each is logged above",
                    len(self.undelivered),
                )
                if code == EXIT_OK:
                    code = EXIT_UNDELIVERED
            log.info(
                "session ended (%s), exit %d: %d requests scored",
                self.stop_reason or "done",
                code,
                self.scored,
            )
            if self.card_wait_s:
                log.info("waited %.0f s in all for the card's voltage", self.card_wait_s)
        return code

    def _end_session(self) -> None:
        """`POST /release {"session"}`: the broker records the session's end (P16), once."""
        if self.session is None or self.session_closed:
            return
        try:
            self.broker.release({"session": self.session, "reason": "graceful"})
            self.session_closed = True
            log.info("session %s ended at the broker", self.session)
        except (BrokerError, Unreachable) as e:
            log.warning("could not tell the broker the session ended: %s", e)

    def _session(self) -> int:
        code = self._session_body()
        # Not to a broker that is down or refused the token; a 403 (a model key it will not
        # grant) still ends the session the token opened.
        if code != EXIT_UNREACHABLE and not self.token_refused:
            self._end_session()
        return code

    def _session_body(self) -> int:
        self._start_window_timer()
        try:
            self._preflight()
            if self.stop.is_set():  # stopped before hello: open no session at all
                log.info("stopped before hello (%s); no session opened", self.stop_reason)
                return EXIT_OK
            self._hello()
            self._start_heartbeat()
            try:
                self._serve()
            finally:
                self._stop_heartbeat()
                self._unload()
        except _Fatal as e:
            log.error("%s", e)
            return e.code
        except Unauthorized as e:
            self.token_refused = True
            log.error("the broker refused the token: %s", e)
            return EXIT_AUTH
        except Forbidden as e:
            log.error("the broker refused a model key: %s", e)
            return EXIT_AUTH
        except Unreachable as e:
            log.error("the broker is unreachable: %s", e)
            return EXIT_UNREACHABLE
        except BrokerError as e:  # an answer this worker has no handling for (400, 404, 413 ...)
            log.error("the broker answered something unexpected: %s", e)
            return EXIT_ERROR
        except Exception:  # noqa: BLE001 - logged in full; the held jobs were handed back
            log.exception("unexpected error")
            return EXIT_ERROR
        return EXIT_OK

    def _preflight(self) -> None:
        cfg = self.cfg
        # A llama.cpp backend needs no model code here: the sidecar holds the model.
        if cfg.backend == "torch" and not self.importable(self.key):
            raise _Fatal(
                EXIT_CONFIG,
                f"this image cannot load {self.key!r}: each model image holds one model's code "
                "(use the image built on that model's base)",
            )
        limit = judges.cgroup_memory_max()
        if cfg.memory_gib and limit is None:
            log.warning(
                "memory_gib = %s not checked: no cgroup v2 memory limit is visible "
                "(no --memory, or cgroup v1)",
                cfg.memory_gib,
            )
        if cfg.memory_gib and limit is not None and limit < cfg.memory_gib * 2**30:
            raise _Fatal(
                EXIT_CONFIG,
                f"the container may use {limit / 2**30:.1f} GiB, the model is expected to need "
                f"{cfg.memory_gib} GiB: it would be killed mid-job (raise --memory or lower "
                "memory_gib)",
            )
        if cfg.nice:
            try:
                os.nice(cfg.nice)
            except OSError as e:  # never fatal: the container's cpu-shares still apply
                log.warning("could not lower the priority by %d: %s", cfg.nice, e)
        if cfg.weights_cache is not None:
            if not cfg.weights_cache.is_dir():
                raise _Fatal(EXIT_CONFIG, f"weights_cache {cfg.weights_cache} does not exist")
            if os.access(cfg.weights_cache, os.W_OK):
                log.warning("weights_cache %s is writable; mount it read-only", cfg.weights_cache)

    def _hello(self) -> None:
        cfg, key = self.cfg, self.key
        body = {
            "worker": cfg.name,
            "models": {  # exactly one: the broker takes one model per session
                key: {
                    "model_version": self.pin.model_version,
                    "weights_revision": self.pin.weights_revision,
                }
            },
            "image": self.image,
            "device": cfg.device,
            "dtype": cfg.dtype,
            "threads": self.threads,
            "config": cfg.hello_config(),
        }
        resp = self.broker.hello(body)
        if not isinstance(resp, dict) or not resp.get("session"):
            raise _Fatal(EXIT_ERROR, "hello: the broker's answer carries no session")
        self.session = resp["session"]
        if resp.get("heartbeat_s"):
            self.heartbeat_s = min(self.heartbeat_s, float(resp["heartbeat_s"]))
        if resp.get("lease_s"):  # the broker's lease length is the one that applies
            self.heartbeat_s = min(self.heartbeat_s, float(resp["lease_s"]) / 2)
        answer = (resp.get("models") or {}).get(key) or {}
        self.stages = {
            f"{st.get('pipeline')}/{st.get('stage')}": st.get("prompt_version")
            for st in answer.get("stages") or []
            if isinstance(st, dict)
        }
        if self.stages:
            log.info(
                "hello: %s stages: %s",
                key,
                ", ".join(f"{k} prompt {v}" for k, v in sorted(self.stages.items())),
            )
        log.info(
            "session %s: worker %s, %s on %s %s, threads %s, window %s",
            self.session,
            cfg.name,
            key,
            cfg.device,
            cfg.dtype,
            self.threads,
            cfg.schedule.describe(),
        )
        if not answer.get("ok"):
            raise _Fatal(
                EXIT_VERSION,
                f"hello: {key} is not ok: this worker serves {self.pin.model_version}, the "
                f"broker's registry {answer.get('model_version')}; nothing will be leased",
            )
        log.info(
            "hello: %s %s ok, %s requests queued",
            key,
            self.pin.model_version,
            answer.get("queued_requests"),
        )

    def _serve(self) -> None:
        while self._may_continue():
            outcome = self._drain(self.key)
            if outcome == "stop" or not self._may_continue():
                return  # stopped, or the window ended
            # The queue is empty.
            if self.cfg.schedule.on_empty == "exit":
                self.stop_reason = "the queue is empty"
                log.info("the queue is empty; exiting (on_empty = exit)")
                return
            wait = self.cfg.schedule.poll_s
            left = self._seconds_to_window_end()
            if left is not None:
                wait = min(wait, left)
            log.info("the queue is empty; polling again in %.0f s", wait)
            if self.clock.wait(wait, self.stop):
                return

    def _drain(self, key: str) -> str:
        """Lease and score `key`'s jobs until its queue is empty ("empty") or the session
        must stop ("stop"). A lease asks for up to `max_jobs`: no time is sent, and what the
        window's end interrupts goes back gracefully."""
        while self._may_continue():
            if not self._wait_for_card():
                return "stop"
            if self._too_late():
                self.request_stop(
                    f"no new lease in the window's last {self.cfg.schedule.no_new_lease_s:.0f} s"
                )
                return "stop"
            body = {
                "session": self.session,
                "model": key,
                "model_version": self.pin.model_version,
                "max_jobs": self.cfg.max_jobs,
                # One id per lease attempt, the same on the client's retries of it: a lease
                # whose answer was lost comes back as the same lease, not orphaned.
                "lease_request_id": uuid.uuid4().hex,
            }
            try:
                lease = self.broker.lease(body)
            except VersionDrift as e:
                raise _Fatal(
                    EXIT_VERSION,
                    f"lease {key}: the broker's version is {e.body.get('current')!r}, this "
                    f"worker serves {self.pin.model_version!r}",
                ) from None
            jobs = lease.get("jobs") or []
            if not lease.get("lease_id") or not jobs:
                self.session_closed = True  # an empty lease ends the session at the broker
                return "empty"
            self.session_closed = False  # a lease with jobs reopens it
            self._check_prompts(key, jobs)
            self._process_lease(key, lease["lease_id"], jobs)
        return "stop"

    # -- the card's voltage ----------------------------------------------------------------

    def _read_card(self) -> int | None:
        """The card's voltage, a failed read retried CARD_READ_TRIES times CARD_RETRY_S apart.
        None when a stop came meanwhile. Still unreadable: the session ends (_Fatal), since
        with the check on, scoring blind is what it exists to prevent."""
        for attempt in range(CARD_READ_TRIES):
            try:
                return judges.read_vddgfx_mv()
            except judges.SensorUnavailable as e:
                if attempt + 1 == CARD_READ_TRIES:
                    raise _Fatal(
                        EXIT_CONFIG,
                        f"max_vddgfx_mv = {self.cfg.max_vddgfx_mv} is set but the card's voltage "
                        f"cannot be read ({e}); refusing to score on the card",
                    ) from None
                log.warning("reading the card's voltage failed (%s); trying again", e)
                if self.clock.wait(CARD_RETRY_S, self.stop):
                    return None
        return None  # unreachable

    def _card_busy(self) -> tuple[int | None, bool]:
        """(the card's voltage in mV, whether the card counts as busy); (None, False) with the
        check off. Busy: above max_vddgfx_mv now (confirmed by a second reading CARD_CONFIRM_S
        later, so a voltage passing through on a state change does not count), or at any reading
        in the last vddgfx_clear_s. The hold is what keeps a job of many short video runs (one
        ffmpeg per item, the engine idle for a second between them) from looking finished in a
        gap. A stop during the reading counts as busy: nothing new starts."""
        limit = self.cfg.max_vddgfx_mv
        if not limit:
            return None, False
        mv = self._read_card()
        if mv is None:
            return None, True
        if mv > limit:
            if self.clock.wait(CARD_CONFIRM_S, self.stop):
                return mv, True
            again = self._read_card()
            if again is None:
                return mv, True
            mv = min(mv, again)
        now = self.clock.monotonic()
        if mv > limit:
            self._card_high_at = now
            return mv, True
        held = self._card_high_at is not None and now - self._card_high_at < self.cfg.vddgfx_clear_s
        return mv, held

    def _wait_for_card(self) -> bool:
        """Before a lease: while the card counts as busy (_card_busy), wait, holding no lease,
        reading it every CARD_SAMPLE_S, until it has read at most max_vddgfx_mv for
        vddgfx_clear_s on end. False when the session must stop (a stop, the window's end)."""
        mv, busy = self._card_busy()
        if not busy:
            return True
        limit = self.cfg.max_vddgfx_mv
        log.warning(
            "the card is at %s mV (above max_vddgfx_mv = %d now or in the last %.0f s: another "
            "app is using its video engine): waiting, holding no lease",
            mv,
            limit,
            self.cfg.vddgfx_clear_s,
        )
        t0 = self.clock.monotonic()
        try:
            while True:
                wait = CARD_SAMPLE_S
                left = self._seconds_to_window_end()
                if left is not None:
                    wait = min(wait, left)
                if self.clock.wait(wait, self.stop) or not self._may_continue():
                    log.info("stopped while waiting for the card (%s)", self.stop_reason)
                    return False
                mv, busy = self._card_busy()
                if not busy:
                    log.info(
                        "the card has read at most %d mV for %.0f s (now %s mV), after %.0f s: "
                        "scoring again",
                        limit,
                        self.cfg.vddgfx_clear_s,
                        mv,
                        self.clock.monotonic() - t0,
                    )
                    return True
        finally:
            self.card_wait_s += self.clock.monotonic() - t0

    # -- one lease -------------------------------------------------------------------------

    def _check_prompts(self, key: str, jobs: list[dict]) -> None:
        """Each job's prompt version should be one hello announced for this model. The
        broker renders, so a mismatch is only logged: the registry moved since hello."""
        known = set(self.stages.values())
        if not known:
            return
        for job in jobs:
            if job.get("prompt_version") not in known:
                log.warning(
                    "job %s: prompt version %s is not one hello announced for %s (%s)",
                    job.get("job_id"),
                    job.get("prompt_version"),
                    key,
                    ", ".join(sorted(known)),
                )

    def _held_jobs(self, lease_id: str) -> list[int]:
        """The lease's jobs still this worker's: not settled, not found lost (a release
        naming a lost job would be refused whole, 409)."""
        with self.held.lock:
            return sorted(
                j for j in self.held.leases.get(lease_id, ()) if (lease_id, j) not in self.held.lost
            )

    def _settling(self, lease_id: str, job_ids) -> None:
        """These jobs are being submitted in full or released. Heartbeats keep naming them
        (a final post retrying through an outage must keep its lease alive), but a 409 that
        names them is not marked lost: they are on their way out."""
        with self.held.lock:
            self.held.settling.update((lease_id, j) for j in job_ids)

    def _settle(self, lease_id: str, job_ids) -> None:
        """These jobs need nothing more from this worker: heartbeats stop naming them."""
        with self.held.lock:
            held = self.held.leases.get(lease_id)
            if held is not None:
                held.difference_update(job_ids)
            self.held.settling.difference_update((lease_id, j) for j in job_ids)

    def _process_lease(self, key: str, lease_id: str, jobs: list[dict]) -> None:
        with self.held.lock:
            self.held.leases[lease_id] = {j["job_id"] for j in jobs}
        try:
            # The window may have ended, or a stop come, while the lease was taken: then
            # nothing is loaded, and the whole lease goes back gracefully (below).
            if self._may_continue() and self.judge is None and self._too_late():
                # Taken just before the cutoff: no load this late. The lease goes back whole,
                # gracefully (below), and the session ends.
                self.request_stop(
                    f"no model load in the window's last {self.cfg.schedule.no_new_lease_s:.0f} s"
                )
            if self._may_continue():
                judge = self._ensure_loaded(key, lease_id)
                for job in jobs if judge is not None else ():
                    # Checked again before each job, so right after the load too: a stop that
                    # came during a long load scores nothing.
                    if not self._may_continue():
                        break
                    if not self._process_job(judge, key, lease_id, job):
                        break  # stopped mid-job
        except Unreachable:
            # A release would only retry against the same dead broker, for another full
            # budget; the held jobs come back to the queue when their leases expire.
            raise
        except BaseException:
            # Whatever went wrong (a model that keeps failing or will not load, an
            # unexpected answer, an interrupt), the jobs still held go back once, with
            # no attempt counted, before the error ends the session.
            rest = self._held_jobs(lease_id)
            if rest:
                try:
                    self._release(lease_id, rest, "graceful")
                except Exception as e:  # noqa: BLE001 - the original error matters more
                    log.warning("could not hand back %s: %s", rest, e)
            raise
        else:
            rest = self._held_jobs(lease_id)
            if rest:
                self._release(lease_id, rest, "graceful")
        finally:
            with self.held.lock:
                self.held.leases.pop(lease_id, None)
                self.held.progress = None

    def _ensure_loaded(self, key: str, lease_id: str) -> judges.Judge | None:
        """The session's model, loaded once, on the first lease that brings jobs."""
        if self.judge is not None:
            return self.judge
        cfg = self.cfg
        rt = judges.Runtime(
            cfg.device,
            cfg.dtype,
            self.threads,
            cfg.mmap,
            cfg.weights_cache,
            cfg.backend,
            cfg.llamacpp_url,
            cfg.gguf_path,
            self.stop,
            cfg.require_clock_limit,
        )
        log.info("loading %s (%s, %s) for lease %s", key, cfg.device, cfg.dtype, lease_id)
        try:
            self.judge = self.load_judge(key, rt)
        except judges.LoadInterrupted:
            # A stop came during an interruptible load: nothing is loaded, and the caller's
            # next check sees the stop and hands the lease back gracefully.
            log.info("load of %s interrupted by the stop", key)
            return None
        except Exception as e:  # noqa: BLE001 - every load failure ends the session the same way
            # The jobs are not at fault: the lease goes back gracefully (once, in
            # _process_lease), so a misconfigured worker restarted by a timer cannot turn
            # healthy jobs dead. Exit 2 carries the error.
            raise _Fatal(
                EXIT_CONFIG, f"could not load {key}: {type(e).__name__}: {str(e)[:400]}"
            ) from None
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
            judges.unload(self.judge, self.cfg.device, self.cfg.backend)
            self.judge = None

    def _lost(self, lease_id: str, job_id: int) -> bool:
        with self.held.lock:
            return (lease_id, job_id) in self.held.lost

    def _process_job(self, judge: judges.Judge, key: str, lease_id: str, job: dict) -> bool:
        """Score one job's requests in the order the broker sent them, then submit.
        False when the session stopped before the job was finished (it stays held, and
        goes back with the rest of the lease)."""
        job_id = job["job_id"]
        requests = job.get("requests") or []
        if not requests:  # the contract says a job never carries zero orders; never hold one
            self._release(lease_id, [job_id], "error", "the job carried no requests")
            return True
        scores: list[dict] = []
        # The job is now in hand: say so at once, so an expiry (a crash, a kill for memory)
        # is charged to this job alone, not to the lease's others that never started.
        with self.held.lock:
            self.held.progress = {"job_id": job_id, "order": requests[0].get("order")}
        self.heartbeat_once()
        for req in requests:
            if self._lost(lease_id, job_id):
                break
            if not self._may_continue():
                # The window ended or a stop came: drop the job here. Its finished orders
                # are posted; the rest goes back with the lease, gracefully.
                self._submit(lease_id, job_id, scores, final=False)
                return False
            try:
                mv, busy = self._card_busy()
            except _Fatal:
                self._submit(lease_id, job_id, scores, final=False)
                raise
            if busy:
                # Another app took the card's video engine mid-job (now, or within the hold):
                # no request at that voltage. As for a stop between orders, the finished ones
                # are posted and the job goes back with the lease, gracefully; the next lease
                # waits for the card.
                log.warning(
                    "job %s: the card is at %s mV, busy (max_vddgfx_mv = %d): giving it back",
                    job_id,
                    mv,
                    self.cfg.max_vddgfx_mv,
                )
                self._submit(lease_id, job_id, scores, final=False)
                return False
            payload = req.get("payload")
            if request_sha256(payload) != req.get("request_sha256"):
                # Never score something other than what the broker rendered and hashed.
                self._submit(lease_id, job_id, scores, final=False)
                self._release(lease_id, [job_id], "error", "request_sha256 does not match payload")
                return True
            with self.held.lock:
                self.held.progress = {"job_id": job_id, "order": req.get("order")}
            t0 = self.clock.monotonic()
            try:
                p, extra = judge.score(payload)
            except judges.ScoreInterrupted:
                # A stop between the retries of an over-long request: as for a stop between
                # orders, the finished ones are posted and the job goes back with the lease.
                self._submit(lease_id, job_id, scores, final=False)
                return False
            except Exception as e:  # noqa: BLE001 - recorded on the job, never swallowed
                self._submit(lease_id, job_id, scores, final=False)
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
        if self._lost(lease_id, job_id):
            for s in scores:
                log.warning(
                    "job %s: lease lost; dropping %s %s p=%.4f (another worker holds the job)",
                    job_id,
                    s["order"],
                    s["request_sha256"],
                    s["p"],
                )
            self._settle(lease_id, [job_id])
            return True
        self._submit(lease_id, job_id, scores, final=True)
        return True

    def _undelivered(self, job_id: int, scores: list[dict], why: str) -> None:
        """Scores that did not arrive: logged now, one line each, never only at exit."""
        for s in scores:
            self.undelivered.append({"job_id": job_id, **s})
            log.error(
                "UNDELIVERED score: job %s %s %s p=%.6f (%s)",
                job_id,
                s["order"],
                s["request_sha256"],
                s["p"],
                why,
            )

    def _submit(self, lease_id: str, job_id: int, scores: list[dict], *, final: bool) -> None:
        """Post a job's scores. `final`: the job is finished, so it is settled whatever the
        answer; otherwise it stays held for a release."""
        if final:
            self._settling(lease_id, [job_id])
        if scores:
            cfg = self.cfg
            body = {
                "session": self.session,
                "lease_id": lease_id,
                "job_id": job_id,
                "scores": scores,
                "device": cfg.device,
                "dtype": cfg.dtype,
                "threads": self.threads,
            }
            try:
                resp = self.broker.results(body)
            except Unreachable as e:
                self._undelivered(job_id, scores, f"broker unreachable: {e}")
                raise
            except LeaseLost as e:
                # Scored, posted, refused: they did not arrive from this worker. The job's
                # new holder may score it again, but these scores are lost: say so.
                self._undelivered(job_id, scores, f"refused, lease lost: {e}")
                self._settle(lease_id, [job_id])
                return
            except BrokerError as e:
                self._undelivered(job_id, scores, f"refused: {e}")
            except Exception as e:
                # Whether they arrived is unknown: say so before the error ends the session.
                self._undelivered(job_id, scores, f"{type(e).__name__} while posting: {e}")
                raise
            else:
                log.info(
                    "job %s: %s accepted, %s duplicate, job %s",
                    job_id,
                    resp.get("accepted"),
                    resp.get("duplicate"),
                    resp.get("job"),
                )
        if final:
            self._settle(lease_id, [job_id])

    def _release(self, lease_id: str, job_ids: list[int], reason: str, error=None) -> None:
        body = {"session": self.session, "lease_id": lease_id, "job_ids": job_ids, "reason": reason}
        if error:
            body["error"] = error
        self._settling(lease_id, job_ids)
        try:
            resp = self.broker.release(body)
            log.info("released %s (%s): %s", job_ids, reason, resp)
            if reason == "graceful":
                self.session_closed = True  # a graceful release ends the session at the broker
        except LeaseLost as e:
            log.warning("release of %s: lease already lost (%s)", job_ids, e.job_ids)
        except BrokerError as e:
            log.warning("release of %s refused: %s", job_ids, e)
        # Back with the broker, lost, or refused: none of them is this worker's to hold.
        self._settle(lease_id, job_ids)

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
            # Settling jobs are still named: their final post may be retrying, and the
            # lease must not expire under it.
            held = {
                lid: {j for j in jobs if (lid, j) not in self.held.lost}
                for lid, jobs in self.held.leases.items()
            }
            held = {lid: jobs for lid, jobs in held.items() if jobs}
            progress = dict(self.held.progress) if self.held.progress else None
        if not held:
            return
        lease_ids = sorted(held)
        body = {
            "session": self.session,
            "lease_ids": lease_ids,
            "job_ids": sorted(j for jobs in held.values() for j in jobs),
            "rss_bytes": judges.proc_status("VmRSS"),
        }
        if progress:
            body["progress"] = progress
        try:
            self.broker.heartbeat(body)
        except LeaseLost as e:
            # The live leases were extended all the same; drop only what was lost, and only
            # jobs still held under the leases this heartbeat named (one finished or
            # released meanwhile is not this worker's to drop).
            lost_jobs = set(e.job_ids)
            lost_leases = set(e.body.get("lease_ids") or [])
            with self.held.lock:
                marked = {
                    (lid, j)
                    for lid in lease_ids
                    for j in self.held.leases.get(lid, ())
                    if (j in lost_jobs or lid in lost_leases) and (lid, j) not in self.held.settling
                }
                self.held.lost.update(marked)
            if marked:  # a job finished or released meanwhile is no loss
                log.warning("heartbeat: lost %s; dropping them", sorted(j for _, j in marked))
        except (BrokerError, Unreachable) as e:
            log.warning("heartbeat failed: %s", e)
