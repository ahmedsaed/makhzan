"""Stay up between windows: `[schedule] outside_window = "wait"` (docs/ai/worker.md,
"Waiting for the window").

The process becomes a supervisor that never loads a model. Outside every window it sleeps
until the next one opens. When a window opens it forks a child that runs one ordinary
session (`run.Worker`, exactly what a worker started by a timer runs). The child stops
itself at the window's end with the usual graceful stop (the request in flight finished,
its scores submitted, the rest of the lease released, the session ended, the model
unloaded) and exits. Its exit returns every byte the model, torch and the allocator held:
nothing depends on `free()` giving memory back to the system, so the container drops back
to the supervisor's own few tens of MB between windows. Then the supervisor sleeps until
the next window, forever, until SIGTERM.

- **SIGTERM / SIGINT** while asleep: exit 0 at once. During a session: forwarded to the
  child, which stops gracefully; the supervisor then exits with the child's code.
- **An empty queue with `on_empty = "exit"`** ends that window's session early; the
  supervisor sleeps until the next window (not the rest of this one). With `on_empty =
  "wait"` the child keeps polling until the window's end, as before.
- **An unreachable broker** (exit 4) is tried again every `poll_s` while the window is
  open. **Any other failure** (a model that will not load, version drift, a refused token,
  a child killed for memory) is logged and the supervisor sleeps until the next window:
  restarting at once would only fail again, and `restart: unless-stopped` would turn an
  exit into a loop.
- With `windows = "always"` there is no next window: a session that ended is started again
  after `poll_s`.
- **One model at a time, enforced.** The child itself takes no new lease and starts no load
  in the window's last `no_new_lease_s` (run.py). If it is still running `KILL_AFTER_S`
  (4.5 minutes) after the window's end all the same, the supervisor SIGKILLs it, logged at
  ERROR, so the next worker's window (5 minutes later on the home server) never finds this
  model still in memory. Its lease then expires at the broker, charging the job in hand.

The child is a fork, so the parent must hold no model and no threads when it forks: it
imports nothing heavier than the worker's own standard-library modules (torch is only
imported by `judges.load`, in the child). SIGTERM and SIGINT are blocked across the fork,
and the stop flag is checked once they are blocked: a signal that came before is seen there
and nothing is forked; one that comes after is delivered to the parent once the child's pid
is known (and forwarded) and to the child once its own handlers are in place, never lost.

**Signal-safe.** The supervisor's handler only records the signal number; Python also writes
it to a wakeup pipe, which ends any sleep at once (`select`). The main loop turns the record
into a stop between waits, so no lock is ever taken inside a handler.
"""

from __future__ import annotations

import logging
import os
import select
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from makhzan_ml.worker import run
from makhzan_ml.worker.config import Config

log = logging.getLogger("makhzan_ml.worker.supervisor")

#: The longest single sleep: a sleep is re-measured against the wall clock at least this
#: often, so a clock change or a suspended host cannot make it overshoot by more.
SLEEP_CHUNK_S = 900.0

_SIGNALS = {signal.SIGTERM, signal.SIGINT}

#: How long after a window's end a session may still run before it is killed: above the
#: graceful stop's bound on the home server's CPU (about 170 s for a load in flight, about
#: 144 s for a request, docs/ai/worker.md), below the 5-minute gap before the next window.
KILL_AFTER_S = 270.0
#: How often the supervisor looks at its child while one runs.
POLL_S = 0.5


class WakeClock(run.Clock):
    """The real clock, whose waits also end at once when a signal arrives: they `select` on
    the wakeup pipe Python writes each signal's number to (`install_signal_handlers`)."""

    def __init__(self, cfg: Config):
        super().__init__(cfg)
        self.wake_fd: int | None = None

    def wait(self, seconds: float, stop: threading.Event) -> bool:
        if stop.is_set():
            return True
        if self.wake_fd is None:
            return stop.wait(max(0.0, seconds))
        ready, _, _ = select.select([self.wake_fd], [], [], max(0.0, seconds))
        if ready:
            try:
                os.read(self.wake_fd, 512)
            except BlockingIOError:
                pass
        return stop.is_set()


@dataclass
class Control:
    """What a session's runner gets from the supervisor."""

    #: Kill the session after this many seconds (the window's end + KILL_AFTER_S); None: never.
    deadline_s: float | None = None
    #: Whether the supervisor has been asked to stop (and, if so, has forwarded it).
    should_stop: Callable[[], bool] = lambda: False
    #: Pause up to this many seconds; a signal ends it early.
    pause: Callable[[float], None] = lambda s: None
    monotonic: Callable[[], float] = time.monotonic


class InProcessSession:
    """Runs each window's session in this process. For the tests (a fake judge, a fake clock
    shared with the supervisor); the image always forks (`ForkedSession`)."""

    def __init__(self, make_worker: Callable[[], run.Worker]):
        self.make_worker = make_worker
        self.worker: run.Worker | None = None

    def run(self, ctl: Control | None = None) -> int:
        self.worker = self.make_worker()
        try:
            return self.worker.run()
        finally:
            self.worker = None

    def stop(self, reason: str) -> None:
        worker = self.worker
        if worker is not None:
            worker.request_stop(reason)


class ForkedSession:
    """Runs each window's session in a forked child, which exits at the session's end."""

    def __init__(self, make_worker: Callable[[], run.Worker]):
        self.make_worker = make_worker
        self.pid: int | None = None

    def run(self, ctl: Control | None = None) -> int:
        ctl = ctl or Control()
        old = signal.pthread_sigmask(signal.SIG_BLOCK, _SIGNALS)
        if ctl.should_stop():  # a signal came before they were blocked: start nothing
            signal.pthread_sigmask(signal.SIG_SETMASK, old)
            log.info("stopped before the session started; nothing forked")
            return run.EXIT_OK
        for stream in (sys.stdout, sys.stderr):
            stream.flush()
        try:
            pid = os.fork()
        except BaseException:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)
            raise
        if pid == 0:  # the child: one session, then exit, whatever happens
            code = run.EXIT_ERROR
            try:
                worker = self.make_worker()
                worker.install_signal_handlers()
                signal.pthread_sigmask(signal.SIG_SETMASK, old)  # a pending SIGTERM lands now
                code = worker.run()
            except BaseException:  # noqa: BLE001 - the child must never return into the loop
                log.exception("the session's process failed")
            finally:
                for handler in logging.getLogger().handlers:
                    handler.flush()
                os._exit(code)
        self.pid = pid
        signal.pthread_sigmask(signal.SIG_SETMASK, old)  # a pending signal is recorded now
        try:
            ctl.should_stop()  # and forwarded to the child here, if it came
            return self._wait_child(pid, ctl)
        finally:
            self.pid = None

    def _wait_child(self, pid: int, ctl: Control) -> int:
        """Wait for the child, forwarding a stop, and kill it at the deadline. The exit code,
        negative when it died of a signal."""
        deadline = None if ctl.deadline_s is None else ctl.monotonic() + ctl.deadline_s
        while True:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status)
            ctl.should_stop()
            left = None if deadline is None else deadline - ctl.monotonic()
            if left is not None and left <= 0:
                log.error(
                    "KILLING the session (pid %d): still running %.0f s after the window's "
                    "end; SIGKILL, so its model is out of memory before the next window "
                    "(one model at a time). Its lease will expire at the broker.",
                    pid,
                    KILL_AFTER_S,
                )
                os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
                return os.waitstatus_to_exitcode(status)
            ctl.pause(POLL_S if left is None else min(POLL_S, left))

    def stop(self, reason: str) -> None:
        pid = self.pid
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


class Supervisor:
    def __init__(
        self,
        cfg: Config,
        session: InProcessSession | ForkedSession | None = None,
        *,
        clock: run.Clock | None = None,
        image: str | None = None,
    ):
        self.cfg = cfg
        self.clock = clock or WakeClock(cfg)
        self.session = session or ForkedSession(lambda: run.Worker(cfg, image=image))
        self.stop = threading.Event()
        self.stop_reason: str | None = None
        self.windows = 0  # sessions started
        self.codes: list[int] = []  # each session's exit code
        self._pid = os.getpid()
        self._signalled: int | None = None  # set by the handler, nothing else
        self._never = threading.Event()  # never set: pauses that a stop does not cut short
        self._saved: tuple | None = None

    # -- control ---------------------------------------------------------------------------

    def request_stop(self, reason: str) -> None:
        if not self.stop.is_set():
            self.stop_reason = reason
            log.info("stopping: %s", reason)
            self.stop.set()
        self.session.stop(reason)

    def install_signal_handlers(self) -> None:
        r, w = os.pipe()
        os.set_blocking(r, False)
        os.set_blocking(w, False)
        old_fd = signal.set_wakeup_fd(w, warn_on_full_buffer=False)
        if isinstance(self.clock, WakeClock):
            self.clock.wake_fd = r

        def handler(signum, _frame):
            if os.getpid() == self._pid:  # never act as the supervisor inside a child
                self._signalled = signum  # only a record: no lock is taken in a handler

        old = {sig: signal.signal(sig, handler) for sig in _SIGNALS}
        self._saved = (old_fd, old, r, w)

    def restore_signal_handlers(self) -> None:
        """Undo `install_signal_handlers` (for tests; the image's process just exits)."""
        if self._saved is None:
            return
        old_fd, old, r, w = self._saved
        for sig, h in old.items():
            signal.signal(sig, h)
        signal.set_wakeup_fd(old_fd)
        if isinstance(self.clock, WakeClock):
            self.clock.wake_fd = None
        os.close(r)
        os.close(w)
        self._saved = None

    def _stopped(self) -> bool:
        """Whether to stop; turns a recorded signal into a stop (and forwards it to a child)
        here, in the main loop, never in the handler."""
        signum = self._signalled
        if signum is not None and not self.stop.is_set():
            self.request_stop(signal.Signals(signum).name)
        return self.stop.is_set()

    def _wait(self, seconds: float) -> bool:
        """Sleep up to `seconds`; True when stopped (a signal ends the sleep at once)."""
        if self._stopped():
            return True
        self.clock.wait(seconds, self.stop)
        return self._stopped()

    def _pause(self, seconds: float) -> None:
        """A short pause while a child runs: ended early by a signal, not by a stop."""
        self.clock.wait(seconds, self._never)

    # -- the loop --------------------------------------------------------------------------

    def _hhmm(self, when: datetime) -> str:
        today = self.clock.now().date()
        text = f"{when:%H:%M}" if when.date() == today else f"{when:%a %H:%M}"
        return f"{text} ({self.cfg.schedule.zone_name()})"

    def _sleep_until(self, when: datetime | None) -> bool:
        """Sleep until `when` (None: `poll_s`). True when woken by a stop."""
        if when is None:
            log.info("sleeping %.0f s before the next session", self.cfg.schedule.poll_s)
            return self._wait(self.cfg.schedule.poll_s)
        log.info("sleeping until %s", self._hhmm(when))
        while not self._stopped():
            left = when.timestamp() - self.clock.now().timestamp()
            if left <= 0:
                return False
            if self._wait(min(left, SLEEP_CHUNK_S)):
                return True
        return True

    def run(self) -> int:
        sched = self.cfg.schedule
        log.info(
            "worker %s serves %s in windows %s (%s); between them no model is loaded",
            self.cfg.name,
            self.cfg.model,
            sched.describe(),
            sched.zone_name(),
        )
        result = run.EXIT_OK  # stopped while asleep: 0; during a session: its code
        while not self._stopped():
            now = self.clock.now()
            if not sched.is_open(now):
                if self._sleep_until(sched.opens_at(now)):
                    break
                continue
            closes = sched.closes_at(now)
            log.info(
                "window open: %s, until %s",
                sched.describe(),
                self._hhmm(closes) if closes else "stopped",
            )
            self.windows += 1
            deadline_s = None
            if closes is not None:
                deadline_s = closes.timestamp() - now.timestamp() + KILL_AFTER_S
            ctl = Control(deadline_s, self._stopped, self._pause, self.clock.monotonic)
            code = self.session.run(ctl)
            self.codes.append(code)
            if self._stopped():
                result = code
                break
            now = self.clock.now()
            still_open = sched.is_open(now)
            if code == run.EXIT_UNREACHABLE and still_open:
                wait = sched.poll_s
                left = self._left(now)
                if left is not None:
                    wait = min(wait, left)
                log.warning("the broker was unreachable; trying again in %.0f s", wait)
                if self._wait(wait):
                    break
                continue
            if code < 0:
                try:
                    name = signal.Signals(-code).name
                except ValueError:
                    name = f"signal {-code}"
                log.error("the session was killed by %s; its memory went with it", name)
            elif code not in (run.EXIT_OK, run.EXIT_UNDELIVERED):
                log.error("the session failed (exit %d); see above", code)
            if still_open:
                log.info(
                    "session ended before the window's end (exit %d); model unloaded; "
                    "not starting another until the next window",
                    code,
                )
                if self._sleep_until(sched.opens_at(sched.closes_at(now))):
                    break
            else:
                log.info("window closed; model unloaded (session exit %d)", code)
        log.info("supervisor stopped (%s) after %d session(s)", self.stop_reason, self.windows)
        return result

    def _left(self, now: datetime) -> float | None:
        closes = self.cfg.schedule.closes_at(now)
        return None if closes is None else max(0.0, closes.timestamp() - now.timestamp())
