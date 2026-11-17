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


def test_kev_below_its_threshold_decides_not_same_by_kev():
    step = decide("match", {"kev": _orders(0.95, 0.79)})
    assert (step.action, step.outcome, step.decided_by) == (DECIDE, NOT_SAME, "kev")
    assert step.mins == (("kev", 0.79),)


def test_kev_passing_hands_the_pair_to_pplx():
    step = decide("match", {"kev": _orders(0.80, 0.91)})
    assert (step.action, step.stage) == (SCORE, "pplx")


def test_pplx_at_its_threshold_decides_same_and_below_not_same():
    same = decide("match", {"kev": _orders(0.9, 0.85), "pplx": _orders(0.95, 0.99)})
    assert (same.action, same.outcome, same.decided_by) == (DECIDE, SAME, "pplx")
    assert dict(same.mins) == {"kev": 0.85, "pplx": 0.95}
    no = decide("match", {"kev": _orders(0.9, 0.85), "pplx": _orders(0.97, 0.949)})
    assert (no.outcome, no.decided_by) == (NOT_SAME, "pplx")


def test_one_reading_order_settles_nothing_not_even_a_no():
    assert decide("match", {"kev": _orders(0.01, None)}).stage == "kev"
    assert decide("match", {"kev": _orders(0.9, 0.9), "pplx": _orders(None, 0.99)}).stage == "pplx"


def test_the_audit_records_kev_and_decides_nothing():
    assert transition("audit", {}).stage == "kev"
    step = transition("audit", {"kev": _orders(0.01, 0.02)})
    assert (step.action, step.outcome) == (RECORD, None)
    assert step.mins == (("kev", 0.01),)


def test_an_unknown_pipeline_or_policy_is_refused():
    with pytest.raises(ValueError):
        transition("nope", {})
    with pytest.raises(ValueError):
        decide("match", {"kev": _orders(0.9, 0.9)}, policy="p0")


def test_a_new_pipeline_is_data(monkeypatch):
    # A three-stage pipeline needs no code beyond its declaration.
    third = Stage("kev-again", model="kev", prompt="K1-full", threshold="kev")
    monkeypatch.setitem(
        pipelines.PIPELINES,
        "triple",
        Pipeline("triple", (*pipelines.PIPELINES["match"].stages, third)),
    )
    pipelines.check_registry()
    scores = {"kev": _orders(0.9, 0.9), "pplx": _orders(0.99, 0.99)}
    assert transition("triple", scores).stage == "kev-again"
    scores["kev-again"] = _orders(0.85, 0.82)
    assert transition("triple", scores).outcome == SAME
    assert ("triple", "kev-again") in stages_for_models({"kev"})


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
    assert stages_for_models({"kev"}) == [("match", "kev"), ("audit", "kev")]
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
    x, y, outcome="same", *, kev=0.9, pplx=0.97, state="standing", pipeline="match"
):
    a, b = pair(x, y)
    scores = {"kev": {"model": "kev", "ab": kev, "ba": kev, "min": kev}}
    if pplx is not None:
        scores["pplx"] = {"model": "pplx", "ab": pplx, "ba": pplx, "min": pplx}
    row = AiDecision(
        pipeline=pipeline,
        listing_a=a,
        listing_b=b,
        outcome=outcome,
        decided_by="pplx" if pplx is not None else "kev",
        scores=scores,
        policy_version="p1",
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


async def test_the_group_check_reads_every_standing_kev_no():
    shops = [await _supplier(f"shop-{c}") for c in "abc"]
    a, b, c = [await _listing(s, s.slug) for s in shops]
    await _decision(a, b, outcome="not_same", kev=0.04, pplx=None)
    await _decision(a, c, outcome="not_same", kev=0.05, pplx=None)
    got = await _load()
    assert got.no == {pair(a, b)}  # 0.05 is not below 0.05
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
        ("match", "kev", *pair(a, b)),
        ("match", "pplx", *pair(a, b)),
        ("audit", "kev", *pair(a, b)),
    ]
    # One judge row per (model, model version, prompt version), shared by
    # every stage that reads the same model through the same prompt.
    assert {(v.model, v.prompt_version) for v in versions.values()} == {
        ("kev", "K2-150@6aef2c6c"),
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
