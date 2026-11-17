"""The AI broker's logic: sessions, leases, results and releases (docs/ai/broker-api.md).

The HTTP layer is `apps/api/app/broker/main.py`; everything it does to the
database is here, in one transaction per request, so the tests and the CLI
can reach it without HTTP. Nothing here branches on a model, stage or
pipeline name: which jobs a worker may lease comes from
`pipelines.stages_for_models`, and what follows a result from `flow.advance`.

Every worker is treated the same (owner, 2026-11-17): no host slots, no
arbitration between models. A worker serves the model keys its row allows,
and its own configuration decides when it runs. The broker leases and accepts
results whatever the AI mode; the mode governs only whether the regroup reads
decisions, and whether a worker's session end queues a rebuild (P16).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.ai import flow, triggers
from makhzan_schemas.ai.decisions import STANDING
from makhzan_schemas.ai.mode import LIVE, ai_mode
from makhzan_schemas.ai.pipelines import PIPELINES, SAME, stages_for_models
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.ai.render import load_shown, render
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import (
    AiDecision,
    AiFlag,
    AiJob,
    AiModelVersion,
    AiScore,
    AiSession,
    AiWorker,
    GroupingOverride,
    WorkerState,
)

log = logging.getLogger(__name__)

QUEUED, LEASED, DONE, CANCELLED, DEAD = "queued", "leased", "done", "cancelled", "dead"
OPEN = (QUEUED, LEASED)

DEFAULT_LEASE_S = 900
#: Bounds on the lease length a hello may ask for.
LEASE_S_MIN, LEASE_S_MAX = 60, 7200
HEARTBEAT_S = 60
#: Why a lease came back with no job, in its `reason` and the session's
#: `end_reason`: nothing queued for the model, or work queued but the first
#: job does not fit the time the worker said it has.
EMPTY, NONE_FIT = "empty", "none_fit"
#: Sessions of one worker and model that never got a lease and ended
#: "none_fit", in a week and since that subject's last dismissed or actioned
#: flag, before a `nothing_fits` flag opens.
NONE_FIT_FLAG_AFTER = 3
#: Kept free at the end of a worker's `seconds_left` when sizing a lease.
LEASE_MARGIN_S = 60
#: `worker_state` key: the newest decision id a rebuild was queued for (P16).
REBUILD_STATE_KEY = "ai_rebuild"
#: P16 queues a rebuild for new standing "same" decisions. True queues one for
#: any new standing decision, so a "same" replaced by "not same" (an AI merge
#: to undo) is applied at the window's end, not the next daily rebuild. An
#: owner decision pending; off until then.
REBUILD_ON_UNMERGE = False


class BrokerError(Exception):
    """A refusal, as the contract's status and body (§3.6)."""

    def __init__(self, status: int, body: dict) -> None:
        super().__init__(body.get("error"))
        self.status = status
        self.body = body


def _unauthorized() -> BrokerError:
    return BrokerError(401, {"error": "unauthorized"})


def _not_allowed(model: str) -> BrokerError:
    return BrokerError(403, {"error": "model_not_allowed", "model": model})


def _version(model: str) -> BrokerError:
    current = MODELS[model].model_version if model in MODELS else None
    return BrokerError(409, {"error": "version", "model": model, "current": current})


def _lost(job_ids: list[int], **extra) -> BrokerError:
    return BrokerError(409, {"error": "lease_lost", "job_ids": job_ids, **extra})


# --- tokens -----------------------------------------------------------------------------------


def new_token() -> str:
    """A fresh bearer token: 32 random bytes, URL-safe."""
    return secrets.token_urlsafe(32)


def token_sha256(token: str) -> bytes:
    """What is stored: a high-entropy random token needs no slow hash (P3)."""
    return hashlib.sha256(token.encode("utf-8")).digest()


async def authenticate(session: AsyncSession, token: str | None, now: datetime) -> AiWorker:
    """The worker a bearer token belongs to; 401 for a missing, unknown or
    revoked one. Updates `last_seen_at`."""
    if not token:
        raise _unauthorized()
    worker = await session.scalar(
        select(AiWorker).where(AiWorker.token_sha256 == token_sha256(token))
    )
    if worker is None or worker.revoked_at is not None:
        raise _unauthorized()
    worker.last_seen_at = now
    return worker


async def db_now(session: AsyncSession) -> datetime:
    """The transaction's own clock, so every timestamp of one request agrees
    with the `now()` the database compares against."""
    return await session.scalar(select(func.now()))


async def _session_of(
    session: AsyncSession, worker: AiWorker, session_id: str, *, lock: bool = False
) -> AiSession:
    """The caller's session row. `lock` holds it for the transaction: a
    session's leases take turns, so a retried /lease that overlaps the
    original waits for it and then replays its answer."""
    try:
        sid = uuid.UUID(str(session_id))
    except ValueError:
        raise BrokerError(422, {"error": "invalid", "detail": "session is not a uuid"}) from None
    row = await session.get(AiSession, sid, with_for_update=lock or None)
    if row is None or row.worker_id != worker.id:
        raise BrokerError(422, {"error": "invalid", "detail": "unknown session"})
    return row


async def _open_flag(session: AsyncSession, kind: str, **values) -> None:
    """One open flag per (kind, pair, subject): a second is left alone."""
    await session.execute(
        insert(AiFlag)
        .values(kind=kind, **values)
        .on_conflict_do_nothing(
            index_elements=["kind", "listing_a", "listing_b", "subject"],
            index_where=text("status = 'open'"),  # literal: see triggers.enqueue
        )
    )


def lease_seconds(value) -> int:
    """A hello's `config.lease_s`: an integer within the bounds, else 422."""
    if value is None:
        return DEFAULT_LEASE_S
    if isinstance(value, bool) or not isinstance(value, int):
        raise BrokerError(422, {"error": "invalid", "detail": "config.lease_s is not an integer"})
    if not LEASE_S_MIN <= value <= LEASE_S_MAX:
        raise BrokerError(
            422,
            {"error": "invalid", "detail": f"config.lease_s is {LEASE_S_MIN}..{LEASE_S_MAX}"},
        )
    return value


async def sweep_judges(session: AsyncSession, judges: flow.Judges | None = None) -> int:
    """Move every queued job whose (pipeline, stage, judge) is not its stage's
    current judge (a new model or prompt version) to the current one, keeping
    its reason and priority; a job whose stage left the registry is only
    cancelled. Set-based: one UPDATE, then batched inserts. Run at hello and by
    the daily producers, never inside a lease, so a version bump with a large
    queue does not hold a lease's rows (or its HTTP request) for long. Rows a
    lease has locked are skipped and moved by the next sweep."""
    judges = judges or await flow.current_judges(session)
    current = [(p, s, judge) for (p, s), judge in judges.items()]
    stale = (
        select(AiJob.id)
        .where(
            AiJob.status == QUEUED,
            tuple_(AiJob.pipeline, AiJob.stage, AiJob.model_version_id).not_in(current),
        )
        .with_for_update(skip_locked=True)
    )
    moved = (
        await session.execute(
            update(AiJob)
            .where(AiJob.id.in_(stale))
            .values(status=CANCELLED, last_error="judge changed; moved to the current judge")
            .returning(
                AiJob.pipeline,
                AiJob.stage,
                AiJob.reason,
                AiJob.priority,
                AiJob.listing_a,
                AiJob.listing_b,
            )
            .execution_options(synchronize_session=False)
        )
    ).all()
    by_stage: dict[tuple[str, str], list[triggers.PairRequest]] = {}
    for pipeline_name, stage, reason, priority, a, b in moved:
        if (pipeline_name, stage) in judges:
            by_stage.setdefault((pipeline_name, stage), []).append(
                triggers.PairRequest(a, b, pipeline_name, priority, reason)
            )
    for (_, stage), requests in by_stage.items():
        await triggers.enqueue(session, requests, stage=stage)
    return len(moved)


# --- hello ------------------------------------------------------------------------------------


async def queued_requests(session: AsyncSession, model: str) -> int:
    """Requests waiting for `model`: two per queued job of any stage that uses
    it, whichever judge it was queued at (a stale judge's job is moved to the
    current one at lease). An upper bound: an order already scored is not sent."""
    stages = stages_for_models({model})
    if not stages:
        return 0
    jobs = await session.scalar(
        select(func.count())
        .select_from(AiJob)
        .where(AiJob.status == QUEUED, tuple_(AiJob.pipeline, AiJob.stage).in_(stages))
    )
    return 2 * int(jobs or 0)


async def hello(session: AsyncSession, worker: AiWorker, body: dict, now: datetime) -> dict:
    """Start a session (§3.1): which of the worker's models are at the
    registry's version, and whether there is work for them."""
    reported = body.get("models") or {}
    if len(reported) != 1:
        # One model per session: "never leased" and `end_model` are then per
        # model by construction. A worker serving two keys opens two sessions.
        raise BrokerError(422, {"error": "invalid", "detail": "a hello names exactly one model"})
    allowed = set(worker.models)
    for key in reported:
        if key not in allowed or key not in MODELS:
            raise _not_allowed(key)
    config = body.get("config") or {}
    lease_s = lease_seconds(config.get("lease_s"))
    # Jobs queued at an old judge move to the current one before the counts
    # below, so this worker's own leases see them.
    judges = await flow.current_judges(session)
    await sweep_judges(session, judges)
    answer: dict[str, dict] = {}
    for key, versions in reported.items():
        current = MODELS[key]
        ok = (
            versions.get("model_version") == current.model_version
            and versions.get("weights_revision") == current.weights_revision
        )
        if not ok:
            await _open_flag(
                session,
                "version_drift",
                subject=f"{worker.name}/{key}"[:100],
                detail={
                    "worker": worker.name,
                    "model": key,
                    "reported": versions,
                    "current": {
                        "model_version": current.model_version,
                        "weights_revision": current.weights_revision,
                    },
                },
            )
        answer[key] = {
            "model_version": current.model_version,
            "ok": ok,
            "queued_requests": await queued_requests(session, key),
            # What the broker renders for this model now, per stage: the
            # prompt versions a worker's leases will carry.
            "stages": [
                {
                    "pipeline": p,
                    "stage": s,
                    "prompt_version": PIPELINES[p].stage(s).prompt_version,
                }
                for p, s in stages_for_models({key})
            ],
        }
    row = AiSession(
        id=uuid.uuid4(),
        worker_id=worker.id,
        models={
            key: {
                "model_version": versions.get("model_version"),
                "weights_revision": versions.get("weights_revision"),
                "ok": answer[key]["ok"],
            }
            for key, versions in reported.items()
        },
        hello={k: v for k, v in body.items() if k != "models"},
        lease_s=lease_s,
        started_at=now,
        last_seen_at=now,
    )
    session.add(row)
    worker.last_hello = {**body, "at": now.isoformat(), "session": str(row.id)}
    await session.flush()
    return {
        "session": str(row.id),
        "models": answer,
        "lease_s": lease_s,
        "heartbeat_s": max(1, min(HEARTBEAT_S, lease_s // 3)),
    }


# --- the reaper -------------------------------------------------------------------------------


async def _fail(session: AsyncSession, jobs: list[AiJob], error: str) -> None:
    """Count an attempt on each job (its lease already cleared): queued again,
    or dead at `max_attempts` with a poison flag."""
    for job in jobs:
        job.attempts += 1
        job.last_error = error
        job.lease_id = job.leased_by = job.lease_expires_at = job.in_hand_at = None
        if job.attempts >= job.max_attempts:
            job.status = DEAD
            await _open_flag(
                session,
                "poison_job",
                listing_a=job.listing_a,
                listing_b=job.listing_b,
                job_id=job.id,
                model_version_id=job.model_version_id,
                detail={"pipeline": job.pipeline, "stage": job.stage, "error": error},
            )
        else:
            job.status = QUEUED


def _requeue_free(job: AiJob) -> None:
    job.status = QUEUED
    job.lease_id = job.leased_by = job.lease_expires_at = job.in_hand_at = None


async def reap(session: AsyncSession) -> int:
    """Leases past their time go back to the queue (the worker died: killed
    for memory, a lost machine). Only the job the worker was scoring is
    charged an attempt: the one its last heartbeat named (`in_hand_at`). Its
    co-leased jobs never started, so they go back free, and one poison job no
    longer takes them down with it. A lease with no job reported in hand
    (the worker died before any heartbeat said) charges every job, as before.
    At `max_attempts` a job is dead and flagged. Lazy, at the start of every
    lease: no cron."""
    expired = list(
        await session.scalars(
            select(AiJob)
            .where(AiJob.status == LEASED, AiJob.lease_expires_at < func.now())
            .with_for_update(skip_locked=True)
        )
    )
    by_lease: dict[uuid.UUID, list[AiJob]] = {}
    for job in expired:
        by_lease.setdefault(job.lease_id, []).append(job)
    for jobs in by_lease.values():
        in_hand = [job for job in jobs if job.in_hand_at is not None]
        if not in_hand:
            await _fail(session, jobs, "lease expired")
            continue
        await _fail(session, in_hand, "lease expired while in hand")
        for job in jobs:
            if job not in in_hand:
                job.last_error = "lease expired before it was started; re-queued free"
                _requeue_free(job)
    await session.flush()
    return len(expired)


async def _move(session: AsyncSession, job: AiJob, judges: flow.Judges) -> int:
    """Cancel one queued job that is not at its stage's current judge (the
    sweep missed it: locked, or the version changed since) and queue it
    there, keeping its reason, so its trigger's `still_wanted` still applies."""
    job.status = CANCELLED
    if (job.pipeline, job.stage) not in judges:
        job.last_error = "pipeline or stage no longer registered"
        await session.flush()
        return 0
    job.last_error = "judge changed; moved to the current judge"
    await session.flush()
    return await triggers.enqueue(
        session,
        [
            triggers.PairRequest(
                job.listing_a, job.listing_b, job.pipeline, job.priority, job.reason
            )
        ],
        stage=job.stage,
    )


# --- lease ------------------------------------------------------------------------------------


async def _overridden(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    return (
        await session.scalar(
            select(GroupingOverride.id).where(
                GroupingOverride.listing_a == a,
                GroupingOverride.listing_b == b,
                GroupingOverride.removed_at.is_(None),
            )
        )
    ) is not None


@dataclass
class _Ready:
    job: AiJob
    requests: list[dict]


async def _prepare(
    session: AsyncSession, job: AiJob, judges: flow.Judges, now: datetime
) -> _Ready | None:
    """Re-check a queued job and render what it still needs. None when it was
    cancelled, moved to the current judge, or found fully scored (then done,
    and handed to the transition in this transaction)."""
    if judges.get((job.pipeline, job.stage)) != job.model_version_id:
        # Every path that returns None leaves the job no longer queued, or
        # the lease loop would fetch it again.
        await _move(session, job, judges)
        return None
    shown = await load_shown(session, (job.listing_a, job.listing_b))
    a, b = shown.get(job.listing_a), shown.get(job.listing_b)
    if (
        a is None
        or b is None
        or a.listing.status != ListingStatus.ACTIVE
        or b.listing.status != ListingStatus.ACTIVE
    ):
        job.status, job.last_error = CANCELLED, "a listing is no longer active"
        return None
    if await _overridden(session, job.listing_a, job.listing_b):
        job.status, job.last_error = CANCELLED, "a person has ruled on the pair"
        return None
    if not await triggers.still_wanted(session, job):
        job.status, job.last_error = CANCELLED, f"no longer wanted by {job.reason}"
        return None
    owed = await _render_owed(session, job, a, b)
    if not owed:
        # A job never carries zero orders: done now, and on to the next step.
        job.status, job.done_at = DONE, now
        await session.flush()
        await flow.on_scores(session, job)
        return None
    return _Ready(job, owed)


async def _render_owed(session: AsyncSession, job: AiJob, a, b) -> list[dict]:
    """Render the job's two requests from the current rows, record their
    hashes and the content hashes on the job, and return the orders that have
    no score under its judge yet."""
    stage = PIPELINES[job.pipeline].stage(job.stage)
    rendered = render(stage, a, b)
    job.request_sha256 = rendered.hex()
    job.content_sha256_a, job.content_sha256_b = a.content_sha256, b.content_sha256
    scored = set(
        await session.scalars(
            select(AiScore.request_sha256).where(
                AiScore.model_version_id == job.model_version_id,
                AiScore.request_sha256.in_(list(rendered.sha256.values())),
            )
        )
    )
    return [
        {
            "order": order,
            "request_sha256": rendered.sha256[order].hex(),
            "payload": rendered.payloads[order],
        }
        for order, digest in rendered.sha256.items()
        if digest not in scored
    ]


def _lease_answer(lease_id: uuid.UUID, expires: datetime, taken: list[_Ready]) -> dict:
    return {
        "lease_id": str(lease_id),
        "expires_at": expires.isoformat(),
        "jobs": [
            {
                "job_id": ready.job.id,
                "prompt_version": PIPELINES[ready.job.pipeline]
                .stage(ready.job.stage)
                .prompt_version,
                "requests": ready.requests,
            }
            for ready in taken
        ],
    }


async def _replay(
    session: AsyncSession, worker: AiWorker, row: AiSession, now: datetime
) -> dict | None:
    """A retried /lease (same `lease_request_id`, the session row locked):
    the jobs of the lease it got, still held, re-rendered, their expiry
    renewed. A job found to owe nothing now (scored meanwhile, by request
    hash) is finished, not renewed and left out. None when no job is still
    held, and a fresh lease is made instead. (A session serves one model, so
    the replayed lease is always of the model asked.)"""
    jobs = list(
        await session.scalars(
            select(AiJob)
            .where(
                AiJob.status == LEASED,
                AiJob.lease_id == row.last_lease_id,
                AiJob.leased_by == worker.id,
                # An expired lease is not renewed by a replay, even before
                # the reaper has reached it: it is lost, and a fresh lease
                # (which reaps first) follows.
                AiJob.lease_expires_at > now,
            )
            .order_by(AiJob.priority.desc(), AiJob.created_at, AiJob.id)
            .with_for_update()
        )
    )
    expires = now + timedelta(seconds=row.lease_s)
    taken = []
    for job in jobs:
        shown = await load_shown(session, (job.listing_a, job.listing_b))
        owed = await _render_owed(session, job, shown[job.listing_a], shown[job.listing_b])
        if owed:
            job.lease_expires_at = expires
            taken.append(_Ready(job, owed))
            continue
        job.status, job.done_at = DONE, now
        job.lease_id = job.leased_by = job.lease_expires_at = job.in_hand_at = None
        await session.flush()
        await flow.on_scores(session, job)
    await session.flush()
    return _lease_answer(row.last_lease_id, expires, taken) if taken else None


async def _flag_if_never_fits(
    session: AsyncSession, worker: AiWorker, model: str, body: dict, head_owed: int, now: datetime
) -> None:
    """A worker whose sessions keep ending with nothing fitting its time (a
    window too short for one job, or a wrong `seconds_per_request`) never
    scores anything; after `NONE_FIT_FLAG_AFTER` such sessions in a week a
    person is told.

    Counted per worker and model, over sessions that never got a lease (a
    night that scored and then ran out of window is healthy), and only since
    the subject's latest dismissed or actioned flag, so a dismissal is not
    undone by the sessions it was about."""
    subject = f"{worker.name}/{model}"[:100]
    since = now - timedelta(days=7)
    resolved = await session.scalar(
        select(func.max(func.coalesce(AiFlag.resolved_at, AiFlag.created_at))).where(
            AiFlag.kind == "nothing_fits", AiFlag.subject == subject, AiFlag.status != "open"
        )
    )
    if resolved is not None and resolved > since:
        since = resolved
    recent = await session.scalar(
        select(func.count())
        .select_from(AiSession)
        .where(
            AiSession.worker_id == worker.id,
            AiSession.end_model == model,
            AiSession.end_reason == NONE_FIT,
            AiSession.last_lease_id.is_(None),
            AiSession.ended_at >= since,
        )
    )
    if (recent or 0) >= NONE_FIT_FLAG_AFTER:
        await _open_flag(
            session,
            "nothing_fits",
            subject=subject,
            detail={
                "worker": worker.name,
                "model": model,
                "sessions_counted": int(recent),
                "seconds_left": body.get("seconds_left"),
                "seconds_per_request": body.get("seconds_per_request"),
                "head_job_owes": head_owed,
            },
        )


async def lease(
    session: AsyncSession,
    worker: AiWorker,
    body: dict,
    now: datetime,
    *,
    on_session_end: Callable[[], Awaitable[None]] | None = None,
) -> dict:
    """Up to `max_jobs` jobs for one model, rendered from the current rows (§3.2)."""
    model = body["model"]
    if model not in worker.models or model not in MODELS:
        raise _not_allowed(model)
    row = await _session_of(session, worker, body["session"], lock=True)
    if model not in (row.models or {}):
        # The session said hello for another model: a session serves one.
        raise BrokerError(
            409,
            {"error": "wrong_model", "model": model, "session_model": next(iter(row.models), None)},
        )
    reported = row.models[model]
    if (
        body.get("model_version") != MODELS[model].model_version
        or reported.get("model_version") != MODELS[model].model_version
        or not reported.get("ok")
    ):
        raise _version(model)
    row.last_seen_at = now
    request_id = body.get("lease_request_id")
    if request_id and request_id == row.last_lease_request and row.last_lease_id:
        replay = await _replay(session, worker, row, now)
        if replay is not None:
            return replay

    await reap(session)
    judges = await flow.current_judges(session)
    mine = sorted({judges[key] for key in judges if PIPELINES[key[0]].stage(key[1]).model == model})

    max_jobs = int(body.get("max_jobs") or 1)
    per_request = body.get("seconds_per_request")
    budget = None
    if per_request and body.get("seconds_left") is not None:
        budget = float(body["seconds_left"]) - LEASE_MARGIN_S
    lease_id = uuid.uuid4()
    expires = now + timedelta(seconds=row.lease_s)
    taken: list[_Ready] = []
    seen: list[int] = []
    owed = 0
    head_owed = 0  # requests the first job that did not fit still owed
    full = False
    while not full and len(taken) < max_jobs:
        # Lock only as many rows as are still wanted: a concurrent lease must
        # not find the queue empty because this one holds a wide scan.
        query = (
            select(AiJob)
            .where(AiJob.status == QUEUED, AiJob.model_version_id.in_(mine))
            .order_by(AiJob.priority.desc(), AiJob.created_at, AiJob.id)
            .limit(max_jobs - len(taken))
            .with_for_update(skip_locked=True)
        )
        if seen:
            # Explicit, not left to autoflush: a job looked at once is not
            # fetched again in this lease, whatever became of it.
            query = query.where(AiJob.id.not_in(seen))
        batch = list(await session.scalars(query))
        if not batch:
            break
        for job in batch:
            seen.append(job.id)
            ready = await _prepare(session, job, judges, now)
            if ready is None:
                continue
            if budget is not None and (owed + len(ready.requests)) * float(per_request) > budget:
                # It does not fit: stop here, so priority order holds. It
                # stays queued for the next lease.
                full = True
                head_owed = head_owed or len(ready.requests)
                break
            job.status, job.lease_id, job.leased_by = LEASED, lease_id, worker.id
            job.leased_at, job.lease_expires_at, job.in_hand_at = now, expires, None
            owed += len(ready.requests)
            taken.append(ready)
    await session.flush()
    if not taken and head_owed:
        # Work is queued, but its first job does not fit the time the worker
        # has: not "empty". The session ends (the worker sends nothing more).
        # A session that leased before is a healthy night whose window ran
        # out with a backlog left: it ends like a graceful release, and P16
        # is considered for what it decided. Only a session that never got a
        # lease skips P16, and only those count towards `nothing_fits`.
        row.ended_at, row.end_reason, row.end_model = now, NONE_FIT, model
        await session.flush()
        if row.last_lease_id is not None:
            await maybe_rebuild(session, on_session_end)
        else:
            await _flag_if_never_fits(session, worker, model, body, head_owed, now)
        return {"lease_id": None, "jobs": [], "reason": NONE_FIT}
    if not taken:
        row.ended_at, row.end_reason, row.end_model = now, EMPTY, model
        await session.flush()
        await maybe_rebuild(session, on_session_end)
        return {"lease_id": None, "jobs": [], "reason": EMPTY}
    row.ended_at = row.end_reason = row.end_model = None
    row.last_lease_request, row.last_lease_id = (
        (str(request_id)[:64] if request_id else None),
        (lease_id),
    )
    return _lease_answer(lease_id, expires, taken)


# --- heartbeat --------------------------------------------------------------------------------


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def heartbeat(session: AsyncSession, worker: AiWorker, body: dict, now: datetime) -> dict:
    """Extend this worker's live leases (§3.3). A lease with no live job of
    this worker left, or a named job it no longer holds, is lost: the rest is
    still extended, and the answer is 409 naming what was lost."""
    row = await _session_of(session, worker, body["session"])
    row.last_seen_at = now
    lease_ids = [x for x in (_uuid(v) for v in body.get("lease_ids") or []) if x is not None]
    expires = now + timedelta(seconds=row.lease_s)
    held = list(
        await session.scalars(
            select(AiJob)
            .where(
                AiJob.status == LEASED,
                AiJob.leased_by == worker.id,
                AiJob.lease_id.in_(lease_ids or [uuid.uuid4()]),
            )
            .with_for_update()
        )
    )
    progress = body.get("progress") or {}
    in_hand = progress.get("job_id") if isinstance(progress, dict) else None
    in_hand_lease = next((job.lease_id for job in held if job.id == in_hand), None)
    for job in held:
        job.lease_expires_at = expires
        if in_hand_lease is not None and job.lease_id == in_hand_lease:
            # The job in hand is the one a crash is blamed on (`reap`).
            job.in_hand_at = now if job.id == in_hand else None
    await session.flush()
    live_leases = {job.lease_id for job in held}
    lost_leases = [str(x) for x in lease_ids if x not in live_leases]
    held_ids = {job.id for job in held}
    lost_jobs = sorted(int(j) for j in body.get("job_ids") or [] if int(j) not in held_ids)
    if lost_leases or lost_jobs:
        raise _lost(
            lost_jobs, lease_ids=lost_leases, expires_at=expires.isoformat() if held else None
        )
    return {"expires_at": expires.isoformat()}


# --- results ----------------------------------------------------------------------------------


async def _judge_model(session: AsyncSession, job: AiJob) -> str:
    return await session.scalar(
        select(AiModelVersion.model).where(AiModelVersion.id == job.model_version_id)
    )


async def _scored(session: AsyncSession, job: AiJob, digests: list[bytes]) -> set[bytes]:
    return set(
        await session.scalars(
            select(AiScore.request_sha256).where(
                AiScore.model_version_id == job.model_version_id,
                AiScore.request_sha256.in_(digests),
            )
        )
    )


async def results(session: AsyncSession, worker: AiWorker, body: dict, now: datetime) -> dict:
    """Store one job's scores, idempotent on the request hash, then take the
    pair one step on (§3.4)."""
    row = await _session_of(session, worker, body["session"])
    row.last_seen_at = now
    job_id = int(body["job_id"])
    job = await session.get(AiJob, job_id, with_for_update=True)
    if job is None:
        raise _lost([job_id])
    if await _judge_model(session, job) not in worker.models:
        raise _not_allowed(await _judge_model(session, job))
    scores = body.get("scores") or []
    rendered = job.request_sha256 or {}
    digests = []
    for score in scores:
        if rendered.get(score["order"]) != score["request_sha256"]:
            if job.status == LEASED and job.leased_by == worker.id:
                raise BrokerError(422, {"error": "request_mismatch"})
            raise _lost([job_id])
        digests.append(bytes.fromhex(score["request_sha256"]))
    lease_id = _uuid(body.get("lease_id"))
    if not (job.status == LEASED and job.lease_id == lease_id and job.leased_by == worker.id):
        # A retried POST after the job was done changes nothing, and says so.
        if (
            job.status == DONE
            and digests
            and len(await _scored(session, job, digests)) == len(set(digests))
        ):
            return {"accepted": 0, "duplicate": len(scores), "job": DONE, "next": None}
        raise _lost([job_id])
    accepted = 0
    for score, digest in zip(scores, digests, strict=True):
        inserted = await session.scalar(
            insert(AiScore)
            .values(
                model_version_id=job.model_version_id,
                listing_a=job.listing_a,
                listing_b=job.listing_b,
                reading_order=score["order"],
                request_sha256=digest,
                content_sha256_a=job.content_sha256_a,
                content_sha256_b=job.content_sha256_b,
                p=float(score["p"]),
                extra=score.get("extra"),
                seconds=score.get("seconds"),
                device=body.get("device"),
                dtype=body.get("dtype"),
                threads=body.get("threads"),
                worker_id=worker.id,
                job_id=job.id,
                scored_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_ai_score_request")
            .returning(AiScore.id)
        )
        accepted += inserted is not None
    await session.flush()
    both = [bytes.fromhex(h) for h in rendered.values()]
    if len(await _scored(session, job, both)) < len(set(both)):
        return {
            "accepted": accepted,
            "duplicate": len(scores) - accepted,
            "job": LEASED,
            "next": None,
        }
    job.status, job.done_at = DONE, now
    job.lease_id = job.leased_by = job.lease_expires_at = job.in_hand_at = None
    await session.flush()
    step = await flow.on_scores(session, job)
    nxt: dict = {"action": step.action}
    if step.stage:
        nxt["stage"] = step.stage
    if step.outcome:
        nxt["outcome"] = step.outcome
    return {"accepted": accepted, "duplicate": len(scores) - accepted, "job": DONE, "next": nxt}


# --- release ----------------------------------------------------------------------------------


async def release(
    session: AsyncSession,
    worker: AiWorker,
    body: dict,
    now: datetime,
    *,
    on_session_end: Callable[[], Awaitable[None]] | None = None,
) -> dict:
    """Hand leased jobs back (§3.5): graceful counts no attempt; an error
    counts one, and the job is dead at `max_attempts`. Scores already
    submitted are kept. A graceful release with no jobs is how a worker that
    holds nothing ends its session (so P16 can fire)."""
    row = await _session_of(session, worker, body["session"])
    row.last_seen_at = now
    lease_id = _uuid(body.get("lease_id"))
    ids = [int(j) for j in body.get("job_ids") or []]
    if not ids and body.get("reason", "graceful") != "graceful":
        raise BrokerError(422, {"error": "invalid", "detail": "an error release names its jobs"})
    jobs = list(
        await session.scalars(
            select(AiJob).where(AiJob.id.in_(ids or [-1])).with_for_update().order_by(AiJob.id)
        )
    )
    found = {job.id for job in jobs}
    lost = sorted(
        {j for j in ids if j not in found}
        | {
            job.id
            for job in jobs
            if not (
                job.status == LEASED and job.lease_id == lease_id and job.leased_by == worker.id
            )
        }
    )
    if lost:
        raise _lost(lost)
    for job in jobs:
        model = await _judge_model(session, job)
        if model not in worker.models:
            raise _not_allowed(model)
    graceful = body.get("reason", "graceful") == "graceful"
    if graceful:
        for job in jobs:
            _requeue_free(job)
    else:
        await _fail(session, jobs, str(body.get("error") or "released with an error")[:2000])
    await session.flush()
    if graceful:
        # A session already ended by the broker (empty, none_fit) keeps that
        # end: it is what `nothing_fits` counts. P16 still applies.
        if row.end_reason not in (EMPTY, NONE_FIT):
            row.ended_at, row.end_reason = now, "released"
        await session.flush()
        await maybe_rebuild(session, on_session_end)
    return {"released": len(jobs)}


# --- the rebuild after a window (P16) ---------------------------------------------------------


async def maybe_rebuild(session: AsyncSession, queue: Callable[[], Awaitable[None]] | None) -> bool:
    """When a worker's session ends (a graceful release, an empty lease, a
    none_fit after a lease) and
    standing "same" decisions were written since the last rebuild this
    queued, queue `rebuild_and_reindex` through the window job id
    (`makhzan_schemas.rebuild`). Only when the mode is live: off, the regroup
    reads nothing. Records the highest decision id covered, so the next
    session end queues again only for newer ones.

    The marker is the decision id (an identity, allocated at the insert), not
    `created_at`, which is the writing transaction's start and can lag well
    behind a long lease's commit."""
    if queue is None or await ai_mode(session) != LIVE:
        return False
    state = await session.get(WorkerState, REBUILD_STATE_KEY)
    since = int((state.value or {}).get("through_id") or 0) if state is not None else 0
    wanted = (AiDecision.state == STANDING) & (AiDecision.outcome == SAME)
    if REBUILD_ON_UNMERGE:
        wanted = AiDecision.state == STANDING
    newest = await session.scalar(
        select(func.max(AiDecision.id)).where(wanted, AiDecision.id > since)
    )
    if newest is None:
        return False
    try:
        await queue()
    except Exception:  # noqa: BLE001 - the next session end will try again
        log.exception("could not queue the rebuild after an AI window")
        return False
    value = {"through_id": int(newest)}
    await session.execute(
        insert(WorkerState)
        .values(key=REBUILD_STATE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[WorkerState.key], set_={"value": value, "updated_at": func.now()}
        )
    )
    return True


# --- by hand ----------------------------------------------------------------------------------


async def retry_job(session: AsyncSession, job_id: int) -> AiJob | None:
    """Queue a dead (or cancelled) job again with its attempts reset, if no
    open job for the same pair, stage and judge exists."""
    job = await session.get(AiJob, job_id, with_for_update=True)
    if job is None or job.status not in (DEAD, CANCELLED):
        return None
    open_twin = await session.scalar(
        select(AiJob.id).where(
            AiJob.status.in_(OPEN),
            AiJob.pipeline == job.pipeline,
            AiJob.stage == job.stage,
            AiJob.model_version_id == job.model_version_id,
            AiJob.listing_a == job.listing_a,
            AiJob.listing_b == job.listing_b,
        )
    )
    if open_twin is not None:
        return None
    job.status, job.attempts, job.last_error = QUEUED, 0, None
    await session.execute(
        update(AiFlag)
        .where(
            AiFlag.kind == "poison_job",
            AiFlag.status == "open",
            AiFlag.job_id == job.id,
        )
        .values(status="actioned", resolved_at=func.now(), note="job retried")
    )
    await session.flush()
    return job


__all__ = [
    "BrokerError",
    "authenticate",
    "db_now",
    "heartbeat",
    "hello",
    "lease",
    "maybe_rebuild",
    "new_token",
    "reap",
    "release",
    "results",
    "retry_job",
    "token_sha256",
]
