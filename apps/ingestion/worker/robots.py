"""Honour each host's robots.txt.

Every path makhzan crawls is allowed by the eight suppliers' current robots.txt —
checked by hand on 2026-09-07. That was luck, not mechanism: nothing read the
file, so a supplier adding a rule tomorrow would have gone unnoticed for as long
as nobody thought to look.

This makes it a mechanism. It also takes `Crawl-Delay` seriously, which turned up
a real (if small) breach: one supplier asks for 20 seconds and the crawler's
default is 15, so it was reading that shop faster than it had been asked to in
writing.

Being able to say "we read what you publish and we do what it says" is worth more
than the code costs — it is the strongest sentence available when writing to a
supplier about access.

Groups are matched on our own product token, `makhzanbot`, whichever identity
(worker/identity.py) sends the request: a shop that writes
`User-agent: makhzanbot` / `Disallow: /` is obeyed even while that shop is
still crawled with browser headers. It used to be matched on the token of the
User-Agent string, which for the browser identity is "mozilla" — so no shop
could address us by name at all.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

import httpx

from worker.http import (
    MAX_REDIRECTS,
    HostBackingOff,
    current_request_log,
    hold_host,
    host_of,
    note_response,
    note_trouble,
    take_turn,
)
from worker.identity import ROBOTS_TOKEN, current_identity

#: Re-read a host's robots.txt this often. A sweep of one source runs for hours,
#: and a rule added mid-sweep should take effect within it.
TTL_SECONDS = 3600.0

#: Give up quickly. robots.txt is on the critical path of every fetch, and a slow
#: one must not stall a sweep.
TIMEOUT_SECONDS = 10.0

#: How long a host's last good robots.txt stands in when the file cannot be read
#: (a 5xx, a 429, a timeout). RFC 9309 §2.3.1.4 names 30 days as a "reasonably
#: long period". Older than this, or with no good copy at all, the host is
#: treated as fully disallowed until the file can be read again.
STALE_LIMIT_SECONDS = 30 * 86400

#: How long "unavailable" (unreadable, no usable copy) stands before robots.txt
#: is asked again. Short: one blip must not cost a source its day, and a run
#: whose own host is unavailable stops at once anyway (pipeline).
UNAVAILABLE_TTL_SECONDS = 600.0

#: The most of a robots.txt kept (RFC 9309 §2.5: parse at least 500 KiB).
MAX_BODY = 512 * 1024

log = logging.getLogger(__name__)

#: A user-agent line's product token (RFC 9309 §2.2.1): letters, "_" and "-".
#: `User-agent: makhzanbot/1.0` names the same crawler as `makhzanbot`.
_PRODUCT_TOKEN = re.compile(r"[a-z_-]+")


def _agent_token(value: str) -> str:
    match = _PRODUCT_TOKEN.match(value)
    return match.group(0) if match else value


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    #: (compiled pattern, pattern length, allow)
    rules: list[tuple[re.Pattern[str], int, bool]] = field(default_factory=list)
    crawl_delay: float | None = None


class Rules:
    """A parsed robots.txt, matched the way RFC 9309 says.

    Not `urllib.robotparser`: on the Python the worker runs (3.12) it ignores
    `*` and `$` and lets the *first* matching line win. One supplier's file says
    `Disallow: /collections/*sort_by*`, which that parser reads as a literal
    path nobody requests, and an `Allow: /` above a `Disallow: /cart` would allow
    the cart. Here the longest matching pattern wins, a tie goes to Allow,
    `*` matches any run of characters and a trailing `$` anchors the end.
    """

    def __init__(self, text: str) -> None:
        self.groups: list[_Group] = []
        group: _Group | None = None
        in_rules = False
        for line in text.splitlines():
            key, sep, value = line.split("#", 1)[0].partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                # Consecutive user-agent lines share one group; one after a rule
                # starts the next.
                if group is None or in_rules:
                    group = _Group()
                    self.groups.append(group)
                    in_rules = False
                group.agents.append(value.lower())
            elif group is None:
                continue  # a rule before any user-agent line belongs to nobody
            elif key in ("allow", "disallow"):
                in_rules = True
                if value:  # an empty Disallow allows everything: no rule
                    value = unquote(value)
                    group.rules.append((_compile(value), len(value), key == "allow"))
            elif key == "crawl-delay":
                in_rules = True
                try:
                    delay = float(value)
                except ValueError:
                    continue  # a malformed directive is not a rule
                if group.crawl_delay is None and delay >= 0:
                    group.crawl_delay = delay

    def _groups_for(self, token: str) -> list[_Group]:
        # RFC 9309 §2.2.1: the group whose user-agent is our product token,
        # compared case-insensitively. Every group naming us applies (a file may
        # split them); failing that, "*". An exact match, not a substring: a
        # group for "bot" is not a group for "makhzanbot".
        token = token.strip().lower()
        named = [g for g in self.groups if any(_agent_token(a) == token for a in g.agents)]
        return named or [g for g in self.groups if "*" in g.agents]

    def allowed(self, url: str, token: str = ROBOTS_TOKEN) -> bool:
        parts = urlsplit(url)
        path = parts.path or "/"
        if path == "/robots.txt":
            return True
        # Compared percent-decoded on both sides, so `/a+b` and `/a%2Bb` are one
        # path: a rule must not be dodged by how a character happens to be spelled.
        target = unquote(f"{path}?{parts.query}" if parts.query else path)
        best: tuple[int, bool] | None = None
        for group in self._groups_for(token):
            for pattern, length, allow in group.rules:
                if pattern.match(target) and (
                    best is None or length > best[0] or (length == best[0] and allow)
                ):
                    best = (length, allow)
        return True if best is None else best[1]

    def crawl_delay(self, token: str = ROBOTS_TOKEN) -> float | None:
        delays = [g.crawl_delay for g in self._groups_for(token) if g.crawl_delay is not None]
        return max(delays) if delays else None


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = ".*".join(re.escape(part) for part in pattern.rstrip("$").split("*"))
    return re.compile(body + (r"\Z" if anchored else ""), re.DOTALL)


@dataclass
class _Copy:
    """A robots.txt that was read successfully: its text (None for "no rules", a 4xx)."""

    body: str | None
    status: int
    #: Wall-clock seconds (time.time()) when it was read.
    fetched_at: float

    def rules(self) -> Rules | None:
        return Rules(self.body) if self.body is not None else None


class RobotsStore:
    """Where the last good copy of each host's robots.txt is kept. In memory only."""

    def __init__(self) -> None:
        self._copies: dict[str, _Copy] = {}

    async def load(self, host: str) -> _Copy | None:
        return self._copies.get(host)

    async def save(self, host: str, copy: _Copy) -> None:
        self._copies[host] = copy


class DatabaseRobotsStore(RobotsStore):
    """The `robots_copies` table, so a worker restart does not forget the copies.

    A database failure here is logged and otherwise ignored: losing a copy only
    makes the crawler stricter, and robots.txt must not depend on Postgres to
    answer.
    """

    async def load(self, host: str) -> _Copy | None:
        from makhzan_schemas.db import SessionLocal
        from makhzan_schemas.models import RobotsCopy

        try:
            async with SessionLocal() as session:
                row = await session.get(RobotsCopy, host)
        except Exception as exc:  # noqa: BLE001
            log.warning("robots copy for %s not loaded: %s", host, exc)
            return None
        if row is None:
            return None
        return _Copy(body=row.body, status=row.status, fetched_at=row.fetched_at.timestamp())

    async def save(self, host: str, copy: _Copy) -> None:
        from makhzan_schemas.db import SessionLocal
        from makhzan_schemas.models import RobotsCopy
        from sqlalchemy.dialects.postgresql import insert

        values = {
            "host": host,
            "body": copy.body,
            "status": copy.status,
            "fetched_at": datetime.fromtimestamp(copy.fetched_at, timezone.utc),
        }
        try:
            async with SessionLocal() as session:
                await session.execute(
                    insert(RobotsCopy)
                    .values(**values)
                    .on_conflict_do_update(index_elements=[RobotsCopy.host], set_=values)
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("robots copy for %s not saved: %s", host, exc)


@dataclass
class _Entry:
    rules: Rules | None  # None when no rules apply (none published, or unavailable)
    #: Monotonic time this verdict was reached; it stands for the TTL.
    fetched_at: float
    #: "fetched" (read now), "no_rules" (a 4xx), "stale" (unreadable, a good
    #: copy stands in) or "unavailable" (unreadable, no usable copy: nothing may
    #: be fetched from the host until it can be read — RFC 9309 §2.3.1.4).
    state: str = "fetched"
    #: Wall-clock time the rules in force were read (the copy's, when stale).
    copy_fetched_at: float | None = None
    #: Why the file could not be read, when it could not.
    error: str | None = None

    @property
    def unavailable(self) -> bool:
        return self.state == "unavailable"

    def describe(self, now: float) -> dict:
        """What goes in the run's `stats.robots[host]` (never published)."""
        out: dict = {"state": self.state}
        if self.copy_fetched_at is not None:
            out["copy_age_days"] = round(max(0.0, now - self.copy_fetched_at) / 86400, 1)
        if self.error:
            out["error"] = self.error
        return out


class RobotsCache:
    """Per-host robots.txt, cached with a TTL.

    Failure handling follows RFC 9309. A 4xx (the common 404) means there are no
    rules and everything is allowed; so does a chain of more than five
    redirects (§2.3.1.2). A 5xx, a 429 or a network failure means the rules are
    *unknown*, and the RFC says to "assume complete disallow". So:

      1. the fetch is retried once, after the host's pace (through `take_turn`,
         so the retry is paced and logged like any request; a `Retry-After`
         binds it);
      2. still unreadable, the host's last good copy stands in if it is at most
         `STALE_LIMIT_SECONDS` old — kept in `store` (the database in the
         worker), so a deploy does not forget it;
      3. with no usable copy, every request to the host raises
         `RobotsUnavailable`, and that verdict is cached only for
         `UNAVAILABLE_TTL_SECONDS`, so a blip costs minutes, not the hour.

    A copy older than 30 days is not used: the host is refused instead. That is
    stricter than the research note (which reads the RFC's "MAY" as "treat the
    file as absent and allow all" after 30 days) on purpose: a file nobody could
    read for a month is not evidence that its rules went away. `make status`
    flags any host served from a copy over 7 days old.

    One cache for the whole process, keyed by host, whichever identity asked:
    the token matched is the same in every identity, and today no two sources
    share a host. If two sources with different identities ever shared one,
    the robots.txt fetch would carry whichever identity asked first.
    """

    def __init__(
        self,
        ttl: float = TTL_SECONDS,
        *,
        wall: Callable[[], float] = time.time,
        clock: Callable[[], float] = time.monotonic,
        store: RobotsStore | None = None,
    ) -> None:
        self._ttl = ttl
        self._wall = wall
        self._clock = clock
        self._store = store or RobotsStore()
        self._hosts: dict[str, _Entry] = {}
        #: Per host, the last good copy this process has seen (also in `store`).
        self._good: dict[str, _Copy] = {}
        self.failures: dict[str, str] = {}

    async def _entry(self, url: str) -> _Entry:
        # The pace gate's own key: built any other way, a mixed-case or
        # explicit-port base URL took its robots.txt turn at a different gate
        # than the pages, and the pages never saw its Crawl-delay.
        host = host_of(url)
        entry = await self._lookup(host)
        log = current_request_log()
        if log is not None:
            log.robots_state[host] = entry.describe(self._wall())
        return entry

    async def _lookup(self, host: str) -> _Entry:
        cached = self._hosts.get(host)
        if cached:
            ttl = min(self._ttl, UNAVAILABLE_TTL_SECONDS) if cached.unavailable else self._ttl
            if (self._clock() - cached.fetched_at) < ttl:
                return cached

        copy, failure = None, None
        for attempt in range(2):
            try:
                # A request like any other to the shop: it waits the host's
                # pace, is logged in the run's pacing, and the page after it
                # waits too. The retry waits the pace again.
                await take_turn(host, robots=True)
            except HostBackingOff:
                # The host asked us to hold back. Keep the rules we have rather
                # than forgetting them; with none, the request waits on the host
                # anyway.
                if cached:
                    return cached
                raise
            copy, failure = await self._fetch(host)
            if failure is None:
                break
            if attempt == 0:
                log.info("robots.txt for %s: %s; retrying once", host, failure)

        now = self._clock()
        if failure is None:
            assert copy is not None
            self.failures.pop(host, None)
            self._good[host] = copy
            await self._store.save(host, copy)
            entry = _Entry(
                rules=copy.rules(),
                fetched_at=now,
                state="fetched" if copy.body is not None else "no_rules",
                copy_fetched_at=copy.fetched_at,
            )
        else:
            good = self._good.get(host) or await self._store.load(host)
            age = self._wall() - good.fetched_at if good is not None else None
            if good is not None and age is not None and age <= STALE_LIMIT_SECONDS:
                self._good[host] = good
                self.failures[host] = f"{failure}; using the copy from {age / 86400:.1f} days ago"
                entry = _Entry(
                    rules=good.rules(),
                    fetched_at=now,
                    state="stale",
                    copy_fetched_at=good.fetched_at,
                    error=failure,
                )
            else:
                reason = "no copy" if good is None else f"copy {age / 86400:.0f} days old"
                self.failures[host] = f"{failure}; {reason}, so nothing is fetched"
                entry = _Entry(
                    rules=None,
                    fetched_at=now,
                    state="unavailable",
                    copy_fetched_at=good.fetched_at if good is not None else None,
                    error=failure,
                )
        self._hosts[host] = entry
        return entry

    async def _fetch(self, host: str) -> tuple[_Copy | None, str | None]:
        """One read of the host's robots.txt: (a good copy, None) or (None, why not).

        `HostBackingOff` from a redirect hop's turn propagates: the host asked
        us to wait, which is not the same as robots.txt being unreachable.
        """
        identity = current_identity()
        try:
            # A bare client on purpose: routing this through the adapters' own
            # fetch helper would recurse straight back into this check. It
            # sends as the run's identity, signature included, like the pages.
            # Redirects are followed by hand, each hop a paced and logged
            # request (as worker/http.py does for pages): http to https is the
            # common one, and httpx following it sent it unpaced and uncounted.
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS,
                follow_redirects=False,
                headers=dict(identity.headers),
                auth=identity.auth,
            ) as client:
                response = await client.get(f"{host}/robots.txt")
                for _ in range(MAX_REDIRECTS):
                    hop = response.next_request
                    if hop is None:
                        break
                    await take_turn(host_of(hop.url), robots=True)
                    response = await client.get(str(hop.url))
        except HostBackingOff:
            raise
        except Exception as exc:  # noqa: BLE001 — a probe must not break a sweep
            if isinstance(exc, httpx.TimeoutException):
                note_trouble(host)
            return None, f"robots.txt unreachable: {type(exc).__name__}"

        answered = host_of(response.url)
        note_response(answered, response.status_code)
        status = response.status_code
        if response.is_redirect:
            # RFC 9309 §2.3.1.2: past five hops, robots.txt is unavailable,
            # which is read like a 4xx: no rules.
            return _Copy(body=None, status=status, fetched_at=self._wall()), None
        if status < 400:
            return _Copy(
                body=response.text[:MAX_BODY], status=status, fetched_at=self._wall()
            ), None
        if status == 429 or status >= 500:
            # A 429 is "not now", not "no rules": read like a 5xx. Its
            # Retry-After binds the retry and every request after it.
            hold_host(answered, response.headers.get("Retry-After"))
            return None, f"robots.txt returned {status}"
        # Any other 4xx: no rules published. Everything is allowed.
        return _Copy(body=None, status=status, fetched_at=self._wall()), None

    async def allowed(self, url: str, token: str = ROBOTS_TOKEN) -> bool:
        entry = await self._entry(url)
        if entry.unavailable:
            host = host_of(url)
            raise RobotsUnavailable(host, self.failures.get(host, ""))
        if entry.rules is None:
            return True
        return entry.rules.allowed(url, token)

    async def crawl_delay(self, url: str, token: str = ROBOTS_TOKEN) -> float | None:
        """Seconds the host asks between requests, if it says."""
        try:
            entry = await self._entry(url)
        except HostBackingOff:
            return None  # nothing will be sent to it anyway until it lets us
        if entry.rules is None:
            return None
        return entry.rules.crawl_delay(token)

    def cached_crawl_delay(self, host: str, token: str = ROBOTS_TOKEN) -> float | None:
        """`crawl_delay` from what is already cached, never fetching (for the pace gate)."""
        entry = self._hosts.get(host_of(host))
        if entry is None or entry.rules is None:
            return None
        return entry.rules.crawl_delay(token)


class RobotsUnavailable(Exception):
    """Raised instead of fetching from a host whose robots.txt cannot be read.

    Not a `DisallowedByRobots`: that one means "this path is off limits", and a
    caller may skip the path and carry on (a Shopify shop's collections do).
    This means the rules are unknown, so the page fails, its cursor stays where
    it is, and a run whose own host this is stops sweeping (pipeline).
    """

    def __init__(self, host: str, reason: str) -> None:
        super().__init__(f"robots.txt for {host} cannot be read ({reason}); not crawling it")
        self.host = host
        self.reason = reason


class DisallowedByRobots(Exception):
    """Raised instead of fetching a path the host has asked us not to."""

    def __init__(self, url: str) -> None:
        super().__init__(f"robots.txt disallows {url}")
        self.url = url


#: Process-wide, so one sweep fetches a host's robots.txt once per TTL. Its good
#: copies are kept in the database, so a restart does not forget them.
ROBOTS = RobotsCache(store=DatabaseRobotsStore())


async def polite_pause(base_url: str | None, polite_delay: float) -> float:
    """Seconds to wait before the next request to a source's host.

    `Crawl-Delay` is a floor, never a ceiling: a host asking for 20 seconds gets
    20 even though the default is 15, and a host asking for 1 still gets the full
    polite delay. One supplier does ask for 20, so this was a real if small
    breach — the crawler was reading them faster than they had asked in writing.

    Shared by the pipeline (between pages and partitions) and by an adapter that
    makes more than one request for a page.
    """
    if not base_url:
        return polite_delay
    requested = await ROBOTS.crawl_delay(base_url, ROBOTS_TOKEN)
    return max(polite_delay, requested or 0.0)
