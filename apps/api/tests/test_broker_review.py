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
from makhzan_schemas.models import AiDecision, AiFlag, AiJob, AiModelVersion, AiSession
from makhzan_schemas.overrides import pair
from sqlalchemy import func, select, update

from tests.factories import make_listing, make_supplier
from tests.test_broker import (
    _auth,
    _expire_all,
    _hello,
    _jobs,
    _lease,
    _report,
    _worker,
)


async def _grid(db, n: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """n x n cross-shop pairs."""
    shop_a, shop_b = await make_supplier(db, name="Shop A"), await make_supplier(db, name="Shop B")
    xs = [await make_listing(db, supplier=shop_a, title_en=f"Widget alpha {i}") for i in range(n)]
    ys = [await make_listing(db, supplier=shop_b, title_en=f"Widget beta {i}") for i in range(n)]
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
