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

import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from worker.http import BROWSER_HEADERS

#: Re-read a host's robots.txt this often. A sweep of one source runs for hours,
#: and a rule added mid-sweep should take effect within it.
TTL_SECONDS = 3600.0

#: Give up quickly. robots.txt is on the critical path of every fetch, and a slow
#: one must not stall a sweep.
TIMEOUT_SECONDS = 10.0


@dataclass
class _Entry:
    parser: RobotFileParser | None  # None when the host publishes no usable rules
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

        parser: RobotFileParser | None = None
        try:
            # A bare client on purpose: routing this through the adapters' own
            # fetch helper would recurse straight back into this check.
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=True, headers=BROWSER_HEADERS
            ) as client:
                response = await client.get(f"{host}/robots.txt")
            if response.status_code < 400:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
                self.failures.pop(host, None)
            elif response.status_code < 500:
                # No rules published. Everything is allowed.
                self.failures.pop(host, None)
            else:
                self.failures[host] = f"robots.txt returned {response.status_code}"
        except Exception as exc:  # noqa: BLE001 — a probe must not break a sweep
            self.failures[host] = f"robots.txt unreachable: {type(exc).__name__}"

        entry = _Entry(parser=parser, fetched_at=time.monotonic())
        self._hosts[host] = entry
        return entry

    async def allowed(self, url: str, user_agent: str) -> bool:
        entry = await self._entry(url)
        if entry.parser is None:
            return True
        return entry.parser.can_fetch(user_agent, url)

    async def crawl_delay(self, url: str, user_agent: str) -> float | None:
        """Seconds the host asks between requests, if it says."""
        entry = await self._entry(url)
        if entry.parser is None:
            return None
        try:
            value = entry.parser.crawl_delay(user_agent)
        except Exception:  # noqa: BLE001 — a malformed directive is not a rule
            return None
        return float(value) if value is not None else None


class DisallowedByRobots(Exception):
    """Raised instead of fetching a path the host has asked us not to."""

    def __init__(self, url: str) -> None:
        super().__init__(f"robots.txt disallows {url}")
        self.url = url


#: Process-wide, so one sweep fetches a host's robots.txt once per TTL.
ROBOTS = RobotsCache()
