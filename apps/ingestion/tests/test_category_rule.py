"""The owner's rule for a product a shop files under several categories
(`worker.categories_seen.choose`, decided 2026-11-23).

One category, chosen from the *set* of names the listing was seen under, never
from the order they were swept in: unmapped and ignored names drop out; of a
category and its ancestor the more specific stays (the shop's own tree, then
our taxonomy's parent links); then the crosswalk's `prefer`, then the ref.
Step 3 (what other shops' listings of the same product use) is not built.
No database here: the pipeline's use of it is in test_categories_seen.py.
"""

from __future__ import annotations

from itertools import permutations

import pytest
from makhzan_schemas.enums import SourceType

from worker.categories_seen import choose, names_seen
from worker.sources.base import Page, SourceAdapter, SupplierInfo
from worker.sources.odoo import OdooAdapter


class Shop(SourceAdapter):
    """A crosswalk, an optional shop tree and an optional `prefer`."""

    source_id = "rule-shop"
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug="rule-shop", name="Rule Shop")
    records_categories_seen = True

    def __init__(self, categories, parents=None, prefer=()):
        self.categories = categories
        self._parents = parents or {}
        self.preferred_categories = tuple(prefer)

    def category_parent(self, name):
        return self._parents.get(name)

    def partitions(self):
        return list(self.categories)

    async def fetch_page(self, partition, page):
        return Page([], has_more=False)


SIBLINGS = {
    "Resistors": ("electronics", "resistors"),
    "Capacitors": ("electronics", "capacitors"),
    "Inductors": ("electronics", "inductors"),
}


def _every_order(shop, names):
    picks = {choose(shop, order) for order in permutations(names)}
    assert len(picks) == 1, picks
    return picks.pop()


def test_one_mapped_name_is_its_mapping():
    assert choose(Shop(SIBLINGS), ["Resistors"]) == ("electronics", "resistors")


def test_nothing_mapped_is_none():
    assert choose(Shop(SIBLINGS), []) is None
    assert choose(Shop(SIBLINGS), ["Brand X", "New Arrivals"]) is None


def test_unmapped_and_ignored_names_drop_out():
    """Mapped + unmapped: the mapped one, whatever the order. An ignored name
    is never mapped (the crosswalk refuses both), so it drops out the same way."""
    shop = Shop(SIBLINGS)
    shop.ignored_categories = ("Brand X",)
    assert _every_order(shop, ["Brand X", "Capacitors", "Unmapped"]) == (
        "electronics",
        "capacitors",
    )


def test_names_are_folded_like_every_crosswalk_lookup():
    assert choose(Shop(SIBLINGS), ["  CAPACITORS "]) == ("electronics", "capacitors")


def test_siblings_without_prefer_take_the_first_ref_alphabetically():
    assert _every_order(Shop(SIBLINGS), ["Resistors", "Inductors", "Capacitors"]) == (
        "electronics",
        "capacitors",
    )


def test_siblings_with_prefer_take_the_preferred():
    shop = Shop(SIBLINGS, prefer=["Resistors", "Inductors"])
    assert _every_order(shop, ["Resistors", "Inductors", "Capacitors"]) == (
        "electronics",
        "resistors",
    )
    # A preferred name not among them ranks nothing; the next preferred wins.
    assert _every_order(shop, ["Inductors", "Capacitors"]) == ("electronics", "inductors")


def test_two_names_mapped_alike_are_one_candidate():
    shop = Shop({**SIBLINGS, "Passives": ("electronics", "resistors")}, prefer=["Passives"])
    assert _every_order(shop, ["Capacitors", "Resistors", "Passives"]) == (
        "electronics",
        "resistors",
    )


def test_a_child_beats_its_parent_in_the_shops_tree():
    """Seen under a parent and its child (an Odoo parent page lists its
    children's products): the child's mapping. Held by the parent alone: the
    parent's. Whatever either maps to alphabetically."""
    categories = {
        "measurement": ("tools", "precision-measure"),
        "measurement-multimeters": ("tools", "test-instruments"),
        "measurement-multimeters-clamp": ("tools", "measurement-other"),
    }
    parents = {
        "measurement-multimeters": "measurement",
        "measurement-multimeters-clamp": "measurement-multimeters",
    }
    shop = Shop(categories, parents)
    assert _every_order(shop, ["measurement", "measurement-multimeters"]) == (
        "tools",
        "test-instruments",
    )
    assert _every_order(shop, list(categories)) == ("tools", "measurement-other")
    assert choose(shop, ["measurement"]) == ("tools", "precision-measure")


def test_an_unmapped_child_leaves_the_parents_mapping():
    """Step 1 before step 2: a child the crosswalk does not map is gone before
    specificity is asked, so a product in it takes its mapped parent's."""
    shop = Shop({"lighting": ("electrical", "light-fixtures")}, {"lighting-mixed": "lighting"})
    assert choose(shop, ["lighting-mixed", "lighting"]) == ("electrical", "light-fixtures")


def test_a_child_beats_its_parent_in_our_taxonomy():
    """Inert with today's crosswalks, which may name leaves only, but the rule
    reads the taxonomy's parent links: `components` is resistors' parent."""
    shop = Shop({"Parts": ("electronics", "components"), **SIBLINGS})
    assert _every_order(shop, ["Parts", "Resistors"]) == ("electronics", "resistors")


def test_specificity_is_per_branch():
    """A parent stays when its own descendant is not among the names, and then
    competes with the other branch on prefer and ref."""
    categories = {
        "a": ("tools", "pliers"),
        "a-child": ("tools", "wrenches"),
        "b": ("tools", "drill-bits"),
    }
    shop = Shop(categories, {"a-child": "a"})
    assert _every_order(shop, ["a", "a-child", "b"]) == ("tools", "drill-bits")
    assert _every_order(Shop(categories, {"a-child": "a"}, prefer=["a-child"]), ["a", "b"]) == (
        "tools",
        "drill-bits",
    )
    assert _every_order(Shop(categories, {"a-child": "a"}, prefer=["a"]), ["a", "b"]) == (
        "tools",
        "pliers",
    )


def test_names_seen_is_the_union_of_the_kept_cycles():
    attributes = {
        "categories_seen": {
            "2026-11-08T06:00:00+00:00": ["b", "c"],
            "2026-11-01T06:00:00+00:00": ["a", "b"],
            "not a date": ["x"],
        }
    }
    assert names_seen(attributes) == ["a", "b", "c"]
    assert names_seen({}) == [] and names_seen(None) == []


# --------------------------------------------------------------------------- #
# The Odoo shop's tree, from its slugs
# --------------------------------------------------------------------------- #


def _odoo(**kwargs) -> OdooAdapter:
    return OdooAdapter(
        "odoo-shop",
        "https://odoo.test",
        SupplierInfo(slug="odoo-shop", name="Odoo Shop"),
        **kwargs,
    )


def test_odoo_reads_its_tree_off_slugs_that_embed_the_path():
    shop = _odoo(
        categories={
            "meters-9": ("tools", "precision-measure"),
            "meters-multimeters-50": ("tools", "test-instruments"),
        },
        partition_keys=[
            "power-15",
            "power-low-voltage-109",
            "power-low-voltage-din-rail-88",
            "meters-9",
            "meters-multimeters-50",
        ],
    )
    assert shop.category_parent("power-low-voltage-din-rail-88") == ("power-low-voltage-109")
    assert shop.category_parent("power-low-voltage-109") == "power-15"
    assert shop.category_parent("power-15") is None
    assert shop.category_parent("meters-multimeters-50") == ("meters-9")
    assert _every_order(shop, ["meters-9", "meters-multimeters-50"]) == (
        "tools",
        "test-instruments",
    )


def test_odoo_slugs_without_the_path_give_no_tree():
    """Seo-named slugs, as the Odoo shop's are: no category is anyone's parent."""
    shop = _odoo(
        categories={
            "chargers-40": ("electronics", "batteries"),
            "cells-44": ("electronics", "batteries"),
            "plugs-8": ("electronics", "connectors"),
        }
    )
    assert all(shop.category_parent(k) is None for k in shop.categories)


def test_the_registry_gives_a_recording_source_its_prefer(tmp_path, monkeypatch):
    from makhzan_schemas.models import Source

    from worker.sources.registry import build_adapter

    (tmp_path / "shop.toml").write_text(
        'prefer = ["b-2"]\n[categories]\n"a-1" = "tools:pliers"\n"b-2" = "tools:wrenches"\n'
    )
    monkeypatch.setenv("MAKHZAN_CROSSWALKS", str(tmp_path))
    adapter = build_adapter(
        Source(
            source_id="shop",
            adapter="odoo",
            base_url="https://odoo.test",
            supplier={"slug": "shop", "name": "Shop"},
            enabled=True,
            config={"crosswalk": "shop"},
        )
    )
    assert adapter.preferred_categories == ("b-2",)
    assert choose(adapter, ["a-1", "b-2"]) == ("tools", "wrenches")


@pytest.mark.parametrize("adapter", ["woocommerce", "shopify"])
def test_a_tag_cloud_source_still_takes_prefer_as_its_own(tmp_path, monkeypatch, adapter):
    from makhzan_schemas.models import Source

    from worker.sources.registry import build_adapter

    (tmp_path / "shop.toml").write_text(
        'prefer = ["B"]\n[categories]\n"A" = "tools:pliers"\n"B" = "tools:wrenches"\n'
    )
    monkeypatch.setenv("MAKHZAN_CROSSWALKS", str(tmp_path))
    config = {"crosswalk": "shop"}
    if adapter == "shopify":
        config["collections"] = True
    built = build_adapter(
        Source(
            source_id="shop",
            adapter=adapter,
            base_url="https://shop.test",
            supplier={"slug": "shop", "name": "Shop"},
            enabled=True,
            config=config,
        )
    )
    assert built.preferred_categories == ()
    assert built._preference
