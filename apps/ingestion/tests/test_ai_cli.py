"""`./makhzan ai ...`: workers, the admin token, the mode, redecide, revoke, status.

The shops and listings are fictional.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from makhzan_schemas.ai import broker as core
from makhzan_schemas.ai import policy
from makhzan_schemas.ai.mode import ai_mode
from makhzan_schemas.ai.triggers import PairRequest, enqueue
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import AiDecision, AiJob, AiWorker, Listing, Supplier
from sqlalchemy import select

from worker import ai


async def _two_listings() -> tuple[uuid.UUID, uuid.UUID]:
    ids = []
    async with SessionLocal() as session:
        for slug, title in (("shop-a", "example relay 5v"), ("shop-b", "example relay 5v board")):
            slug = f"{slug}-{uuid.uuid4().hex[:8]}"
            shop = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
            listing = Listing(
                id=uuid.uuid4(),
                supplier_id=shop.id,
                source=slug,
                source_type=SourceType.SCRAPED,
                external_id=str(uuid.uuid4()),
                domain="electronics",
                title_en=title,
                price=Decimal("20"),
                images=[],
                attributes={},
            )
            session.add_all([shop, listing])
            ids.append(listing.id)
        await session.commit()
    return tuple(sorted(ids))


async def _decision(outcome: str, kev: float, pplx: float | None) -> int:
    a, b = await _two_listings()
    scores = {"kev": {"model": "kev", "model_version_id": 1, "ab": kev, "ba": kev, "min": kev}}
    if pplx is not None:
        scores["pplx"] = {
            "model": "pplx",
            "model_version_id": 2,
            "ab": pplx,
            "ba": pplx,
            "min": pplx,
        }
    row = AiDecision(
        pipeline="match",
        listing_a=a,
        listing_b=b,
        outcome=outcome,
        decided_by="pplx" if pplx is not None else "kev",
        scores=scores,
        policy_version="p1",
        content_sha256_a=b"\0" * 32,
        content_sha256_b=b"\0" * 32,
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
    return row.id


async def test_a_worker_token_is_printed_once_and_stored_as_its_sha256(capsys):
    assert await ai.run(["worker", "add", "cpu-kev", "--models", "kev"]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    async with SessionLocal() as session:
        worker = await session.scalar(select(AiWorker))
    assert worker.models == ["kev"]
    assert worker.token_sha256 == hashlib.sha256(token.encode()).digest()
    assert token.encode() not in worker.token_sha256
    assert await ai.run(["worker", "add", "cpu-kev", "--models", "kev"]) == 1
    assert await ai.run(["worker", "add", "x", "--models", "nope"]) == 1
    assert await ai.run(["worker", "list"]) == 0
    assert "cpu-kev" in capsys.readouterr().out
    assert await ai.run(["worker", "revoke", "cpu-kev"]) == 0
    async with SessionLocal() as session:
        with pytest.raises(core.BrokerError) as refused:
            await core.authenticate(session, token, await core.db_now(session))
    assert refused.value.status == 401


async def test_the_admin_token_comes_with_the_hash_the_broker_keeps(capsys):
    assert await ai.run(["admin-token"]) == 0
    lines = dict(line.split("=", 1) for line in capsys.readouterr().out.split())
    assert hashlib.sha256(lines["token"].encode()).hexdigest() == lines["sha256"]


async def test_the_mode_is_off_until_set_live(capsys):
    assert await ai.run(["mode"]) == 0
    assert "off" in capsys.readouterr().out
    assert await ai.run(["mode", "live"]) == 0
    async with SessionLocal() as session:
        assert await ai_mode(session) == "live"
    with pytest.raises(SystemExit):
        await ai.run(["mode", "shadow"])  # there is no shadow mode (P4)


async def test_redecide_dry_run_recomputes_from_stored_scores_and_writes_nothing(
    capsys, monkeypatch
):
    await _decision("same", 0.9, 0.97)
    await _decision("not_same", 0.5, None)
    monkeypatch.setitem(policy.POLICIES, "p-strict", {"kev": 0.80, "pplx": 0.99})
    monkeypatch.setitem(policy.POLICIES, "p-loose", {"kev": 0.40, "pplx": 0.95})
    assert await ai.run(["redecide", "--dry-run", "--policy", "p-strict"]) == 0
    out = capsys.readouterr().out
    assert "same -> not_same" in out and "unchanged not_same" in out
    assert await ai.run(["redecide", "--dry-run", "--policy", "p-loose"]) == 0
    assert "needs pplx scores first" in capsys.readouterr().out
    async with SessionLocal() as session:
        assert sorted(d.outcome for d in await session.scalars(select(AiDecision))) == [
            "not_same",
            "same",
        ]
    with pytest.raises(SystemExit):
        await ai.run(["redecide"])  # only a dry run exists


async def test_revoke_withdraws_a_standing_decision_with_a_note(capsys):
    decision_id = await _decision("same", 0.9, 0.97)
    assert (
        await ai.run(
            ["revoke", str(decision_id), "--note", "a bracket, not the sensor", "--by", "tester"]
        )
        == 0
    )
    async with SessionLocal() as session:
        row = await session.get(AiDecision, decision_id)
    assert (row.state, row.revoked_by, row.revoke_note) == (
        "revoked",
        "tester",
        "a bracket, not the sensor",
    )
    assert await ai.run(["revoke", str(decision_id), "--note", "again"]) == 1


async def test_status_reports_the_queue_and_decisions(capsys):
    a, b = await _two_listings()
    async with SessionLocal() as session:
        await enqueue(session, [PairRequest(a, b, "match", 60, "candidates")])
        await session.commit()
    await _decision("same", 0.9, 0.97)
    assert await ai.run(["status"]) == 0
    out = capsys.readouterr().out
    assert "mode: off" in out
    assert "queue match.kev" in out and "1 queued (2 requests" in out
    assert "standing: same 1" in out
    assert await ai.run(["status", "--json"]) == 0
    assert '"match.kev"' in capsys.readouterr().out


async def test_a_dead_job_is_retried_by_hand(capsys):
    a, b = await _two_listings()
    async with SessionLocal() as session:
        await enqueue(session, [PairRequest(a, b, "match", 60, "candidates")])
        job = await session.scalar(select(AiJob))
        job.status, job.attempts = "dead", 3
        await session.commit()
    assert await ai.run(["jobs", "list", "--dead"]) == 0
    assert f"#{job.id}" in capsys.readouterr().out
    assert await ai.run(["jobs", "retry", str(job.id)]) == 0
    async with SessionLocal() as session:
        again = await session.get(AiJob, job.id)
    assert (again.status, again.attempts) == ("queued", 0)


async def test_a_flag_is_dismissed_with_a_note_and_its_resolved_time(capsys):
    from makhzan_schemas.models import AiFlag

    async with SessionLocal() as session:
        flag = AiFlag(kind="version_drift", subject="cpu-kev/kev", detail={})
        session.add(flag)
        await session.commit()
    assert await ai.run(["flags", "list"]) == 0
    assert f"#{flag.id} version_drift open cpu-kev/kev" in capsys.readouterr().out
    assert (
        await ai.run(
            ["flags", "dismiss", str(flag.id), "--note", "worker updated", "--by", "tester"]
        )
        == 0
    )
    async with SessionLocal() as session:
        row = await session.get(AiFlag, flag.id)
    assert (row.status, row.resolved_by, row.note) == ("dismissed", "tester", "worker updated")
    assert row.resolved_at is not None
    assert await ai.run(["flags", "dismiss", str(flag.id), "--note", "again"]) == 1


def _status_fixture(**decisions) -> dict:
    """The smallest `collect()` result `format_text` prints."""
    return {
        "at": "2026-11-19T12:00:00+00:00",
        "mode": "live",
        "policy": {"name": "p1", "thresholds": {"kev": 0.5}},
        "judges": {},
        "queue": {},
        "throughput": {},
        "nights": {},
        "workers": [],
        "flags": {},
        "decisions": decisions,
        "rescore_due": {"due": 0, "open_job": 0, "dead_job": 0, "no_job": 0},
        "audit": {"scored": 0, "below_0.8": 0, "below_0.05": 0},
    }


def test_a_worker_seen_after_the_status_snapshot_is_not_seen_in_the_future():
    """`now` is the status transaction's start; a worker that calls the broker
    while status reads stamps `last_seen_at` a moment later. That once printed
    "last seen -1h ago"."""
    from makhzan_schemas.ai.status import _age, format_text

    now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    assert _age((now + timedelta(seconds=3)).isoformat(), now) == "0h"
    assert _age((now - timedelta(minutes=10)).isoformat(), now) == "0h"
    assert _age((now - timedelta(hours=5, minutes=1)).isoformat(), now) == "5h"
    assert _age((now - timedelta(days=2, hours=3)).isoformat(), now) == "2d 3h"
    data = _status_fixture()
    data["workers"] = [
        {
            "name": "cpu-1",
            "models": ["kev"],
            "last_seen_at": "2026-11-19T12:00:02.5+00:00",
            "revoked": False,
            "device": "cpu",
            "dtype": None,
            "threads": None,
            "window": None,
        }
    ]
    out = format_text(data)
    assert "last seen 0h ago" in out and "-1h" not in out
