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

The child is a fork, so the parent must hold no model and no threads when it forks: it
imports nothing heavier than the worker's own standard-library modules (torch is only
imported by `judges.load`, in the child). SIGTERM and SIGINT are blocked across the fork,
so a signal that arrives meanwhile is delivered to the child once its own handlers are in
place, never lost.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from collections.abc import Callable
from datetime import datetime

from makhzan_ml.worker import run
from makhzan_ml.worker.config import Config

log = logging.getLogger("makhzan_ml.worker.supervisor")

#: The longest single sleep: a sleep is re-measured against the wall clock at least this
#: often, so a clock change or a suspended host cannot make it overshoot by more.
SLEEP_CHUNK_S = 900.0

_SIGNALS = {signal.SIGTERM, signal.SIGINT}


class InProcessSession:
    """Runs each window's session in this process. For the tests (a fake judge, a fake clock
    shared with the supervisor); the image always forks (`ForkedSession`)."""

    def __init__(self, make_worker: Callable[[], run.Worker]):
        self.make_worker = make_worker
        self.worker: run.Worker | None = None

    def run(self) -> int:
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

    def run(self) -> int:
        old = signal.pthread_sigmask(signal.SIG_BLOCK, _SIGNALS)
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
        signal.pthread_sigmask(signal.SIG_SETMASK, old)  # a pending SIGTERM is forwarded now
        try:
            _, status = os.waitpid(pid, 0)  # retried across signals (PEP 475)
        finally:
            self.pid = None
        return os.waitstatus_to_exitcode(status)  # negative: killed by that signal

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
        self.clock = clock or run.Clock(cfg)
        self.session = session or ForkedSession(lambda: run.Worker(cfg, image=image))
        self.stop = threading.Event()
        self.stop_reason: str | None = None
        self.windows = 0  # sessions started
        self.codes: list[int] = []  # each session's exit code
        self._pid = os.getpid()

    # -- control ---------------------------------------------------------------------------

    def request_stop(self, reason: str) -> None:
        if not self.stop.is_set():
            self.stop_reason = reason
            log.info("stopping: %s", reason)
            self.stop.set()
        self.session.stop(reason)

    def install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            if os.getpid() == self._pid:  # never act as the supervisor inside a child
                self.request_stop(signal.Signals(signum).name)

        for sig in _SIGNALS:
            signal.signal(sig, handler)

    # -- the loop --------------------------------------------------------------------------

    def _hhmm(self, when: datetime) -> str:
        today = self.clock.now().date()
        text = f"{when:%H:%M}" if when.date() == today else f"{when:%a %H:%M}"
        return f"{text} ({self.cfg.schedule.zone_name()})"

    def _sleep_until(self, when: datetime | None) -> bool:
        """Sleep until `when` (None: `poll_s`). True when woken by a stop."""
        if when is None:
            log.info("sleeping %.0f s before the next session", self.cfg.schedule.poll_s)
            return self.clock.wait(self.cfg.schedule.poll_s, self.stop)
        log.info("sleeping until %s", self._hhmm(when))
        while not self.stop.is_set():
            left = when.timestamp() - self.clock.now().timestamp()
            if left <= 0:
                return False
            if self.clock.wait(min(left, SLEEP_CHUNK_S), self.stop):
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
        while not self.stop.is_set():
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
            code = self.session.run()
            self.codes.append(code)
            if self.stop.is_set():
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
                if self.clock.wait(wait, self.stop):
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
