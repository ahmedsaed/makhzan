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

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

import httpx

from worker.http import (
    MAX_REDIRECTS,
    HostBackingOff,
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
class _Entry:
    rules: Rules | None  # None when the host publishes no usable rules
    fetched_at: float
    #: robots.txt could not be read and no good copy stands in: nothing may be
    #: fetched from the host until it can (RFC 9309 §2.3.1.4).
    unavailable: bool = False


class RobotsCache:
    """Per-host robots.txt, cached with a TTL.

    Failure handling follows RFC 9309. A 4xx (the common 404) means there are no
    rules and everything is allowed; so does a chain of more than five
    redirects (§2.3.1.2). A 5xx, a 429 or a network failure means the rules are
    *unknown*, and the RFC says to "assume complete disallow": the host's last
    good copy is used if it is at most `STALE_LIMIT_SECONDS` old, and otherwise
    every request to the host raises `RobotsUnavailable` until the file can be
    read again — for the rest of the TTL, so a run does not keep asking.

    That used to allow everything instead, on the theory that a blip should not
    halt a catalogue. The durable cursor makes the cost small: a partition that
    is refused today resumes at the same page tomorrow.

    The good copies live in this process only: a worker restart forgets them,
    and a host whose robots.txt then fails is disallowed until it recovers.
    """

    def __init__(self, ttl: float = TTL_SECONDS, *, wall: Callable[[], float] = time.time) -> None:
        self._ttl = ttl
        self._wall = wall
        self._hosts: dict[str, _Entry] = {}
        #: Per host, the last robots.txt that was read (rules, or None for "no
        #: rules"), and when, in wall-clock seconds.
        self._good: dict[str, tuple[Rules | None, float]] = {}
        self.failures: dict[str, str] = {}

    async def _entry(self, url: str) -> _Entry:
        # The pace gate's own key: built any other way, a mixed-case or
        # explicit-port base URL took its robots.txt turn at a different gate
        # than the pages, and the pages never saw its Crawl-delay.
        host = host_of(url)
        cached = self._hosts.get(host)
        if cached and (time.monotonic() - cached.fetched_at) < self._ttl:
            return cached

        try:
            # A request like any other to the shop: it waits the host's pace,
            # is logged in the run's pacing, and the page after it waits too.
            await take_turn(host, robots=True)
        except HostBackingOff:
            # The host asked us to hold back. Keep the rules we have rather than
            # forgetting them; with none, the request waits on the host anyway.
            if cached:
                return cached
            raise

        failure: str | None = None
        rules: Rules | None = None
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
            note_response(host_of(response.url), response.status_code)
            if response.is_redirect:
                # RFC 9309 §2.3.1.2: past five hops, robots.txt is unavailable,
                # which is read like a 4xx below: no rules.
                pass
            elif response.status_code < 400:
                rules = Rules(response.text)
            elif response.status_code == 429 or response.status_code >= 500:
                # A 429 is "not now", not "no rules": read like a 5xx.
                failure = f"robots.txt returned {response.status_code}"
            # Any other 4xx: no rules published. Everything is allowed.
        except Exception as exc:  # noqa: BLE001 — a probe must not break a sweep
            if isinstance(exc, httpx.TimeoutException):
                note_trouble(host)
            failure = f"robots.txt unreachable: {type(exc).__name__}"

        now = time.monotonic()
        if failure is None:
            self.failures.pop(host, None)
            self._good[host] = (rules, self._wall())
            entry = _Entry(rules=rules, fetched_at=now)
        else:
            good = self._good.get(host)
            age = self._wall() - good[1] if good is not None else None
            if good is not None and age is not None and age <= STALE_LIMIT_SECONDS:
                self.failures[host] = f"{failure}; using the copy from {age / 86400:.1f} days ago"
                entry = _Entry(rules=good[0], fetched_at=now)
            else:
                self.failures[host] = f"{failure}; no usable copy, so nothing is fetched"
                entry = _Entry(rules=None, fetched_at=now, unavailable=True)
        self._hosts[host] = entry
        return entry

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
    This means the rules are unknown, so the page fails and its cursor stays
    where it is for the next run.
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


#: Process-wide, so one sweep fetches a host's robots.txt once per TTL.
ROBOTS = RobotsCache()


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
