"""Who sent a request: the visitor's address behind the proxies, for rate limiting only.

In production a request reaches the API through two hops of ours (DEPLOYMENT.md):

    visitor -> your reverse proxy (TLS) -> web (Next.js, rewrites /api) -> api

So the TCP peer the API sees is always the web container, and the visitor's
address is only in `X-Forwarded-For`. That header is also something any
visitor can send, so it is believed only this far:

- Only when the peer is one of ours (`TRUSTED_PROXY_NETWORKS`, by default
  loopback and the private ranges Docker networks use). A request from
  anywhere else, an API exposed directly, uses its own peer address.
- Only the entry our own proxies wrote. A proxy that appends (nginx's
  `$proxy_add_x_forwarded_for`) puts the address it saw at the right-hand
  end, after whatever the visitor sent, so the visitor's own entries are to
  the left and never read. `TRUSTED_PROXY_HOPS` is how many proxies in front
  of the web app append one (1: your reverse proxy alone; 2 with a CDN in front
  of it), and the entry that many from the right is the visitor.

The web app adds no entry of its own: Next's rewrite passes the header through
unchanged, and sets one only when there is none (its own peer, the reverse
proxy). Your reverse proxy must set or append `X-Forwarded-For`; if it passed a
visitor's header through untouched, the visitor could choose their address.

Nothing here is stored: the reports endpoint keeps only a salted hash of what
this returns, for 24 hours.
"""

from __future__ import annotations

import ipaddress
import os

from starlette.requests import Request

_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.environ.get("TRUSTED_PROXY_NETWORKS", _DEFAULT_TRUSTED)
    return [ipaddress.ip_network(n.strip(), strict=False) for n in raw.split(",") if n.strip()]


def _hops() -> int:
    try:
        return max(1, int(os.environ.get("TRUSTED_PROXY_HOPS", "1")))
    except ValueError:
        return 1


def _parse(value: str | None) -> IPAddress | None:
    if not value:
        return None
    value = value.strip()
    # "[2001:db8::1]:443" and "203.0.113.7:51234": a port some proxies keep.
    if value.startswith("["):
        value = value[1 : value.find("]")] if "]" in value else value
    elif value.count(":") == 1:
        value = value.split(":", 1)[0]
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    # An IPv4 client seen over an IPv6 socket.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _trusted(address: IPAddress) -> bool:
    return any(address in network for network in _networks())


def client_address(request: Request) -> IPAddress | None:
    """The visitor's address, as far as the proxies in front can vouch for it."""
    peer = _parse(request.client.host if request.client else None)
    if peer is None or not _trusted(peer):
        return peer
    entries = [
        entry.strip()
        for header in request.headers.getlist("x-forwarded-for")
        for entry in header.split(",")
        if entry.strip()
    ]
    if not entries:
        return peer
    hops = _hops()
    # Fewer entries than proxies appending them: the header is short, so the
    # left-most one is the furthest any of ours saw.
    candidate = _parse(entries[max(0, len(entries) - hops)])
    return candidate or peer


def rate_limit_key(address: IPAddress | None) -> str | None:
    """What one sender is counted under: the address, or an IPv6 address's /64.

    A home or mobile IPv6 connection is given a whole /64 and may use any
    address in it, so counting single addresses would let one phone send
    without limit.
    """
    if address is None:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)
