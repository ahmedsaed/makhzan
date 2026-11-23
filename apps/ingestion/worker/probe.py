"""Ask each supplier what it thinks of each crawler identity, with the crawler's own client.

    python -m worker.probe [--source ID] [--sites FILE] [--delay 15] [--no-ip]

On the server (the worker's environment: its key, SITE_URL, the database and
the private configuration):

    docker compose -f docker-compose.prod.yml --env-file .env.prod \\
        run --rm --no-deps ingestion python -m worker.probe

For each source it sends, to the URL of the source's real first page
(`SourceAdapter.probe_url`, else the private `probe-sites.txt`, else the shop's
home page):

    robots      robots.txt through the crawler's own cache (`worker.robots.ROBOTS`),
                read as the source's configured identity if not cached: its
                state (fetched, no rules, stale copy, unavailable), whether it
                disallows the page, and whether a group names makhzanbot
    browser     the browser identity (what sources send by default)
    makhzanbot  the honest identity, unsigned
    signed      makhzanbot with a Web Bot Auth signature (only with a key)
    ipv6        whether the shop can be crawled over IPv6 (worker/egress.py): its
                host's IPv6 address (AAAA), then, with a crawl pool configured
                (crawl-pool.yaml), the page asked as the source's own
                identity from one pool address, with no fallback to IPv4

Each other cell is the status code and the HTTP version the server answered with.
The first three columns go out over IPv4, from the server's own address.

**Why Python and not curl.** It used to be a curl script. curl differs from the
crawler's httpx client in its TLS fingerprint (JA3/JA4), in negotiating HTTP/2
where our client speaks HTTP/1.1, and in header order and defaults — all things
Cloudflare scores. curl with browser headers got 429 from a shop the crawler,
with the same headers, read fine. So every request here is built by
`worker.http.make_client` with the identity under test: the probe sends what a
run would send, or it measures nothing.

Read-only and polite: one GET per column per source, no retries, no redirects
followed for the page (a 3xx is reported as such), at least `MIN_GAP` seconds
between any two requests to the same host, and every request through the
crawl's own gate (`worker.http.take_turn`: the host's pace and Crawl-delay, a
pending Retry-After, the slowdown after errors). robots.txt is read as a run
reads it, redirects and stored copies included, and obeyed: a page it
disallows for makhzanbot, or a host whose robots.txt cannot be read (which a
run would refuse too), is not requested at all. A host holding us off (a
pending Retry-After, or slowed after errors) is not probed. Its requests
belong to no run, so no run's `stats.pacing` counts them.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from worker import egress, http
from worker.http import HostBackingOff, host_of, make_client, take_turn
from worker.identity import BROWSER, MAKHZANBOT, Identity, identity_for, using_identity
from worker.robots import ROBOTS_TOKEN, _agent_token

#: Seconds between two requests to one host, at least: the crawler's pace.
MIN_GAP = 15.0

COLUMNS = ("robots", "browser", "makhzanbot", "signed", "ipv6")


@dataclass
class Target:
    source_id: str
    url: str
    #: The identity the source is configured with (robots.txt is asked as it).
    identity: str = BROWSER


@dataclass
class Cell:
    status: int | None = None
    http_version: str | None = None
    error: str | None = None
    note: str | None = None
    #: robots.txt says the page must not be requested (disallowed or unreadable).
    forbids: bool = False

    def text(self) -> str:
        if self.error:
            return self.error
        if self.status is None:
            return self.note or "-"
        version = (self.http_version or "").replace("HTTP/", "h")
        out = f"{self.status} {version}".strip()
        return f"{out} {self.note}" if self.note else out


@dataclass
class Row:
    target: Target
    cells: dict[str, Cell] = field(default_factory=dict)


class _Gate:
    """At least `gap` seconds between requests to one host, and the crawler's own gate.

    Every request also passes `worker.http.take_turn`, the per-host gate every
    crawl request passes: it waits out a pending `Retry-After`, honours the
    host's slowdown after errors and its pace, shares the last-sent time with
    any run in the same process, and refuses (`HostBackingOff`) a host that
    asked for longer than `RETRY_AFTER_CAP`. In the worker (the dashboard's
    probe) that gate is the one the crawl uses; run on its own, it is this
    process's.
    """

    def __init__(
        self,
        gap: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.gap = gap
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    async def space(self, url: str) -> None:
        """Wait out the probe's own gap to `url`'s host (no turn taken)."""
        last = self._last.get(host_of(url))
        if last is not None:
            remaining = last + self.gap - self._clock()
            if remaining > 0:
                await self._sleep(remaining)

    def mark(self, url: str) -> None:
        """A request to the host just went out (or was answered from cache)."""
        self._last[host_of(url)] = self._clock()

    async def wait(self, url: str) -> None:
        await self.space(url)
        await take_turn(host_of(url))
        self.mark(url)


def refusal(url: str) -> str | None:
    """Why the probe must not ask `url`'s host now, if the crawler's gate says so.

    A `Retry-After` still pending, or a host slowed down after recent errors:
    the probe is a diagnosis, and a host in either state has already said what
    it thinks. Read from the process's gate (`worker.http`), which in the
    worker is the crawl's.
    """
    host = host_of(url)
    remaining = http._NOT_BEFORE.get(host, 0.0) - time.monotonic()
    if remaining > 0:
        return f"{host} asked us to wait {remaining:.0f}s more (Retry-After); not probed"
    if http.slowdown(host) > 1:
        return f"{host} is slowed down after recent errors; not probed"
    return None


async def _get(identity: Identity, url: str, gate: _Gate) -> tuple[Cell, httpx.Response | None]:
    await gate.wait(url)
    try:
        async with make_client(identity=identity) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        if isinstance(exc, httpx.TimeoutException):
            http.note_trouble(host_of(url))
        return Cell(error=f"ERR {type(exc).__name__}"), None
    # What the host answered binds the crawl too: a 429's Retry-After holds
    # every later request to it, and errors slow it down (worker.http).
    host = host_of(url)
    http.note_response(host, response.status_code)
    if response.status_code in http._RETRYABLE:
        http.hold_host(host, response.headers.get("Retry-After"))
    return Cell(status=response.status_code, http_version=response.http_version), response


async def _ipv6_addresses(host: str) -> list[str]:
    """The host's IPv6 addresses (AAAA), or none: what decides whether IPv6 is worth asking."""
    import socket

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, family=socket.AF_INET6, type=socket.SOCK_STREAM)
    except OSError:
        return []
    return sorted({info[4][0] for info in infos})


async def _ipv6(
    identity: Identity,
    url: str,
    gate: _Gate,
    *,
    pool: tuple[str, ...] | None = None,
    choose: Callable[[list[str]], str] | None = None,
) -> Cell:
    """Whether `url` answers over IPv6 from the crawl pool, asked as `identity`.

    No AAAA record: nothing is sent, the cell says so. A pool configured: one
    GET from one pool address at random, through the same gate, and no
    fallback, so a failure to connect shows as one. No pool: the DNS answer
    alone, so a shop can be checked before the addresses exist.
    """
    import random

    hostname = httpx.URL(url).host
    if not await _ipv6_addresses(hostname):
        return Cell(note="no IPv6 address")
    pool = egress.configured_pool() if pool is None else pool
    if not pool:
        return Cell(note="has IPv6; no pool here")
    address = (choose or random.choice)(list(pool))
    await gate.wait(url)
    try:
        async with make_client(
            identity=identity, transport=egress.http_transport(address)
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        if isinstance(exc, httpx.TimeoutException):
            http.note_trouble(host_of(url))
        return Cell(error=f"ERR {type(exc).__name__}")
    host = host_of(url)
    http.note_response(host, response.status_code)
    if response.status_code in http._RETRYABLE:
        http.hold_host(host, response.headers.get("Retry-After"))
    return Cell(status=response.status_code, http_version=response.http_version)


async def _robots(identity: Identity, url: str, gate: _Gate) -> Cell:
    """What robots.txt says of `url`, read through the crawler's own cache (`worker.robots.ROBOTS`).

    So the probe sees what a run would: the cached rules or a fresh read (as
    `identity`, paced by the host's gate, redirects followed as a run follows
    them), a stored copy standing in for an unreadable file, `RobotsUnavailable`
    when there is neither, and the file's Crawl-delay, which the gate then
    applies to the probe's own requests. The cell says the cache's state, not a
    status code: a cached file sends nothing.
    """
    from worker import robots as robots_mod

    cache = robots_mod.ROBOTS
    host = host_of(url)
    await gate.space(url)
    try:
        with using_identity(identity):
            allowed = await cache.allowed(url, ROBOTS_TOKEN)
    except robots_mod.RobotsUnavailable as exc:
        gate.mark(url)
        # A run would refuse the host too: nothing else is asked.
        return Cell(error=f"unavailable ({exc.reason[:60]})", forbids=True)
    gate.mark(url)
    entry = getattr(cache, "_hosts", {}).get(host)
    state = getattr(entry, "state", None) or "read"
    words = {"fetched": "fetched", "no_rules": "no rules", "stale": "stale copy"}
    cell = Cell(note=words.get(state, state))
    rules = getattr(entry, "rules", None)
    if not allowed:
        cell.note, cell.forbids = f"{cell.note}; DISALLOWS this page", True
    elif rules is not None and any(
        _agent_token(a) == ROBOTS_TOKEN for group in rules.groups for a in group.agents
    ):
        cell.note = f"{cell.note}; names makhzanbot"
    return cell


def _identities(sign: bool) -> tuple[dict[str, Identity], list[str]]:
    """The identities to compare, and why any is missing."""
    out: dict[str, Identity] = {"browser": identity_for(BROWSER)}
    notes: list[str] = []
    try:
        out["makhzanbot"] = identity_for(MAKHZANBOT, sign=False)
    except RuntimeError as exc:
        notes.append(f"makhzanbot skipped: {exc}")
        return out, notes
    if sign:
        try:
            signed = identity_for(MAKHZANBOT)
        except (RuntimeError, ValueError) as exc:
            notes.append(f"signed skipped: {exc}")
        else:
            if signed.signed:
                out["signed"] = signed
            else:
                notes.append("signed skipped: no MAKHZANBOT_SIGNING_KEY in this environment")
    return out, notes


async def probe(
    targets: list[Target],
    *,
    gap: float = MIN_GAP,
    sign: bool = True,
    gate: _Gate | None = None,
    on_row: Callable[[Row], None] | None = None,
) -> tuple[list[Row], list[str]]:
    """Probe every target; rows in order, and notes on any column skipped."""
    gate = gate or _Gate(max(gap, MIN_GAP))
    identities, notes = _identities(sign)
    rows = []
    for target in targets:
        row = Row(target)
        if why := refusal(target.url):
            row.cells = {column: Cell(error="not asked") for column in COLUMNS}
            rows.append(row)
            notes.append(f"{target.source_id}: {why}")
            if on_row:
                on_row(row)
            continue
        try:
            await _probe_target(row, identities, gate)
        except HostBackingOff as exc:
            for column in COLUMNS:
                row.cells.setdefault(column, Cell(error="not asked"))
            notes.append(f"{target.source_id}: {exc}; not probed further")
        rows.append(row)
        if on_row:
            on_row(row)
    return rows, notes


async def _probe_target(row: Row, identities: dict[str, Identity], gate: _Gate) -> None:
    target = row.target
    robots_identity = identities.get(target.identity, identities["browser"])
    robots = row.cells["robots"] = await _robots(robots_identity, target.url, gate)
    for column in ("browser", "makhzanbot", "signed"):
        identity = identities.get(column)
        if robots.forbids or refusal(target.url):
            # robots.txt rules it out, or the host just told us to hold off
            # (a 429's Retry-After): ask it nothing more.
            row.cells[column] = Cell(error="not asked")
        elif identity is None:
            row.cells[column] = Cell()
        else:
            row.cells[column] = (await _get(identity, target.url, gate))[0]
    if robots.forbids or refusal(target.url):
        row.cells["ipv6"] = Cell(error="not asked")
    else:
        # As the source's own identity, signed where it is: what a run would send.
        own = identities.get("signed") if target.identity == MAKHZANBOT else None
        own = own or identities.get(target.identity) or identities["browser"]
        row.cells["ipv6"] = await _ipv6(own, target.url, gate)


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #


def default_sites_file() -> Path | None:
    """`probe-sites.txt` beside the private `sources.toml`, if there is one."""
    if explicit := os.environ.get("PROBE_SITES"):
        return Path(explicit)
    sources = os.environ.get("MAKHZAN_SOURCES")
    if sources:
        path = Path(sources).with_name("probe-sites.txt")
        if path.exists():
            return path
    return None


def read_sites(path: Path) -> dict[str, str]:
    """`label|url` per line, `#` comments ignored."""
    sites: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        label, url = line.split("|", 1)
        sites[label.strip()] = url.strip()
    return sites


async def targets_from_sources(
    sites: dict[str, str], source_filter: str | None = None
) -> list[Target]:
    """Every enabled source in the `sources` table, at its real first page."""
    from worker.sources.registry import all_enabled, load_adapters

    errors = await load_adapters()
    for source_id, error in errors.items():
        print(f"  {source_id}: not loaded ({error})", file=sys.stderr)
    targets = []
    for adapter in all_enabled():
        if source_filter and adapter.source_id != source_filter:
            continue
        if target := target_for(adapter, sites):
            targets.append(target)
    return targets


def target_for(adapter, sites: dict[str, str]) -> Target | None:
    """Where to probe one source: its real first page, else the sites list, else its home page.

    Any source, enabled or not: the admin dashboard probes one shop at a time,
    and the shop it asks about is usually one paused because it was blocked.
    """
    url = adapter.probe_url() or sites.get(adapter.source_id)
    if not url and adapter.base_url:
        url = f"{adapter.base_url}/"
    return Target(adapter.source_id, url, adapter.identity) if url else None


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

_WIDTHS = {
    "source": 14,
    "robots": 26,
    "browser": 11,
    "makhzanbot": 11,
    "signed": 11,
    "ipv6": 22,
}


def _line(values: dict[str, str]) -> str:
    return " ".join(f"{values.get(k, ''):{w}s}" for k, w in _WIDTHS.items())


def _print_row(row: Row) -> None:
    values = {"source": row.target.source_id}
    values.update({k: c.text() for k, c in row.cells.items()})
    print(_line(values), flush=True)


FOOTER = """
makhzanbot 200            → the shop can be switched (docs/crawler-identity.md).
browser 200, makhzanbot 403/429
                          → its edge refuses unknown bots: register the key, re-probe
                            signed, and write to the shop. A shop already on
                            makhzanbot is not switched back to get past it.
403/429 in every column   → not the headers. Compare with a run from another IP.
ipv6 200                  → the shop answers our pool over IPv6: it can be given
                            egress = "ipv6" (worker/egress.py).
ipv6 no IPv6 address      → it stays on IPv4; nothing was sent over IPv6.
ipv6 ERR, IPv4 columns 200 → IPv6 is broken between us and the shop: leave it on IPv4.
robots unreadable/ERR     → a run would refuse the host today unless it holds a good
                            copy (make status, ROBOTS.TXT); its pages were not asked.
robots DISALLOWS          → the shop's robots.txt rules this page out for makhzanbot
                            (every identity obeys it); its page was not asked.
"""


async def _egress_ip() -> str:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            return (await client.get("https://api.ipify.org")).text.strip()
    except httpx.HTTPError:
        return "unknown"


async def main_async(args: argparse.Namespace) -> int:
    sites_path = Path(args.sites) if args.sites else default_sites_file()
    sites = read_sites(sites_path) if sites_path and sites_path.exists() else {}
    if args.no_db:
        # No database at all: robots.txt copies are kept in memory for this
        # probe, never written to `robots_copies`.
        from worker import robots as robots_mod

        robots_mod.ROBOTS = robots_mod.RobotsCache(store=robots_mod.RobotsStore())
        targets = [Target(label, url) for label, url in sites.items()]
        if args.source:
            targets = [t for t in targets if t.source_id == args.source]
    else:
        targets = await targets_from_sources(sites, args.source)
    if not targets:
        print("nothing to probe (no enabled sources, and no probe-sites list)", file=sys.stderr)
        return 1

    if not args.no_ip:
        print(f"egress IP: {await _egress_ip()}")
    print(f"host:      {os.uname().nodename}")
    gap = max(args.delay, MIN_GAP)
    print(f"gap:       {gap:g} s between requests to one host; no retries, no redirects\n")
    # Rows print as they arrive, so the name column is sized before the first:
    # A long source id overran a fixed 14 and pushed its row out of line.
    _WIDTHS["source"] = max(len("source"), *(len(t.source_id) for t in targets))
    print(_line({k: k for k in _WIDTHS}))
    print(_line({k: "-" * len(k) for k in _WIDTHS}))
    _, notes = await probe(targets, gap=gap, sign=not args.no_sign, on_row=_print_row)
    for note in notes:
        print(f"  ({note})")
    print(FOOTER)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m worker.probe", description=__doc__)
    parser.add_argument("--source", help="only this source id (or probe-sites label)")
    parser.add_argument("--sites", help="a probe-sites.txt (label|url) for fallbacks/--no-db")
    parser.add_argument("--no-db", action="store_true", help="probe the sites list only")
    parser.add_argument("--no-sign", action="store_true", help="skip the signed column")
    parser.add_argument("--no-ip", action="store_true", help="do not look up the egress IP")
    parser.add_argument(
        "--delay", type=float, default=MIN_GAP, help=f"seconds per host (min {MIN_GAP:g})"
    )
    return asyncio.run(main_async(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
