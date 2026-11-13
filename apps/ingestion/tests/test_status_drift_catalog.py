"""`make status` CROSSWALK DRIFT reads the newest check, and CATALOG counts
price-on-request apart from listings that lost their price."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import IngestionRun, Listing, Source, Supplier
from test_pipeline import SRC, CategoryAdapter, _seed_taxonomy
from test_status_details import _status
from worker.pipeline import run_source

DRIFTED = {
    "observed": 12,
    "unmapped": {"Cooling Solutions": 401},
    "unmapped_listings": 401,
}
CLEAN = {"observed": 12, "unmapped": {}, "unmapped_listings": 0}


def _run(source: str, minutes_ago: int, crosswalk: dict | None) -> IngestionRun:
    stats: dict = {"pacing": {}}
    if crosswalk is not None:
        stats["crosswalk"] = crosswalk
    return IngestionRun(
        source=source,
        source_type=SourceType.SCRAPED,
        started_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        stats=stats,
    )


async def _drift_report(capsys, runs: list[IngestionRun]) -> str:
    async with SessionLocal() as session:
        session.add_all(runs)
        await session.commit()
        await _status().crosswalk_drift(session, None)
    return capsys.readouterr().out


async def test_a_clean_slice_does_not_hide_another_slices_drift(capsys):
    """A paced source sweeps a slice a day; a clean slice speaks only for its own
    names. Without a completed cycle to vouch for the rest, it is not "clean"."""
    out = await _drift_report(capsys, [_run("shop", 120, DRIFTED), _run("shop", 5, CLEAN)])
    assert "1 unmapped" in out and "Cooling Solutions" in out
    assert "matches the source" not in out


async def test_a_clean_slice_alone_is_not_called_a_match(capsys):
    out = await _drift_report(capsys, [_run("shop", 5, CLEAN)])
    assert "matches the source" not in out
    assert "no unmapped names seen this cycle" in out


async def test_drift_from_before_the_last_completed_cycle_is_dropped(capsys):
    """The window starts at the newest completed cycle: a name unmapped in an
    earlier cycle and not seen since is no longer reported."""
    closing = _run("shop", 5, CLEAN)
    closing.stats["cycle"] = {
        "cycle_started_at": (datetime.now(UTC) - timedelta(minutes=60)).isoformat()
    }
    out = await _drift_report(
        capsys, [_run("shop", 120, DRIFTED), _run("shop", 30, CLEAN), closing]
    )
    assert "Cooling Solutions" not in out
    assert "crosswalk matches the source" in out


async def test_a_complete_clean_sweep_clears_drift_end_to_end(capsys):
    """End to end: the pipeline must record the clean check of a full sweep, or
    status falls back to the last run that drifted."""
    await _seed_taxonomy()
    crosswalk = {"cat-resistors": ("electronics", "resistors")}
    parts = ["cat-resistors", "cat-brand"]

    drifted = await run_source(SRC, CategoryAdapter(parts, crosswalk))
    assert drifted.stats["crosswalk"]["unmapped"] == {"cat-brand": 1}

    fixed = CategoryAdapter(parts, crosswalk)
    fixed.ignored_categories = ("cat-brand",)
    clean = await run_source(SRC, fixed)
    assert clean.stats["crosswalk"]["unmapped"] == {}

    async with SessionLocal() as session:
        await _status().crosswalk_drift(session, None)
    out = capsys.readouterr().out
    assert "cat-brand" not in out
    assert "crosswalk matches the source" in out


async def test_a_run_without_the_key_is_not_taken_as_clean(capsys):
    """Runs from before clean checks were recorded (or that saw nothing) carry no
    `crosswalk` key: that means "not checked", so the older drift still shows."""
    out = await _drift_report(capsys, [_run("shop", 120, DRIFTED), _run("shop", 5, None)])
    assert "1 unmapped" in out and "Cooling Solutions" in out
    assert "matches the source" not in out


async def test_unused_comes_from_the_newest_run_that_could_speak_for_it(capsys):
    """A resumed or paced run carries no `unused`, so it neither clears nor
    invents retirements; a later complete run with an empty list clears them.
    (No Source row here, so no current crosswalk filters them.)"""
    complete_drift = {**CLEAN, "unused": ["Teensy Board"], "unused_count": 1}
    out = await _drift_report(capsys, [_run("shop", 120, complete_drift), _run("shop", 5, CLEAN)])
    assert "1 entries never matched" in out and "Teensy Board" in out

    complete_clean = {**CLEAN, "unused": [], "unused_count": 0}
    out = await _drift_report(capsys, [_run("shop", 1, complete_clean)])
    assert "Teensy Board" not in out
    assert "crosswalk matches the source" in out


def _closing(minutes_ago: int, cycle_started_minutes_ago: int, crosswalk=CLEAN) -> IngestionRun:
    run = _run("shop", minutes_ago, crosswalk)
    run.stats["cycle"] = {
        "cycle_started_at": (
            datetime.now(UTC) - timedelta(minutes=cycle_started_minutes_ago)
        ).isoformat()
    }
    return run


async def test_a_cycle_that_started_before_the_window_is_read_from_its_start(capsys):
    """The 30-day cutoff must not truncate the cycle it claims to cover: a slice
    swept on day 1 of a cycle that started 40 days ago still counts."""
    day = 24 * 60
    out = await _drift_report(capsys, [_run("shop", 35 * day, DRIFTED), _closing(5, 40 * day)])
    assert "Cooling Solutions" in out
    assert "matches the source" not in out


async def test_no_run_checked_this_cycle_is_said_not_called_a_match(capsys):
    out = await _drift_report(capsys, [_run("shop", 120, DRIFTED), _closing(5, 60, None)])
    assert "0 runs checked (this cycle)" in out
    assert "matches the source" not in out


async def test_a_capped_list_is_said_and_never_called_a_match(capsys, tmp_path, monkeypatch):
    """A run stores only its biggest unmapped names. Even when every listed one
    is since ignored, the tail it left out is unknown, so no "matches"."""
    _crosswalk_file(tmp_path, monkeypatch, 'ignore = ["Fans"]\n\n[categories]\n"A" = "x:y"\n')
    capped = {"observed": 9, "unmapped": {"Fans": 50}, "unmapped_count": 3, "unmapped_listings": 80}
    out = await _drift_report(capsys, [_source_row(), _closing(5, 60, capped)])
    assert "+2 more names / 30 listings not listed" in out
    assert "Fans" not in out.replace("+2 more names", "")
    assert "matches the source" not in out


async def test_a_capped_unused_list_is_at_least(capsys):
    complete = {**CLEAN, "unused": ["Teensy Board"], "unused_count": 30}
    out = await _drift_report(capsys, [_run("shop", 5, complete)])
    assert "at least 30 entries never matched" in out


async def test_a_run_cut_off_mid_sweep_has_already_recorded_what_it_saw():
    """The per-page checkpoint carries the names seen so far: a run killed after
    its cursors moved past a page must not lose that page's names."""
    from sqlalchemy import select

    await _seed_taxonomy()
    seen: list[dict | None] = []

    class Watched(CategoryAdapter):
        async def fetch_page(self, partition, page):
            if partition == "cat-later":
                async with SessionLocal() as other:
                    row = (
                        await other.execute(select(IngestionRun).where(IngestionRun.source == SRC))
                    ).scalar_one()
                    seen.append((row.stats or {}).get("crosswalk"))
            return await super().fetch_page(partition, page)

    await run_source(
        SRC, Watched(["cat-new", "cat-later"], {"cat-x": ("electronics", "resistors")})
    )
    assert seen and seen[0]["unmapped"] == {"cat-new": 1}
    assert "unused" not in seen[0]


def _crosswalk_file(tmp_path, monkeypatch, body: str) -> None:
    (tmp_path / "shop_x.toml").write_text(body)
    monkeypatch.setenv("MAKHZAN_CROSSWALKS", str(tmp_path))


def _source_row(crosswalk: str = "shop_x") -> Source:
    return Source(
        source_id="shop",
        adapter="fixture",
        enabled=True,
        supplier={"slug": "shop", "name": "shop"},
        config={"crosswalk": crosswalk},
    )


async def test_a_name_ignored_since_leaves_the_report_at_once(capsys, tmp_path, monkeypatch):
    """Filtered by the crosswalk as it stands now, not by the next run."""
    _crosswalk_file(
        tmp_path,
        monkeypatch,
        'ignore = ["cooling   solutions"]\n\n[categories]\n"Sensors" = "electronics:sensors"\n',
    )
    out = await _drift_report(capsys, [_source_row(), _run("shop", 120, DRIFTED)])
    assert "Cooling Solutions" not in out
    assert "not filtered" not in out


async def test_unused_is_filtered_by_the_current_crosswalk(capsys, tmp_path, monkeypatch):
    _crosswalk_file(tmp_path, monkeypatch, '[categories]\n"Teensy Board" = "electronics:boards"\n')
    complete = {**CLEAN, "unused": ["Teensy Board", "Removed Since"], "unused_count": 2}
    out = await _drift_report(capsys, [_source_row(), _run("shop", 5, complete)])
    assert "1 entries never matched" in out and "Teensy Board" in out
    assert "Removed Since" not in out


async def test_an_unloadable_crosswalk_is_said_and_drift_still_shown(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("MAKHZAN_CROSSWALKS", str(tmp_path))
    out = await _drift_report(capsys, [_source_row("missing"), _run("shop", 5, DRIFTED)])
    assert "Cooling Solutions" in out
    assert "not filtered by the current crosswalk" in out and "'missing'" in out


async def test_a_limit_run_records_no_crosswalk_check():
    """`limit=` runs are ephemeral: a clean result there would read as a check."""
    await _seed_taxonomy()
    run = await run_source(
        SRC, CategoryAdapter(["cat-brand"], {"cat-x": ("electronics", "resistors")}), limit=1
    )
    assert run.stats.get("limit") == 1
    assert "crosswalk" not in run.stats


async def test_catalog_counts_price_on_request_apart_from_no_price(capsys):
    supplier = Supplier(id=uuid.uuid4(), slug="por-shop", name="P", source_type=SourceType.SCRAPED)
    rows = [
        (Decimal("10.00"), {}),
        (None, {}),  # lost its price: the failure "no price" is for
        (None, {"price_on_request": True}),
        (None, {"price_on_request": True}),
        # Not a real flag, read as the API reads it.
        (None, {"price_on_request": "yes"}),
    ]
    async with SessionLocal() as session:
        session.add(supplier)
        await session.flush()
        for i, (price, attributes) in enumerate(rows):
            session.add(
                Listing(
                    id=uuid.uuid4(),
                    supplier_id=supplier.id,
                    source="por-shop",
                    source_type=SourceType.SCRAPED,
                    external_id=str(i),
                    title_en=f"Item {i}",
                    domain="electronics",
                    price=price,
                    attributes=attributes,
                )
            )
        await session.commit()
        await _status().catalog(session, None)

    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    header = next(line for line in out.splitlines() if "no price" in line)
    assert "on req" in header
    line = next(line for line in out.splitlines() if line.strip().startswith("por-shop"))
    cells = line.split()
    # supplier domain total archived uncat no-price on-req verified...
    total, no_price, on_request = cells[2], cells[5], cells[6]
    assert (total, no_price, on_request) == ("5", "2", "2")
