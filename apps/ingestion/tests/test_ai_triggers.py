"""The AI producers on a synthetic catalogue: candidates, backlog, audit, re-score.

The shops and listings are fictional. No model runs: scores are inserted as a
worker would have posted them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from makhzan_schemas import overrides as rulings
from makhzan_schemas.ai import broker as core
from makhzan_schemas.ai import candidates as producers
from makhzan_schemas.ai import flow, triggers
from makhzan_schemas.ai.pipelines import PIPELINES, SAME
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.ai.render import load_shown, render
from makhzan_schemas.ai.triggers import PairRequest, enqueue
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import (
    AiDecision,
    AiJob,
    AiListingState,
    AiModelVersion,
    AiScore,
    AiWorker,
    Listing,
    Product,
    Supplier,
)
from makhzan_schemas.overrides import pair
from sqlalchemy import func, select, text, update


async def _shop(slug: str) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    async with SessionLocal() as session:
        session.add(supplier)
        await session.commit()
    return supplier


async def _listing(shop, title, *, price=10, product=None, via=None, part_number=None):
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=shop.id,
        source=shop.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        domain="electronics",
        title_en=title,
        part_number=part_number,
        price=Decimal(str(price)),
        images=[],
        attributes={},
        product_id=product,
        matched_via=via,
    )
    async with SessionLocal() as session:
        session.add(listing)
        await session.commit()
    return listing.id


async def _product() -> uuid.UUID:
    product = Product(id=uuid.uuid4(), group_key=f"test:{uuid.uuid4()}")
    async with SessionLocal() as session:
        session.add(product)
        await session.commit()
    return product.id


async def _daily() -> list[dict]:
    async with SessionLocal() as session:
        out = await producers.daily(session)
        await session.commit()
    return out


async def _jobs(**where) -> list[AiJob]:
    async with SessionLocal() as session:
        query = select(AiJob).order_by(AiJob.id)
        for column, value in where.items():
            query = query.where(getattr(AiJob, column) == value)
        return list(await session.scalars(query))


def _pairs(jobs) -> set[tuple]:
    return {(j.listing_a, j.listing_b) for j in jobs}


async def _score_all(a, b, *, h2o=0.9, pplx=0.97) -> None:
    """Both stages' scores for the pair's current requests, as workers would
    post; a request already scored keeps its score (idempotent, as /results)."""
    from sqlalchemy.dialects.postgresql import insert

    a, b = pair(a, b)
    async with SessionLocal() as session:
        shown = await load_shown(session, (a, b))
        judges = await flow.current_judges(session)
        for name, p in (("h2o", h2o), ("pplx", pplx)):
            stage = PIPELINES["match"].stage(name)
            for order, digest in render(stage, shown[a], shown[b]).sha256.items():
                await session.execute(
                    insert(AiScore)
                    .values(
                        model_version_id=judges[("match", name)],
                        listing_a=a,
                        listing_b=b,
                        reading_order=order,
                        request_sha256=digest,
                        content_sha256_a=shown[a].content_sha256,
                        content_sha256_b=shown[b].content_sha256,
                        p=p,
                    )
                    .on_conflict_do_nothing(constraint="uq_ai_score_request")
                )
        await session.commit()


async def _decide(a, b) -> AiDecision:
    """Settle the pair from its stored scores, as the broker would."""
    async with SessionLocal() as session:
        await flow.advance(session, [PairRequest(a, b, "match", 60, "candidates")])
        await session.commit()
        a, b = pair(a, b)
        return await session.scalar(
            select(AiDecision).where(
                AiDecision.listing_a == a, AiDecision.listing_b == b, AiDecision.state == "standing"
            )
        )


# --- candidates -------------------------------------------------------------------------------


async def test_the_first_run_records_a_baseline_and_offers_nothing():
    a, b = await _shop("shop-a"), await _shop("shop-b")
    await _listing(a, "carbon film resistor 10k ohm")
    await _listing(b, "carbon film resistor 10k ohm quarter watt")
    _, candidates, *_ = await _daily()
    assert candidates["baseline"] == 2
    assert await _jobs() == []
    async with SessionLocal() as session:
        states = list(await session.scalars(select(AiListingState)))
    assert len(states) == 2
    assert all(s.candidates_sha256 == s.content_sha256 for s in states)


async def test_new_listings_get_their_top_k_filtered_by_todays_vetoes():
    a, b, c = await _shop("shop-a"), await _shop("shop-b"), await _shop("shop-c")
    await _listing(a, "seed listing for the baseline")
    await _daily()

    a1 = await _listing(a, "carbon film resistor 10k ohm", price=1)
    a2 = await _listing(a, "carbon film resistor 10k ohm axial", price=1)
    b1 = await _listing(b, "carbon film resistor 10k ohm quarter watt", price=1)
    await _listing(b, "carbon film resistor 22k ohm", price=1)  # values: 22k is not 10k
    await _listing(c, "carbon film resistor 10k ohm", price=50)  # price: 50x apart
    product = await _product()  # merged by the rules already
    await _listing(a, "ne555 precision timer dip8", product=product, part_number="NE555")
    await _listing(b, "ne555 precision timer dip8", product=product, part_number="NE555")
    a4 = await _listing(a, "ultrasonic ranger hcsr04 example")  # a person ruled never
    c4 = await _listing(c, "ultrasonic ranger hcsr04 example")
    async with SessionLocal() as session:
        await rulings.add(session, a4, c4, rulings.NEVER, created_by="test", note="test")
        await session.commit()

    _, candidates, *_ = await _daily()
    jobs = await _jobs(pipeline="match")
    assert _pairs(jobs) == {pair(a1, b1), pair(a2, b1)}
    assert {(j.stage, j.priority, j.reason) for j in jobs} == {("h2o", 60, "candidates")}
    assert candidates["veto_values"] >= 1
    assert candidates["veto_price"] >= 1
    assert candidates["rules_merged"] == 1
    assert candidates["override"] == 1
    assert candidates["veto_same_shop"] == 0  # one shop's listings are never candidates

    # Nothing changed since: nothing is due, nothing more is queued.
    _, again, *_ = await _daily()
    assert again["queries"] == 0
    assert len(await _jobs(pipeline="match")) == 2


async def test_top_k_is_bounded_and_never_reaches_into_the_same_shop():
    a, b = await _shop("shop-a"), await _shop("shop-b")
    await _listing(a, "seed listing for the baseline")
    await _daily()
    query = await _listing(a, "example widget alpha")
    for n in range(15):
        await _listing(b, f"example widget alpha variant{n}")
    for n in range(3):
        await _listing(a, f"example widget alpha sibling{n}")
    async with SessionLocal() as session:
        catalogue = await producers.load_catalogue(session)
    i = catalogue.index[query]
    top = catalogue.top_k(i)
    assert len(top) == producers.K
    assert all(catalogue.listings[j].supplier_id == b.id for j, _ in top)


async def test_the_backlog_offers_the_whole_catalogue_at_its_priority():
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _daily()  # baseline: nothing offered
    async with SessionLocal() as session:
        result = await producers.backlog(session)
        await session.commit()
    assert result["queued"] == 1
    [job] = await _jobs()
    assert (job.listing_a, job.listing_b) == pair(x, y)
    assert (job.priority, job.reason) == (40, "backlog")


async def test_a_pair_already_scored_is_settled_without_a_job():
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _score_all(x, y)
    async with SessionLocal() as session:
        result = await producers.backlog(session)
        await session.commit()
    assert (result["queued"], result["decided"]) == (0, 1)
    assert await _jobs() == []


# --- re-score ---------------------------------------------------------------------------------


async def test_a_changed_text_requeues_a_standing_same_first():
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _daily()
    await _score_all(x, y)
    decision = await _decide(x, y)
    assert decision.outcome == SAME
    assert await _daily()  # nothing due yet
    assert await _jobs() == []

    async with SessionLocal() as session:
        await session.execute(
            update(Listing).where(Listing.id == y).values(title_en="carbon resistor 10k ohm 1/4w")
        )
        await session.commit()
    _, _, rescore, _ = await _daily()
    assert rescore["text"] == 1
    [job] = await _jobs()
    assert (job.pipeline, job.stage, job.priority, job.reason) == ("match", "h2o", 100, "rescore")
    # The old decision stays in force until the new one is written (P6).
    async with SessionLocal() as session:
        standing = await session.get(AiDecision, decision.id)
    assert standing.state == "standing"


async def test_a_change_no_judge_can_see_rewrites_the_decision_in_place():
    """The Arabic title under an English one moves the content hash but not
    the requests: the decision is re-labelled, same id, and nothing is queued."""
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _daily()
    await _score_all(x, y)
    decision = await _decide(x, y)
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == y).values(title_ar="مقاومة"))
        await session.commit()
    _, _, rescore, _ = await _daily()
    assert rescore["text"] == 1 and rescore["decided"] == 1 and rescore["queued"] == 0
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(AiDecision)))
        shown = await load_shown(session, (y,))
    assert [r.id for r in rows] == [decision.id]
    side = "content_sha256_b" if pair(x, y)[1] == y else "content_sha256_a"
    assert getattr(rows[0], side) == shown[y].content_sha256
    assert await _jobs() == []
    _, _, again, _ = await _daily()
    assert again.get("text", 0) == 0  # settled: not offered again


async def test_a_version_bump_rescores_after_new_pairs_same_before_not_same():
    a, b = await _shop("shop-a"), await _shop("shop-b")
    s1 = await _listing(a, "carbon film resistor 10k ohm")
    s2 = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    n1 = await _listing(a, "ceramic capacitor 100nf 50v")
    n2 = await _listing(b, "ceramic capacitor 100nf 50v disc")
    await _daily()
    await _score_all(s1, s2)
    await _score_all(n1, n2, h2o=0.3)
    assert (await _decide(s1, s2)).outcome == SAME
    assert (await _decide(n1, n2)).outcome == "not_same"
    # A new H2O version: the stored decisions now name an old judge.
    async with SessionLocal() as session:
        old = AiModelVersion(
            model="h2o",
            model_version="h2o-4b@older",
            prompt_version="K2-150@older",
            weights_revision="0" * 40,
            scoring={},
        )
        session.add(old)
        await session.flush()
        for d in await session.scalars(select(AiDecision)):
            d.scores = {**d.scores, "h2o": {**d.scores["h2o"], "model_version_id": old.id}}
        await session.commit()
    async with SessionLocal() as session:
        result = await producers.run(session, producers.RescoreTrigger())
        await session.commit()
    assert result["version"] == 2
    jobs = {(j.listing_a, j.listing_b): j.priority for j in await _jobs()}
    # The scores are byte-identical, so no job is needed at all: both settle.
    assert jobs == {} and result["decided"] == 2

    # With the requests changed too (a new prompt would do it), jobs are owed: below new
    # pairs and the backlog (owner, 2026-11-26), the standing "same" before the "not same".
    assert triggers.CANDIDATE > triggers.BACKLOG > triggers.RESCORE_SAME_VERSION
    assert triggers.RESCORE_SAME_VERSION > triggers.RESCORE_VERSION
    async with SessionLocal() as session:
        await session.execute(
            update(AiScore).values(request_sha256=func.sha256(AiScore.request_sha256))
        )
        old_id = await session.scalar(
            select(AiModelVersion.id).where(AiModelVersion.model_version == "h2o-4b@older")
        )
        for d in await session.scalars(select(AiDecision)):
            d.scores = {**d.scores, "h2o": {**d.scores["h2o"], "model_version_id": old_id}}
        await session.commit()
    async with SessionLocal() as session:
        await producers.run(session, producers.RescoreTrigger())
        await session.commit()
    jobs = {(j.listing_a, j.listing_b): j.priority for j in await _jobs()}
    assert jobs == {pair(s1, s2): 35, pair(n1, n2): 30}

    token = core.new_token()
    async with SessionLocal() as session:
        worker = AiWorker(name="cpu-h2o", token_sha256=core.token_sha256(token), models=["h2o"])
        session.add(worker)
        await session.flush()
        now = await core.db_now(session)
        h2o = MODELS["h2o"]
        hello = await core.hello(
            session,
            worker,
            {
                "models": {
                    "h2o": {
                        "model_version": h2o.model_version,
                        "weights_revision": h2o.weights_revision,
                    }
                }
            },
            now,
        )
        lease = await core.lease(
            session,
            worker,
            {
                "session": hello["session"],
                "model": "h2o",
                "model_version": h2o.model_version,
                "max_jobs": 1,
            },
            now,
        )
        await session.commit()
    [leased] = await _jobs(status="leased")
    assert lease["jobs"][0]["job_id"] == leased.id
    assert (leased.listing_a, leased.listing_b) == pair(s1, s2)


async def test_the_first_judge_leaving_the_registry_moves_its_work_to_the_new_one():
    """D25: Kev's stage left `match` when H2O replaced it. A queued Kev job is
    re-offered to the pipeline (queued at H2O, same reason and priority), and
    a standing decision carrying a Kev score is re-scored at the version-bump
    priorities, "same" before "not same"."""
    a, b = await _shop("shop-a"), await _shop("shop-b")
    s1 = await _listing(a, "carbon film resistor 10k ohm")
    s2 = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    n1 = await _listing(a, "ceramic capacitor 100nf 50v")
    n2 = await _listing(b, "ceramic capacitor 100nf 50v disc")
    q1 = await _listing(a, "electrolytic capacitor 100uf 25v")
    q2 = await _listing(b, "electrolytic capacitor 100uf 25v radial")
    r1 = await _listing(a, "tantalum capacitor 10uf 16v")
    r2 = await _listing(b, "tantalum capacitor 10uf 16v smd")
    await _daily()
    await _score_all(s1, s2)
    await _score_all(n1, n2, h2o=0.3)
    assert (await _decide(s1, s2)).outcome == SAME
    assert (await _decide(n1, n2)).outcome == "not_same"
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM ai_jobs"))
        kev = AiModelVersion(
            model="kev",
            model_version="kev-4b-Q4_K_M@older",
            prompt_version="K2-150@older",
            weights_revision="0" * 40,
            scoring={},
        )
        session.add(kev)
        await session.flush()
        # The decisions as p1 left them: a Kev score, no H2O score stored.
        for d in await session.scalars(select(AiDecision)):
            old = d.scores.pop("h2o")
            d.scores = {**d.scores, "kev": {**old, "model": "kev", "model_version_id": kev.id}}
            d.policy_version = "p1"
            if d.decided_by == "h2o":
                d.decided_by = "kev"
        h2o_judge = (await flow.current_judges(session))[("match", "h2o")]
        await session.execute(
            AiScore.__table__.delete().where(AiScore.model_version_id == h2o_judge)
        )
        x, y = pair(q1, q2)
        session.add(
            AiJob(
                pipeline="match",
                stage="kev",
                listing_a=x,
                listing_b=y,
                model_version_id=kev.id,
                priority=60,
                reason="candidates",
            )
        )
        # A pplx job queued because Kev passed: pplx's judge is unchanged, but H2O has not
        # seen the pair, so it must not be scored by pplx first.
        r_a, r_b = pair(r1, r2)
        session.add(
            AiJob(
                pipeline="match",
                stage="pplx",
                listing_a=r_a,
                listing_b=r_b,
                model_version_id=(await flow.current_judges(session))[("match", "pplx")],
                priority=80,
                reason="candidates",
            )
        )
        await session.commit()

    async with SessionLocal() as session:
        assert await core.sweep_judges(session) == 1
        await session.commit()
    queued = await _jobs(status="queued")
    assert {(j.listing_a, j.listing_b): (j.stage, j.priority, j.reason) for j in queued} == {
        pair(q1, q2): ("h2o", 60, "candidates"),
        pair(r1, r2): ("h2o", 80, "candidates"),
    }
    # Once H2O has scored, a queued pplx job is left alone by the next sweep.
    await _score_all(r1, r2)
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM ai_jobs WHERE listing_a = :a"), {"a": r_a})
        session.add(
            AiJob(
                pipeline="match",
                stage="pplx",
                listing_a=r_a,
                listing_b=r_b,
                model_version_id=(await flow.current_judges(session))[("match", "pplx")],
                priority=80,
                reason="candidates",
            )
        )
        await session.commit()
    async with SessionLocal() as session:
        await core.sweep_judges(session)
        await session.commit()
    assert [(j.stage, j.listing_a) for j in await _jobs(status="queued", listing_a=r_a)] == [
        ("pplx", r_a)
    ]
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM ai_jobs WHERE listing_a = :a"), {"a": r_a})
        await session.commit()

    async with SessionLocal() as session:
        await producers.run(session, producers.RescoreTrigger())
        await session.commit()
    jobs = {(j.listing_a, j.listing_b): (j.stage, j.priority) for j in await _jobs(status="queued")}
    assert jobs == {
        pair(q1, q2): ("h2o", 60),
        pair(s1, s2): ("h2o", 35),
        pair(n1, n2): ("h2o", 30),
    }


async def test_a_queued_job_offered_higher_is_raised_and_a_leased_one_is_not():
    """A "same" queued at 35 for a new judge whose text then changes is re-offered at 100:
    the queued job rises to 100 (P8 as amended 2026-11-26). Never lowered, never a second
    job, and a leased job is a worker's: left alone."""
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    v = await _listing(b, "ceramic capacitor 100nf 50v")
    same = triggers.RESCORE_SAME_VERSION
    async with SessionLocal() as session:
        assert await enqueue(session, [PairRequest(x, y, "match", same, "rescore")]) == 1
        assert await enqueue(session, [PairRequest(x, y, "match", 100, "rescore")]) == 0
        assert await enqueue(session, [PairRequest(x, y, "match", 30, "candidates")]) == 0
        # Two offers of one pair in one call: one job, at the higher priority.
        assert await enqueue(
            session, [PairRequest(x, v, "match", 35, "rescore"), PairRequest(v, x, "match", 60,
                                                                             "rescore")]
        ) == 1  # fmt: skip
        await session.commit()
    jobs = {(j.listing_a, j.listing_b): j for j in await _jobs()}
    assert len(jobs) == 2
    assert (jobs[pair(x, y)].priority, jobs[pair(x, y)].reason) == (100, "rescore")
    assert jobs[pair(x, v)].priority == 60

    async with SessionLocal() as session:
        await session.execute(
            update(AiJob).values(status="leased", priority=same, lease_id=uuid.uuid4())
        )
        await session.commit()
    async with SessionLocal() as session:
        assert await enqueue(session, [PairRequest(x, y, "match", 100, "rescore")]) == 0
        await session.commit()
    assert {j.priority for j in await _jobs()} == {same}


async def test_enqueue_never_waits_on_a_job_the_broker_holds_locked():
    """A heartbeat or a submit holds its jobs FOR UPDATE. A re-offer must neither wait for
    them nor lock a leased one: a leased job is left alone, and a locked queued one is
    raised at the next offer, after the lock is gone."""
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    v = await _listing(b, "ceramic capacitor 100nf 50v")
    async with SessionLocal() as session:
        await enqueue(session, [PairRequest(x, y, "match", 35, "rescore"),
                                PairRequest(x, v, "match", 35, "rescore")])  # fmt: skip
        await session.commit()
    jobs = {(j.listing_a, j.listing_b): j for j in await _jobs()}
    leased, queued = jobs[pair(x, y)], jobs[pair(x, v)]
    async with SessionLocal() as session:
        await session.execute(
            update(AiJob).where(AiJob.id == leased.id).values(status="leased",
                                                             lease_id=uuid.uuid4())
        )  # fmt: skip
        await session.commit()

    async with SessionLocal() as holder, SessionLocal() as producer:
        # The broker's side: both rows locked, as a heartbeat or a submit holds them.
        await holder.execute(
            select(AiJob.id).where(AiJob.id.in_([leased.id, queued.id])).with_for_update()
        )
        await producer.execute(text("SET LOCAL lock_timeout = '2s'"))
        await producer.execute(text("SET LOCAL statement_timeout = '5s'"))
        offer = [PairRequest(x, y, "match", 100, "rescore"),
                 PairRequest(x, v, "match", 100, "rescore")]  # fmt: skip
        assert await enqueue(producer, offer) == 0  # neither waits nor fails
        await producer.commit()
        await holder.rollback()
    jobs = {(j.listing_a, j.listing_b): j.priority for j in await _jobs()}
    assert jobs == {pair(x, y): 35, pair(x, v): 35}  # the locked queued one: not yet

    async with SessionLocal() as producer:
        assert await enqueue(producer, [PairRequest(x, v, "match", 100, "rescore")]) == 0
        await producer.commit()
    jobs = {(j.listing_a, j.listing_b): j.priority for j in await _jobs()}
    assert jobs == {pair(x, y): 35, pair(x, v): 100}  # raised at the next offer


# --- audit ------------------------------------------------------------------------------------


async def test_the_audit_offers_rules_merged_pairs_once_and_never_ai_joined_ones():
    a, b, c = await _shop("shop-a"), await _shop("shop-b"), await _shop("shop-c")
    product = await _product()
    x = await _listing(a, "ne555 precision timer dip8", product=product)
    y = await _listing(b, "ne555 timer dip-8", product=product)
    await _listing(c, "555 timer chip", product=product, via="ai")
    await _listing(a, "ne555 timer spare", product=product)  # same shop as x
    *_, audit = await _daily()
    jobs = await _jobs(pipeline="audit")
    assert {(j.listing_a, j.listing_b) for j in jobs} >= {pair(x, y)}
    assert all(j.priority == 10 and j.reason == "audit" and j.stage == "h2o" for j in jobs)
    count = len(jobs)
    *_, again = await _daily()
    assert again["offered"] == 0
    assert len(await _jobs(pipeline="audit")) == count


async def test_a_dead_job_is_left_for_a_person_not_requeued_by_the_next_run():
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    request = PairRequest(x, y, "match", 60, "candidates")
    async with SessionLocal() as session:
        assert (await flow.offer(session, [request]))["queued"] == 1
        await session.execute(update(AiJob).values(status="dead", attempts=3))
        await session.commit()
    async with SessionLocal() as session:
        assert (await flow.offer(session, [request]))["queued"] == 0
        await session.commit()
    assert [j.status for j in await _jobs()] == ["dead"]
    async with SessionLocal() as session:
        [job] = await _jobs()
        assert await core.retry_job(session, job.id) is not None
        await session.commit()
    assert [j.status for j in await _jobs()] == ["queued"]


async def test_two_producer_runs_never_overlap():
    a = await _shop("shop-a")
    await _listing(a, "seed listing for the baseline")
    async with SessionLocal() as holding:
        first = await producers.daily(holding)
        assert first[0]["trigger"] == "judge sweep"
        async with SessionLocal() as other:
            assert await producers.daily(other) == [producers.BUSY]
            assert await producers.backlog(other) == producers.BUSY
        await holding.commit()
    async with SessionLocal() as session:
        assert (await producers.daily(session))[0]["trigger"] == "judge sweep"
        await session.commit()


async def test_a_listing_that_leaves_electronics_loses_its_state():
    """So the re-score trigger stops looking at its decisions, instead of
    rewriting them every day against a hash nothing updates."""
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _daily()
    await _score_all(x, y)
    await _decide(x, y)
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == y).values(domain="tools"))
        await session.commit()
    _, _, rescore, _ = await _daily()
    assert rescore.get("text", 0) == 0 and rescore["decided"] == 0
    async with SessionLocal() as session:
        ids = set(await session.scalars(select(AiListingState.listing_id)))
    assert ids == {x}


# --- owner decisions, 2026-11-17 ------------------------------------------------------------


async def _revoke(decision_id: int) -> None:
    async with SessionLocal() as session:
        row = await session.get(AiDecision, decision_id)
        row.state, row.revoked_at, row.revoked_by, row.revoke_note = (
            "revoked",
            func.now(),
            "test",
            "test",
        )
        await session.commit()


async def test_a_revoked_pair_is_offered_again_only_after_a_text_change():
    """Option (b): with unchanged text a revoked pair stays out; once a
    listing's content hash moves it is a candidate again."""
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _daily()  # baseline
    await _score_all(x, y)
    await _revoke((await _decide(x, y)).id)
    async with SessionLocal() as session:
        unchanged = await producers.backlog(session)
        await session.commit()
    assert unchanged["kept"] == 0 and await _jobs() == []
    async with SessionLocal() as session:
        await session.execute(
            update(Listing).where(Listing.id == y).values(title_en="carbon resistor 10k ohm 1/4w")
        )
        await session.commit()
    _, candidates, *_ = await _daily()
    assert candidates["kept"] == 1
    assert _pairs(await _jobs(pipeline="match")) == {pair(x, y)}


async def test_a_decision_stops_acting_when_a_listing_leaves_electronics():
    from makhzan_schemas.ai.decisions import load_ai_same
    from makhzan_schemas.overrides import load_overrides

    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _score_all(x, y)
    assert (await _decide(x, y)).outcome == SAME
    async with SessionLocal() as session:
        assert (await load_ai_same(session, await load_overrides(session))).pairs == {pair(x, y)}
        await session.execute(update(Listing).where(Listing.id == y).values(domain="tools"))
        await session.commit()
        assert not (await load_ai_same(session, await load_overrides(session))).pairs


async def test_a_not_same_decision_also_queues_the_rebuild_after_a_window():
    """REBUILD_ON_UNMERGE: any new standing decision, so an AI merge to undo
    is applied at the window's end."""
    from makhzan_schemas.ai.mode import set_ai_mode

    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _score_all(x, y, h2o=0.2)
    assert (await _decide(x, y)).outcome == "not_same"
    queued: list[int] = []

    async def queue() -> None:
        queued.append(1)

    async with SessionLocal() as session:
        await set_ai_mode(session, "live")
        assert await core.maybe_rebuild(session, queue)
        assert not await core.maybe_rebuild(session, queue)  # nothing newer
        await session.commit()
    assert queued == [1]


# --- revoked pairs: re-offered only when what the models see changes ------------------------


async def _revoked_pair(**listing_b) -> tuple:
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    if listing_b:
        async with SessionLocal() as session:
            await session.execute(update(Listing).where(Listing.id == y).values(**listing_b))
            await session.commit()
    await _daily()  # baseline
    await _score_all(x, y)
    decision = await _decide(x, y)
    await _revoke(decision.id)
    return x, y


async def _standing() -> list[AiDecision]:
    async with SessionLocal() as session:
        return list(await session.scalars(select(AiDecision).where(AiDecision.state == "standing")))


async def test_an_arabic_title_change_under_an_english_one_does_not_reoffer():
    """The content hash moves (P5 names both languages) but no judge sees the
    Arabic title: the revoked pair stays out, and nothing is settled."""
    x, y = await _revoked_pair()
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == y).values(title_ar="مقاومة"))
        await session.commit()
    _, candidates, *_ = await _daily()
    assert candidates["queries"] == 1  # the listing is due: its hash moved
    assert candidates.get("revoked_reoffered", 0) == 0
    assert await _jobs() == [] and await _standing() == []


async def test_a_hash_version_bump_does_not_reoffer(monkeypatch):
    from makhzan_schemas.ai import hashing

    await _revoked_pair()
    monkeypatch.setattr(hashing, "HASH_VERSION", hashing.HASH_VERSION + 1)
    _, candidates, *_ = await _daily()
    assert candidates["queries"] == 2  # every hash moved
    assert candidates.get("revoked_reoffered", 0) == 0
    assert await _jobs() == [] and await _standing() == []


async def test_a_visible_change_reoffers_with_fresh_scoring_and_a_second_revocation_holds():
    x, y = await _revoked_pair()
    async with SessionLocal() as session:
        await session.execute(
            update(Listing).where(Listing.id == y).values(title_en="carbon resistor 10k ohm 1/4w")
        )
        await session.commit()
    _, candidates, *_ = await _daily()
    assert candidates["revoked_reoffered"] == 1
    [job] = await _jobs()
    assert (job.stage, job.status) == ("h2o", "queued")  # the models are asked again
    assert await _standing() == []
    # Scored on the new text, decided, revoked again: out until the next change.
    await _score_all(x, y)
    await _revoke((await _decide(x, y)).id)
    async with SessionLocal() as session:
        await session.execute(update(AiJob).values(status="cancelled"))
        await session.commit()
    async with SessionLocal() as session:
        again = await producers.backlog(session)
        await session.commit()
    assert again.get("revoked_reoffered", 0) == 0 and again["kept"] == 0
    assert await _standing() == []


async def test_a_reoffered_pair_is_never_settled_from_scores_the_revocation_saw():
    """An edit past H2O's 150-word cap changes pplx's view only. If H2O's old
    score alone would decide the pair, it is not offered: no model would look."""
    description = " ".join(f"word{i}" for i in range(200))
    x, y = await _revoked_pair(description_en=description)
    async with SessionLocal() as session:
        await session.execute(update(AiDecision).values(outcome="not_same"))
        await session.commit()
    # H2O said no on the old text (its view is unchanged by the edit below).
    async with SessionLocal() as session:
        await session.execute(update(AiScore).values(p=0.1))
        await session.commit()
    edited = description.replace("word180", "changed180")
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == y).values(description_en=edited))
        await session.commit()
    _, candidates, *_ = await _daily()
    assert candidates["revoked_reoffered"] == 1
    assert candidates["revoked_blocked"] == 1
    assert await _jobs() == [] and await _standing() == []


async def test_an_h2o_confident_no_blocks_whatever_the_department():
    from makhzan_schemas.ai.decisions import load_ai_same
    from makhzan_schemas.overrides import load_overrides

    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _score_all(x, y, h2o=0.01)
    assert (await _decide(x, y)).outcome == "not_same"
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == y).values(domain="tools"))
        await session.commit()
        ai = await load_ai_same(session, await load_overrides(session))
    assert ai.no == {pair(x, y)}


# --- the revocation guard in write_decision -------------------------------------------------

_A = "carbon film resistor 10k ohm quarter watt"
_B = "carbon resistor 10k ohm 1/4w metal"


async def _set(y, **values) -> None:
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == y).values(**values))
        await session.commit()


async def _two() -> tuple:
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, _A)
    await _daily()  # baseline
    return x, y


async def test_a_revert_to_text_scored_before_the_revocation_does_not_restore_it():
    """Decided on A, re-decided on B, revoked on B, text back to A: A's
    requests differ from B's, so the pair is offered, but A's scores all
    predate the revocation: no decision is written."""
    x, y = await _two()
    await _score_all(x, y)
    await _decide(x, y)
    await _set(y, title_en=_B)
    await _daily()
    await _score_all(x, y)
    revoked = await _decide(x, y)
    async with SessionLocal() as session:
        await session.execute(update(AiJob).values(status="cancelled"))
        await session.commit()
    await _revoke(revoked.id)
    await _set(y, title_en=_A)
    _, candidates, *_ = await _daily()
    assert candidates["revoked_reoffered"] == 1
    assert candidates["revoked_blocked"] == 1
    assert await _standing() == []


async def test_a_job_queued_before_a_revocation_decides_nothing_after_it():
    """A re-score job queued on B; the person revokes; the text reverts to A
    before a lease: the lease finds the job scored (A's old scores), marks it
    done, and writes no decision."""
    x, y = await _two()
    await _score_all(x, y)
    revoked = await _decide(x, y)
    await _set(y, title_en=_B)
    await _daily()
    [job] = await _jobs(status="queued")
    await _revoke(revoked.id)
    await _set(y, title_en=_A)
    async with SessionLocal() as session:
        row = await session.get(AiJob, job.id)
        judges = await flow.current_judges(session)
        assert await core._prepare(session, row, judges, await core.db_now(session)) is None
        await session.commit()
    assert [j.status for j in await _jobs()] == ["done"]
    assert await _standing() == []


async def test_a_new_model_version_on_the_revoked_text_does_not_stand(monkeypatch):
    """Fresh scores, after the revocation, by a new judge, of exactly the
    requests the revocation saw: still not a reason to undo it."""
    from dataclasses import replace

    from makhzan_schemas.ai import policy

    x, y = await _two()
    await _score_all(x, y)
    await _revoke((await _decide(x, y)).id)
    monkeypatch.setitem(
        policy.MODELS, "h2o", replace(policy.MODELS["h2o"], model_version="h2o-4b@newer")
    )
    await _score_all(x, y)  # the new judge scores the same text, after the revocation
    async with SessionLocal() as session:
        outcome = await flow.offer(session, [PairRequest(x, y, "match", 60, "rescore")])
        await session.commit()
    assert outcome["revoked_blocked"] == 1
    assert await _standing() == []


async def test_a_pplx_only_change_after_an_h2o_yes_is_offered_and_can_stand():
    """An edit past H2O's cap: H2O's view is unchanged (its old yes stands),
    pplx is asked again, and its fresh score on new text may decide."""
    description = " ".join(f"word{i}" for i in range(200))
    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, _A)
    await _set(y, description_en=description)
    await _daily()
    await _score_all(x, y)
    await _revoke((await _decide(x, y)).id)
    await _set(y, description_en=description.replace("word180", "changed180"))
    _, candidates, *_ = await _daily()
    assert candidates["revoked_reoffered"] == 1
    assert [(j.stage, j.status) for j in await _jobs()] == [("pplx", "queued")]
    assert await _standing() == []
    await _score_all(x, y)  # pplx scores the new text, after the revocation
    decision = await _decide(x, y)
    assert decision is not None and decision.state == "standing"


async def test_revoking_cancels_the_pairs_queued_jobs(capsys):
    from worker import ai

    x, y = await _two()
    await _score_all(x, y)
    decision = await _decide(x, y)
    await _set(y, title_en=_B)
    await _daily()
    assert [j.status for j in await _jobs()] == ["queued"]
    assert await ai.run(["revoke", str(decision.id), "--note", "wrong", "--by", "t"]) == 0
    assert "1 queued job(s) cancelled" in capsys.readouterr().out
    assert [j.status for j in await _jobs()] == ["cancelled"]


async def test_a_decision_written_while_a_revoke_is_open_waits_and_is_refused():
    """The race: a revoke holds its transaction open; a decision for the same
    pair waits on the pair's advisory lock, then sees the revocation."""
    import asyncio

    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _daily()
    await _score_all(x, y)
    decision = await _decide(x, y)

    revoker = SessionLocal()
    try:
        _, _, refusal = await flow.revoke_decision(revoker, decision.id, by="t", note="race")
        assert refusal is None  # revoked, not yet committed

        async def deciding():
            async with SessionLocal() as session:
                out = await flow.advance(session, [PairRequest(x, y, "match", 60, "candidates")])
                await session.commit()
                return out

        task = asyncio.create_task(deciding())
        await asyncio.sleep(0.5)
        assert not task.done()  # waiting on the pair's lock
        await revoker.commit()
    finally:
        await revoker.close()
    out = await asyncio.wait_for(task, 10)
    assert out["revoked_blocked"] == 1
    assert await _standing() == []


async def test_the_audit_total_counts_pairs_once_whichever_judges_scored_them():
    """A pair Kev audited before D25 and H2O after counts once in the total, once per model."""
    import hashlib

    from makhzan_schemas.ai import status

    a, b = await _shop("shop-a"), await _shop("shop-b")
    x, y = pair(await _listing(a, "relay module 5v"), await _listing(b, "relay module 5v 1ch"))
    async with SessionLocal() as session:
        for model, low in (("kev", 0.03), ("h2o", 0.5)):
            version = AiModelVersion(
                model=model,
                model_version=f"{model}@audit-test",
                prompt_version="K2-150@test",
                weights_revision="0" * 40,
                scoring={},
            )
            session.add(version)
            await session.flush()
            hashes = {}
            for order, p in (("ab", low), ("ba", 0.9)):
                digest = hashlib.sha256(f"{model}{order}".encode()).digest()
                hashes[order] = digest.hex()
                session.add(
                    AiScore(
                        model_version_id=version.id,
                        listing_a=x,
                        listing_b=y,
                        reading_order=order,
                        request_sha256=digest,
                        content_sha256_a=b"\0" * 32,
                        content_sha256_b=b"\0" * 32,
                        p=p,
                    )
                )
            session.add(
                AiJob(
                    pipeline="audit",
                    stage=model,
                    reason="audit",
                    model_version_id=version.id,
                    listing_a=x,
                    listing_b=y,
                    priority=10,
                    status="done",
                    request_sha256=hashes,
                )
            )
        await session.commit()
        got = await status._audit(session, {})
    assert got["scored"] == 1
    assert got["by_model"] == {
        "kev": {"scored": 1, "below": [[0.8, 1], [0.05, 1]]},
        "h2o": {"scored": 1, "below": [[0.578, 1], [0.19, 0]]},
    }
