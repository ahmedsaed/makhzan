"""Which local address the crawler sends from: the server's IPv4, or a pool of IPv6 addresses.

Chosen per source by `egress = "ipv4" | "ipv6"` in its config (default "ipv4",
so nothing changes until a shop is switched by hand, after a probe shows it
answers over IPv6).

The pool is a fixed set of addresses used for crawling and nothing else,
listed in `crawl-pool.yaml` in the private configuration (`MAKHZAN_CRAWL_POOL`
names the file; production sets it, so a laptop or a test run has no pool),
so changing it is a reviewed commit. It is published on /how-we-crawl with its reverse DNS
name, so a shop can verify and block it like any other part of our identity.
Each request of an IPv6 source goes out from one of them at random. The owner's
ruling (2026-11-23): the set changes only as the crawler grows, never in
answer to a block. A shop that refuses us is written to, not moved to fresh
addresses, and the shops that block us stay disabled.

**Pacing is untouched.** The pace gate (`worker.http.take_turn`) keys on the
shop's host, never on our address, so a shop sees exactly the requests and
gaps it saw from one address. Spreading them over more addresses changes
which address each request comes from, not how many there are or when they
arrive. Never pace per address: that would multiply the load on every shop.

**A connection that fails over IPv6 falls back to IPv4** (owner): no IPv6
address for the host, a refused connection, a connect timeout. Only failures
before anything was sent fall back, so the shop never sees a request twice.
Each is counted per host in the run's `stats.egress`, with why, and `make
status` (and so the admin dashboard) shows a week of them per shop: a shop
that keeps failing over IPv6 is switched back to "ipv4" by a person. A 403
or a 429 is an answer, not a failure, and never changes the address.

The egress in force is a context variable the pipeline sets for the run, like
the identity, so every client the run makes (`worker.http.make_client`,
robots.txt, the details stage, a bespoke adapter) takes it. Without a pool
configured, clients are built exactly as before. With one, an "ipv4" source
binds 0.0.0.0, or the crawler's own IPv4 address once the pool file lists a
dedicated one (`ipv4: [{address, shared: false}]`), so a server that now has
IPv6 does not start sending its requests over IPv6 from an address that is not
ours to publish.

**Publishing.** With `publish: true` in the pool file, the worker states the
addresses in the database (`makhzan_schemas.crawl.record_crawl_addresses`) at
startup and before each daily sweep. The API serves them, and /how-we-crawl
lists them with `reverse_dns`, the name each dedicated address resolves back
to. Turn it on only once that reverse DNS exists.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import random
import re
import socket
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass

import httpx

IPV4 = "ipv4"
IPV6 = "ipv6"
EGRESSES = (IPV4, IPV6)

#: The environment variable naming the pool file. Unset or empty: no pool.
POOL_ENV = "MAKHZAN_CRAWL_POOL"

#: What every IPv4 connection binds once a pool exists: any local IPv4 address.
IPV4_ANY = "0.0.0.0"

#: Fallback reasons, as counted in `stats.egress`.
NO_IPV6_ADDRESS = "no IPv6 address"
NO_POOL = "no pool configured"


def check_egress(value: object) -> str:
    """A source's `egress` setting, refusing anything but the two modes."""
    if value not in EGRESSES:
        raise ValueError(f"egress must be one of {EGRESSES}, got {value!r}")
    return value  # type: ignore[return-value]


def parse_pool(value: object, *, where: str = POOL_ENV) -> tuple[str, ...]:
    """The addresses in a pool file's `ipv6` list, validated, deduplicated and sorted.

    A typo must fail loudly rather than silently shrink the pool: every entry
    has to be a global unicast IPv6 address.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{where}: `ipv6` must be a list of addresses")
    out: set[str] = set()
    for item in value:
        try:
            address = ipaddress.IPv6Address(str(item).strip())
        except ValueError as exc:
            raise ValueError(f"{where}: {item!r} is not an IPv6 address") from exc
        if not address.is_global:
            raise ValueError(f"{where}: {address} is not a global address")
        out.add(str(address))
    return tuple(sorted(out, key=ipaddress.IPv6Address))


@dataclass(frozen=True)
class PoolConfig:
    """What `crawl-pool.yaml` says: the addresses, and whether to publish them.

    - `ipv6`: the pool IPv6 sources send from, at random.
    - `ipv4`: the IPv4 addresses requests leave from, each `shared` or not. A
      shared one (the server's own, which carries other services) is only
      published, with no crawler reverse DNS. A dedicated one (`shared:
      false`) is used only by the crawler, which then binds it for every IPv4
      connection instead of letting the system pick.
    - `reverse_dns`: the name every dedicated address resolves back to.
    - `publish`: whether /how-we-crawl and /crawler-addresses.json list them.
      Off until the reverse DNS exists, so the check the page describes works.
    """

    ipv6: tuple[str, ...] = ()
    ipv4: tuple[tuple[str, bool], ...] = ()
    reverse_dns: str | None = None
    publish: bool = False

    @property
    def ipv4_bind(self) -> str:
        """The address IPv4 connections bind: the first dedicated one, else any."""
        return next((address for address, shared in self.ipv4 if not shared), IPV4_ANY)

    @property
    def empty(self) -> bool:
        """Nothing to send from: clients are built as they always were."""
        return not self.ipv6 and self.ipv4_bind == IPV4_ANY

    def published(self) -> dict | None:
        """What the worker states for the API (`makhzan_schemas.crawl`), or None."""
        if not self.publish:
            return None
        return {
            "reverse_dns": self.reverse_dns,
            "ipv6": list(self.ipv6),
            "ipv4": [{"address": a, "shared": shared} for a, shared in self.ipv4],
        }


_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _parse_ipv4(value: object, *, where: str) -> tuple[tuple[str, bool], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{where}: `ipv4` must be a list of {{address, shared}}")
    out: list[tuple[str, bool]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"address", "shared"} or "address" not in item:
            raise ValueError(f"{where}: each `ipv4` entry is {{address: ..., shared: true|false}}")
        try:
            address = ipaddress.IPv4Address(str(item["address"]).strip())
        except ValueError as exc:
            raise ValueError(f"{where}: {item['address']!r} is not an IPv4 address") from exc
        if not address.is_global:
            raise ValueError(f"{where}: {address} is not a global address")
        shared = item.get("shared", True)
        if not isinstance(shared, bool):
            raise ValueError(f"{where}: `shared` must be true or false")
        out.append((str(address), shared))
    return tuple(out)


def load_pool_config(path: str) -> PoolConfig:
    """`crawl-pool.yaml`: `ipv6`, and optionally `ipv4`, `reverse_dns`, `publish`."""
    import yaml

    with open(path, encoding="utf-8") as handle:
        try:
            data = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"{path}: not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping with an `ipv6` list")
    unknown = set(data) - {"ipv6", "ipv4", "reverse_dns", "publish"}
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    reverse_dns = data.get("reverse_dns")
    if reverse_dns is not None:
        reverse_dns = str(reverse_dns).strip().lower().rstrip(".")
        if not _HOSTNAME.match(reverse_dns):
            raise ValueError(f"{path}: `reverse_dns` {reverse_dns!r} is not a host name")
    publish = data.get("publish", False)
    if not isinstance(publish, bool):
        raise ValueError(f"{path}: `publish` must be true or false")
    if publish and reverse_dns is None:
        raise ValueError(f"{path}: `publish: true` needs `reverse_dns`")
    config = PoolConfig(
        ipv6=parse_pool(data.get("ipv6"), where=path),
        ipv4=_parse_ipv4(data.get("ipv4"), where=path),
        reverse_dns=reverse_dns,
        publish=publish,
    )
    if publish and not config.ipv6 and not config.ipv4:
        raise ValueError(f"{path}: `publish: true` with no addresses to publish")
    return config


def load_pool_file(path: str) -> tuple[str, ...]:
    """The IPv6 pool listed in the YAML file at `path`."""
    return load_pool_config(path).ipv6


#: (path, mtime) -> config: a client is built per request, the file read once.
_POOL_CACHE: dict[tuple[str, float], PoolConfig] = {}


#: The last config read successfully, kept when a later read fails.
_LAST_GOOD: dict[str, PoolConfig] = {}

log = logging.getLogger(__name__)


def configured_pool_config() -> PoolConfig:
    """The pool file `MAKHZAN_CRAWL_POOL` names, read; empty when unset.

    Named but missing or invalid is an error, not an empty pool: a pool that
    vanished must not quietly turn every IPv6 source into an IPv4 one. That
    error stops the worker at startup (`worker.main.startup`). Once it has
    been read, a later failed read (a bad commit, or a read during `git pull`)
    keeps the last good one and logs why, so one bad file cannot make every
    client of every source raise.
    """
    path = os.environ.get(POOL_ENV, "").strip()
    if not path:
        return PoolConfig()
    try:
        mtime = os.stat(path).st_mtime
        key = (path, mtime)
        if key not in _POOL_CACHE:
            config = load_pool_config(path)
            _POOL_CACHE.clear()
            _POOL_CACHE[key] = config
            _LAST_GOOD[path] = config
        return _POOL_CACHE[key]
    except (OSError, ValueError, ImportError) as exc:
        error = ValueError(f"{POOL_ENV}={path}: {exc}")
        if isinstance(exc, FileNotFoundError):
            error = ValueError(f"{POOL_ENV}={path}: no such file")
        if path in _LAST_GOOD:
            good = _LAST_GOOD[path]
            log.error("%s; keeping the last good pool (%d addresses)", error, len(good.ipv6))
            return good
        raise error from exc


def configured_pool() -> tuple[str, ...]:
    """The crawl's IPv6 pool (`configured_pool_config().ipv6`)."""
    return configured_pool_config().ipv6


_EGRESS: ContextVar[str] = ContextVar("crawler_egress", default=IPV4)


def current_egress() -> str:
    """The egress of the run in progress in this task; IPv4 outside any run."""
    return _EGRESS.get()


@contextlib.contextmanager
def using_egress(egress: str) -> Iterator[str]:
    """Send every request made inside the block (and tasks it starts) over `egress`."""
    token = _EGRESS.set(check_egress(egress))
    try:
        yield egress
    finally:
        _EGRESS.reset(token)


def _fallback_reason(exc: Exception) -> str:
    """Why a connection over IPv6 failed, in a word a person can act on."""
    seen: set[int] = set()
    cause: BaseException | None = exc
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, socket.gaierror):
            return NO_IPV6_ADDRESS
        cause = cause.__cause__ or cause.__context__
    text = str(exc).lower()
    if "name or service not known" in text or "no address associated" in text:
        return NO_IPV6_ADDRESS
    return type(exc).__name__


def http_transport(local_address: str) -> httpx.AsyncBaseTransport:
    """httpx's own transport, its connections bound to `local_address`.

    Binding picks the family too: anyio resolves the shop for the bound
    address's family only, so an IPv6 address asks for AAAA records alone and
    0.0.0.0 for A records alone. Looked up at call time, so tests can route it.
    """
    return httpx.AsyncHTTPTransport(local_address=local_address)


class EgressTransport(httpx.AsyncBaseTransport):
    """Sends each request from a random pool address, or from IPv4.

    One inner transport per address, so connections are kept per address. A
    failure to *connect* over IPv6 — nothing sent — is retried once over IPv4
    and counted; anything after the connection is the response, as ever.
    """

    def __init__(
        self,
        egress: str,
        pool: tuple[str, ...],
        *,
        choose: Callable[[list[str]], str] = random.choice,
        transport_for: Callable[[str], httpx.AsyncBaseTransport] | None = None,
        ipv4: str = IPV4_ANY,
    ) -> None:
        self.egress = check_egress(egress)
        self._choose = choose
        self._transport_for = transport_for or (lambda address: http_transport(address))
        self._ipv4 = self._transport_for(ipv4)
        self._addresses = list(pool) if egress == IPV6 else []
        #: Built on first use: a client is made per request, and an SSL
        #: context per pool address would be spent on all but one.
        self._ipv6: dict[str, httpx.AsyncBaseTransport] = {}

    def _for(self, address: str) -> httpx.AsyncBaseTransport:
        if address not in self._ipv6:
            self._ipv6[address] = self._transport_for(address)
        return self._ipv6[address]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        from worker.http import current_request_log, host_of

        log = current_request_log()
        host = host_of(request.url)
        if not self._addresses:
            if log is not None:
                if self.egress == IPV6:
                    log.note_egress(host, fallback=NO_POOL)
                else:
                    log.note_egress(host, ipv4=True)
            return await self._ipv4.handle_async_request(request)
        address = self._choose(self._addresses)
        try:
            response = await self._for(address).handle_async_request(request)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if log is not None:
                log.note_egress(host, address=address, fallback=_fallback_reason(exc))
            return await self._ipv4.handle_async_request(request)
        if log is not None:
            log.note_egress(host, address=address)
        return response

    async def aclose(self) -> None:
        await self._ipv4.aclose()
        for transport in self._ipv6.values():
            await transport.aclose()


def transport_for_run() -> httpx.AsyncBaseTransport | None:
    """The transport a client of this run should use; None (httpx's own) without a pool."""
    config = configured_pool_config()
    if config.empty:
        if current_egress() == IPV6:
            # Switched to IPv6 with nothing to send from: IPv4, counted, so
            # `make status` says why rather than the shop seeming to refuse.
            return EgressTransport(IPV6, ())
        return None
    return EgressTransport(current_egress(), config.ipv6, ipv4=config.ipv4_bind)


# --------------------------------------------------------------------------- #
# Checking the pool
# --------------------------------------------------------------------------- #

#: Answers with the address a request came from, over IPv6 only. Never a shop:
#: the check asks which of our addresses work, not what any shop thinks of us.
ECHO_URL = "https://api6.ipify.org"


async def check_address(address: str, *, url: str = ECHO_URL, timeout: float = 15.0) -> dict:
    """One request from `address`: whether it connected, and that it left from `address`.

    `seen` is what the echo service saw. Anything but `address` means the
    server is not sending from it (not configured on the interface, or a route
    picking another source), which would make the published list untrue.
    """
    try:
        async with httpx.AsyncClient(transport=http_transport(address), timeout=timeout) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return {"address": address, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    seen = response.text.strip()
    try:
        matches = ipaddress.IPv6Address(seen) == ipaddress.IPv6Address(address)
    except ValueError:
        matches = False
    return {
        "address": address,
        "ok": response.status_code == 200 and matches,
        "status": response.status_code,
        "seen": seen[:64],
    }


async def check_pool(pool: tuple[str, ...], *, url: str = ECHO_URL) -> list[dict]:
    """`check_address` for every address of the pool, one after another."""
    return [await check_address(address, url=url) for address in pool]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        prog="python -m worker.egress",
        description="The crawl's IPv6 pool: list it, or check every address works.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the pool as the file MAKHZAN_CRAWL_POOL names gives it")
    check = sub.add_parser("check", help="one request from each address to an IPv6 echo service")
    check.add_argument("--url", default=ECHO_URL, help=f"the echo service (default {ECHO_URL})")
    args = parser.parse_args(argv)

    pool = configured_pool()
    if not pool:
        print(f"no pool: {POOL_ENV} names no file in this environment")
        return 1
    if args.command == "list":
        for address in pool:
            print(address)
        return 0
    results = asyncio.run(check_pool(pool, url=args.url))
    for result in results:
        if result["ok"]:
            print(f"  ok    {result['address']}")
        elif "error" in result:
            print(f"  FAIL  {result['address']}  {result['error']}")
        else:
            print(
                f"  FAIL  {result['address']}  HTTP {result['status']}, "
                f"seen as {result['seen'] or '(empty)'}"
            )
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)} of {len(results)} addresses work")
    if failed:
        print(
            "Remove the failing ones from crawl-pool.yaml (or report them to the host by address)."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
