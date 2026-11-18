"""Importing a locally scored backlog (`worker.ai_import`).

The shops and listings here are fictional.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from makhzan_schemas.ai.pipelines import pipeline
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.ai.render import load_shown, render
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType
from makhzan_schemas.models import AiDecision, AiModelVersion, AiScore, Listing, Supplier
from makhzan_schemas.overrides import pair
from sqlalchemy import func, select

from worker import ai_import
from worker.ai_import import ImportRefused, import_scores, verify

T0 = datetime(2026, 1, 1, tzinfo=UTC)
KEV, PPLX = pipeline("match").stages


async def _shop(slug: str) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    async with SessionLocal() as session:
        session.add(supplier)
        await session.commit()
    return supplier


async def _listing(shop: Supplier, title: str) -> uuid.UUID:
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=shop.id,
        source=shop.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        title_en=title,
        price=100,
        images=[],
        attributes={},
        first_seen_at=T0,
        status=ListingStatus.ACTIVE,
        domain="electronics",
    )
    async with SessionLocal() as session:
        session.add(listing)
        await session.commit()
    return listing.id


async def _lines(x, y, stage, ab: float, ba: float, **override) -> list[dict]:
    """Both orders of one stage, as the backlog driver writes them."""
    a, b = pair(x, y)
    async with SessionLocal() as session:
        shown = await load_shown(session, (a, b))
    rendered = render(stage, shown[a], shown[b])
    model = MODELS[stage.model]
    out = []
    for order, p in (("ab", ab), ("ba", ba)):
        line = {
            "listing_a": str(a),
            "listing_b": str(b),
            "order": order,
            "shown_as_a": str(a if order == "ab" else b),
            "p": p,
            "model": stage.model,
            "model_version": model.model_version,
            "weights_revision": model.weights_revision,
            "prompt_variant": stage.prompt,
            "prompt_version": stage.prompt_version,
            "request_sha256": rendered.sha256[order].hex(),
            "content_sha256_a": shown[a].content_sha256.hex(),
            "content_sha256_b": shown[b].content_sha256.hex(),
            "hash_version": 2,
            "extra": {"usage": {"input_tokens": 10}},
            "seconds": 0.1,
            "device": "cuda",
            "dtype": "bf16",
            "threads": None,
            "scored_at": "2026-01-02T00:00:00+00:00",
            "source": "test",
        }
        line.update(override)
        out.append(line)
    return out


def _write(directory, kev: list[dict], pplx: list[dict]):
    for name, rows in (("kev", kev), ("pplx", pplx)):
        with (directory / f"scores-{name}.jsonl").open("w") as handle:
            handle.writelines(json.dumps(r) + "\n" for r in rows)
    return directory


def _quiet(*_):
    pass


async def _count(model) -> int:
    async with SessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def _scenario(tmp_path):
    """Three pairs: one same, one not same by Kev, one not same by pplx."""
    shops = [await _shop(f"shop-{c}") for c in "abc"]
    one = await _listing(shops[0], "Example sensor module XY-1")
    two = await _listing(shops[1], "XY-1 example sensor module")
    three = await _listing(shops[2], "Example relay board RB-2")
    kev = (
        await _lines(one, two, KEV, 0.9, 0.85)
        + await _lines(one, three, KEV, 0.01, 0.3)
        + await _lines(two, three, KEV, 0.95, 0.9)
    )
    pplx = await _lines(one, two, PPLX, 0.99, 0.96) + await _lines(two, three, PPLX, 0.97, 0.5)
    return _write(tmp_path, kev, pplx), (one, two, three)


async def test_import_stores_scores_and_decides_through_the_pipeline(tmp_path):
    directory, (one, two, three) = await _scenario(tmp_path)
    report = await import_scores(directory, log=_quiet)
    assert report.inserted == 10 and report.already_stored == 0
    assert dict(report.decided) == {"same": 1, "not_same": 2}
    assert dict(report.decided_by) == {"kev": 1, "pplx": 2}
    async with SessionLocal() as session:
        judges = (await session.scalars(select(AiModelVersion))).all()
        assert {(j.model, j.model_version, j.prompt_version) for j in judges} == {
            (s.model, s.model_version, s.prompt_version) for s in (KEV, PPLX)
        }
        decisions = {
            (d.listing_a, d.listing_b): d for d in (await session.scalars(select(AiDecision)))
        }
    same = decisions[pair(one, two)]
    assert (same.outcome, same.decided_by, same.state, same.policy_version) == (
        "same",
        "pplx",
        "standing",
        "p1",
    )
    assert same.scores["kev"]["min"] == 0.85 and same.scores["pplx"]["min"] == 0.96
    # The evidence carries both orders' request hashes, as the broker writes them.
    assert set(same.scores["pplx"]["requests"]) == {"ab", "ba"}
    no = decisions[pair(one, three)]
    assert (no.outcome, no.decided_by, no.scores["kev"]["min"]) == ("not_same", "kev", 0.01)
    assert decisions[pair(two, three)].outcome == "not_same"
    assert (await verify(directory)).mismatches == []


async def test_a_second_run_changes_nothing(tmp_path):
    directory, _ = await _scenario(tmp_path)
    await import_scores(directory, log=_quiet)
    async with SessionLocal() as session:
        before = sorted((d.id, d.outcome) for d in await session.scalars(select(AiDecision)))
    again = await import_scores(directory, log=_quiet)
    assert again.inserted == 0 and again.already_stored == 10
    assert dict(again.previous) == {"same_outcome": 3}
    async with SessionLocal() as session:
        after = sorted((d.id, d.outcome) for d in await session.scalars(select(AiDecision)))
    assert after == before
    assert await _count(AiScore) == 10


async def test_a_dry_run_writes_nothing(tmp_path):
    directory, _ = await _scenario(tmp_path)
    report = await import_scores(directory, dry_run=True, log=_quiet)
    assert report.inserted == 10 and dict(report.decided) == {"same": 1, "not_same": 2}
    assert await _count(AiScore) == 0
    assert await _count(AiDecision) == 0
    assert await _count(AiModelVersion) == 0


async def test_a_listing_whose_text_changed_is_skipped_and_counted(tmp_path):
    directory, (one, two, _) = await _scenario(tmp_path)
    async with SessionLocal() as session:
        listing = await session.get(Listing, one)
        listing.title_en = "Example sensor module XY-1 v2"
        await session.commit()
    report = await import_scores(directory, log=_quiet)
    # Every line of the two pairs that show `one` is stale: 4 Kev, 2 pplx.
    assert dict(report.stale) == {"kev": 4, "pplx": 2}
    assert report.inserted == 4
    assert report.unsettled == 2
    assert dict(report.decided) == {"not_same": 1}
    async with SessionLocal() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AiDecision)
                .where(
                    AiDecision.listing_a.in_(pair(one, two)),
                    AiDecision.listing_b.in_(pair(one, two)),
                )
            )
            == 0
        )
    assert (await verify(directory)).mismatches == []


async def test_a_request_two_lines_share_is_stored_once(tmp_path):
    directory, _ = await _scenario(tmp_path)
    kev = (directory / "scores-kev.jsonl").read_text().splitlines()
    (directory / "scores-kev.jsonl").write_text("\n".join(kev + kev[:1]) + "\n")
    report = await import_scores(directory, log=_quiet)
    assert report.repeated_in_files == 1 and report.inserted == 10


@pytest.mark.parametrize(
    "override",
    [
        {"model_version": "kev-4b@000000000000+kev-0000000+T1.0"},
        {"prompt_version": "K2-150@00000000"},
        {"hash_version": 1},
        {"model": "other"},
        {"prompt_variant": "K1-full"},
        {"p": 1.5},
    ],
)
async def test_a_line_of_another_judge_refuses_the_whole_import(tmp_path, override):
    shops = [await _shop(f"shop-{c}") for c in "ab"]
    one = await _listing(shops[0], "Example part P-1")
    two = await _listing(shops[1], "Example part P-1 module")
    _write(tmp_path, await _lines(one, two, KEV, 0.9, 0.9, **override), [])
    with pytest.raises(ImportRefused):
        await import_scores(tmp_path, log=_quiet)
    assert await _count(AiScore) == 0


async def test_the_import_refuses_another_policy(tmp_path):
    directory, _ = await _scenario(tmp_path)
    with pytest.raises(ImportRefused):
        await import_scores(directory, policy="p0", log=_quiet)


async def test_verify_reports_a_decision_that_is_missing(tmp_path):
    directory, (one, two, _) = await _scenario(tmp_path)
    await import_scores(directory, log=_quiet)
    async with SessionLocal() as session:
        row = await session.scalar(
            select(AiDecision)
            .where(AiDecision.listing_a == pair(one, two)[0])
            .where(AiDecision.listing_b == pair(one, two)[1])
        )
        await session.delete(row)
        await session.commit()
    report = await verify(directory)
    assert len(report.mismatches) == 1 and "no standing decision" in report.mismatches[0]


async def test_the_cli_runs_the_import(tmp_path, capsys):
    directory, _ = await _scenario(tmp_path)
    args = ai_import._parser().parse_args([str(directory), "--dry-run"])
    assert await ai_import.main(args) == 0
    assert json.loads(capsys.readouterr().out.split("rolled back\n", 1)[1])["decisions"] == {
        "same": 1,
        "not_same": 2,
    }
