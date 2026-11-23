"""Which local address the crawler sends from: the server's IPv4, or a pool of IPv6 addresses.

Chosen per source by `egress = "ipv4" | "ipv6"` in its config (default "ipv4",
so nothing changes until a shop is switched by hand, after a probe shows it
answers over IPv6).

The pool is a fixed set of addresses used for crawling and nothing else
(`CRAWL_IPV6_ADDRESSES`). It is published on /how-we-crawl with its reverse DNS
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
binds 0.0.0.0, so a server that now has IPv6 does not start sending its
requests over IPv6 from an address that is not ours to publish.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import random
import re
import socket
from collections.abc import Callable, Iterator
from contextvars import ContextVar

import httpx

IPV4 = "ipv4"
IPV6 = "ipv6"
EGRESSES = (IPV4, IPV6)

#: The pool, separated by commas or whitespace. Read when a client is built.
POOL_ENV = "CRAWL_IPV6_ADDRESSES"

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


def parse_pool(value: str) -> tuple[str, ...]:
    """The addresses in `value`, validated, deduplicated and sorted.

    A typo must fail loudly rather than silently shrink the pool: every entry
    has to be a global unicast IPv6 address.
    """
    out: set[str] = set()
    for item in re.split(r"[\s,]+", value.strip()):
        if not item:
            continue
        try:
            address = ipaddress.IPv6Address(item)
        except ValueError as exc:
            raise ValueError(f"{POOL_ENV}: {item!r} is not an IPv6 address") from exc
        if not address.is_global:
            raise ValueError(f"{POOL_ENV}: {item} is not a global address")
        out.add(str(address))
    return tuple(sorted(out, key=ipaddress.IPv6Address))


def configured_pool() -> tuple[str, ...]:
    """The crawl pool from the environment; empty when none is configured."""
    return parse_pool(os.environ.get(POOL_ENV, ""))


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
    ) -> None:
        self.egress = check_egress(egress)
        self._choose = choose
        self._transport_for = transport_for or (lambda address: http_transport(address))
        self._ipv4 = self._transport_for(IPV4_ANY)
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
    pool = configured_pool()
    if not pool:
        egress = current_egress()
        if egress == IPV6:
            # Switched to IPv6 with nothing to send from: IPv4, counted, so
            # `make status` says why rather than the shop seeming to refuse.
            return EgressTransport(IPV6, ())
        return None
    return EgressTransport(current_egress(), pool)


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
    sub.add_parser("list", help=f"the pool as {POOL_ENV} gives it")
    check = sub.add_parser("check", help="one request from each address to an IPv6 echo service")
    check.add_argument("--url", default=ECHO_URL, help=f"the echo service (default {ECHO_URL})")
    args = parser.parse_args(argv)

    pool = configured_pool()
    if not pool:
        print(f"no pool: {POOL_ENV} is empty in this environment")
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
        print(f"Remove the failing ones from {POOL_ENV} (or report them to the host by address).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
