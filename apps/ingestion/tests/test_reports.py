"""Visitors' reports: what the worker erases, when, and the review command.

The privacy page promises an email is erased 90 days after its report is
closed and an address's hash 24 hours after the report was sent. The worker's
hourly cron keeps that promise (`worker.main.purge_reports`). Reviewing happens
on the server, through `python -m worker.reports` (`./makhzan reports`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import Report
from makhzan_schemas.reports import purge_personal_data
from sqlalchemy import select

from worker import main
from worker import reports as cli

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)

SNAPSHOT = {
    "taken_at": NOW.isoformat(),
    "product": {
        "id": "6f1c2a9e-3b7d-4c51-9a0e-2d8f61b4c7a3",
        "title": "TB6600 Stepper Motor Driver 4A",
        "category": "electronics:stepper-drivers",
        "category_name": "Stepper drivers",
        "listings": [
            {
                "id": "0b6e41d2-7c1a-4f0e-b5a3-91d2c4e8a601",
                "title": "TB6600 Stepper Motor Driver 4A 9-42V",
                "shop": {"slug": "delta-components", "name": "Delta Components"},
                "price": "425.00",
                "currency": "EGP",
                "stock": "in_stock",
                "ticked": False,
            },
            {
                "id": "50b396c7-c16f-4e53-8af8-e6c7193dfb06",
                "title": "TB6600 4A Stepper Driver Module",
                "shop": {"slug": "bazaar-hub", "name": "Bazaar Hub"},
                "price": "504.00",
                "currency": "EGP",
                "stock": "out_of_stock",
                "ticked": True,
            },
        ],
    },
    "other_product": None,
}


async def _report(**fields) -> int:
    values = {
        "product_id": uuid.uuid4(),
        "reason": "offers_not_same",
        "snapshot": SNAPSHOT,
        "created_at": NOW,
        **fields,
    }
    async with SessionLocal() as session:
        report = Report(**values)
        session.add(report)
        await session.commit()
        return report.id


async def _get(report_id: int) -> Report:
    async with SessionLocal() as session:
        return await session.get(Report, report_id)


@pytest.mark.parametrize(
    "status, closed_days_ago, kept",
    [
        ("accepted", 91, False),
        ("rejected", 90, False),
        ("accepted", 89, True),
        # Never closed: kept, however old, so the reply can still be sent.
        ("new", None, True),
    ],
)
async def test_an_email_goes_90_days_after_its_report_is_closed(status, closed_days_ago, kept):
    reviewed = None if closed_days_ago is None else NOW - timedelta(days=closed_days_ago)
    report_id = await _report(
        email="buyer@example.com",
        status=status,
        reviewed_at=reviewed,
        created_at=NOW - timedelta(days=200),
    )
    async with SessionLocal() as session:
        await purge_personal_data(session, now=NOW)
    report = await _get(report_id)
    assert (report.email == "buyer@example.com") is kept
    # The report itself stays.
    assert report.reason == "offers_not_same" and report.snapshot == SNAPSHOT


@pytest.mark.parametrize("hours_ago, kept", [(25, False), (24, False), (23, True)])
async def test_an_address_hash_goes_after_24_hours(hours_ago, kept):
    report_id = await _report(ip_hash="ab" * 32, created_at=NOW - timedelta(hours=hours_ago))
    async with SessionLocal() as session:
        counts = await purge_personal_data(session, now=NOW)
    assert ((await _get(report_id)).ip_hash is not None) is kept
    assert counts["ip_hashes"] == (0 if kept else 1)


async def test_purging_twice_changes_nothing_more():
    await _report(ip_hash="ab" * 32, created_at=NOW - timedelta(days=2))
    async with SessionLocal() as session:
        assert (await purge_personal_data(session, now=NOW))["ip_hashes"] == 1
        assert await purge_personal_data(session, now=NOW) == {"emails": 0, "ip_hashes": 0}


async def test_the_cron_job_purges(monkeypatch):
    report_id = await _report(ip_hash="ab" * 32, created_at=datetime.now(UTC) - timedelta(days=2))
    assert await main.purge_reports({}) == {"emails": 0, "ip_hashes": 1}
    assert (await _get(report_id)).ip_hash is None


def test_the_purge_runs_every_hour_whatever_the_crawl_flag():
    [job] = [j for j in main.WorkerSettings.cron_jobs if j.coroutine is main.purge_reports]
    # No hour given: every hour. Not gated on CRAWL_ENABLED (refresh_all is).
    assert job.hour is None
    assert job.minute == 17
    assert job.run_at_startup


async def test_review_sets_the_status_and_when(capsys):
    a = await _report()
    b = await _report(reason="wrong_category")
    assert await cli.run(["accept", f"R-{a}"]) == 0
    assert await cli.run(["reject", str(b)]) == 0
    ra, rb = await _get(a), await _get(b)
    assert (ra.status, rb.status) == ("accepted", "rejected")
    assert ra.reviewed_at is not None and rb.reviewed_at is not None
    assert f"R-{a} accepted." in capsys.readouterr().out


async def test_reviewing_a_missing_report_says_so(capsys):
    assert await cli.run(["accept", "999999"]) == 1
    assert "No report R-999999" in capsys.readouterr().err


async def test_the_list_shows_new_reports_with_what_the_page_showed(capsys):
    shown = await _report(email="buyer@example.com", description="Bazaar Hub's is a module.")
    closed = await _report(status="accepted", reviewed_at=NOW)
    assert await cli.run([]) == 0
    out = capsys.readouterr().out
    assert f"R-{shown}" in out and f"R-{closed}" not in out
    assert "These offers aren't the same product" in out
    assert "[x] TB6600 4A Stepper Driver Module | Bazaar Hub | EGP 504.00 | out_of_stock" in out
    assert "[ ] TB6600 Stepper Motor Driver 4A 9-42V | Delta Components" in out
    assert "Bazaar Hub's is a module." in out
    # The address to reply to is only in `show`, so a pasted list carries none.
    assert "buyer@example.com" not in out
    assert "Reply wanted" in out


async def test_show_prints_one_report_in_full(capsys):
    report_id = await _report(email="buyer@example.com", field=None)
    assert await cli.run(["show", f"r-{report_id}"]) == 0
    assert "Reply to: buyer@example.com" in capsys.readouterr().out


async def test_an_empty_queue_says_so(capsys):
    assert await cli.run(["list"]) == 0
    assert "No new reports." in capsys.readouterr().out


async def test_purge_by_hand(capsys):
    await _report(ip_hash="ab" * 32, created_at=datetime.now(UTC) - timedelta(days=2))
    assert await cli.run(["purge"]) == 0
    assert "Erased 0 emails and 1 address hashes." in capsys.readouterr().out
    async with SessionLocal() as session:
        assert (await session.scalars(select(Report.ip_hash))).all() == [None]


def test_a_bad_id_is_refused():
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["accept", "R-abc"])
