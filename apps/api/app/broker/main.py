"""The AI broker: the only thing AI workers talk to (docs/ai/broker-api.md).

A separate service built from the API image, with its own app object, port
and reverse-proxy hostname (P2), never under the public site's `/api`
rewrite: run it as `uvicorn app.broker.main:app`. Workers authenticate with
their own bearer token, stored only as its sha256 (P3); `GET /status` takes
the admin token, whose sha256 is `AI_BROKER_ADMIN_TOKEN_SHA256`.

Production never runs a model. The broker renders requests from the current
rows, hands them to authenticated workers over TLS, stores their scores and
takes each pair one step on (`makhzan_schemas.ai.broker`, `flow`). Each
request is one transaction.

Configuration, all from the environment: `DATABASE_URL` (the same database
as the API), `REDIS_URL` (to queue the rebuild after a window, P16),
`AI_BROKER_ADMIN_TOKEN_SHA256`, `GIT_SHA` (what `/health` reports, baked in
at build), `AI_BROKER_MAX_BODY` (bytes, default 256 KiB).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from makhzan_schemas.ai import broker as core
from makhzan_schemas.ai import candidates  # noqa: F401  (registers the triggers' still_wanted)
from makhzan_schemas.ai.status import collect
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.rebuild import REBUILD_FUNCTION, rebuild_job_id
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.body_limit import BodyLimit

log = logging.getLogger(__name__)

PREFIX = "/ai/v1"
MAX_BODY = int(os.getenv("AI_BROKER_MAX_BODY", str(256 * 1024)))

app = FastAPI(
    title="makhzan AI broker", version="1", docs_url=None, redoc_url=None, openapi_url=None
)
# Results are small; nothing posted here should be large.
app.add_middleware(BodyLimit, limit=MAX_BODY, guards=lambda method, path: method == "POST")


async def queue_rebuild() -> None:
    """Queue `rebuild_and_reindex` for the end of this window, deduplicated by
    the window's job id: the scheme the worker's own `request_rebuild` uses."""
    from arq import create_pool
    from arq.connections import RedisSettings

    job_id, runs_at = rebuild_job_id(datetime.now(timezone.utc))
    pool = await create_pool(
        RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
    )
    try:
        await pool.enqueue_job(REBUILD_FUNCTION, _job_id=job_id, _defer_until=runs_at)
    finally:
        await pool.aclose()


#: What a session's end calls to queue the rebuild; the tests replace it.
app.state.queue_rebuild = queue_rebuild


# --- bodies -----------------------------------------------------------------------------------


class ModelReport(BaseModel):
    model_version: str
    weights_revision: str


class HelloConfig(BaseModel):
    """The worker's configuration as it reports it. Only `lease_s` is acted
    on; the rest (window, max_jobs, on_empty, ...) is kept for status."""

    model_config = ConfigDict(extra="allow")

    lease_s: StrictInt = Field(core.DEFAULT_LEASE_S, ge=core.LEASE_S_MIN, le=core.LEASE_S_MAX)


class HelloBody(BaseModel):
    worker: str | None = None
    models: dict[str, ModelReport]
    image: str | None = None
    device: str | None = None
    dtype: str | None = None
    threads: int | None = None
    config: HelloConfig = Field(default_factory=HelloConfig)


class LeaseBody(BaseModel):
    session: str
    model: str
    model_version: str
    max_jobs: int = Field(1, ge=1, le=1000)
    seconds_left: float | None = Field(None, ge=0)
    seconds_per_request: float | None = Field(None, gt=0)
    #: The worker's id for this request: a retry with the same id gets the
    #: same jobs back instead of a second lease.
    lease_request_id: str | None = Field(None, min_length=1, max_length=64)


class Progress(BaseModel):
    """The job the worker is scoring now: the one an expiry is charged to."""

    model_config = ConfigDict(extra="allow")

    job_id: StrictInt
    order: Literal["ab", "ba"] | None = None


class HeartbeatBody(BaseModel):
    session: str
    lease_ids: list[str] = Field(default_factory=list)
    job_ids: list[int] = Field(default_factory=list)
    rss_bytes: int | None = None
    progress: Progress | None = None


class Score(BaseModel):
    order: Literal["ab", "ba"]
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    p: float = Field(ge=0.0, le=1.0)
    seconds: float | None = Field(None, ge=0)
    extra: dict[str, Any] | None = None


class ResultsBody(BaseModel):
    session: str
    lease_id: str
    job_id: int
    scores: list[Score] = Field(min_length=1, max_length=2)
    device: str | None = Field(None, max_length=16)
    dtype: str | None = Field(None, max_length=16)
    threads: int | None = Field(None, ge=0, le=32767)


class ReleaseBody(BaseModel):
    """No jobs (and no lease) with reason graceful: the session ends."""

    session: str
    lease_id: str | None = None
    job_ids: list[int] = Field(default_factory=list)
    reason: Literal["graceful", "error"] = "graceful"
    error: str | None = None


# --- plumbing ---------------------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def _invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": "invalid", "detail": jsonable_encoder(exc.errors())}
    )


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


async def _as_worker(
    authorization: str | None,
    handler: Callable[..., Awaitable[dict]],
    body: dict,
    **kwargs,
) -> JSONResponse:
    """Authenticate, run one core call in one transaction, commit."""
    token = _bearer(authorization)
    if not token or not 16 <= len(token) <= 256:
        # Refused before a database session is opened: nothing to look up.
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    async with SessionLocal() as session:
        worker = None
        try:
            now = await core.db_now(session)
            worker = await core.authenticate(session, token, now)
            result = await handler(session, worker, body, now, **kwargs)
            await session.commit()
            return JSONResponse(jsonable_encoder(result))
        except core.BrokerError as refusal:
            if refusal.status == 409 and refusal.body.get("error") == "lease_lost":
                # The leases it still holds were extended: keep that.
                await session.commit()
            else:
                await session.rollback()
                if worker is not None:
                    # Every request a known worker makes counts as seen.
                    await core.authenticate(session, token, now)
                    await session.commit()
            return JSONResponse(status_code=refusal.status, content=refusal.body)


# --- endpoints --------------------------------------------------------------------------------


@app.get(f"{PREFIX}/health")
async def health() -> dict:
    return {"ok": True, "broker": os.getenv("GIT_SHA", "unknown")}


@app.post(f"{PREFIX}/hello")
async def hello(body: HelloBody, authorization: str | None = Header(None)) -> JSONResponse:
    return await _as_worker(authorization, core.hello, body.model_dump())


@app.post(f"{PREFIX}/lease")
async def lease(body: LeaseBody, authorization: str | None = Header(None)) -> JSONResponse:
    return await _as_worker(
        authorization, core.lease, body.model_dump(), on_session_end=app.state.queue_rebuild
    )


@app.post(f"{PREFIX}/heartbeat")
async def heartbeat(body: HeartbeatBody, authorization: str | None = Header(None)) -> JSONResponse:
    return await _as_worker(authorization, core.heartbeat, body.model_dump())


@app.post(f"{PREFIX}/results")
async def results(body: ResultsBody, authorization: str | None = Header(None)) -> JSONResponse:
    return await _as_worker(authorization, core.results, body.model_dump())


@app.post(f"{PREFIX}/release")
async def release(body: ReleaseBody, authorization: str | None = Header(None)) -> JSONResponse:
    return await _as_worker(
        authorization, core.release, body.model_dump(), on_session_end=app.state.queue_rebuild
    )


def _admin_ok(authorization: str | None) -> bool:
    expected = os.getenv("AI_BROKER_ADMIN_TOKEN_SHA256", "").strip().lower()
    token = _bearer(authorization)
    if not expected or not token:
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)


@app.get(f"{PREFIX}/status")
async def status(authorization: str | None = Header(None)) -> JSONResponse:
    if not _admin_ok(authorization):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    async with SessionLocal() as session:
        return JSONResponse(jsonable_encoder(await collect(session)))
