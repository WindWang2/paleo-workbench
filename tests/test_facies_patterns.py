"""Facies → SVG pattern data-contract tests (map polygon pattern fills).

Covers the contract layer only — no rendering:
``paleo_workbench.mapping.facies_patterns``, the ``VectorStyle.fill_patterns``
serialization, and the ``facies_v2`` symbol wiring.
"""

from __future__ import annotations

from paleo_workbench.mapping.facies_patterns import (
    FACIES_PATTERN_DIR,
    FACIES_PATTERN_MAP,
    pattern_id_for_facies,
    pattern_path_for_facies,
)
from paleo_workbench.mapping.geological_symbols import symbol_by_id
from paleo_workbench.mapping.map_styles import VectorStyle

# providers first: providers ↔ mock_facies import each other at module level,
# so importing providers first lets the cycle resolve (cf.
# tests/test_mock_facies_providers.py which imports mock_facies lazily).
from paleo_workbench.prediction import providers as _providers  # noqa: F401
from paleo_workbench.prediction.mock_facies import MOCK_FACIES_CLASSES

#: The 9 geological_symbols._FACIES_CLASSES English ids.  Each entry states
#: the contract decision: the expected pattern id, or None when the class
#: deliberately has no tile (volcanic/other).
ENGLISH_FACIES_EXPECTATIONS: tuple[tuple[str, str | None], ...] = (
    ("alluvial_fan", "alluvial_fan"),
    ("fluvial", "fluvial"),
    ("lacustrine", "lacustrine"),
    ("delta", "delta"),
    ("shoreline", "shoreface"),  # nearest: wave-dominated shoreline deposit
    ("shallow_marine", "shallow_marine"),
    ("deep_marine", "deep_marine"),
    ("volcanic", None),  # no volcanic tile in the asset library
    ("other", None),  # catch-all class, no tile by design
)

#: The 4 mock Chinese classes — the integration requirement is that every
#: one resolves to a pattern (no hard-fallback allowed).
MOCK_FACIES_EXPECTATIONS: tuple[tuple[str, str], ...] = (
    ("扇三角洲", "delta"),  # fan delta → delta-front system tile
    ("三角洲前缘", "delta"),  # delta-front subfacies → delta tile
    ("滨浅湖", "lacustrine"),  # lacustrine sub-environment, not marine shore
    ("湖相泥", "lacustrine"),  # lake mud → lacustrine tile
)


def test_pattern_dir_resolves_to_existing_asset_directory() -> None:
    assert FACIES_PATTERN_DIR.is_dir()
    assert (FACIES_PATTERN_DIR / "delta.svg").is_file()


def test_english_facies_ids_either_hit_a_tile_or_explicitly_none() -> None:
    for facies_id, expected in ENGLISH_FACIES_EXPECTATIONS:
        pattern_id = pattern_id_for_facies(facies_id)
        assert pattern_id == expected, facies_id
        if expected is None:
            assert facies_id not in FACIES_PATTERN_MAP
            assert pattern_path_for_facies(facies_id) is None
        else:
            path = pattern_path_for_facies(facies_id)
            assert path is not None and path.is_file(), facies_id


def test_mock_chinese_classes_all_resolve_to_existing_tiles() -> None:
    assert tuple(MOCK_FACIES_CLASSES) == tuple(
        name for name, _ in MOCK_FACIES_EXPECTATIONS
    )
    for name, expected in MOCK_FACIES_EXPECTATIONS:
        assert pattern_id_for_facies(name) == expected, name
        path = pattern_path_for_facies(name)
        assert path is not None and path.is_file(), name


def test_pattern_path_for_unknown_name_returns_none() -> None:
    assert pattern_path_for_facies("not_a_facies") is None
    assert pattern_path_for_facies("") is None
    assert pattern_id_for_facies("not_a_facies") is None


def test_vector_style_fill_patterns_round_trip() -> None:
    style = VectorStyle(
        renderer="categorized",
        field="facies_name",
        categories=(("delta", "#d9a066", "三角洲"),),
        fill_patterns=(("delta", "delta"), ("lacustrine", "lacustrine")),
    )
    parsed = VectorStyle.from_dict(style.to_dict())
    assert parsed == style
    assert parsed.fill_patterns == (("delta", "delta"), ("lacustrine", "lacustrine"))


def test_vector_style_without_fill_patterns_omits_key_and_stays_compatible() -> None:
    style = VectorStyle(fill="#6c8ebf")
    assert "fill_patterns" not in style.to_dict()
    assert VectorStyle.from_dict(style.to_dict()) == style
    # Legacy payloads without the key parse to an empty tuple.
    assert VectorStyle.from_dict({"fill": "#123456"}).fill_patterns == ()


def test_facies_v2_legacy_fallback_carries_existing_pattern_tiles() -> None:
    facies = symbol_by_id("facies_v2")
    fallback = facies.legacy_fallback
    assert fallback.fill_patterns  # non-empty
    for value, pattern_id in fallback.fill_patterns:
        path = pattern_path_for_facies(value)
        assert path is not None and path.is_file(), value
        assert pattern_id == pattern_id_for_facies(value)
        assert (FACIES_PATTERN_DIR / f"{pattern_id}.svg").is_file()
    # Unmapped classes stay out of the overlay, base fills still classify all.
    assert {value for value, _ in fallback.fill_patterns} == {
        value for value, _ in ENGLISH_FACIES_EXPECTATIONS if _ is not None
    }
    assert len(fallback.categories) == 9


def test_facies_v2_renderer_rules_carry_pattern_where_mapped() -> None:
    facies = symbol_by_id("facies_v2")
    rules = {rule["value"]: rule for rule in facies.renderer_hint["rules"]}
    for facies_id, expected in ENGLISH_FACIES_EXPECTATIONS:
        if expected is None:
            assert "pattern" not in rules[facies_id], facies_id
        else:
            assert rules[facies_id]["pattern"] == expected, facies_id


def test_facies_hatch_v2_untouched_by_patterns() -> None:
    hatch = symbol_by_id("facies_hatch_v2")
    assert hatch.legacy_fallback.fill_patterns == ()
    assert all("pattern" not in rule for rule in hatch.renderer_hint["rules"])
