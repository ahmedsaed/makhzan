"""Importing a locally scored backlog (`worker.ai_import`).

The shops and listings here are fictional.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from makhzan_schemas import overrides as rulings
from makhzan_schemas.ai import flow
from makhzan_schemas.ai.pipelines import pipeline
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.ai.render import load_shown, render
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType
from makhzan_schemas.models import (
    AiDecision,
    AiListingState,
    AiModelVersion,
    AiScore,
    GroupingOverride,
    Listing,
    Supplier,
)
from makhzan_schemas.overrides import pair
from sqlalchemy import func, select, update

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


async def _lines(x, y, stage, ab: float, ba: float, *, drop=(), **override) -> list[dict]:
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
        for key in drop:
            line.pop(key, None)
        out.append(line)
    return out


def _write(directory, kev: list, pplx: list):
    for name, rows in (("kev", kev), ("pplx", pplx)):
        with (directory / f"scores-{name}.jsonl").open("w") as handle:
            handle.writelines((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows)
    return directory


def _quiet(*_):
    pass


async def _count(model, *where) -> int:
    async with SessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where))


def _of_pair(x, y):
    a, b = pair(x, y)
    return (AiDecision.listing_a == a, AiDecision.listing_b == b)


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
    assert dict(report.planned) == dict(report.written) == {"same": 1, "not_same": 2}
    assert dict(report.written_by) == {"kev": 1, "pplx": 2}
    assert report.recommendation is None
    async with SessionLocal() as session:
        judges = (await session.scalars(select(AiModelVersion))).all()
        assert {
            (j.model, j.model_version, j.prompt_version, j.weights_revision) for j in judges
        } == {
            (s.model, s.model_version, s.prompt_version, MODELS[s.model].weights_revision)
            for s in (KEV, PPLX)
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
    checked = await verify(directory)
    assert checked.mismatches == [] and dict(checked.written) == {"same": 1, "not_same": 2}


async def test_one_pair_a_chunk_decides_the_same(tmp_path):
    directory, _ = await _scenario(tmp_path)
    report = await import_scores(directory, chunk=1, log=_quiet)
    assert dict(report.written) == {"same": 1, "not_same": 2}
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
    assert report.inserted == 10 and dict(report.planned) == {"same": 1, "not_same": 2}
    assert not report.written
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
    assert report.stale_pairs == 2 and report.stale_listings == [str(one)]
    # No trigger state at all: its first run records the new text and offers nothing.
    assert report.stranded_listings == 1
    assert "./makhzan ai backlog" in report.recommendation
    assert report.inserted == 4
    assert report.unsettled == 2 and not report.owes
    assert dict(report.written) == {"not_same": 1}
    assert await _count(AiDecision, *_of_pair(one, two)) == 0
    assert (await verify(directory)).mismatches == []


async def test_a_listing_that_is_gone_is_skipped_and_counted(tmp_path):
    directory, (_, _, three) = await _scenario(tmp_path)
    async with SessionLocal() as session:
        await session.delete(await session.get(Listing, three))
        await session.commit()
    report = await import_scores(directory, log=_quiet)
    # one-three and two-three by Kev, two-three by pplx.
    assert report.missing_listing == 6
    assert report.stale_listings == [str(three)]
    assert dict(report.written) == {"same": 1}
    assert (await verify(directory)).mismatches == []


async def test_a_change_no_judge_sees_keeps_the_scores(tmp_path):
    directory, (one, two, _) = await _scenario(tmp_path)
    async with SessionLocal() as session:
        listing = await session.get(Listing, one)
        listing.title_ar = "وحدة استشعار مثال"  # under an English title: no prompt shows it
        await session.commit()
    report = await import_scores(directory, log=_quiet)
    assert report.content_hash_differs == 6 and not report.stale
    assert dict(report.written) == {"same": 1, "not_same": 2}
    async with SessionLocal() as session:
        decision = await session.scalar(select(AiDecision).where(*_of_pair(one, two)))
        shown = await load_shown(session, (one,))
    # The decision carries the listing's current content hash, as write_decision does.
    a, _ = pair(one, two)
    current = decision.content_sha256_a if a == one else decision.content_sha256_b
    assert current == shown[one].content_sha256


async def test_a_request_two_lines_share_is_stored_once(tmp_path):
    directory, _ = await _scenario(tmp_path)
    kev = (directory / "scores-kev.jsonl").read_text().splitlines()
    (directory / "scores-kev.jsonl").write_text("\n".join(kev + kev[:1]) + "\n")
    report = await import_scores(directory, log=_quiet)
    assert report.repeated_in_files == 1 and report.inserted == 10


async def test_a_score_already_stored_wins_and_is_counted(tmp_path):
    directory, (one, two, _) = await _scenario(tmp_path)
    first = json.loads((directory / "scores-pplx.jsonl").read_text().splitlines()[0])
    async with SessionLocal() as session:
        judge = (await ai_import.judges_for(session))["pplx"]
        session.add(
            AiScore(
                model_version_id=judge,
                listing_a=uuid.UUID(first["listing_a"]),
                listing_b=uuid.UUID(first["listing_b"]),
                reading_order=first["order"],
                request_sha256=bytes.fromhex(first["request_sha256"]),
                content_sha256_a=bytes.fromhex(first["content_sha256_a"]),
                content_sha256_b=bytes.fromhex(first["content_sha256_b"]),
                p=0.98,  # a broker result, before the import: the file says 0.99
            )
        )
        await session.commit()
    report = await import_scores(directory, log=_quiet)
    assert report.already_stored == 1 and report.already_stored_p_differs == 1
    assert report.inserted == 9
    checked = await verify(directory)
    assert checked.mismatches == [] and checked.held_before_import_p_differs == 1


async def test_verify_catches_a_stored_score_that_differs_from_the_file(tmp_path):
    directory, _ = await _scenario(tmp_path)
    await import_scores(directory, log=_quiet)
    async with SessionLocal() as session:
        target = await session.scalar(select(AiScore.id).order_by(AiScore.id).limit(1))
        await session.execute(update(AiScore).where(AiScore.id == target).values(p=0.5))
        await session.commit()
    report = await verify(directory)
    assert any("stored p 0.5" in m for m in report.mismatches)


async def test_a_revoked_pair_is_blocked_and_verify_accepts_it(tmp_path):
    directory, (one, two, _) = await _scenario(tmp_path)
    await import_scores(directory, log=_quiet)
    async with SessionLocal() as session:
        decision = await session.scalar(select(AiDecision).where(*_of_pair(one, two)))
        _, _, refused = await flow.revoke_decision(session, decision.id, by="test", note="wrong")
        assert refused is None
        await session.commit()
    again = await import_scores(directory, log=_quiet)
    assert again.blocked_by_revocation == 1 and again.revoked_pairs == 1
    assert dict(again.written) == {"not_same": 2}
    assert await _count(AiDecision, *_of_pair(one, two), AiDecision.state == "standing") == 0
    checked = await verify(directory)
    assert checked.mismatches == [] and checked.blocked_by_revocation == 1


async def test_a_pair_a_person_ruled_on_is_not_decided(tmp_path):
    directory, (one, two, _) = await _scenario(tmp_path)
    a, b = pair(one, two)
    async with SessionLocal() as session:
        session.add(
            GroupingOverride(
                listing_a=a,
                listing_b=b,
                kind=rulings.NEVER,
                source="manual",
                note="test",
                created_by="test",
            )
        )
        await session.commit()
    report = await import_scores(directory, log=_quiet)
    assert report.ruled == 1 and dict(report.written) == {"not_same": 2}
    assert report.inserted == 10  # the scores are kept as evidence
    assert await _count(AiDecision, *_of_pair(one, two)) == 0
    checked = await verify(directory)
    assert checked.mismatches == [] and checked.ruled == 1


@pytest.mark.parametrize(
    "change",
    [
        {"model_version": "kev-4b@000000000000+kev-0000000+T1.0"},
        {"weights_revision": "0" * 40},
        {"drop": ("weights_revision",)},
        {"drop": ("scored_at",)},
        {"prompt_version": "K2-150@00000000"},
        {"hash_version": 1},
        {"model": "other"},
        {"prompt_variant": "K1-full"},
        {"p": 1.5},
        {"p": True},
        {"listing_a": "not-a-uuid"},
        {"shown_as_a": "nope"},
        {"scored_at": "yesterday"},
        {"scored_at": "2026-01-02T00:00:00"},
        {"request_sha256": "abc"},
    ],
)
async def test_a_bad_line_refuses_the_whole_import(tmp_path, change):
    shops = [await _shop(f"shop-{c}") for c in "ab"]
    one = await _listing(shops[0], "Example part P-1")
    two = await _listing(shops[1], "Example part P-1 module")
    _write(tmp_path, await _lines(one, two, KEV, 0.9, 0.9, **change), [])
    with pytest.raises(ImportRefused, match=r"scores-kev\.jsonl:1"):
        await import_scores(tmp_path, log=_quiet)
    assert await _count(AiScore) == 0


@pytest.mark.parametrize("text", ["[1, 2]", '"a string"', "{not json"])
async def test_a_line_that_is_not_a_json_object_is_refused_with_its_number(tmp_path, text):
    directory, _ = await _scenario(tmp_path)
    kev = (directory / "scores-kev.jsonl").read_text().splitlines()
    (directory / "scores-kev.jsonl").write_text("\n".join([kev[0], text, *kev[1:]]) + "\n")
    with pytest.raises(ImportRefused, match=r"scores-kev\.jsonl:2"):
        await import_scores(directory, log=_quiet)


async def test_an_empty_folder_is_refused(tmp_path):
    with pytest.raises(ImportRefused, match="no scores"):
        await import_scores(tmp_path, log=_quiet)


async def test_the_import_refuses_another_policy(tmp_path):
    directory, _ = await _scenario(tmp_path)
    with pytest.raises(ImportRefused):
        await import_scores(directory, policy="p0", log=_quiet)


async def _record_state(listing_id, recorded: bytes) -> None:
    async with SessionLocal() as session:
        session.add(
            AiListingState(
                listing_id=listing_id,
                content_sha256=recorded,
                candidates_sha256=recorded,
                candidates_at=T0,
            )
        )
        await session.commit()


async def test_a_stale_listing_is_stranded_once_the_trigger_recorded_its_text(tmp_path):
    directory, (one, _, three) = await _scenario(tmp_path)
    async with SessionLocal() as session:
        before = (await load_shown(session, (one,)))[one].content_sha256
        listing = await session.get(Listing, one)
        listing.title_en = "Example sensor module XY-1 v2"
        await session.commit()
        changed = (await load_shown(session, (one,)))[one].content_sha256
    await _record_state(three, b"\1" * 32)  # some state exists: not a first run
    await _record_state(one, changed)
    report = await import_scores(directory, dry_run=True, log=_quiet)
    assert report.stale_listings == [str(one)] and report.stranded_listings == 1
    # Recorded at its old text instead, the trigger offers it again: not stranded.
    async with SessionLocal() as session:
        state = await session.get(AiListingState, one)
        state.candidates_sha256 = before
        await session.commit()
    report = await import_scores(directory, dry_run=True, log=_quiet)
    assert report.stranded_listings == 0
    assert "./makhzan ai backlog" in report.recommendation
    async with SessionLocal() as session:  # read-only
        assert (await session.get(AiListingState, one)).candidates_sha256 == before


async def test_a_pair_owing_a_stage_is_counted_by_stage_and_recommended(tmp_path):
    shops = [await _shop(f"shop-{c}") for c in "ab"]
    one = await _listing(shops[0], "Example part P-1")
    two = await _listing(shops[1], "Example part P-1 module")
    _write(tmp_path, await _lines(one, two, KEV, 0.9, 0.9), [])  # Kev passes, no pplx line
    report = await import_scores(tmp_path, log=_quiet)
    assert dict(report.owes) == {"pplx": 1} and report.unsettled == 0
    assert not report.stale_listings and not report.written
    assert "1 pair(s) owing the pplx stage" in report.recommendation
    assert "./makhzan ai backlog" in report.recommendation
    checked = await verify(tmp_path)
    assert checked.mismatches == [] and dict(checked.owes) == {"pplx": 1}


async def test_verify_reports_a_decision_that_is_missing(tmp_path):
    directory, (one, two, _) = await _scenario(tmp_path)
    await import_scores(directory, log=_quiet)
    async with SessionLocal() as session:
        row = await session.scalar(select(AiDecision).where(*_of_pair(one, two)))
        await session.delete(row)
        await session.commit()
    report = await verify(directory)
    assert len(report.mismatches) == 1 and "no standing decision" in report.mismatches[0]


async def test_the_cli_runs_the_import(tmp_path, capsys):
    directory, _ = await _scenario(tmp_path)
    args = ai_import._parser().parse_args([str(directory), "--dry-run"])
    assert await ai_import.main(args) == 0
    out = capsys.readouterr().out
    assert json.loads(out.split("rolled back\n", 1)[1])["decisions_planned"] == {
        "same": 1,
        "not_same": 2,
    }
