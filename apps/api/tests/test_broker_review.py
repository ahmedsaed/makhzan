"""The broker after its review: leases under a judge sweep, blame on crash,
bounded lease lengths, retried leases, ending a session, per-worker drift
flags, and partial-index upserts past asyncpg's generic-plan switch.

The shops and listings are fictional; no model runs.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from makhzan_schemas.ai import broker as core
from makhzan_schemas.ai import flow
from makhzan_schemas.ai.mode import set_ai_mode
from makhzan_schemas.ai.triggers import PairRequest, enqueue
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import (
    AiDecision,
    AiFlag,
    AiJob,
    AiModelVersion,
    AiScore,
    AiSession,
    AiWorker,
)
from makhzan_schemas.overrides import pair
from sqlalchemy import func, select, update

from tests.factories import make_listing, make_supplier
from tests.test_broker import (
    MODELS,
    _auth,
    _expire_all,
    _hello,
    _jobs,
    _lease,
    _post,
    _report,
    _scores,
    _worker,
)


async def _grid(db, n: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """n x n cross-shop pairs, every title distinct across calls: identical
    text renders identical requests, and one pair's scores would settle the
    other's (freshness by request hash)."""
    tag = uuid.uuid4().hex[:6]
    shop_a, shop_b = await make_supplier(db, name="Shop A"), await make_supplier(db, name="Shop B")
    xs = [
        await make_listing(db, supplier=shop_a, title_en=f"Widget alpha {tag} {i}")
        for i in range(n)
    ]
    ys = [
        await make_listing(db, supplier=shop_b, title_en=f"Widget beta {tag} {i}") for i in range(n)
    ]
    return [pair(x.id, y.id) for x in xs for y in ys]


async def _queue_many(pairs, priority=60) -> None:
    async with SessionLocal() as session:
        await enqueue(
            session, [PairRequest(a, b, "match", priority, "candidates") for a, b in pairs]
        )
        await session.commit()


async def _old_judge(session) -> int:
    judges = await flow.current_judges(session)
    current = await session.get(AiModelVersion, judges[("match", "kev")])
    old = AiModelVersion(
        model=current.model,
        model_version=current.model_version,
        prompt_version="OLD@0",
        weights_revision=current.weights_revision,
        scoring={},
    )
    session.add(old)
    await session.flush()
    return old.id


async def test_leases_during_a_judge_sweep_find_work_and_never_share_it(broker, db):
    """The sweep holds the stale jobs' rows, not the current ones, and a lease
    locks only the rows it takes: two leases mid-sweep both get jobs."""
    pairs = await _grid(db, 12)  # 144 pairs
    await _queue_many(pairs[:10])
    async with SessionLocal() as session:
        old = await _old_judge(session)
        session.add_all(
            AiJob(
                pipeline="match",
                stage="kev",
                reason="candidates",
                model_version_id=old,
                listing_a=a,
                listing_b=b,
                priority=60,
            )
            for a, b in pairs[10:]
        )
        await session.commit()
    one, two = await _worker("w1", ["kev"]), await _worker("w2", ["kev"])
    h1, h2 = await _hello(broker, one, "kev"), await _hello(broker, two, "kev")
    # Stale jobs again (the hellos swept the first lot), and a sweep left open.
    async with SessionLocal() as session:
        await session.execute(
            update(AiJob)
            .where(AiJob.status == "queued", AiJob.id > 10)
            .values(model_version_id=old)
        )
        await session.commit()
    async with SessionLocal() as sweeping:
        moved = await core.sweep_judges(sweeping)
        assert moved == len(pairs) - 10
        a, b = await asyncio.gather(
            _lease(broker, one, h1["session"], "kev", max_jobs=4),
            _lease(broker, two, h2["session"], "kev", max_jobs=4),
        )
        await sweeping.commit()
    ids_a = {j["job_id"] for j in a["jobs"]}
    ids_b = {j["job_id"] for j in b["jobs"]}
    assert len(ids_a) == 4 and len(ids_b) == 4
    assert not ids_a & ids_b
    async with SessionLocal() as session:
        ended = list(await session.scalars(select(AiSession.end_reason)))
    assert "empty" not in ended


async def test_a_crash_is_charged_to_the_job_in_hand_only(broker, db):
    await _queue_many(await _grid(db, 1) + await _grid(db, 1))
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    lease = await _lease(broker, kev, hello["session"], "kev", max_jobs=2)
    first, second = (j["job_id"] for j in lease["jobs"])
    r = await broker.post(
        "/ai/v1/heartbeat",
        json={
            "session": hello["session"],
            "lease_ids": [lease["lease_id"]],
            "progress": {"job_id": second, "order": "ab"},
        },
        headers=_auth(kev),
    )
    assert r.status_code == 200
    await _expire_all()
    async with SessionLocal() as session:
        await core.reap(session)
        await session.commit()
    jobs = {j.id: j for j in await _jobs()}
    assert (jobs[second].attempts, jobs[second].status) == (1, "queued")
    assert (jobs[first].attempts, jobs[first].status) == (0, "queued")
    assert "re-queued free" in jobs[first].last_error


async def test_with_nothing_reported_in_hand_every_job_is_charged(broker, db):
    await _queue_many(await _grid(db, 1) + await _grid(db, 1))
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    await _lease(broker, kev, hello["session"], "kev", max_jobs=2)
    await _expire_all()
    async with SessionLocal() as session:
        await core.reap(session)
        await session.commit()
    assert sorted(j.attempts for j in await _jobs()) == [1, 1]


@pytest.mark.parametrize("lease_s", [10**12, -5, 30, 7201, "abc", "900", True, 1.5])
async def test_a_lease_length_outside_the_bounds_or_not_an_integer_is_refused(broker, lease_s):
    kev = await _worker("cpu-kev", ["kev"])
    r = await broker.post(
        "/ai/v1/hello",
        json={"models": _report("kev"), "config": {"lease_s": lease_s}},
        headers=_auth(kev),
    )
    assert r.status_code == 422
    assert r.json()["error"] == "invalid"


async def test_a_lease_length_within_the_bounds_is_kept(broker):
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev", lease_s=120)
    assert (hello["lease_s"], hello["heartbeat_s"]) == (120, 40)


async def test_a_retried_lease_gets_the_same_jobs_back(broker, db):
    await _queue_many(await _grid(db, 2))
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    first = await _lease(broker, kev, hello["session"], "kev", max_jobs=2, lease_request_id="r1")
    again = await _lease(broker, kev, hello["session"], "kev", max_jobs=2, lease_request_id="r1")
    assert again["lease_id"] == first["lease_id"]
    assert [j["job_id"] for j in again["jobs"]] == [j["job_id"] for j in first["jobs"]]
    assert again["jobs"][0]["requests"] == first["jobs"][0]["requests"]
    other = await _lease(broker, kev, hello["session"], "kev", max_jobs=2, lease_request_id="r2")
    assert {j["job_id"] for j in other["jobs"]}.isdisjoint(j["job_id"] for j in first["jobs"])
    assert sum(j.status == "leased" for j in await _jobs()) == 4


async def test_an_empty_release_ends_the_session_and_can_queue_the_rebuild(broker, db):
    a, b = (await _grid(db, 1))[0]
    async with SessionLocal() as session:
        session.add(
            AiDecision(
                pipeline="match",
                listing_a=a,
                listing_b=b,
                outcome="same",
                decided_by="pplx",
                scores={},
                policy_version="p1",
                content_sha256_a=b"\0" * 32,
                content_sha256_b=b"\0" * 32,
            )
        )
        await set_ai_mode(session, "live")
        await session.commit()
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    r = await broker.post("/ai/v1/release", json={"session": hello["session"]}, headers=_auth(kev))
    assert r.json() == {"released": 0}
    assert broker.rebuilds == ["rebuild"]
    async with SessionLocal() as session:
        row = await session.get(AiSession, uuid.UUID(hello["session"]))
    assert row.end_reason == "released"
    refused = await broker.post(
        "/ai/v1/release",
        json={"session": hello["session"], "reason": "error"},
        headers=_auth(kev),
    )
    assert refused.status_code == 422


async def test_version_drift_is_one_flag_per_worker_and_model(broker):
    for name in ("w1", "w2"):
        token = await _worker(name, ["kev"])
        for _ in range(2):
            r = await broker.post(
                "/ai/v1/hello",
                json={"models": _report("kev", weights="f" * 40)},
                headers=_auth(token),
            )
            assert r.status_code == 200
    async with SessionLocal() as session:
        subjects = sorted(await session.scalars(select(AiFlag.subject)))
    assert subjects == ["w1/kev", "w2/kev"]


async def test_partial_index_upserts_survive_asyncpgs_generic_plan(db):
    """`ON CONFLICT ... WHERE` on a partial index fails once asyncpg's
    prepared statement goes generic (the sixth run on a connection) unless the
    predicate is literal SQL. Ten runs on one session, both upserts."""
    pairs = await _grid(db, 4)
    async with SessionLocal() as session:
        for a, b in pairs[:10]:
            await enqueue(session, [PairRequest(a, b, "match", 60, "candidates")])
            await enqueue(session, [PairRequest(a, b, "match", 60, "candidates")])  # conflict
            await core._open_flag(session, "poison_job", listing_a=a, listing_b=b)
            await core._open_flag(session, "poison_job", listing_a=a, listing_b=b)  # conflict
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(AiJob)) == 10
        assert await session.scalar(select(func.count()).select_from(AiFlag)) == 10


# --- second review -------------------------------------------------------------------------


async def _session_body(token: str, broker, **extra) -> tuple[AiWorker, dict]:
    hello = await _hello(broker, token, "kev")
    async with SessionLocal() as session:
        worker = await session.scalar(
            select(AiWorker).where(AiWorker.token_sha256 == core.token_sha256(token))
        )
    body = {
        "session": hello["session"],
        "model": "kev",
        "model_version": MODELS["kev"].model_version,
        "max_jobs": 2,
        **extra,
    }
    return worker, body


async def test_a_retry_that_overlaps_the_original_waits_and_replays_it(broker, db):
    """The repro: the retry arrives while the original lease is still
    uncommitted. The session row lock makes it wait, then replay: one lease,
    and nothing charged when the original's jobs are the ones the worker has."""
    await _queue_many(await _grid(db, 2))
    token = await _worker("cpu-kev", ["kev"])
    worker, body = await _session_body(token, broker, lease_request_id="r1")
    s1, s2 = SessionLocal(), SessionLocal()
    try:
        w1, w2 = await s1.get(AiWorker, worker.id), await s2.get(AiWorker, worker.id)
        original = await core.lease(s1, w1, body, await core.db_now(s1))  # not committed
        retry = asyncio.create_task(core.lease(s2, w2, body, await core.db_now(s2)))
        await asyncio.sleep(0.5)
        assert not retry.done()  # waiting on the session row
        await s1.commit()
        replayed = await retry
        await s2.commit()
    finally:
        await s1.close()
        await s2.close()
    assert replayed["lease_id"] == original["lease_id"]
    assert [j["job_id"] for j in replayed["jobs"]] == [j["job_id"] for j in original["jobs"]]
    jobs = await _jobs()
    assert sum(j.status == "leased" for j in jobs) == 2
    assert len({j.lease_id for j in jobs if j.lease_id}) == 1


async def test_a_lease_request_id_reused_for_another_model_is_refused(broker, db):
    await _queue_many(await _grid(db, 1))
    x, y = (await _grid(db, 1))[0]
    async with SessionLocal() as session:
        await enqueue(session, [PairRequest(x, y, "match", 60, "x")], stage="pplx")
        await session.commit()
    token = await _worker("both", ["kev", "pplx"])
    hello = await _hello(broker, token, "kev", "pplx")
    await _lease(broker, token, hello["session"], "kev", lease_request_id="r1")
    r = await broker.post(
        "/ai/v1/lease",
        json={
            "session": hello["session"],
            "model": "pplx",
            "model_version": MODELS["pplx"].model_version,
            "lease_request_id": "r1",
        },
        headers=_auth(token),
    )
    assert r.status_code == 422


async def _store_scores(job: dict, orders=("ab", "ba"), p: float = 0.1) -> None:
    """Scores for a leased job's requests, as if another worker posted them."""
    async with SessionLocal() as session:
        row = await session.get(AiJob, job["job_id"])
        for request in job["requests"]:
            if request["order"] in orders:
                session.add(
                    AiScore(
                        model_version_id=row.model_version_id,
                        listing_a=row.listing_a,
                        listing_b=row.listing_b,
                        reading_order=request["order"],
                        request_sha256=bytes.fromhex(request["request_sha256"]),
                        content_sha256_a=row.content_sha256_a or b"\0" * 32,
                        content_sha256_b=row.content_sha256_b or b"\0" * 32,
                        p=p,
                    )
                )
        await session.commit()


async def test_a_replayed_job_scored_meanwhile_is_finished_not_renewed(broker, db):
    await _queue_many(await _grid(db, 1) + await _grid(db, 1))
    token = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, token, "kev")
    first = await _lease(broker, token, hello["session"], "kev", max_jobs=2, lease_request_id="r1")
    scored, kept = first["jobs"]
    await _store_scores(scored)
    again = await _lease(broker, token, hello["session"], "kev", max_jobs=2, lease_request_id="r1")
    assert [j["job_id"] for j in again["jobs"]] == [kept["job_id"]]
    jobs = {j.id: j for j in await _jobs()}
    assert (jobs[scored["job_id"]].status, jobs[scored["job_id"]].lease_id) == ("done", None)


@pytest.mark.parametrize("ending", ["release", "results", "reap"])
async def test_a_replay_of_a_lease_no_longer_held_is_a_fresh_lease(broker, db, ending):
    await _queue_many(await _grid(db, 1) + await _grid(db, 1))
    token = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, token, "kev")
    first = await _lease(broker, token, hello["session"], "kev", max_jobs=1, lease_request_id="r1")
    [job] = first["jobs"]
    if ending == "release":
        await broker.post(
            "/ai/v1/release",
            json={
                "session": hello["session"],
                "lease_id": first["lease_id"],
                "job_ids": [job["job_id"]],
            },
            headers=_auth(token),
        )
    elif ending == "results":
        await _post(broker, token, hello["session"], first, job, _scores(job, 0.1, 0.1))
    else:
        await _expire_all()
    again = await _lease(broker, token, hello["session"], "kev", max_jobs=1, lease_request_id="r1")
    assert again["lease_id"] != first["lease_id"]
    assert len(again["jobs"]) == 1
    leased = [j for j in await _jobs() if j.status == "leased"]
    assert [str(j.lease_id) for j in leased] == [again["lease_id"]]
    if ending == "results":
        assert again["jobs"][0]["job_id"] != job["job_id"]


async def test_a_lease_stops_at_the_first_job_that_does_not_fit(broker, db):
    """A head job owing two requests, behind it one owing one: with time for
    one request, nothing is leased (the broker never skips ahead), and the
    answer says none fit rather than empty."""
    head, small = await _grid(db, 1), await _grid(db, 1)
    await _queue_many(small, priority=60)
    token = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, token, "kev")
    # Make `small` owe one request only: lease it, score "ab", release it.
    first = await _lease(broker, token, hello["session"], "kev", max_jobs=1)
    await _store_scores(first["jobs"][0], orders=("ab",))
    await broker.post(
        "/ai/v1/release",
        json={
            "session": hello["session"],
            "lease_id": first["lease_id"],
            "job_ids": [first["jobs"][0]["job_id"]],
        },
        headers=_auth(token),
    )
    await _queue_many(head, priority=70)
    tight = await _lease(
        broker,
        token,
        hello["session"],
        "kev",
        max_jobs=2,
        seconds_left=60 + 150,
        seconds_per_request=100,
    )
    assert tight == {"lease_id": None, "jobs": [], "reason": "none_fit"}
    roomy = await _lease(
        broker,
        token,
        hello["session"],
        "kev",
        max_jobs=2,
        seconds_left=60 + 250,
        seconds_per_request=100,
    )
    assert [len(j["requests"]) for j in roomy["jobs"]] == [2]  # the head job, alone


async def test_nothing_fitting_is_not_empty_queues_no_rebuild_and_is_flagged(broker, db):
    a, b = (await _grid(db, 1))[0]
    await _queue_many([(a, b)])
    async with SessionLocal() as session:
        session.add(
            AiDecision(
                pipeline="match",
                listing_a=a,
                listing_b=b,
                outcome="same",
                decided_by="pplx",
                scores={},
                policy_version="p1",
                content_sha256_a=b"\0" * 32,
                content_sha256_b=b"\0" * 32,
            )
        )
        await set_ai_mode(session, "live")
        await session.commit()
    token = await _worker("cpu-kev", ["kev"])
    for night in range(core.NONE_FIT_FLAG_AFTER):
        hello = await _hello(broker, token, "kev")
        answer = await _lease(
            broker, token, hello["session"], "kev", seconds_left=100, seconds_per_request=100
        )
        assert answer["reason"] == "none_fit"
        async with SessionLocal() as session:
            row = await session.get(AiSession, uuid.UUID(hello["session"]))
            flags = list(await session.scalars(select(AiFlag)))
        assert row.end_reason == "none_fit"
        assert bool(flags) == (night == core.NONE_FIT_FLAG_AFTER - 1)
    assert broker.rebuilds == []
    assert (flags[0].kind, flags[0].subject) == ("nothing_fits", "cpu-kev/kev")


async def test_a_heartbeat_progress_job_id_must_be_an_integer(broker):
    token = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, token, "kev")
    r = await broker.post(
        "/ai/v1/heartbeat",
        json={"session": hello["session"], "lease_ids": [], "progress": {"job_id": "12"}},
        headers=_auth(token),
    )
    assert r.status_code == 422


# --- final review: healthy nights, per model, after a dismissal ------------------------------


async def _never_fits(broker, token: str, model: str) -> dict:
    """A session that leases nothing: its first job does not fit."""
    hello = await _hello(broker, token, model)
    return await _lease(
        broker, token, hello["session"], model, seconds_left=100, seconds_per_request=100
    )


async def _flag_rows() -> list[AiFlag]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(AiFlag).order_by(AiFlag.id)))


async def test_a_healthy_night_ending_in_none_fit_is_not_flagged_and_considers_p16(broker, db):
    """Each night the worker scores a job, then its window runs low with a
    backlog left: the normal end of a backlog night. No flag, and the night's
    "same" decisions get their rebuild."""
    await _queue_many(await _grid(db, 3))
    a, b = (await _grid(db, 1))[0]
    async with SessionLocal() as session:
        await set_ai_mode(session, "live")
        await session.commit()
    token = await _worker("cpu-kev", ["kev"])
    for night in range(core.NONE_FIT_FLAG_AFTER + 1):
        hello = await _hello(broker, token, "kev")
        lease = await _lease(broker, token, hello["session"], "kev", max_jobs=1)
        [job] = lease["jobs"]
        await _post(broker, token, hello["session"], lease, job, _scores(job, 0.1, 0.1))
        if night == 0:  # a "same" decided that night
            async with SessionLocal() as session:
                session.add(
                    AiDecision(
                        pipeline="match",
                        listing_a=a,
                        listing_b=b,
                        outcome="same",
                        decided_by="pplx",
                        scores={},
                        policy_version="p1",
                        content_sha256_a=b"\0" * 32,
                        content_sha256_b=b"\0" * 32,
                    )
                )
                await session.commit()
        end = await _lease(
            broker, token, hello["session"], "kev", seconds_left=100, seconds_per_request=100
        )
        assert end["reason"] == "none_fit"
        if night == 0:
            assert broker.rebuilds == ["rebuild"]
    assert await _flag_rows() == []


async def test_never_fit_sessions_are_counted_per_worker_and_model(broker, db):
    await _queue_many(await _grid(db, 1))
    x, y = (await _grid(db, 1))[0]
    async with SessionLocal() as session:
        await enqueue(session, [PairRequest(x, y, "match", 60, "x")], stage="pplx")
        await session.commit()
    token = await _worker("both", ["kev", "pplx"])
    for model in ("kev", "kev", "pplx"):
        assert (await _never_fits(broker, token, model))["reason"] == "none_fit"
    assert await _flag_rows() == []
    await _never_fits(broker, token, "kev")
    [flag] = await _flag_rows()
    assert (flag.subject, flag.detail["sessions_counted"]) == ("both/kev", 3)


async def test_a_dismissed_nothing_fits_flag_does_not_reopen_from_old_sessions(broker, db):
    await _queue_many(await _grid(db, 1))
    token = await _worker("cpu-kev", ["kev"])
    for _ in range(core.NONE_FIT_FLAG_AFTER):
        await _never_fits(broker, token, "kev")
    [flag] = await _flag_rows()
    async with SessionLocal() as session:
        await session.execute(
            update(AiFlag)
            .where(AiFlag.id == flag.id)
            .values(status="dismissed", resolved_at=func.now())
        )
        await session.commit()
    await _never_fits(broker, token, "kev")
    assert [f.status for f in await _flag_rows()] == ["dismissed"]
    for _ in range(core.NONE_FIT_FLAG_AFTER - 1):
        await _never_fits(broker, token, "kev")
    assert [f.status for f in await _flag_rows()] == ["dismissed", "open"]
