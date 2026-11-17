"""The AI broker's endpoints, end to end against a real database (docs/ai/broker-api.md).

Workers are fakes that post made-up scores; production never runs a model. The
shops and listings are fictional.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import timedelta

import pytest
from makhzan_schemas import overrides as rulings
from makhzan_schemas.ai import broker as core
from makhzan_schemas.ai import flow
from makhzan_schemas.ai.mode import set_ai_mode
from makhzan_schemas.ai.pipelines import DECIDE, NOT_SAME, PIPELINES, SAME, Step
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.ai.render import load_shown, render
from makhzan_schemas.ai.triggers import PairRequest, enqueue
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import AiDecision, AiFlag, AiJob, AiScore, AiSession, AiWorker, Listing
from makhzan_schemas.overrides import pair
from sqlalchemy import func, select, text, update

from tests.factories import make_listing, make_supplier

KEV = MODELS["kev"]
PPLX = MODELS["pplx"]


async def _worker(name: str, models: list[str]) -> str:
    token = core.new_token()
    async with SessionLocal() as session:
        session.add(AiWorker(name=name, token_sha256=core.token_sha256(token), models=models))
        await session.commit()
    return token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _report(*keys: str, weights: str | None = None) -> dict:
    return {
        key: {
            "model_version": MODELS[key].model_version,
            "weights_revision": weights or MODELS[key].weights_revision,
        }
        for key in keys
    }


async def _hello(http, token: str, *keys: str, lease_s: int = 900) -> dict:
    r = await http.post(
        "/ai/v1/hello",
        json={
            "models": _report(*keys),
            "device": "cpu",
            "dtype": "fp32",
            "threads": 6,
            "config": {"lease_s": lease_s, "window": "00:30-04:30"},
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _lease(http, token: str, session: str, model: str, **extra) -> dict:
    r = await http.post(
        "/ai/v1/lease",
        json={
            "session": session,
            "model": model,
            "model_version": MODELS[model].model_version,
            "max_jobs": 4,
            **extra,
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()


def _scores(job: dict, *ps: float) -> list[dict]:
    return [
        {"order": req["order"], "request_sha256": req["request_sha256"], "p": p, "seconds": 80.0}
        for req, p in zip(job["requests"], ps, strict=True)
    ]


async def _post(http, token: str, session: str, lease: dict, job: dict, scores: list[dict]):
    return await http.post(
        "/ai/v1/results",
        json={
            "session": session,
            "lease_id": lease["lease_id"],
            "job_id": job["job_id"],
            "scores": scores,
            "device": "cpu",
            "dtype": "fp32",
            "threads": 6,
        },
        headers=_auth(token),
    )


async def _pair(db, title_a="Example HC-SR04 ultrasonic sensor", title_b="HC-SR04 sonar module"):
    shop_a = await make_supplier(db, name="Shop A")
    shop_b = await make_supplier(db, name="Shop B")
    a = await make_listing(db, supplier=shop_a, title_en=title_a)
    b = await make_listing(db, supplier=shop_b, title_en=title_b)
    return pair(a.id, b.id)


async def _queue(a, b, pipeline="match", priority=60, reason="candidates", stage=None):
    async with SessionLocal() as session:
        await enqueue(session, [PairRequest(a, b, pipeline, priority, reason)], stage=stage)
        await session.commit()


async def _jobs() -> list[AiJob]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(AiJob).order_by(AiJob.id)))


async def _decisions() -> list[AiDecision]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(AiDecision).order_by(AiDecision.id)))


# --- health and auth --------------------------------------------------------------------------


async def test_health_needs_no_token_and_says_nothing_about_queues(broker):
    r = await broker.get("/ai/v1/health")
    assert r.status_code == 200
    assert set(r.json()) == {"ok", "broker"}


async def test_a_missing_unknown_or_revoked_token_is_unauthorized(broker):
    body = {"models": _report("kev")}
    assert (await broker.post("/ai/v1/hello", json=body)).status_code == 401
    assert (
        await broker.post("/ai/v1/hello", json=body, headers=_auth("not-a-token"))
    ).status_code == 401
    token = await _worker("cpu-kev", ["kev"])
    async with SessionLocal() as session:
        await session.execute(update(AiWorker).values(revoked_at=func.now()))
        await session.commit()
    r = await broker.post("/ai/v1/hello", json=body, headers=_auth(token))
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


async def test_a_model_the_worker_does_not_serve_is_refused(broker):
    token = await _worker("cpu-kev", ["kev"])
    r = await broker.post("/ai/v1/hello", json={"models": _report("pplx")}, headers=_auth(token))
    assert r.status_code == 403
    assert r.json() == {"error": "model_not_allowed", "model": "pplx"}


async def test_status_takes_the_admin_token_never_a_worker_token(broker, monkeypatch):
    admin = "admin-secret-for-tests"
    monkeypatch.setenv("AI_BROKER_ADMIN_TOKEN_SHA256", hashlib.sha256(admin.encode()).hexdigest())
    worker = await _worker("cpu-kev", ["kev"])
    assert (await broker.get("/ai/v1/status", headers=_auth(worker))).status_code == 401
    r = await broker.get("/ai/v1/status", headers=_auth(admin))
    assert r.status_code == 200
    assert r.json()["mode"] == "off"


# --- the round trip ---------------------------------------------------------------------------


async def test_kev_then_pplx_then_a_same_decision(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    pplx = await _worker("cpu-pplx", ["pplx"])

    hello = await _hello(broker, kev, "kev")
    assert hello["models"]["kev"]["model_version"] == KEV.model_version
    assert (hello["models"]["kev"]["ok"], hello["models"]["kev"]["queued_requests"]) == (True, 2)
    assert {
        "pipeline": "match",
        "stage": "kev",
        "prompt_version": PIPELINES["match"].stage("kev").prompt_version,
    } in (hello["models"]["kev"]["stages"])
    lease = await _lease(broker, kev, hello["session"], "kev")
    [job] = lease["jobs"]
    assert [r["order"] for r in job["requests"]] == ["ab", "ba"]
    assert job["prompt_version"] == PIPELINES["match"].stage("kev").prompt_version
    # What was sent is exactly what the shared renderer makes from the rows.
    async with SessionLocal() as session:
        shown = await load_shown(session, (a, b))
    expected = render(PIPELINES["match"].stage("kev"), shown[a], shown[b])
    assert {r["order"]: r["request_sha256"] for r in job["requests"]} == expected.hex()
    assert job["requests"][0]["payload"] == expected.payloads["ab"]
    # "ab" shows the pair's listing_a (the smaller id) as LISTING A.
    title_a = shown[a].record["title"]
    assert f"[LISTING A]\nTitle: {title_a}\n" in job["requests"][0]["payload"]["state"]

    r = await _post(broker, kev, hello["session"], lease, job, _scores(job, 0.91, 0.87))
    assert r.json() == {
        "accepted": 2,
        "duplicate": 0,
        "job": "done",
        "next": {"action": "score", "stage": "pplx"},
    }

    hello2 = await _hello(broker, pplx, "pplx")
    assert hello2["models"]["pplx"]["queued_requests"] == 2
    lease2 = await _lease(broker, pplx, hello2["session"], "pplx")
    [job2] = lease2["jobs"]
    r = await _post(broker, pplx, hello2["session"], lease2, job2, _scores(job2, 0.97, 0.99))
    assert r.json()["next"] == {"action": "decide", "outcome": "same"}

    [decision] = await _decisions()
    assert (decision.outcome, decision.decided_by, decision.state) == (SAME, "pplx", "standing")
    assert decision.scores["kev"]["min"] == pytest.approx(0.87)
    assert decision.scores["pplx"]["ab"] == pytest.approx(0.97)
    assert decision.content_sha256_a == shown[a].content_sha256
    assert [j.status for j in await _jobs()] == ["done", "done"]


async def test_kev_below_its_threshold_decides_not_same_with_no_pplx_job(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    lease = await _lease(broker, kev, hello["session"], "kev")
    [job] = lease["jobs"]
    # One order high, the other low: the lower one counts (P11).
    r = await _post(broker, kev, hello["session"], lease, job, _scores(job, 0.95, 0.20))
    assert r.json()["next"] == {"action": "decide", "outcome": "not_same"}
    [decision] = await _decisions()
    assert (decision.outcome, decision.decided_by) == (NOT_SAME, "kev")
    assert len(await _jobs()) == 1


async def test_an_empty_queue_answers_no_lease(broker):
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    assert hello["models"]["kev"]["queued_requests"] == 0
    assert await _lease(broker, kev, hello["session"], "kev") == {
        "lease_id": None,
        "jobs": [],
        "reason": "empty",
    }


async def test_a_lease_fits_the_time_left(broker, db):
    for n in range(3):
        a, b = await _pair(db, f"Example part {n} sensor", f"Example part {n} module")
        await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    # Four requests of 100 s fit in 460 s less the 60 s margin; six do not.
    lease = await _lease(
        broker, kev, hello["session"], "kev", seconds_left=460, seconds_per_request=100
    )
    assert len(lease["jobs"]) == 2


# --- idempotency ------------------------------------------------------------------------------


async def test_results_are_idempotent_on_the_request_hash(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    lease = await _lease(broker, kev, hello["session"], "kev")
    [job] = lease["jobs"]
    ab, ba = _scores(job, 0.5, 0.6)

    first = await _post(broker, kev, hello["session"], lease, job, [ab])
    assert first.json() == {"accepted": 1, "duplicate": 0, "job": "leased", "next": None}
    again = await _post(broker, kev, hello["session"], lease, job, [ab])
    assert again.json() == {"accepted": 0, "duplicate": 1, "job": "leased", "next": None}
    done = await _post(broker, kev, hello["session"], lease, job, [ab, ba])
    assert done.json()["accepted"] == 1 and done.json()["job"] == "done"
    # A retried POST after the job is done is a duplicate and changes nothing.
    retry = await _post(broker, kev, hello["session"], lease, job, [ab, ba])
    assert retry.status_code == 200
    assert retry.json() == {"accepted": 0, "duplicate": 2, "job": "done", "next": None}
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(AiScore)) == 2
    assert len(await _decisions()) == 1


async def test_a_hash_the_broker_did_not_render_is_refused_and_nothing_stored(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    lease = await _lease(broker, kev, hello["session"], "kev")
    [job] = lease["jobs"]
    ab, ba = _scores(job, 0.5, 0.6)
    ba["request_sha256"] = "0" * 64
    r = await _post(broker, kev, hello["session"], lease, job, [ab, ba])
    assert r.status_code == 422
    assert r.json() == {"error": "request_mismatch"}
    bad_p = await _post(broker, kev, hello["session"], lease, job, [{**ab, "p": 1.5}])
    assert bad_p.status_code == 422
    assert bad_p.json()["error"] == "invalid"
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(AiScore)) == 0


async def test_a_job_whose_requests_are_all_scored_is_not_leased(broker, db):
    """Freshness by request hash: the second job for the same text goes
    straight to the transition with no model call."""
    a, b = await _pair(db)
    await _queue(a, b, pipeline="audit", reason="manual")
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    lease = await _lease(broker, kev, hello["session"], "kev", max_jobs=1)
    [job] = lease["jobs"]
    await _post(broker, kev, hello["session"], lease, job, _scores(job, 0.9, 0.9))
    # The audit and match Kev stages share a judge, so the other job is owed nothing.
    assert await _lease(broker, kev, hello["session"], "kev") == {
        "lease_id": None,
        "jobs": [],
        "reason": "empty",
    }
    statuses = {(j.pipeline, j.stage): j.status for j in await _jobs()}
    assert statuses == {
        ("audit", "kev"): "done",
        ("match", "kev"): "done",
        ("match", "pplx"): "queued",
    }


# --- who may post -----------------------------------------------------------------------------


async def test_only_the_leaseholder_may_post_or_release(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    one = await _worker("cpu-kev", ["kev"])
    two = await _worker("gpu-kev", ["kev"])
    h1, h2 = await _hello(broker, one, "kev"), await _hello(broker, two, "kev")
    lease = await _lease(broker, one, h1["session"], "kev")
    [job] = lease["jobs"]
    r = await _post(broker, two, h2["session"], lease, job, _scores(job, 0.9, 0.9))
    assert r.status_code == 409
    assert r.json() == {"error": "lease_lost", "job_ids": [job["job_id"]]}
    r = await broker.post(
        "/ai/v1/release",
        json={"session": h2["session"], "lease_id": lease["lease_id"], "job_ids": [job["job_id"]]},
        headers=_auth(two),
    )
    assert r.status_code == 409


async def test_a_worker_may_not_post_for_a_model_it_does_not_serve(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    pplx = await _worker("cpu-pplx", ["pplx"])
    hello = await _hello(broker, kev, "kev")
    lease = await _lease(broker, kev, hello["session"], "kev")
    [job] = lease["jobs"]
    h2 = await _hello(broker, pplx, "pplx")
    r = await _post(broker, pplx, h2["session"], lease, job, _scores(job, 0.9, 0.9))
    assert r.status_code == 403
    r = await broker.post(
        "/ai/v1/lease",
        json={"session": h2["session"], "model": "kev", "model_version": KEV.model_version},
        headers=_auth(pplx),
    )
    assert r.status_code == 403


async def test_a_model_version_other_than_the_registrys_gets_409_and_no_job(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    r = await broker.post(
        "/ai/v1/hello", json={"models": _report("kev", weights="f" * 40)}, headers=_auth(kev)
    )
    assert r.json()["models"]["kev"]["ok"] is False
    drifted = r.json()["session"]
    async with SessionLocal() as session:
        assert await session.scalar(select(AiFlag.kind)) == "version_drift"
    refused = await broker.post(
        "/ai/v1/lease",
        json={"session": drifted, "model": "kev", "model_version": KEV.model_version},
        headers=_auth(kev),
    )
    assert refused.status_code == 409
    assert refused.json() == {"error": "version", "model": "kev", "current": KEV.model_version}
    hello = await _hello(broker, kev, "kev")
    old = await broker.post(
        "/ai/v1/lease",
        json={"session": hello["session"], "model": "kev", "model_version": "kev-4b@old"},
        headers=_auth(kev),
    )
    assert old.status_code == 409
    assert [j.status for j in await _jobs()] == ["queued"]


# --- leases: expiry, heartbeat, release -------------------------------------------------------


async def _expire_all() -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(AiJob)
            .where(AiJob.status == "leased")
            .values(lease_expires_at=func.now() - timedelta(seconds=1))
        )
        await session.commit()


async def test_an_expired_lease_is_reaped_counted_and_poisoned_at_three(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    first = await _lease(broker, kev, hello["session"], "kev")
    for attempt in (1, 2):
        await _expire_all()
        again = await _lease(broker, kev, hello["session"], "kev")
        [job] = await _jobs()
        assert job.attempts == attempt and job.status == "leased"
        assert again["lease_id"] != first["lease_id"]
    # The first lease is gone: its results are refused, its heartbeat lost.
    [old_job] = first["jobs"]
    r = await _post(broker, kev, hello["session"], first, old_job, _scores(old_job, 0.9, 0.9))
    assert r.status_code == 409
    hb = await broker.post(
        "/ai/v1/heartbeat",
        json={"session": hello["session"], "lease_ids": [first["lease_id"]]},
        headers=_auth(kev),
    )
    assert hb.status_code == 409 and hb.json()["lease_ids"] == [first["lease_id"]]
    await _expire_all()
    assert (await _lease(broker, kev, hello["session"], "kev"))["jobs"] == []
    [job] = await _jobs()
    assert (job.status, job.attempts, job.lease_id) == ("dead", 3, None)
    async with SessionLocal() as session:
        flag = await session.scalar(select(AiFlag))
    assert (flag.kind, flag.job_id) == ("poison_job", job.id)


async def test_a_heartbeat_extends_only_the_callers_live_leases(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev", lease_s=600)
    lease = await _lease(broker, kev, hello["session"], "kev")
    [before] = await _jobs()
    r = await broker.post(
        "/ai/v1/heartbeat",
        json={"session": hello["session"], "lease_ids": [lease["lease_id"]], "rss_bytes": 1},
        headers=_auth(kev),
    )
    assert r.status_code == 200
    [after] = await _jobs()
    assert after.lease_expires_at >= before.lease_expires_at


async def test_release_graceful_counts_nothing_and_error_counts_an_attempt(broker, db):
    a, b = await _pair(db)
    await _queue(a, b)
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    lease = await _lease(broker, kev, hello["session"], "kev")
    [job] = lease["jobs"]
    ab, _ = _scores(job, 0.4, 0.4)
    await _post(broker, kev, hello["session"], lease, job, [ab])
    r = await broker.post(
        "/ai/v1/release",
        json={
            "session": hello["session"],
            "lease_id": lease["lease_id"],
            "job_ids": [job["job_id"]],
            "reason": "graceful",
        },
        headers=_auth(kev),
    )
    assert r.json() == {"released": 1}
    [row] = await _jobs()
    assert (row.status, row.attempts, row.lease_id) == ("queued", 0, None)
    # Half a job is kept: the next lease carries only the order still owed.
    lease = await _lease(broker, kev, hello["session"], "kev")
    assert [r["order"] for r in lease["jobs"][0]["requests"]] == ["ba"]
    r = await broker.post(
        "/ai/v1/release",
        json={
            "session": hello["session"],
            "lease_id": lease["lease_id"],
            "job_ids": [job["job_id"]],
            "reason": "error",
            "error": "out of memory",
        },
        headers=_auth(kev),
    )
    [row] = await _jobs()
    assert (row.status, row.attempts, row.last_error) == ("queued", 1, "out of memory")
    async with SessionLocal() as session:
        ended = await session.get(AiSession, uuid.UUID(hello["session"]))
    assert ended.end_reason in ("released", None)


# --- eligibility at lease time ----------------------------------------------------------------


async def test_a_ruled_or_archived_pair_is_cancelled_at_lease(broker, db):
    a, b = await _pair(db)
    c, d = await _pair(db, "Example relay board 5V", "Relay board 5V example")
    await _queue(a, b)
    await _queue(c, d)
    async with SessionLocal() as session:
        await rulings.add(session, a, b, rulings.NEVER, created_by="test", note="test")
        await session.execute(
            update(Listing).where(Listing.id == c).values(status=ListingStatus.ARCHIVED)
        )
        await session.commit()
    kev = await _worker("cpu-kev", ["kev"])
    hello = await _hello(broker, kev, "kev")
    assert (await _lease(broker, kev, hello["session"], "kev"))["jobs"] == []
    assert [(j.status, j.last_error) for j in await _jobs()] == [
        ("cancelled", "a person has ruled on the pair"),
        ("cancelled", "a listing is no longer active"),
    ]


# --- the rebuild after a window (P16) ---------------------------------------------------------


async def test_a_session_end_queues_a_rebuild_only_when_live_and_only_for_new_same(broker, db):
    a, b = await _pair(db)
    await _queue(a, b, stage="pplx")
    pplx = await _worker("cpu-pplx", ["pplx"])
    hello = await _hello(broker, pplx, "pplx")
    lease = await _lease(broker, pplx, hello["session"], "pplx")
    [job] = lease["jobs"]
    async with SessionLocal() as session:  # Kev's scores, as if scored earlier
        shown = await load_shown(session, (a, b))
        kev_stage = PIPELINES["match"].stage("kev")
        judge = (await flow.current_judges(session))[("match", "kev")]
        for order, digest in render(kev_stage, shown[a], shown[b]).sha256.items():
            session.add(
                AiScore(
                    model_version_id=judge,
                    listing_a=a,
                    listing_b=b,
                    reading_order=order,
                    request_sha256=digest,
                    content_sha256_a=shown[a].content_sha256,
                    content_sha256_b=shown[b].content_sha256,
                    p=0.9,
                )
            )
        await session.commit()
    r = await _post(broker, pplx, hello["session"], lease, job, _scores(job, 0.99, 0.98))
    assert r.json()["next"] == {"action": "decide", "outcome": "same"}

    await _lease(broker, pplx, hello["session"], "pplx")  # empty, but the mode is off
    assert broker.rebuilds == []
    async with SessionLocal() as session:
        await set_ai_mode(session, "live")
        await session.commit()
    await _lease(broker, pplx, hello["session"], "pplx")
    assert broker.rebuilds == ["rebuild"]
    await _lease(broker, pplx, hello["session"], "pplx")  # nothing newer since
    assert broker.rebuilds == ["rebuild"]


# --- the decision writer ----------------------------------------------------------------------


def _step(outcome: str, low: float) -> tuple[Step, flow.PairScores]:
    evidence = {"kev": {"model": "kev", "model_version_id": 1, "ab": low, "ba": low}}
    return (
        Step(DECIDE, outcome=outcome, decided_by="kev", mins=(("kev", low),)),
        flow.PairScores({"kev": {"ab": low, "ba": low}}, evidence),
    )


async def test_write_decision_keeps_the_row_when_the_outcome_is_unchanged(db):
    a, b = await _pair(db)
    async with SessionLocal() as session:
        await flow.current_judges(session)
        first = await flow.write_decision(session, "match", a, b, *_step(NOT_SAME, 0.3))
        await session.commit()
        again = await flow.write_decision(session, "match", a, b, *_step(NOT_SAME, 0.1))
        await session.commit()
    assert again.id == first.id
    [row] = await _decisions()
    assert row.scores["kev"]["min"] == pytest.approx(0.1)


async def test_concurrent_decisions_on_one_pair_serialise(db):
    """Two results for one pair at once (two workers): the advisory lock makes
    them take turns, so exactly one decision stands and the other is stale."""
    a, b = await _pair(db)
    async with SessionLocal() as session:
        await flow.current_judges(session)
        await session.commit()
    entered = asyncio.Event()

    async def write(outcome: str, low: float, hold: bool) -> None:
        async with SessionLocal() as session:
            await flow.write_decision(session, "match", a, b, *_step(outcome, low))
            if hold:
                async with SessionLocal() as other:
                    held = await other.scalar(
                        text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
                    )
                assert held == 1
                entered.set()
                await asyncio.sleep(0.3)  # holding the lock, uncommitted
            await session.commit()

    async def second() -> None:
        await entered.wait()
        await write(SAME, 0.9, hold=False)

    await asyncio.gather(write(NOT_SAME, 0.2, hold=True), second())
    rows = await _decisions()
    assert sorted((r.state, r.outcome) for r in rows) == [("stale", NOT_SAME), ("standing", SAME)]


async def test_a_job_at_another_stages_judge_is_moved_not_leased_forever(broker, db):
    """A judge id can be current for one stage and stale for another: such a
    job is moved to its own stage's judge, and the lease returns."""
    a, b = await _pair(db)
    async with SessionLocal() as session:
        judges = await flow.current_judges(session)
        session.add(
            AiJob(
                pipeline="match",
                stage="kev",
                reason="candidates",
                model_version_id=judges[("match", "pplx")],
                listing_a=a,
                listing_b=b,
                priority=60,
            )
        )
        await session.commit()
    pplx = await _worker("cpu-pplx", ["pplx"])
    hello = await _hello(broker, pplx, "pplx")
    lease = await asyncio.wait_for(_lease(broker, pplx, hello["session"], "pplx"), timeout=20)
    assert lease["jobs"] == []
    rows = [(j.stage, j.model_version_id, j.status, j.reason) for j in await _jobs()]
    assert rows == [
        ("kev", judges[("match", "pplx")], "cancelled", "candidates"),
        ("kev", judges[("match", "kev")], "queued", "candidates"),  # its reason kept
    ]
