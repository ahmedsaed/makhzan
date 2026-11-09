"""Sources as data: the `sources` table, the file it is seeded from, and the
factory that turns a row into an adapter.

What these protect is that nothing about a supplier lives in code any more. A
row has to build exactly the adapter a hand-written constructor call would
have, a bad row has to fail loudly at sync rather than quietly at 3am, and one
bad row must not stop every other source from being swept.
"""

from __future__ import annotations

import textwrap

import pytest
from makhzan_schemas.config import REPO_CONFIG_DIR
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import Source
from sqlalchemy import select
from worker.sources import registry
from worker.sources.fixture import FixtureAdapter
from worker.sources.odoo import OdooAdapter
from worker.sources.registry import adapter_class, build_adapter, load_adapters
from worker.sources.shopify import ShopifyAdapter
from worker.sources.sync import read_sources, sync_sources
from worker.sources.woocommerce import WooCommerceAdapter

SUPPLIER = {"slug": "shop-a", "name": "Shop A", "website_url": "https://shop-a.test"}


def _row(**kw) -> Source:
    defaults = dict(
        source_id="shop-a",
        adapter="woocommerce",
        base_url="https://shop-a.test",
        enabled=True,
        supplier=SUPPLIER,
        config={},
    )
    return Source(**{**defaults, **kw})


def _crosswalks(tmp_path, monkeypatch, **files):
    for name, text in files.items():
        (tmp_path / f"{name}.toml").write_text(textwrap.dedent(text), encoding="utf-8")
    monkeypatch.setenv("MAKHZAN_CROSSWALKS", str(tmp_path))


# --------------------------------------------------------------------------- #
# The factory
# --------------------------------------------------------------------------- #


def test_a_row_builds_the_adapter_it_names():
    adapter = build_adapter(_row(config={"polite_delay": 20, "max_pages_per_run": 3}))

    assert isinstance(adapter, WooCommerceAdapter)
    assert adapter.source_id == "shop-a"
    assert adapter.base_url == "https://shop-a.test"
    assert adapter.supplier.slug == "shop-a"
    assert adapter.supplier.website_url == "https://shop-a.test"
    assert adapter.polite_delay == 20
    assert adapter.max_pages_per_run == 3
    assert adapter.enabled is True


@pytest.mark.parametrize(
    ("name", "cls"),
    [
        ("woocommerce", WooCommerceAdapter),
        ("shopify", ShopifyAdapter),
        ("odoo", OdooAdapter),
        ("fixture", FixtureAdapter),
    ],
)
def test_every_built_in_adapter_builds_from_a_row(name, cls):
    base_url = None if name == "fixture" else "https://shop-a.test"
    assert type(build_adapter(_row(adapter=name, base_url=base_url))) is cls


def test_an_adapter_kept_in_another_package_is_named_by_import_path():
    """How a bespoke adapter is wired in without the platform knowing about it."""
    adapter = build_adapter(_row(adapter="worker.sources.shopify:ShopifyAdapter"))
    assert isinstance(adapter, ShopifyAdapter)


@pytest.mark.parametrize("name", ["magento", "worker.sources.shopify:Nope"])
def test_an_unknown_adapter_is_an_error(name):
    with pytest.raises((ValueError, AttributeError)):
        adapter_class(name)


def test_an_import_path_must_name_an_adapter():
    with pytest.raises(TypeError, match="not a SourceAdapter"):
        adapter_class("worker.sources.base:SupplierInfo")


def test_an_unknown_setting_is_an_error_not_ignored():
    """A typo'd `max_page_per_run` silently ignored would leave a source paced at
    the default — sweeping a whole catalogue in one go."""
    with pytest.raises(TypeError, match="max_page_per_run"):
        build_adapter(_row(config={"max_page_per_run": 3}))


def test_the_supplier_domain_is_the_fallback_vertical():
    adapter = build_adapter(_row(supplier={**SUPPLIER, "domain": "tools"}))
    assert adapter.supplier.domain == "tools"


def test_a_crosswalk_is_named_and_loaded(tmp_path, monkeypatch):
    _crosswalks(
        tmp_path,
        monkeypatch,
        shop_a="""
        [categories]
        "Ceramic Capacitors" = "electronics:capacitors"
        """,
    )
    adapter = build_adapter(_row(config={"crosswalk": "shop_a"}))
    assert adapter.categories == {"Ceramic Capacitors": ("electronics", "capacitors")}
    assert adapter.authoritative_categories is False


def test_a_crosswalk_with_partitions_drives_a_category_sweep(tmp_path, monkeypatch):
    """The Odoo shape: browsed by category, so the crosswalk says what to visit —
    including the category it does not map — and the whole-shop pass goes first."""
    _crosswalks(
        tmp_path,
        monkeypatch,
        shop_b="""
        partitions = ["connectors-12", "keypads-40"]
        [categories]
        "connectors-12" = "electronics:connectors"
        """,
    )
    adapter = build_adapter(
        _row(adapter="odoo", config={"crosswalk": "shop_b", "sweep_whole_shop": True})
    )
    assert adapter.partitions() == ["", "connectors-12", "keypads-40"]
    assert adapter.authoritative_categories is True


@pytest.mark.parametrize("adapter_type", ["woocommerce", "odoo", "shopify"])
def test_a_crosswalk_ignore_list_reaches_any_adapter(tmp_path, monkeypatch, adapter_type):
    """Read by the drift check only, so no adapter has to accept it as a keyword."""
    _crosswalks(
        tmp_path,
        monkeypatch,
        shop_a="""
        ignore = ["Uni-T", "Accessories"]
        [categories]
        "Sensors" = "electronics:sensors"
        """,
    )
    adapter = build_adapter(_row(adapter=adapter_type, config={"crosswalk": "shop_a"}))
    assert adapter.ignored_categories == ("Uni-T", "Accessories")
    assert build_adapter(_row()).ignored_categories == ()


def test_a_crosswalk_preference_reaches_a_tag_cloud_adapter(tmp_path, monkeypatch):
    _crosswalks(
        tmp_path,
        monkeypatch,
        shop_a="""
        prefer = ["LEDs"]
        [categories]
        "Displays (LCD & LED)" = "electronics:displays"
        "LEDs" = "electronics:leds"
        """,
    )
    adapter = build_adapter(_row(config={"crosswalk": "shop_a"}))
    raw = adapter._to_raw(
        {
            "id": 1,
            "name": "LED 3mm Red",
            "categories": [{"name": "Displays (LCD & LED)"}, {"name": "LEDs"}],
        },
        "in stock",
    )
    assert adapter.category_for(raw) == ("electronics", "leds")


def test_a_preference_on_a_single_category_source_is_refused(tmp_path, monkeypatch):
    """A Shopify product has one product_type, so there is nothing to rank; a
    `prefer` there is a mistake and fails the build rather than being ignored."""
    _crosswalks(
        tmp_path,
        monkeypatch,
        shop_c="""
        prefer = ["sensor"]
        [categories]
        "sensor" = "electronics:sensors"
        """,
    )
    with pytest.raises(TypeError, match="prefer"):
        build_adapter(_row(adapter="shopify", config={"crosswalk": "shop_c"}))


def test_a_missing_crosswalk_is_an_error(tmp_path, monkeypatch):
    _crosswalks(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        build_adapter(_row(config={"crosswalk": "nowhere"}))


# --------------------------------------------------------------------------- #
# Reading the file
# --------------------------------------------------------------------------- #


def _sources_file(tmp_path, text):
    path = tmp_path / "sources.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_columns_are_split_from_adapter_settings(tmp_path):
    path = _sources_file(
        tmp_path,
        """
        [[source]]
        id = "shop-a"
        adapter = "woocommerce"
        base_url = "https://shop-a.test"
        max_pages_per_run = 3
        supplier = { slug = "shop-a", name = "Shop A" }
        """,
    )
    (row,) = read_sources(path)
    assert row.source_id == "shop-a"
    assert row.adapter == "woocommerce"
    assert row.enabled is True, "enabled defaults to true"
    assert row.supplier == {"slug": "shop-a", "name": "Shop A"}
    assert row.config == {"max_pages_per_run": 3}


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (
            """
            [[source]]
            id = "shop-a"
            adapter = "woocommerce"
            """,
            "missing",
        ),
        (
            """
            [[source]]
            id = "shop-a"
            adapter = "fixture"
            supplier = { slug = "a", name = "A" }
            [[source]]
            id = "shop-a"
            adapter = "fixture"
            supplier = { slug = "a", name = "A" }
            """,
            "duplicate",
        ),
        (
            """
            [[source]]
            id = "shop-a"
            adapter = "woocommerce"
            base_url = "https://shop-a.test"
            polite_dleay = 20
            supplier = { slug = "a", name = "A" }
            """,
            "'shop-a' does not build",
        ),
    ],
)
def test_an_invalid_file_is_refused_whole(tmp_path, entries, message):
    """Validated by building every adapter, so the typo surfaces at sync — at
    deploy — and not as a source that quietly stops being crawled."""
    with pytest.raises(ValueError, match=message):
        read_sources(_sources_file(tmp_path, entries))


def test_the_example_file_builds():
    """It documents the format, so it must stay a working one."""
    rows = read_sources(REPO_CONFIG_DIR / "sources.example.toml")
    assert [r.source_id for r in rows] == ["fixture"]
    assert rows[0].enabled is False


# --------------------------------------------------------------------------- #
# Syncing into the table
# --------------------------------------------------------------------------- #


async def _sync(rows):
    async with SessionLocal() as session:
        return await sync_sources(session, rows)


async def _stored():
    async with SessionLocal() as session:
        return {s.source_id: s for s in (await session.execute(select(Source))).scalars()}


async def test_sync_creates_then_leaves_an_unchanged_source_alone():
    assert (await _sync([_row()]))["created"] == ["shop-a"]
    assert (await _sync([_row()]))["unchanged"] == ["shop-a"]
    assert list(await _stored()) == ["shop-a"]


async def test_the_file_wins_for_every_source_it_names():
    await _sync([_row(config={"max_pages_per_run": 3})])
    report = await _sync([_row(enabled=False, config={"max_pages_per_run": 5})])

    assert report["updated"] == ["shop-a"]
    stored = (await _stored())["shop-a"]
    assert stored.enabled is False
    assert stored.config == {"max_pages_per_run": 5}


async def test_a_source_the_file_does_not_name_is_reported_not_deleted():
    """The table is the source of truth and may hold sources added another way.
    Deleting one would orphan its listings' provenance; it is only reported."""
    await _sync([_row(), _row(source_id="shop-b", supplier={"slug": "shop-b", "name": "B"})])
    report = await _sync([_row()])

    assert report["not_in_file"] == ["shop-b"]
    assert set(await _stored()) == {"shop-a", "shop-b"}


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #


async def test_the_registry_is_built_from_the_table():
    await _sync(
        [
            _row(),
            _row(source_id="shop-b", enabled=False, supplier={"slug": "shop-b", "name": "B"}),
        ]
    )
    assert await load_adapters() == {}

    assert registry.get("shop-a").source_id == "shop-a"
    assert registry.get("shop-b").enabled is False, "disabled sources still build, to run by hand"
    assert [a.source_id for a in registry.all_enabled()] == ["shop-a"]


async def test_loading_again_reflects_a_changed_table():
    """The daily refresh reloads, so a disabled or removed source takes effect
    without restarting the worker."""
    await _sync([_row()])
    await load_adapters()
    await _sync([_row(enabled=False)])
    await load_adapters()
    assert registry.all_enabled() == []


async def test_one_broken_row_does_not_stop_the_others():
    """A row edited by hand into something that no longer builds is skipped and
    reported. Skipping is safe: a source with no run archives nothing."""
    async with SessionLocal() as session:
        session.add(_row())
        session.add(
            _row(source_id="broken", adapter="magento", supplier={"slug": "x", "name": "X"})
        )
        await session.commit()

    errors = await load_adapters()

    assert list(errors) == ["broken"]
    assert "magento" in errors["broken"]
    assert [a.source_id for a in registry.all_enabled()] == ["shop-a"]
