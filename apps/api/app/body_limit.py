"""A ceiling on request bodies for the API's one public write, before anything parses them.

`POST /reports` is open to anyone, so a body is refused with 413 once it is
larger than `MAX_BODY_BYTES`: at once when `Content-Length` says so, and
otherwise (a chunked body, or a length that lies) as soon as that many bytes
have arrived. Nothing is parsed or held beyond the limit. Every other route
is a GET and passes straight through.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from makhzan_schemas.reports import MAX_BODY_BYTES

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: The routes it guards: method and path.
GUARDED = {("POST", "/reports")}


class BodyLimit:
    def __init__(self, app: ASGIApp, limit: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope["method"], scope["path"]) not in GUARDED:
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > self.limit:
                        await _too_large(send)
                        return
                except ValueError:
                    await _too_large(send, status=400, detail=b"bad content-length")
                    return
        # Read it all here, up to the limit, then hand the app what was read.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.limit:
                await _too_large(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _too_large(send: Send, status: int = 413, detail: bytes = b"request too large") -> None:
    body = b'{"detail":"' + detail + b'"}'
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
