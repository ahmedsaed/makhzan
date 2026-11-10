"""`make status` CRAWLER IDENTITY: each source's configured identity, and what its last run sent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from makhzan_schemas import botauth
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import IngestionRun, Source
from test_status_details import _status


def _source(source_id: str, **config) -> Source:
    return Source(
        source_id=source_id,
        adapter="fixture",
        enabled=True,
        supplier={"slug": source_id, "name": source_id},
        config=config,
    )


def _run(source: str, identity: dict, minutes_ago: int) -> IngestionRun:
    return IngestionRun(
        source=source,
        source_type=SourceType.SCRAPED,
        started_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        stats={"identity": identity},
    )


async def test_each_source_shows_its_identity_and_whether_it_was_signed(capsys, monkeypatch):
    monkeypatch.delenv(botauth.KEY_ENV, raising=False)
    async with SessionLocal() as session:
        session.add_all(
            [
                _source("browser-shop"),
                _source("bot-shop", identity="makhzanbot"),
                _source("unsigned-shop", identity="makhzanbot"),
                _run("browser-shop", {"name": "browser", "signed": False}, 5),
                # The latest run wins.
                _run("bot-shop", {"name": "browser", "signed": False}, 60),
                _run("bot-shop", {"name": "makhzanbot", "signed": True, "keyid": "abcdef" * 7}, 5),
                _run("unsigned-shop", {"name": "makhzanbot", "signed": False}, 5),
            ]
        )
        await session.commit()
        await _status().crawler_identity(session, None)

    lines = {
        line.split()[0]: line for line in capsys.readouterr().out.splitlines() if "-shop" in line
    }
    assert (
        "browser" in lines["browser-shop"]
        and "last run: browser, unsigned" in lines["browser-shop"]
    )
    assert "unverifiable" not in lines["browser-shop"]
    assert "last run: makhzanbot, signed (keyid abcdefabcdef…)" in lines["bot-shop"]
    assert "unverifiable: no key on the worker" in lines["unsigned-shop"]


def _robots_run(source: str, robots: dict, stopped: str | None = None) -> IngestionRun:
    stats: dict = {"robots": robots}
    if stopped:
        stats["stopped"] = stopped
    return IngestionRun(
        source=source,
        source_type=SourceType.SCRAPED,
        started_at=datetime.now(UTC),
        stats=stats,
    )


async def test_robots_txt_outcomes_are_shown_and_old_copies_flagged(capsys):
    async with SessionLocal() as session:
        session.add_all(
            [
                _robots_run("fine-shop", {"https://fine.test": {"state": "fetched"}}),
                _robots_run(
                    "stale-shop",
                    {
                        "https://stale.test": {
                            "state": "stale",
                            "copy_age_days": 9.5,
                            "error": "robots.txt returned 503",
                        }
                    },
                ),
                _robots_run(
                    "refused-shop",
                    {"https://refused.test": {"state": "unavailable", "error": "unreachable"}},
                    stopped="refused by its host: robots.txt for https://refused.test",
                ),
            ]
        )
        await session.commit()
        status = _status()
        await status.robots_health(session, None)
    out = capsys.readouterr().out
    assert "https://fine.test fetched" in out
    stale = next(line for line in out.splitlines() if "stale.test" in line)
    assert "using a copy 9.5d old" in stale and status.RED in stale  # past a week
    assert "https://refused.test UNAVAILABLE" in out
    assert "run stopped early: refused by its host" in out
