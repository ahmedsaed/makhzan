"""`python -m makhzan_ml.worker.proxy --listen 0.0.0.0:8100 --to <broker ip>:8100`: the
workers' only way out.

A TCP forwarder to one fixed address, for the home server's compose stack
(ml/deploy/home-server/compose.yml): the workers sit on a Docker network with `internal:
true`, which has no route anywhere, and this proxy sits on that network and on an ordinary
bridge. Every connection it accepts is joined to `--to`, byte for byte, and to nothing
else: it reads no request, so no request can name another destination (an HTTP `CONNECT`
or an absolute URL is just bytes delivered to the broker, which refuses them). The target
must be an IP address, never a name, so no DNS answer can move it.

Standard library only; it loads no model and no torch, and runs from the worker image.
Limits: `--max-connections` at once (more are closed on accept), and a connection idle in
both directions for `--idle-s` is closed. Logs one line per refused or failed connection,
never the bytes.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ipaddress
import logging
import signal
import sys

log = logging.getLogger("makhzan_ml.worker.proxy")

BUFFER = 64 * 1024


def address(text: str, *, what: str) -> tuple[str, int]:
    """`HOST:PORT` or `[V6]:PORT`, the host an IP address (never a name)."""
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"{what} {text!r}: expected IP:PORT")
    host = host.removeprefix("[").removesuffix("]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{what} {text!r}: the host must be an IP address, not a name"
        ) from None
    port_n = int(port)
    if not 0 < port_n < 65536:
        raise argparse.ArgumentTypeError(f"{what} {text!r}: port out of range")
    return str(ip), port_n


class Proxy:
    def __init__(
        self,
        listen: tuple[str, int],
        target: tuple[str, int],
        *,
        max_connections: int = 32,
        idle_s: float = 900.0,
        connect_timeout_s: float = 10.0,
    ):
        self.listen = listen
        self.target = target
        self.max_connections = max_connections
        self.idle_s = idle_s
        self.connect_timeout_s = connect_timeout_s
        self.active = 0
        self.server: asyncio.base_events.Server | None = None

    async def start(self) -> tuple[str, int]:
        self.server = await asyncio.start_server(self._handle, *self.listen)
        sock = self.server.sockets[0].getsockname()
        log.info("forwarding %s:%s to %s:%s, and nowhere else", sock[0], sock[1], *self.target)
        return sock[0], sock[1]

    async def serve_forever(self) -> None:
        assert self.server is not None
        async with self.server:
            await self.server.serve_forever()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        if self.active >= self.max_connections:
            log.warning("refused %s: %d connections already open", peer, self.active)
            writer.close()
            return
        self.active += 1
        try:
            try:
                up_r, up_w = await asyncio.wait_for(
                    asyncio.open_connection(*self.target), self.connect_timeout_s
                )
            except (OSError, TimeoutError) as e:
                log.warning("%s: could not reach %s:%s: %s", peer, *self.target, e or "timeout")
                return
            try:
                await self._pipe_both(reader, writer, up_r, up_w)
            finally:
                up_w.close()
                with contextlib.suppress(Exception):
                    await up_w.wait_closed()
        finally:
            self.active -= 1
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _pipe_both(self, a_r, a_w, b_r, b_w) -> None:
        idle = asyncio.Event()  # set by each copy on every chunk: "not idle"

        async def copy(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while data := await src.read(BUFFER):
                    idle.set()
                    dst.write(data)
                    await dst.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                with contextlib.suppress(Exception):
                    if dst.can_write_eof():
                        dst.write_eof()  # half-close: the other direction may still answer

        tasks = [asyncio.create_task(copy(a_r, b_w)), asyncio.create_task(copy(b_r, a_w))]
        pending = set(tasks)
        try:
            while pending:
                idle.clear()
                done, pending = await asyncio.wait(pending, timeout=self.idle_s)
                if not done and not idle.is_set():
                    log.info("closing a connection idle for %.0f s", self.idle_s)
                    break
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def _main(args: argparse.Namespace) -> int:
    proxy = Proxy(args.listen, args.to, max_connections=args.max_connections, idle_s=args.idle_s)
    await proxy.start()
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    serving = asyncio.create_task(proxy.serve_forever())
    await stop.wait()
    log.info("stopping")
    serving.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await serving
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m makhzan_ml.worker.proxy", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("--listen", required=True, type=lambda t: address(t, what="--listen"))
    ap.add_argument("--to", required=True, type=lambda t: address(t, what="--to"))
    ap.add_argument("--max-connections", type=int, default=32)
    ap.add_argument("--idle-s", type=float, default=900.0)
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
