"""Ask each supplier what it thinks of each crawler identity, with the crawler's own client.

    python -m worker.probe [--source ID] [--sites FILE] [--delay 15] [--no-ip]

On the server (the worker's environment: its key, SITE_URL, the database and
the private configuration):

    docker compose -f docker-compose.prod.yml --env-file .env.prod \\
        run --rm --no-deps ingestion python -m worker.probe

For each source it sends, to the URL of the source's real first page
(`SourceAdapter.probe_url`, else the private `probe-sites.txt`, else the shop's
home page):

    robots      GET /robots.txt, as the source's configured identity: its status,
                and whether a group naming makhzanbot applies to the page
    browser     the browser identity (what sources send by default)
    makhzanbot  the honest identity, unsigned
    signed      makhzanbot with a Web Bot Auth signature (only with a key)

Each cell is the status code and the HTTP version the server answered with.

**Why Python and not curl.** It used to be a curl script. curl differs from the
crawler's httpx client in its TLS fingerprint (JA3/JA4), in negotiating HTTP/2
where our client speaks HTTP/1.1, and in header order and defaults — all things
Cloudflare scores. curl with browser headers got 429 from a shop the crawler,
with the same headers, read fine. So every request here is built by
`worker.http.make_client` with the identity under test: the probe sends what a
run would send, or it measures nothing.

Read-only and polite: one GET per column per source, no retries, no redirects
followed (a 3xx is reported as such), and at least `MIN_GAP` seconds between
any two requests to the same host — the crawler's own pace. robots.txt is asked
first and obeyed: a page it disallows for makhzanbot, or a host whose robots.txt
cannot be read (which a run would refuse too), is not requested at all.
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

from worker.http import host_of, make_client
from worker.identity import BROWSER, MAKHZANBOT, Identity, identity_for
from worker.robots import ROBOTS_TOKEN, Rules, _agent_token

#: Seconds between two requests to one host, at least: the crawler's pace.
MIN_GAP = 15.0

COLUMNS = ("robots", "browser", "makhzanbot", "signed")


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
            return "-"
        version = (self.http_version or "").replace("HTTP/", "h")
        out = f"{self.status} {version}".strip()
        return f"{out} {self.note}" if self.note else out


@dataclass
class Row:
    target: Target
    cells: dict[str, Cell] = field(default_factory=dict)


class _Gate:
    """At least `gap` seconds between requests to one host."""

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

    async def wait(self, url: str) -> None:
        host = host_of(url)
        last = self._last.get(host)
        if last is not None:
            remaining = last + self.gap - self._clock()
            if remaining > 0:
                await self._sleep(remaining)
        self._last[host] = self._clock()


async def _get(identity: Identity, url: str, gate: _Gate) -> tuple[Cell, httpx.Response | None]:
    await gate.wait(url)
    try:
        async with make_client(identity=identity) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return Cell(error=f"ERR {type(exc).__name__}"), None
    return Cell(status=response.status_code, http_version=response.http_version), response


async def _robots(identity: Identity, url: str, gate: _Gate) -> Cell:
    cell, response = await _get(identity, f"{host_of(url)}/robots.txt", gate)
    if response is None:
        cell.forbids = True  # unreachable: a run would refuse the host too
        return cell
    status = response.status_code
    if status < 300:
        rules = Rules(response.text)
        named = any(_agent_token(a) == ROBOTS_TOKEN for group in rules.groups for a in group.agents)
        if not rules.allowed(url, ROBOTS_TOKEN):
            cell.note, cell.forbids = "DISALLOWS this page", True
        elif named:
            cell.note = "names makhzanbot"
    elif status == 429 or status >= 500:
        cell.note, cell.forbids = "unreadable", True
    elif 400 <= status < 500:
        cell.note = "no rules"
    else:
        # A redirecting robots.txt: the crawler follows up to five hops and obeys
        # where they lead. The probe does not follow redirects, so it has not
        # read the rules, and asks for nothing it has not cleared.
        cell.note, cell.forbids = "redirects (not followed)", True
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
        robots_identity = identities.get(target.identity, identities["browser"])
        robots = row.cells["robots"] = await _robots(robots_identity, target.url, gate)
        for column in ("browser", "makhzanbot", "signed"):
            identity = identities.get(column)
            if robots.forbids:
                row.cells[column] = Cell(error="not asked")
            elif identity is None:
                row.cells[column] = Cell()
            else:
                row.cells[column] = (await _get(identity, target.url, gate))[0]
        rows.append(row)
        if on_row:
            on_row(row)
    return rows, notes


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
        url = adapter.probe_url() or sites.get(adapter.source_id)
        if not url and adapter.base_url:
            url = f"{adapter.base_url}/"
        if url:
            targets.append(Target(adapter.source_id, url, adapter.identity))
    return targets


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

_WIDTHS = {"source": 14, "robots": 26, "browser": 11, "makhzanbot": 11, "signed": 11}


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
