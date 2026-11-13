"""`make status` CROSSWALK DRIFT reads the newest check, and CATALOG counts
price-on-request apart from listings that lost their price."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import IngestionRun, Listing, Supplier
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


async def test_a_clean_run_after_a_drifted_one_clears_the_report(capsys):
    """Drift fixed by a mapping or an `ignore` entry must not linger for weeks."""
    out = await _drift_report(capsys, [_run("shop", 120, DRIFTED), _run("shop", 5, CLEAN)])
    assert "Cooling Solutions" not in out
    assert "crosswalk matches the source" in out


async def test_drift_fixed_by_an_ignore_entry_clears_on_the_next_run(capsys):
    """End to end: the pipeline must record the clean check, or status falls back
    to the last run that drifted."""
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
    invents retirements; a later complete run with an empty list clears them."""
    complete_drift = {**CLEAN, "unused": ["Teensy Board"], "unused_count": 1}
    out = await _drift_report(capsys, [_run("shop", 120, complete_drift), _run("shop", 5, CLEAN)])
    assert "1 entries never matched" in out and "Teensy Board" in out

    complete_clean = {**CLEAN, "unused": [], "unused_count": 0}
    out = await _drift_report(capsys, [_run("shop", 1, complete_clean)])
    assert "Teensy Board" not in out
    assert "crosswalk matches the source" in out


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
