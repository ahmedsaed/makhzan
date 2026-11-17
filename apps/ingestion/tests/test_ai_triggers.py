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
from makhzan_schemas.ai import flow
from makhzan_schemas.ai.pipelines import PIPELINES, SAME
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.ai.render import load_shown, render
from makhzan_schemas.ai.triggers import PairRequest
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
from sqlalchemy import func, select, update


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


async def _score_all(a, b, *, kev=0.9, pplx=0.97) -> None:
    """Both stages' scores for the pair's current requests, as workers would post."""
    a, b = pair(a, b)
    async with SessionLocal() as session:
        shown = await load_shown(session, (a, b))
        judges = await flow.current_judges(session)
        for name, p in (("kev", kev), ("pplx", pplx)):
            stage = PIPELINES["match"].stage(name)
            for order, digest in render(stage, shown[a], shown[b]).sha256.items():
                session.add(
                    AiScore(
                        model_version_id=judges[("match", name)],
                        listing_a=a,
                        listing_b=b,
                        reading_order=order,
                        request_sha256=digest,
                        content_sha256_a=shown[a].content_sha256,
                        content_sha256_b=shown[b].content_sha256,
                        p=p,
                    )
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
    assert {(j.stage, j.priority, j.reason) for j in jobs} == {("kev", 60, "candidates")}
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
    assert (job.pipeline, job.stage, job.priority, job.reason) == ("match", "kev", 100, "rescore")
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


async def test_a_version_bump_rescores_standing_same_decisions_first():
    a, b = await _shop("shop-a"), await _shop("shop-b")
    s1 = await _listing(a, "carbon film resistor 10k ohm")
    s2 = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    n1 = await _listing(a, "ceramic capacitor 100nf 50v")
    n2 = await _listing(b, "ceramic capacitor 100nf 50v disc")
    await _daily()
    await _score_all(s1, s2)
    await _score_all(n1, n2, kev=0.3)
    assert (await _decide(s1, s2)).outcome == SAME
    assert (await _decide(n1, n2)).outcome == "not_same"
    # A new Kev version: the stored decisions now name an old judge.
    async with SessionLocal() as session:
        old = AiModelVersion(
            model="kev",
            model_version="kev-4b@older",
            prompt_version="K2-150@older",
            weights_revision="0" * 40,
            scoring={},
        )
        session.add(old)
        await session.flush()
        for d in await session.scalars(select(AiDecision)):
            d.scores = {**d.scores, "kev": {**d.scores["kev"], "model_version_id": old.id}}
        await session.commit()
    async with SessionLocal() as session:
        result = await producers.run(session, producers.RescoreTrigger())
        await session.commit()
    assert result["version"] == 2
    jobs = {(j.listing_a, j.listing_b): j.priority for j in await _jobs()}
    # The scores are byte-identical, so no job is needed at all: both settle.
    assert jobs == {} and result["decided"] == 2

    # With the requests changed too (a new prompt would do it), jobs are owed:
    # the standing "same" first.
    async with SessionLocal() as session:
        await session.execute(
            update(AiScore).values(request_sha256=func.sha256(AiScore.request_sha256))
        )
        old_id = await session.scalar(
            select(AiModelVersion.id).where(AiModelVersion.model_version == "kev-4b@older")
        )
        for d in await session.scalars(select(AiDecision)):
            d.scores = {**d.scores, "kev": {**d.scores["kev"], "model_version_id": old_id}}
        await session.commit()
    async with SessionLocal() as session:
        await producers.run(session, producers.RescoreTrigger())
        await session.commit()
    jobs = {(j.listing_a, j.listing_b): j.priority for j in await _jobs()}
    assert jobs == {pair(s1, s2): 100, pair(n1, n2): 30}

    token = core.new_token()
    async with SessionLocal() as session:
        worker = AiWorker(name="cpu-kev", token_sha256=core.token_sha256(token), models=["kev"])
        session.add(worker)
        await session.flush()
        now = await core.db_now(session)
        kev = MODELS["kev"]
        hello = await core.hello(
            session,
            worker,
            {
                "models": {
                    "kev": {
                        "model_version": kev.model_version,
                        "weights_revision": kev.weights_revision,
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
                "model": "kev",
                "model_version": kev.model_version,
                "max_jobs": 1,
            },
            now,
        )
        await session.commit()
    [leased] = await _jobs(status="leased")
    assert lease["jobs"][0]["job_id"] == leased.id
    assert (leased.listing_a, leased.listing_b) == pair(s1, s2)


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
    assert all(j.priority == 10 and j.reason == "audit" and j.stage == "kev" for j in jobs)
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
    await _score_all(x, y, kev=0.2)
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
    assert (job.stage, job.status) == ("kev", "queued")  # the models are asked again
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
    """An edit past Kev's 150-word cap changes pplx's view only. If Kev's old
    score alone would decide the pair, it is not offered: no model would look."""
    description = " ".join(f"word{i}" for i in range(200))
    x, y = await _revoked_pair(description_en=description)
    async with SessionLocal() as session:
        await session.execute(update(AiDecision).values(outcome="not_same"))
        await session.commit()
    # Kev said no on the old text (its view is unchanged by the edit below).
    async with SessionLocal() as session:
        await session.execute(update(AiScore).values(p=0.1))
        await session.commit()
    edited = description.replace("word180", "changed180")
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == y).values(description_en=edited))
        await session.commit()
    _, candidates, *_ = await _daily()
    assert candidates["revoked_reoffered"] == 1
    assert candidates["revoked_stale_scores"] == 1
    assert await _jobs() == [] and await _standing() == []


async def test_a_kev_confident_no_blocks_whatever_the_department():
    from makhzan_schemas.ai.decisions import load_ai_same
    from makhzan_schemas.overrides import load_overrides

    a, b = await _shop("shop-a"), await _shop("shop-b")
    x = await _listing(a, "carbon film resistor 10k ohm")
    y = await _listing(b, "carbon film resistor 10k ohm quarter watt")
    await _score_all(x, y, kev=0.01)
    assert (await _decide(x, y)).outcome == "not_same"
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == y).values(domain="tools"))
        await session.commit()
        ai = await load_ai_same(session, await load_overrides(session))
    assert ai.no == {pair(x, y)}
