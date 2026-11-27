"""AI matching's core: pipelines as data, one transition rule, triggers, mode, and
what the regroup reads of decisions.

The shops and listings here are fictional.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from makhzan_schemas import overrides as rulings
from makhzan_schemas.ai import pipelines
from makhzan_schemas.ai.decisions import load_ai_same
from makhzan_schemas.ai.mode import ai_mode, set_ai_mode
from makhzan_schemas.ai.pipelines import (
    DECIDE,
    NOT_SAME,
    RECORD,
    SAME,
    SCORE,
    Pipeline,
    Stage,
    decide,
    stages_for_models,
    transition,
)
from makhzan_schemas.ai.triggers import PairRequest, enqueue
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType
from makhzan_schemas.models import AiDecision, AiJob, AiModelVersion, Listing, Supplier
from makhzan_schemas.overrides import load_overrides, pair
from sqlalchemy import select

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _orders(ab, ba):
    return {"ab": ab, "ba": ba}


# --- the transition rule, pure ----------------------------------------------


def test_h2o_below_its_threshold_decides_not_same_by_h2o():
    step = decide("match", {"h2o": _orders(0.95, 0.577)})
    assert (step.action, step.outcome, step.decided_by) == (DECIDE, NOT_SAME, "h2o")
    assert step.mins == (("h2o", 0.577),)


def test_h2o_passing_hands_the_pair_to_pplx():
    step = decide("match", {"h2o": _orders(0.578, 0.91)})
    assert (step.action, step.stage) == (SCORE, "pplx")


def test_pplx_at_its_threshold_decides_same_and_below_not_same():
    same = decide("match", {"h2o": _orders(0.9, 0.85), "pplx": _orders(0.95, 0.99)})
    assert (same.action, same.outcome, same.decided_by) == (DECIDE, SAME, "pplx")
    assert dict(same.mins) == {"h2o": 0.85, "pplx": 0.95}
    no = decide("match", {"h2o": _orders(0.9, 0.85), "pplx": _orders(0.97, 0.949)})
    assert (no.outcome, no.decided_by) == (NOT_SAME, "pplx")


def test_one_reading_order_settles_nothing_not_even_a_no():
    assert decide("match", {"h2o": _orders(0.01, None)}).stage == "h2o"
    assert decide("match", {"h2o": _orders(0.9, 0.9), "pplx": _orders(None, 0.99)}).stage == "pplx"


def test_the_audit_records_h2o_and_decides_nothing():
    assert transition("audit", {}).stage == "h2o"
    step = transition("audit", {"h2o": _orders(0.01, 0.02)})
    assert (step.action, step.outcome) == (RECORD, None)
    assert step.mins == (("h2o", 0.01),)


def test_an_unknown_pipeline_or_policy_is_refused():
    with pytest.raises(ValueError):
        transition("nope", {})
    with pytest.raises(ValueError):
        decide("match", {"h2o": _orders(0.9, 0.9)}, policy="p0")


def test_a_policy_without_the_stages_threshold_is_refused():
    # p1 (Kev first) stays in POLICIES as history and rollback, but has no
    # threshold for the h2o stage: deciding under it is an error, not a guess.
    with pytest.raises(ValueError, match="no threshold 'h2o'"):
        decide("match", {"h2o": _orders(0.9, 0.9)}, policy="p1")


def test_a_new_pipeline_is_data(monkeypatch):
    # A three-stage pipeline needs no code beyond its declaration.
    third = Stage("h2o-again", model="h2o", prompt="K1-full", threshold="h2o")
    monkeypatch.setitem(
        pipelines.PIPELINES,
        "triple",
        Pipeline("triple", (*pipelines.PIPELINES["match"].stages, third)),
    )
    pipelines.check_registry()
    scores = {"h2o": _orders(0.9, 0.9), "pplx": _orders(0.99, 0.99)}
    assert transition("triple", scores).stage == "h2o-again"
    scores["h2o-again"] = _orders(0.85, 0.82)
    assert transition("triple", scores).outcome == SAME
    assert ("triple", "h2o-again") in stages_for_models({"h2o"})


def test_the_registry_refuses_an_unknown_model_prompt_or_threshold(monkeypatch):
    good = pipelines.PIPELINES["match"]
    for bad in (
        replace(good.stages[0], model="nope"),
        replace(good.stages[0], prompt="nope"),
        replace(good.stages[0], threshold="nope"),
        replace(good.stages[0], threshold=None),
    ):
        monkeypatch.setitem(pipelines.PIPELINES, "bad", Pipeline("bad", (bad,)))
        with pytest.raises(ValueError):
            pipelines.check_registry()


def test_a_worker_leases_every_stage_its_models_serve():
    assert stages_for_models({"h2o"}) == [("match", "h2o"), ("audit", "h2o")]
    assert stages_for_models({"pplx"}) == [("match", "pplx")]
    assert stages_for_models({"other"}) == []


# --- against the database ---------------------------------------------------


async def _supplier(slug: str) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    async with SessionLocal() as session:
        session.add(supplier)
        await session.commit()
    return supplier


async def _listing(supplier: Supplier, title: str, status=ListingStatus.ACTIVE) -> uuid.UUID:
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        source=supplier.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        title_en=title,
        price=100,
        images=[],
        attributes={},
        first_seen_at=T0,
        status=status,
    )
    async with SessionLocal() as session:
        session.add(listing)
        await session.commit()
    return listing.id


async def _decision(
    x,
    y,
    outcome="same",
    *,
    first=0.9,
    judge="h2o",
    pplx=0.97,
    state="standing",
    pipeline="match",
):
    a, b = pair(x, y)
    scores = {judge: {"model": judge, "ab": first, "ba": first, "min": first}}
    if pplx is not None:
        scores["pplx"] = {"model": "pplx", "ab": pplx, "ba": pplx, "min": pplx}
    row = AiDecision(
        pipeline=pipeline,
        listing_a=a,
        listing_b=b,
        outcome=outcome,
        decided_by="pplx" if pplx is not None else judge,
        scores=scores,
        policy_version="p2" if judge == "h2o" else "p1",
        content_sha256_a=b"\0" * 32,
        content_sha256_b=b"\0" * 32,
        state=state,
        revoked_at=T0 if state == "revoked" else None,
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _load(**kw):
    async with SessionLocal() as session:
        return await load_ai_same(session, await load_overrides(session), **kw)


async def test_the_mode_is_off_until_set_and_refuses_an_unknown_one():
    async with SessionLocal() as session:
        assert await ai_mode(session) == "off"
        await set_ai_mode(session, "live")
        await session.commit()
        assert await ai_mode(session) == "live"
        with pytest.raises(ValueError):
            await set_ai_mode(session, "on")


async def test_only_standing_same_decisions_between_active_listings_count():
    shops = [await _supplier(f"shop-{c}") for c in "abcdefgh"]
    a = await _listing(shops[0], "Example part one")
    b = await _listing(shops[1], "Example part two")
    kept = await _decision(a, b)
    c, d = await _listing(shops[2], "c"), await _listing(shops[3], "d")
    await _decision(c, d, state="revoked")
    e, f = await _listing(shops[4], "e"), await _listing(shops[5], "f")
    await _decision(e, f, outcome="not_same", pplx=0.5)
    g = await _listing(shops[6], "g", status=ListingStatus.ARCHIVED)
    h = await _listing(shops[7], "h")
    await _decision(g, h)
    await _decision(a, h, state="stale")

    got = await _load()
    assert got.pairs == {pair(a, b)} and got.ids == {pair(a, b): kept}


async def test_a_ruled_pair_is_never_read_and_one_shops_pair_cannot_act():
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    a, b = await _listing(shop_a, "a"), await _listing(shop_b, "b")
    a2 = await _listing(shop_a, "a2")
    await _decision(a, b)
    await _decision(a, a2)
    async with SessionLocal() as session:
        await rulings.add(session, a, b, rulings.NEVER, created_by="test", note="test")
        await session.commit()
    assert not await _load()


async def test_only_the_best_match_per_other_shop_counts_on_both_sides():
    shop_a, shop_b, shop_c = [await _supplier(s) for s in ("shop-a", "shop-b", "shop-c")]
    x = await _listing(shop_a, "x")
    b1, b2 = await _listing(shop_b, "b1"), await _listing(shop_b, "b2")
    c1 = await _listing(shop_c, "c1")
    await _decision(x, b1, pplx=0.99)
    await _decision(x, b2, pplx=0.96)  # x's weaker match in shop b
    await _decision(x, c1, pplx=0.96)  # the only match in shop c
    got = await _load()
    assert got.pairs == {pair(x, b1), pair(x, c1)}
    # Strength, last stage first: what orders competing pairs in the regroup.
    assert got.rank == {pair(x, b1): (0.99, 0.9), pair(x, c1): (0.96, 0.9)}


async def test_the_group_check_reads_every_standing_first_judge_no_at_its_own_floor():
    shops = [await _supplier(f"shop-{c}") for c in "abcde"]
    a, b, c, d, e = [await _listing(s, s.slug) for s in shops]
    await _decision(a, b, outcome="not_same", first=0.18, pplx=None)
    await _decision(a, c, outcome="not_same", first=0.19, pplx=None)
    # A decision still carrying Kev's score (made under p1, not yet re-scored
    # by H2O) is read at Kev's floor: H2O's would block nearly every Kev "no".
    await _decision(a, d, outcome="not_same", first=0.04, judge="kev", pplx=None)
    await _decision(a, e, outcome="not_same", first=0.18, judge="kev", pplx=None)
    got = await _load()
    assert got.no == {pair(a, b), pair(a, d)}  # 0.19 is not below 0.19
    assert not got  # no "same" pair: nothing to read


async def test_enqueue_puts_a_pair_into_its_pipelines_first_stage_once():
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    a, b = await _listing(shop_a, "a"), await _listing(shop_b, "b")
    request = PairRequest(b, a, "match", priority=60, reason="candidates")
    async with SessionLocal() as session:
        assert await enqueue(session, [request]) == 1
        assert await enqueue(session, [request]) == 0  # already queued
        assert await enqueue(session, [request], stage="pplx") == 1  # the broker's next step
        assert await enqueue(session, [replace(request, pipeline="audit")]) == 1
        await session.commit()
        jobs = list(await session.scalars(select(AiJob).order_by(AiJob.id)))
        versions = {v.id: v for v in await session.scalars(select(AiModelVersion))}
    assert [(j.pipeline, j.stage, j.listing_a, j.listing_b) for j in jobs] == [
        ("match", "h2o", *pair(a, b)),
        ("match", "pplx", *pair(a, b)),
        ("audit", "h2o", *pair(a, b)),
    ]
    # One judge row per (model, model version, prompt version), shared by
    # every stage that reads the same model through the same prompt.
    assert {(v.model, v.prompt_version) for v in versions.values()} == {
        ("h2o", "K2-150@6aef2c6c"),
        ("pplx", "K1-full@6aef2c6c"),
    }
    assert jobs[0].model_version_id == jobs[2].model_version_id


async def test_enqueue_refuses_an_unknown_pipeline():
    async with SessionLocal() as session:
        with pytest.raises(ValueError):
            await enqueue(session, [PairRequest(uuid.uuid4(), uuid.uuid4(), "nope", 1, "x")])


async def test_a_decision_of_an_unregistered_pipeline_is_skipped_not_a_crash(caplog):
    shops = [await _supplier(f"shop-{c}") for c in "abcd"]
    a, b, c, d = [await _listing(s, s.slug) for s in shops]
    await _decision(a, b, pipeline="retired-pipeline")
    await _decision(c, d)
    got = await _load()
    assert got.pairs == {pair(c, d)}
    assert "retired-pipeline" in caplog.text


@pytest.mark.parametrize("newer_first", [False, True])
async def test_an_exact_tie_goes_to_the_pair_whose_ids_sort_first(newer_first):
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    x = await _listing(shop_a, "x")
    b1, b2 = await _listing(shop_b, "b1"), await _listing(shop_b, "b2")
    first, second = sorted([pair(x, b1), pair(x, b2)], key=lambda p: (str(p[0]), str(p[1])))
    # The same scores on both: whichever decision is newer, the pair whose
    # listing ids sort first wins, never the newest decision id.
    for p in [second, first] if newer_first else [first, second]:
        await _decision(*p)
    got = await _load()
    assert got.pairs == {first}
