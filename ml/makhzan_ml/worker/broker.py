"""The worker's only connection: the broker's `/ai/v1` API, over HTTPS, with a bearer token.

docs/ai/broker-api.md is the contract. Standard library only (urllib, ssl), so it runs
in any model image unchanged.

**Retries.** A network failure (refused, reset, timed out, TLS dropped), a 5xx or a 429
is retried with exponential backoff (1 s, 2 s, 4 s ... capped at 60 s, at least what a
`Retry-After` asks), for up to `retry_max_s` in all; then `Unreachable` is raised and the
caller decides what that means. A 4xx is the broker's answer, never retried: it maps to
a typed error (§3.6) so the caller can act on it: `Unauthorized`, `Forbidden`,
`VersionDrift`, `LeaseLost`, `Invalid`.

**A stop sets one deadline for the whole session.** When the worker stops (its window
ends, SIGTERM), `stopping()` sets a deadline `STOP_GRACE_S` ahead, and from then on every
attempt uses a short socket timeout (`STOP_TIMEOUT_S`). Every call still makes one attempt,
but no retry starts past the deadline, and a call in backoff wakes at once. So
delivering the scores in hand and releasing the rest fits inside a `docker stop` grace
period (one request in flight, plus the grace, plus a short attempt per call), and
whatever is still undelivered is logged by the worker rather than killed with the
process. `cutoff`, when set, is asked before each retry; the worker uses it to notice its
window ending while a call is retrying.

Redirects are refused (a 3xx is an error): urllib would otherwise re-send the
Authorization header to wherever the redirect points. Proxy environment variables are
ignored: the only peer is the broker, reached directly.

The token is sent only in the Authorization header and never logged; request bodies
(which carry catalogue text on the way back from `/lease`) are never logged either.
"""

from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("makhzan_ml.worker.broker")

BACKOFF_FIRST_S = 1.0
BACKOFF_CAP_S = 60.0
#: Per-call socket timeout: a results POST is small, a lease renders a few requests.
TIMEOUT_S = 60.0
#: Once the worker is stopping: how long, in all, calls may keep retrying ...
STOP_GRACE_S = 60.0
#: ... and the socket timeout of each attempt.
STOP_TIMEOUT_S = 10.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None  # the 3xx surfaces as an HTTPError, never followed


class BrokerError(Exception):
    """The broker answered with a 4xx this worker cannot retry its way past."""

    def __init__(self, status: int, body: dict, path: str):
        self.status, self.body, self.path = status, body, path
        super().__init__(f"{path}: HTTP {status} {body}")


class Unauthorized(BrokerError):
    """401: a missing, unknown or revoked token."""


class Forbidden(BrokerError):
    """403: a model key this worker is not registered for."""


class VersionDrift(BrokerError):
    """409 version: the broker's registry runs another model version than this worker."""


class LeaseLost(BrokerError):
    """409 lease_lost: this worker no longer holds the lease (expired, moved on)."""

    @property
    def job_ids(self) -> list[int]:
        return list(self.body.get("job_ids") or [])


class Invalid(BrokerError):
    """422: request_mismatch or a validation failure."""


class Unreachable(Exception):
    """The broker could not be reached, or kept failing, for `retry_max_s`."""


_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_ERRORS = (
    urllib.error.URLError,
    http.client.HTTPException,
    ConnectionError,
    TimeoutError,
    ssl.SSLError,
    OSError,
)


def _error_for(status: int, body: dict, path: str) -> BrokerError:
    kind = body.get("error")
    if status == 401:
        return Unauthorized(status, body, path)
    if status == 403:
        return Forbidden(status, body, path)
    if status == 409 and kind == "version":
        return VersionDrift(status, body, path)
    if status == 409 and kind == "lease_lost":
        return LeaseLost(status, body, path)
    if status == 422:
        return Invalid(status, body, path)
    return BrokerError(status, body, path)


class Broker:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        ca_file: Path | None = None,
        retry_max_s: float = 900.0,
        timeout_s: float = TIMEOUT_S,
        sleep: Callable[[float], object] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.url = url.rstrip("/")
        self._auth = f"Bearer {token}"
        self.retry_max_s = retry_max_s
        self.timeout_s = timeout_s
        self._sleep, self._monotonic = sleep, monotonic
        self._ssl = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),  # never a proxy from the environment
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=self._ssl),
        )
        #: Set by the worker: a backoff wakes when it is set.
        self.stop_event: threading.Event | None = None
        #: Set by the worker: asked before each retry (it may call `stopping()`).
        self.cutoff: Callable[[], object] | None = None
        #: Set by the worker: seconds until its window ends (None: never); no backoff
        #: sleeps past it, so the window's end is noticed when it comes.
        self.until_cutoff: Callable[[], float | None] | None = None
        self._deadline: float | None = None

    def stopping(self, grace: float = STOP_GRACE_S) -> None:
        """The session is ending: no retry past `grace` seconds from now, short timeouts."""
        if self._deadline is None:
            self._deadline = self._monotonic() + grace

    @property
    def deadline(self) -> float | None:
        return self._deadline

    # -- endpoints (broker-api.md §3) --------------------------------------------------------

    def hello(self, body: dict) -> dict:
        return self.call("/hello", body)

    def lease(self, body: dict) -> dict:
        return self.call("/lease", body)

    def heartbeat(self, body: dict) -> dict:
        # One attempt: the next heartbeat is the retry, and a heartbeat blocked in backoff
        # would hold up nothing but itself.
        return self.call("/heartbeat", body, retry=False)

    def results(self, body: dict) -> dict:
        return self.call("/results", body)

    def release(self, body: dict) -> dict:
        return self.call("/release", body)

    # -- plumbing ----------------------------------------------------------------------------

    def _once(self, path: str, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url + path,
            data=data,
            method="POST",
            headers={
                "Authorization": self._auth,
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "makhzan-ai-worker/1",
            },
        )
        timeout = STOP_TIMEOUT_S if self._deadline is not None else self.timeout_s
        with self._opener.open(req, timeout=min(timeout, self.timeout_s)) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}

    def call(self, path: str, body: dict, *, retry: bool = True) -> dict:
        """POST `body` to `path`, retrying as the module says (the same body each time)."""
        start = self._monotonic()
        delay = BACKOFF_FIRST_S
        attempt = 0
        while True:
            attempt += 1
            wait = delay
            try:
                return self._once(path, body)
            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    payload = json.loads(e.read() or b"{}")
                except (ValueError, OSError, http.client.HTTPException):
                    payload = {}  # an unreadable error body: the status alone decides
                if not isinstance(payload, dict):
                    payload = {}
                if status not in _RETRYABLE_STATUS:
                    raise _error_for(status, payload, path) from None
                after = e.headers.get("Retry-After") if e.headers else None
                if after and after.strip().isdigit():
                    wait = max(wait, float(after))
                reason = f"HTTP {status}"
            except _NETWORK_ERRORS as e:
                reason = f"{type(e).__name__}: {e}"
            except ValueError as e:  # a 2xx whose body is not JSON: a proxy, not the broker
                reason = f"unreadable response: {e}"
            if self.cutoff is not None:
                self.cutoff()  # may call stopping(): the window has ended
            now = self._monotonic()
            elapsed = now - start
            over_stop = self._deadline is not None and now + wait > self._deadline
            if not retry or elapsed + wait > self.retry_max_s or over_stop:
                why = " (stopping)" if over_stop else ""
                raise Unreachable(
                    f"{path}: {reason} (attempt {attempt}, {elapsed:.0f} s){why}"
                ) from None
            log.warning("%s: %s; retrying in %.0f s (attempt %d)", path, reason, wait, attempt)
            if self.until_cutoff is not None and self._deadline is None:
                left = self.until_cutoff()
                if left is not None:
                    wait = min(wait, max(0.0, left))
            self._pause(wait)
            delay = min(delay * 2, BACKOFF_CAP_S)

    def _pause(self, seconds: float) -> None:
        # Before a stop, a backoff wakes as soon as the stop comes; after it, it sleeps out
        # its time (no tight loop), within the deadline.
        if (
            self.stop_event is not None
            and not self.stop_event.is_set()
            and self._sleep is time.sleep
        ):
            self.stop_event.wait(seconds)
        else:
            self._sleep(seconds)
