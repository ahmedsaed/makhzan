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
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

import httpx

from worker.http import BROWSER_HEADERS, HostBackingOff, take_turn

#: Re-read a host's robots.txt this often. A sweep of one source runs for hours,
#: and a rule added mid-sweep should take effect within it.
TTL_SECONDS = 3600.0

#: Give up quickly. robots.txt is on the critical path of every fetch, and a slow
#: one must not stall a sweep.
TIMEOUT_SECONDS = 10.0


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

    def _groups_for(self, user_agent: str) -> list[_Group]:
        # Matched on the product token, as urllib.robotparser does: "Mozilla/5.0
        # (...)" is "mozilla". Every group naming us applies; failing that, "*".
        token = user_agent.split("/", 1)[0].strip().lower()
        named = [g for g in self.groups if any(a != "*" and a in token for a in g.agents)]
        return named or [g for g in self.groups if "*" in g.agents]

    def allowed(self, url: str, user_agent: str) -> bool:
        parts = urlsplit(url)
        path = parts.path or "/"
        if path == "/robots.txt":
            return True
        # Compared percent-decoded on both sides, so `/a+b` and `/a%2Bb` are one
        # path: a rule must not be dodged by how a character happens to be spelled.
        target = unquote(f"{path}?{parts.query}" if parts.query else path)
        best: tuple[int, bool] | None = None
        for group in self._groups_for(user_agent):
            for pattern, length, allow in group.rules:
                if pattern.match(target) and (
                    best is None or length > best[0] or (length == best[0] and allow)
                ):
                    best = (length, allow)
        return True if best is None else best[1]

    def crawl_delay(self, user_agent: str) -> float | None:
        delays = [g.crawl_delay for g in self._groups_for(user_agent) if g.crawl_delay is not None]
        return max(delays) if delays else None


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = ".*".join(re.escape(part) for part in pattern.rstrip("$").split("*"))
    return re.compile(body + (r"\Z" if anchored else ""), re.DOTALL)


@dataclass
class _Entry:
    rules: Rules | None  # None when the host publishes no usable rules
    fetched_at: float


class RobotsCache:
    """Per-host robots.txt, cached with a TTL.

    Failure handling follows RFC 9309: a 4xx (including the common 404) means
    there are no rules and everything is allowed, while anything else leaves the
    host's rules unknown. On "unknown" this allows the request and records the
    reason — refusing to crawl because a robots.txt request timed out would let a
    blip halt a catalogue, which is a worse failure than the one it avoids.
    """

    def __init__(self, ttl: float = TTL_SECONDS) -> None:
        self._ttl = ttl
        self._hosts: dict[str, _Entry] = {}
        self.failures: dict[str, str] = {}

    async def _entry(self, url: str) -> _Entry:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
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

        rules: Rules | None = None
        try:
            # A bare client on purpose: routing this through the adapters' own
            # fetch helper would recurse straight back into this check.
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=True, headers=BROWSER_HEADERS
            ) as client:
                response = await client.get(f"{host}/robots.txt")
            if response.status_code < 400:
                rules = Rules(response.text)
                self.failures.pop(host, None)
            elif response.status_code < 500:
                # No rules published. Everything is allowed.
                self.failures.pop(host, None)
            else:
                self.failures[host] = f"robots.txt returned {response.status_code}"
        except Exception as exc:  # noqa: BLE001 — a probe must not break a sweep
            self.failures[host] = f"robots.txt unreachable: {type(exc).__name__}"

        entry = _Entry(rules=rules, fetched_at=time.monotonic())
        self._hosts[host] = entry
        return entry

    async def allowed(self, url: str, user_agent: str) -> bool:
        entry = await self._entry(url)
        if entry.rules is None:
            return True
        return entry.rules.allowed(url, user_agent)

    async def crawl_delay(self, url: str, user_agent: str) -> float | None:
        """Seconds the host asks between requests, if it says."""
        try:
            entry = await self._entry(url)
        except HostBackingOff:
            return None  # nothing will be sent to it anyway until it lets us
        if entry.rules is None:
            return None
        return entry.rules.crawl_delay(user_agent)

    def cached_crawl_delay(self, host: str, user_agent: str) -> float | None:
        """`crawl_delay` from what is already cached, never fetching (for the pace gate)."""
        entry = self._hosts.get(host)
        if entry is None or entry.rules is None:
            return None
        return entry.rules.crawl_delay(user_agent)


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
    requested = await ROBOTS.crawl_delay(base_url, BROWSER_HEADERS["User-Agent"])
    return max(polite_delay, requested or 0.0)
