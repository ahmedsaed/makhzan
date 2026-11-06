"""Crosswalks: the name normalization they are keyed on, the loader, and the
checks every configured crosswalk must pass.

A crosswalk turns a supplier's own category into ours. The tables are data in
`crosswalk_dir()`, and the last section here runs over whichever of them are
configured — so the same checks guard configuration kept outside this
repository. What any one table deliberately maps, or refuses to, is about that
supplier and is tested beside the data, in the private configuration's tests/.
"""

from __future__ import annotations

import pytest
from makhzan_schemas.domains import get_profile
from makhzan_schemas.domains.crosswalks import (
    fold_crosswalk,
    list_crosswalks,
    load_crosswalk,
    normalize_category_name,
)

# --------------------------------------------------------------------------- #
# Name normalization
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("authored", "live"),
    [
        # Every one of these was a real dead key, found by diffing the crosswalks
        # against the live shops. The shop kept the category and the products and
        # only re-typed the punctuation.
        ("Diodes - General Purpose", "Diodes – General Purpose"),
        ("Diodes - Fast Recovery Rectifiers", "Diodes – Fast Recovery Rectifiers"),
        ("SMD Diodes - General Purpose", "SMD Diodes – General Purpose"),
        ("0603x4 Resistor", "0603×4 Resistor"),
        ("X - power batteries", "X – power batteries"),
        ("ADC & DAC Converters IC's", "ADC & DAC Converters IC’s"),
        # And the ordinary ones.
        ("Hand &amp; Repair Tools", "Hand & Repair Tools"),
        ("Sensors", "  sensors  "),
        ('Kits "Packages"', "Kits “Packages”"),
    ],
)
def test_punctuation_a_cms_rewrites_does_not_break_a_mapping(authored, live):
    assert normalize_category_name(authored) == normalize_category_name(live)


def test_normalization_does_not_fold_different_categories_together():
    """It folds punctuation, not words — "Power Resistors" must never become
    "Resistors"."""
    assert normalize_category_name("Power Resistors") != normalize_category_name("Resistors")
    assert normalize_category_name("SMD Capacitor") != normalize_category_name("Capacitors")


def test_fold_crosswalk_refuses_a_collision():
    """Two keys that normalize alike are a mistake in the table; which one won
    would otherwise depend on dict order."""
    with pytest.raises(ValueError, match="collide"):
        fold_crosswalk(
            {
                "Diodes - General Purpose": ("electronics", "diodes"),
                "Diodes – General Purpose": ("electronics", "ics"),
            }
        )


def test_a_duplicate_spelling_agreeing_on_its_target_is_fine():
    folded = fold_crosswalk({"IC's": ("electronics", "ics"), "IC’s": ("electronics", "ics")})
    assert folded[normalize_category_name("IC's")] == ("electronics", "ics")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def _write(tmp_path, text, name="shop"):
    (tmp_path / f"{name}.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_a_crosswalk_maps_names_to_domain_and_leaf_in_file_order(tmp_path):
    _write(
        tmp_path,
        """
        # Comments are kept in the file, where the reasoning belongs.
        [categories]
        "Ceramic Capacitors" = "electronics:capacitors"  # type-bearing
        "Spindles | Chucks | Collets" = "tools:drill-bits"
        """,
    )
    crosswalk = load_crosswalk("shop", tmp_path)
    assert list(crosswalk.categories.items()) == [
        ("Ceramic Capacitors", ("electronics", "capacitors")),
        ("Spindles | Chucks | Collets", ("tools", "drill-bits")),
    ]
    assert crosswalk.partitions == ()


def test_a_crosswalk_can_carry_the_partitions_to_sweep(tmp_path):
    """Wider than the mapping: an unmapped category still has to be swept."""
    _write(
        tmp_path,
        """
        partitions = ["connectors-12", "keypads-40"]
        [categories]
        "connectors-12" = "electronics:connectors"
        """,
    )
    crosswalk = load_crosswalk("shop", tmp_path)
    assert crosswalk.partitions == ("connectors-12", "keypads-40")
    assert set(crosswalk.categories) < set(crosswalk.partitions)


def test_a_package_size_key_stays_a_string(tmp_path):
    """The reason these are TOML and not YAML: an unquoted 0805 is a number
    there, and NO is false. TOML requires the quotes."""
    _write(tmp_path, '[categories]\n"0805" = "electronics:resistors"\n')
    assert "0805" in load_crosswalk("shop", tmp_path).categories


@pytest.mark.parametrize(
    "ref", ["capacitors", "electronics:", ":capacitors", "a:b:c", '["electronics", "capacitors"]']
)
def test_a_ref_that_is_not_domain_colon_slug_is_refused(tmp_path, ref):
    """A bare slug is ambiguous across domains, so it is an error, not a guess."""
    value = ref if ref.startswith("[") else f'"{ref}"'
    _write(tmp_path, f'[categories]\n"Capacitors" = {value}\n')
    with pytest.raises(ValueError, match="domain:slug"):
        load_crosswalk("shop", tmp_path)


def test_a_misspelt_table_is_refused_rather_than_loaded_empty(tmp_path):
    """`[categorise]` would otherwise load as a crosswalk that maps nothing —
    which looks exactly like a supplier whose categories all went unmapped."""
    _write(tmp_path, '[categorise]\n"Capacitors" = "electronics:capacitors"\n')
    with pytest.raises(ValueError, match="unknown keys"):
        load_crosswalk("shop", tmp_path)


def test_keys_that_collide_once_normalized_are_refused_at_load(tmp_path):
    _write(
        tmp_path,
        """
        [categories]
        "Diodes - General Purpose" = "electronics:diodes"
        "Diodes – General Purpose" = "electronics:ics"
        """,
    )
    with pytest.raises(ValueError, match="collide"):
        load_crosswalk("shop", tmp_path)


def test_the_directory_comes_from_the_environment(tmp_path, monkeypatch):
    """How configuration kept outside the repository is found."""
    _write(tmp_path, '[categories]\n"Fans" = "electronics:fans-cooling"\n', name="elsewhere")
    monkeypatch.setenv("MAKHZAN_CROSSWALKS", str(tmp_path))
    assert list_crosswalks() == ["elsewhere"]
    assert load_crosswalk("elsewhere").categories == {"Fans": ("electronics", "fans-cooling")}


# --------------------------------------------------------------------------- #
# Every configured crosswalk
# --------------------------------------------------------------------------- #

CONFIGURED = list_crosswalks()


@pytest.mark.parametrize("name", CONFIGURED)
def test_every_crosswalk_loads(name):
    """Refs well-formed, no unknown keys, no keys colliding once normalized."""
    load_crosswalk(name)


@pytest.mark.parametrize("name", CONFIGURED)
def test_every_crosswalk_target_is_a_real_taxonomy_leaf(name):
    """A typo silently uncategorizes a whole supplier category.

    Checked against the taxonomy of *its own* domain, since a crosswalk spans
    verticals — a tools slug is not a valid electronics leaf.
    """
    leaves: dict[str, set[str]] = {}
    unknown = {}
    for source_name, (domain, leaf) in load_crosswalk(name).categories.items():
        if domain not in leaves:
            leaves[domain] = {
                slug for slug, _en, _ar, parent in get_profile(domain).taxonomy if parent
            }
        if leaf not in leaves[domain]:
            unknown[source_name] = (domain, leaf)
    assert not unknown, f"{name} points at non-existent leaves: {list(unknown.items())[:5]}"


@pytest.mark.parametrize("name", [n for n in CONFIGURED if load_crosswalk(n).partitions])
def test_every_mapping_is_a_category_that_gets_swept(name):
    """For a source browsed by category, a mapping for a category no partition
    visits is dead code."""
    crosswalk = load_crosswalk(name)
    assert set(crosswalk.categories) <= set(crosswalk.partitions)


@pytest.mark.parametrize("name", [n for n in CONFIGURED if load_crosswalk(n).partitions])
def test_partitions_are_unique(name):
    partitions = load_crosswalk(name).partitions
    assert len(set(partitions)) == len(partitions)
