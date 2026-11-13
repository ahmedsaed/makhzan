"""Shared HTTP client for adapters.

Lessons baked in from real supplier sites:
  - Who we say we are is per source (worker/identity.py): the browser headers
    every source has used so far, or the honest `makhzanbot` identity with Web
    Bot Auth signatures. `make_client` takes the run's identity, so every
    request a run sends — pages, retries, redirect hops, robots.txt, product
    pages — carries the same one.
  - Sites rate-limit, so `get_json` backs off and retries on 429/503 (honoring
    Retry-After), and adapters pace themselves between pages.
  - A host that keeps erroring or timing out is slowed down (`_HEALTH`), not
    retried harder.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from makhzan_schemas.crawl import pacing_stats

# Re-exported: the header sets live with the identities that send them.
from worker.identity import (  # noqa: F401
    BROWSER_HEADERS,
    CHROME_VERSION,
    ROBOTS_TOKEN,
    Identity,
    current_identity,
)

#: Default seconds to wait between paginated requests to the same host.
#: Sized for a weekly refresh cycle rather than a daily one: each run now sweeps
#: a slice of the catalogue, so even the busiest source makes a few hundred
#: requests a day and can afford a long pause between them.
#: This is a per-HOST pace, not a global one: sources hit different origins with
#: independent rate limits, so the worker scrapes them concurrently (one job
#: per source, see worker.main) while each host still sees only one request per this interval.
#: Touchier sources (e.g. behind Cloudflare) can raise it via SourceAdapter.polite_delay.
POLITE_DELAY = 15.0

_RETRYABLE = {429, 503}

#: Responses that say the host is struggling: with timeouts, what counts as an
#: error for the slowdown below. 429 is here too: without a `Retry-After` it is
#: the only signal we get.
_SLOW_DOWN_ON = {429, 500, 502, 503, 504}

#: Consecutive errors before a host's pace is raised, and again for every
#: further run of this many. One error now and then is noise and changes
#: nothing; a host failing request after request is told so by a wider gap.
#: (The research note: "after three consecutive errors".)
SLOWDOWN_AFTER = 3
#: Each raise doubles the pace, up to this: 15 s becomes at most 60 s. Low on
#: purpose: the run's time budget (`pipeline.RUN_TIME_SHARE`) is what bounds a
#: run against a host that stays slow, and a cap of 8 put a busy source past
#: the 6 h job timeout on the multiplier alone.
SLOWDOWN_CAP = 4.0
#: Consecutive 2xx responses that halve a raised pace. From the cap back to the
#: plain pace takes 2 × this — quick enough that a recovered host is not left
#: crawled at a quarter speed, slow enough that one lucky answer is not trusted.
RECOVER_AFTER = 3
#: Seconds after the host's last error that its slowdown is forgotten. Runs are
#: daily, so yesterday's trouble does not slow today's first request.
SLOWDOWN_FORGET = 3600.0


class _Health:
    __slots__ = ("errors", "successes", "multiplier", "last_trouble")

    def __init__(self) -> None:
        self.errors = 0  # consecutive
        self.successes = 0  # consecutive, counted only while slowed
        self.multiplier = 1.0
        self.last_trouble = 0.0


#: Per host, its recent errors and the pace multiplier they earned. Read by
#: `_pace_of`, so it acts through `take_turn` on every request to the host and
#: `stats.pacing` measures the slower gaps it causes (never why: that endpoint
#: is public).
_HEALTH: dict[str, _Health] = {}


def note_trouble(host: str) -> None:
    """The host errored or timed out. Every `SLOWDOWN_AFTER`-th error in a row doubles its pace."""
    health = _HEALTH.setdefault(host, _Health())
    health.errors += 1
    health.successes = 0
    health.last_trouble = _now()
    if health.errors % SLOWDOWN_AFTER == 0:
        health.multiplier = min(SLOWDOWN_CAP, health.multiplier * 2)


def note_success(host: str) -> None:
    """A 2xx: the run of errors is over, and `RECOVER_AFTER` in a row halve the pace."""
    health = _HEALTH.get(host)
    if health is None:
        return
    health.errors = 0
    if health.multiplier <= 1.0:
        _HEALTH.pop(host, None)
        return
    health.successes += 1
    if health.successes >= RECOVER_AFTER:
        health.successes = 0
        health.multiplier = max(1.0, health.multiplier / 2)
        if health.multiplier == 1.0:
            _HEALTH.pop(host, None)


def note_response(host: str, status: int) -> None:
    if status in _SLOW_DOWN_ON:
        note_trouble(host)
    elif 200 <= status < 300:
        note_success(host)


def slowdown(host: str) -> float:
    """The host's current pace multiplier (1 when it has been well)."""
    health = _HEALTH.get(host)
    if health is None:
        return 1.0
    if _now() - health.last_trouble > SLOWDOWN_FORGET:
        _HEALTH.pop(host, None)
        return 1.0
    return health.multiplier


def hold_host(host: str, retry_after: str | None) -> float | None:
    """Make a `Retry-After` bind every later request to `host`. Returns the seconds asked."""
    asked = retry_after_seconds(retry_after)
    if asked is not None:
        _NOT_BEFORE[host] = time.monotonic() + asked
    return asked


#: The longest `Retry-After` the crawler waits out in place. A host asking for
#: more is not retried in this run: the request fails, the partition's cursor
#: stays where it is, and the next run picks it up. Waiting less than asked is
#: never an option — a survey that sent six more requests 12 s after a 429 with
#: `Retry-After: 60` is exactly what this exists to prevent.
RETRY_AFTER_CAP = 600.0

#: Per host, the monotonic time before which nothing may be sent to it. Set from
#: a `Retry-After`, and checked before *every* request, so the wait also binds
#: the next partition and the next adapter call — not only the retry loop that
#: received it.
_NOT_BEFORE: dict[str, float] = {}


#: When a request goes out, for the request log. Looked up at call time.
_now: Callable[[], float] = time.monotonic


class RequestLog:
    """When each request of one run went out, by host — the evidence for `stats.pacing`.

    Recorded in `_request`, the one door every adapter request goes through
    (pages, a Shopify shop's collection lists, the once-a-cycle reference data),
    at the moment each is sent, retries included. So the gaps it reports are the
    ones the shop's server saw, not the ones the pacing code meant to leave.
    robots.txt fetches (worker/robots.py) are recorded too, as `robots`: the shop
    sees them like any other request.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock
        self.times: dict[str, list[float]] = defaultdict(list)
        #: robots.txt fetches among `times`, by host.
        self.robots: Counter[str] = Counter()
        #: Per host, what robots.txt said for this run (worker/robots.py): read
        #: fresh, a stale copy standing in, or unavailable. `stats.robots`.
        self.robots_state: dict[str, dict] = {}
        #: Per host, how many 2xx responses carried a cache validator
        #: (`note_validators`). `stats.validators`, never `stats.pacing`.
        self.validators: dict[str, Counter[str]] = defaultdict(Counter)

    def note_validators(self, host: str, response: httpx.Response) -> None:
        """Count whether a 2xx response carried `ETag` / `Last-Modified` (T11, measure only).

        Whether conditional requests could ever save a shop anything depends on
        how many of its pages carry a validator, so each answer is counted —
        presence only, never the values. Kept out of `stats.pacing`: that is
        published on /how-we-crawl, and this is not what was sent but what
        came back.
        """
        if not 200 <= response.status_code < 300:
            return
        counts = self.validators[host]
        counts["responses"] += 1
        etag = response.headers.get("ETag")
        if etag:
            counts["etag"] += 1
            if etag.strip().startswith("W/"):
                counts["etag_weak"] += 1
        if response.headers.get("Last-Modified"):
            counts["last_modified"] += 1

    def validator_stats(self) -> dict[str, dict[str, int]]:
        """`stats.validators`: per host, 2xx responses and how many carried each validator."""
        return {
            host: {key: counts[key] for key in ("responses", "etag", "etag_weak", "last_modified")}
            for host, counts in sorted(self.validators.items())
            if counts["responses"]
        }

    def record(self, host: str, *, robots: bool = False) -> None:
        self.times[host].append((self._clock or _now)())
        if robots:
            self.robots[host] += 1

    def pacing(self) -> dict:
        """`stats.pacing` (see makhzan_schemas.crawl)."""
        return pacing_stats(self.times, robots=self.robots)


#: The log of the run in progress in this task, if any. A context variable, not
#: a global: the daily refresh runs sources concurrently, one task each.
_REQUEST_LOG: ContextVar[RequestLog | None] = ContextVar("request_log", default=None)


def current_request_log() -> RequestLog | None:
    """The log of the run in progress in this task, if any."""
    return _REQUEST_LOG.get()


@contextlib.contextmanager
def logging_requests(log: RequestLog | None = None) -> Iterator[RequestLog]:
    """Record every request sent inside the block (and tasks it starts) into `log`."""
    log = log or RequestLog()
    token = _REQUEST_LOG.set(log)
    try:
        yield log
    finally:
        _REQUEST_LOG.reset(token)


class HostBackingOff(Exception):
    """Raised instead of sending a request the host asked us to hold back."""

    def __init__(self, host: str, seconds: float) -> None:
        super().__init__(f"{host} asked us to wait {seconds:.0f}s more (Retry-After)")
        self.host = host
        self.seconds = seconds


def retry_after_seconds(value: str | None, now: datetime | None = None) -> float | None:
    """A `Retry-After` header in seconds: delta-seconds or an HTTP-date.

    None when absent or unreadable; never negative (a date in the past means
    "now").
    """
    value = (value or "").strip()
    if not value:
        return None
    if value.isascii() and value.isdigit():  # delta-seconds is digits only (RFC 9110 §10.2.3)
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _host(url: httpx.URL) -> str:
    """`scheme://host[:port]`, normalised so one host has one key.

    Lowercase scheme and host, and no default port: httpx keeps an explicit
    `:443` when the scheme was typed in capitals, so `HTTPS://Shop.TEST:443` and
    `https://shop.test` would otherwise be two hosts — two pace gates, and a
    robots.txt whose Crawl-delay the pages never see.
    """
    scheme = url.scheme.lower()
    host = url.host.lower()
    if ":" in host:  # an IPv6 literal keeps its brackets
        host = f"[{host}]"
    port = url.port
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


#: Per host, the pace the source running against it asked for (its
#: `polite_delay`), set by the pipeline at the start of a run. `Crawl-Delay` is a
#: floor on it (see `_pace_of`). A host nobody registered has no gate: only an
#: adapter called directly, outside a run, sends to one.
_HOST_PACE: dict[str, float] = {}

#: Per host, when the last request to it went out (`_now` time).
_LAST_SENT: dict[str, float] = {}

#: Per host, held while a request waits its turn, so two tasks sharing a host
#: cannot both decide the gap is long enough.
_TURN_LOCKS: dict[str, asyncio.Lock] = {}


def host_of(url: str | httpx.URL) -> str:
    """`scheme://host[:port]` of a URL: the one key every per-host table uses.

    The pace gate, the request log, `Retry-After` and robots.txt's cache
    (worker/robots.py) all key on this, so a robots.txt fetch and the pages after
    it always queue at the same gate and read the same Crawl-delay.
    """
    return _host(url if isinstance(url, httpx.URL) else httpx.URL(url))


def set_host_pace(base_url: str | None, seconds: float) -> None:
    """Make `seconds` the least gap between any two requests to `base_url`'s host."""
    if base_url:
        _HOST_PACE[host_of(base_url)] = float(seconds)


def _pace_of(host: str, *, default: float = 0.0) -> float:
    """The host's pace: its registered polite delay, with its Crawl-Delay as a floor,
    multiplied by its slowdown after recent errors.

    Reads robots.txt only from the cache: fetching it from here would wait on
    the very gate this computes.
    """
    from worker.robots import ROBOTS

    cached = getattr(ROBOTS, "cached_crawl_delay", None)
    asked = cached(host, ROBOTS_TOKEN) if cached else None
    return max(_HOST_PACE.get(host, default), asked or 0.0) * slowdown(host)


async def take_turn(host: str, *, robots: bool = False) -> None:
    """Wait until `host` may be sent its next request, then claim the slot.

    The one gate every request to a shop passes — pages, cycle data, a retry,
    a robots.txt fetch — so none goes out closer than the host's pace to the
    one before it, whichever code path sent either. Logged for `stats.pacing`.
    """
    lock = _TURN_LOCKS.setdefault(host, asyncio.Lock())
    async with lock:
        await _wait_for_host(host)
        last = _LAST_SENT.get(host)
        if last is not None:
            remaining = last + _pace_of(host) - _now()
            if remaining > 0:
                await asyncio.sleep(remaining)
        _LAST_SENT[host] = _now()
        log = _REQUEST_LOG.get()
        if log is not None:
            log.record(host, robots=robots)


async def _wait_for_host(host: str) -> None:
    """Hold until the host's Retry-After has passed, or refuse if that is too far off."""
    remaining = _NOT_BEFORE.get(host, 0.0) - time.monotonic()
    if remaining <= 0:
        _NOT_BEFORE.pop(host, None)
        return
    if remaining > RETRY_AFTER_CAP:
        raise HostBackingOff(host, remaining)
    await asyncio.sleep(remaining)


#: Most redirects followed for one request: what a shop does in practice is one
#: hop (http to https, a trailing slash, a renamed path) or two.
MAX_REDIRECTS = 5


def make_client(*, identity: Identity | None = None, **kwargs) -> httpx.AsyncClient:
    """A client sending as `identity` — by default the run's (`worker.identity`).

    Its headers, and for a signed identity its `Auth`, apply to every request
    the client sends, redirect hops included: httpx runs the auth flow on each
    `send`, so each is signed afresh.
    """
    identity = identity or current_identity()
    # Redirects are followed by `_request`, one hop at a time: followed here,
    # httpx sent each hop at once, past the pace gate and missing from the
    # request log, so a shop's server could see two requests a few ms apart
    # under a page that publishes "at least 15 seconds".
    return httpx.AsyncClient(
        headers=dict(identity.headers),
        auth=identity.auth,
        timeout=httpx.Timeout(30.0),
        follow_redirects=False,
        **kwargs,
    )


async def _send_following_redirects(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    params: dict | None,
    **kwargs,
) -> httpx.Response:
    """Send a request whose turn is taken, then follow its redirects as requests of their own.

    Each hop is checked against robots.txt, waits its host's turn and is logged,
    exactly like a page: the shop's server cannot tell the two apart. httpx
    builds each hop (`next_request`) the way it would have followed it — method
    and body kept on 307/308, a GET after 303 or a POST's 301/302 — so what is
    fetched is unchanged; only when.
    """
    from worker.robots import ROBOTS, DisallowedByRobots

    resp = await client.request(method, url, params=params, follow_redirects=False, **kwargs)
    for _ in range(MAX_REDIRECTS):
        hop = resp.next_request
        if hop is None:
            return resp
        await resp.aclose()
        if not await ROBOTS.allowed(str(hop.url), ROBOTS_TOKEN):
            raise DisallowedByRobots(str(hop.url))
        await take_turn(host_of(hop.url))
        resp = await client.send(hop, follow_redirects=False)
    if resp.next_request is not None:
        await resp.aclose()
        raise httpx.TooManyRedirects(
            f"more than {MAX_REDIRECTS} redirects from {url}", request=resp.request
        )
    return resp


async def _request(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None,
    retries: int,
    base_delay: float,
    method: str = "GET",
    **kwargs,
) -> httpx.Response:
    """Request with backoff on rate-limit/unavailable responses.

    Not every source answers on GET: one marketplace returns its product listings only
    to a POST against the same URL. The retry and pacing behaviour is identical
    either way, so the method is a parameter rather than a second code path.

    On 429/503 a `Retry-After` is a floor: the retry waits at least that long
    (and at least the backoff), and a host asking for longer than
    `RETRY_AFTER_CAP` is not retried at all in this run.
    """
    # Imported here rather than at module scope: robots.py needs this module's
    # pace gate, so a top-level import would be circular.
    from worker.robots import ROBOTS, DisallowedByRobots

    # robots.txt is checked against the URL actually sent, query string included:
    # rules such as `Disallow: /collections/*sort_by*` live in the query.
    target = httpx.URL(url).copy_merge_params(params) if params else httpx.URL(url)
    if not await ROBOTS.allowed(str(target), ROBOTS_TOKEN):
        raise DisallowedByRobots(str(target))
    host = _host(target)

    resp = None
    for attempt in range(retries + 1):
        await take_turn(host)
        try:
            resp = await _send_following_redirects(client, method, url, params, **kwargs)
        except httpx.TimeoutException as exc:
            # Not retried (a slow host is not helped by more requests), but the
            # next request to it waits longer.
            try:
                note_trouble(host_of(exc.request.url))  # a redirect hop's host
            except RuntimeError:  # no request attached
                note_trouble(host)
            raise
        # The host that answered: after a redirect, not necessarily the first.
        note_response(host_of(resp.url), resp.status_code)
        if (log := _REQUEST_LOG.get()) is not None:
            log.note_validators(host_of(resp.url), resp)
        if resp.status_code in _RETRYABLE:
            # The host that asked: after a redirect, not necessarily the first.
            asked = hold_host(host_of(resp.url), resp.headers.get("Retry-After"))
            if attempt < retries and (asked is None or asked <= RETRY_AFTER_CAP):
                # The published pace is a floor here too: a retry is a request
                # like any other. Above it the backoff still grows, and a
                # Retry-After longer than both wins. `take_turn` then holds the
                # same floor against every other request to the host.
                backoff = base_delay * (2**attempt) + random.uniform(0, 0.5)
                floor = _pace_of(host, default=POLITE_DELAY)
                await asyncio.sleep(max(floor, backoff, asked or 0.0))
                continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()  # exhausted retries — surface the last error
    return resp  # unreachable


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    *,
    retries: int = 5,
    base_delay: float = 2.0,
    method: str = "GET",
    **kwargs,
):
    """Fetch parsed JSON (GET by default; pass method="POST" where a source needs it)."""
    return (await _request(client, url, params, retries, base_delay, method, **kwargs)).json()


async def get_response(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    *,
    retries: int = 5,
    base_delay: float = 2.0,
) -> httpx.Response:
    """GET returning the whole response, for a caller that needs its headers too.

    WordPress says how many pages a collection has (`X-WP-TotalPages`) and
    answers the page after the last with a 400, so paging one to the end needs
    the header rather than "stop at the first empty page".
    """
    return await _request(client, url, params, retries, base_delay)


def total_pages(response: httpx.Response) -> int | None:
    """WordPress's `X-WP-TotalPages`, if the response carries a usable one."""
    value = response.headers.get("X-WP-TotalPages", "")
    return int(value) if value.isdigit() else None


async def get_text(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    *,
    retries: int = 5,
    base_delay: float = 2.0,
) -> str:
    """GET returning response text (for HTML-scraped sources)."""
    return (await _request(client, url, params, retries, base_delay)).text


class CycleFetcher:
    """Paced, counted GETs for a source's once-a-cycle reference data.

    Some of what a shop publishes is not per page of products but per shop: its
    category tree, the price of every variant, its quantity breaks, its address.
    Fetching that a handful of requests at a time once a cycle is cheap; fetching
    it on every run of a week-long cycle is not. This is the one door those
    requests go through, so each waits the host's pace (its `Crawl-Delay` as a
    floor) like a product page does, honours robots.txt and `Retry-After` through
    `_request`, and is counted by label for the run's stats.
    """

    def __init__(self, pace: Callable[[], Awaitable[float]], *, retries: int = 5) -> None:
        self._pace = pace
        #: Retries per request on 429/5xx. Product-page details pass 1: a page
        #: that fails twice waits for tomorrow rather than costing the host five
        #: more requests (each still paced, but requests all the same).
        self._retries = retries
        #: Requests made, by what they were for ("variations", "contact", ...).
        self.requests: Counter[str] = Counter()

    async def get(self, label: str, url: str, params: dict | None = None) -> httpx.Response:
        if self.requests.total():
            await asyncio.sleep(await self._pace())
        # Counted before it is sent: a request that failed still reached the host.
        self.requests[label] += 1
        async with make_client() as client:
            return await get_response(client, url, params, retries=self._retries)
