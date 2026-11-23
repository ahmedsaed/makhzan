"""A crosswalk must point at categories this code has (worker/sources/registry.py).

`load_crosswalk` checks only the `domain:slug` form. A ref to a missing slug
(a typo, or a crosswalk deployed before the taxonomy change it needs) used to
build fine and then file every listing under it as uncategorized, silently.
The deploy's sync builds every adapter, so refusing it there stops the deploy.
"""

from __future__ import annotations

import pytest
from makhzan_schemas.models import Source

from worker.sources.registry import build_adapter, check_crosswalk_targets


def _crosswalk(tmp_path, monkeypatch, body: str) -> None:
    (tmp_path / "shop.toml").write_text(body)
    monkeypatch.setenv("MAKHZAN_CROSSWALKS", str(tmp_path))


def _source() -> Source:
    return Source(
        source_id="shop",
        adapter="shopify",
        base_url="https://shop.test",
        supplier={"slug": "shop", "name": "Shop"},
        enabled=True,
        config={"crosswalk": "shop"},
    )


def test_a_crosswalk_to_real_leaves_builds(tmp_path, monkeypatch):
    _crosswalk(tmp_path, monkeypatch, '[categories]\n"Breakers" = "electrical:circuit-breakers"\n')
    build_adapter(_source())


@pytest.mark.parametrize(
    "ref",
    [
        "electrical:no-such-slug",  # a slug this code lacks
        "electricl:circuit-breakers",  # a misspelled domain, not the default's leaf
        "electrical:protection",  # a parent, not a leaf
    ],
)
def test_a_crosswalk_to_a_missing_category_stops_the_sync(tmp_path, monkeypatch, ref):
    _crosswalk(tmp_path, monkeypatch, f'[categories]\n"Things" = "{ref}"\n')
    with pytest.raises(ValueError, match="does not have"):
        build_adapter(_source())


def test_the_error_names_the_missing_refs():
    with pytest.raises(ValueError, match="'Lamps' -> electrical:nope"):
        check_crosswalk_targets("shop", {"Lamps": ("electrical", "nope")})


@pytest.mark.parametrize("ref", ["safety:fall-protection", "safety:fire-hoses"])
def test_the_safety_leaves_a_safety_shop_maps_to_exist(ref):
    """The private crosswalk maps a safety shop's fall-protection and
    fire-fighting product types here; the sync refuses it until these exist."""
    domain, slug = ref.split(":")
    check_crosswalk_targets("shop", {"Things": (domain, slug)})
