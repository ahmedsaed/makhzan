"""The broker proxy: one fixed target, byte for byte, nothing else."""

from __future__ import annotations

import argparse
import asyncio
import contextlib

import pytest
from makhzan_ml.worker import proxy


class Target:
    """A listener standing in for the broker: records what arrives, answers with a prefix."""

    def __init__(self):
        self.received: list[bytes] = []
        self.server = None

    async def start(self) -> tuple[str, int]:
        async def handle(reader, writer):
            data = await reader.read()  # until the client half-closes
            self.received.append(data)
            writer.write(b"broker:" + data)
            await writer.drain()
            writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[:2]


@contextlib.asynccontextmanager
async def running(target_addr, **kw):
    p = proxy.Proxy(("127.0.0.1", 0), target_addr, **kw)
    addr = await p.start()
    task = asyncio.create_task(p.serve_forever())
    try:
        yield p, addr
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def exchange(addr, data: bytes) -> bytes:
    reader, writer = await asyncio.open_connection(*addr)
    writer.write(data)
    await writer.drain()
    writer.write_eof()
    answer = await asyncio.wait_for(reader.read(), 5)
    writer.close()
    return answer


async def test_it_forwards_both_ways_to_the_target():
    target = Target()
    taddr = await target.start()
    async with running(taddr) as (_, addr):
        body = b"POST /ai/v1/hello HTTP/1.1\r\nHost: broker-proxy\r\n\r\n" + b"x" * 200_000
        assert await exchange(addr, body) == b"broker:" + body
    assert target.received == [body]


async def test_a_request_naming_another_host_still_goes_to_the_target():
    """Not an open proxy: CONNECT or an absolute URL is only bytes for the broker."""
    target = Target()
    taddr = await target.start()
    async with running(taddr) as (_, addr):
        for req in (
            b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n",
            b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n",
        ):
            assert await exchange(addr, req) == b"broker:" + req
    assert len(target.received) == 2


async def test_an_unreachable_target_closes_the_connection():
    # A port nothing listens on.
    s = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = s.sockets[0].getsockname()[1]
    s.close()
    await s.wait_closed()
    async with running(("127.0.0.1", port), ) as (_, addr):  # fmt: skip
        assert await exchange(addr, b"hello") == b""


async def test_connections_over_the_limit_are_refused():
    hold = asyncio.Event()

    async def slow(reader, writer):
        await hold.wait()
        writer.close()

    server = await asyncio.start_server(slow, "127.0.0.1", 0)
    taddr = server.sockets[0].getsockname()[:2]
    async with running(taddr, max_connections=1) as (p, addr):
        r1, w1 = await asyncio.open_connection(*addr)
        for _ in range(50):
            if p.active == 1:
                break
            await asyncio.sleep(0.01)
        r2, w2 = await asyncio.open_connection(*addr)
        assert await asyncio.wait_for(r2.read(), 5) == b""  # closed at once
        hold.set()
        w1.close()
        w2.close()
    server.close()


async def test_an_idle_connection_is_closed():
    async def silent(reader, writer):
        await asyncio.sleep(10)

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    taddr = server.sockets[0].getsockname()[:2]
    async with running(taddr, idle_s=0.2) as (_, addr):
        reader, writer = await asyncio.open_connection(*addr)
        assert await asyncio.wait_for(reader.read(), 5) == b""
        writer.close()
    server.close()


@pytest.mark.parametrize(
    "text, ok",
    [
        ("100.64.0.1:8100", ("100.64.0.1", 8100)),
        ("0.0.0.0:8100", ("0.0.0.0", 8100)),
        ("[fd7a:115c:a1e0::1]:8100", ("fd7a:115c:a1e0::1", 8100)),
        ("broker.example.test:8100", None),  # never a name
        ("broker-proxy:8100", None),
        ("100.64.0.1", None),
        ("100.64.0.1:0", None),
        ("100.64.0.1:70000", None),
        ("100.64.0.1:http", None),
    ],
)
def test_addresses_are_ip_and_port_only(text, ok):
    if ok:
        assert proxy.address(text, what="--to") == ok
    else:
        with pytest.raises(argparse.ArgumentTypeError):
            proxy.address(text, what="--to")


def test_the_command_line_refuses_a_name_as_target(capsys):
    with pytest.raises(SystemExit) as e:
        proxy.main(["--listen", "127.0.0.1:8100", "--to", "broker.example.test:8100"])
    assert e.value.code == 2
    assert "must be an IP address" in capsys.readouterr().err
