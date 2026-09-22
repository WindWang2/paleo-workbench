"""Unified cartographic style/symbol system tests."""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.map_styles import (
    LinePattern,
    MarkerSymbol,
    TextStyle,
    VectorStyle,
    STYLE_LIBRARY,
    default_style_for,
    load_style_library,
    save_style_library,
    style_dict_revision,
)


def test_vector_style_round_trip_keeps_established_and_new_keys() -> None:
    style = VectorStyle(
        fill="#123456",
        stroke="#abcdef",
        stroke_width=2.5,
        line_pattern=LinePattern.FAULT,
        marker=MarkerSymbol.WELL,
        marker_size=8.0,
        labels=TextStyle(field="name", size=11.0, bold=True),
    )

    parsed = VectorStyle.from_dict(style.to_dict())

    assert parsed == style


def test_vector_style_from_dict_is_tolerant_of_unknown_and_legacy_keys() -> None:
    parsed = VectorStyle.from_dict(
        {
            "fill": "#00ff00",
            "stroke": "#ff0000",
            "stroke_width": 3,
            "unknown_future_key": {"ignored": True},
            "categories": {"shoreface": "#e03131", "channel": "#1971c2"},
            "labels": {"field": "facies", "size": 9.0, "buffer": 1.0},
        }
    )

    assert parsed.fill == "#00ff00"
    assert parsed.stroke_width == 3.0
    # Mapping-style categories (the established QGIS payload form) are accepted.
    assert ("channel", "#1971c2", "") in parsed.categories
    assert parsed.labels is not None and parsed.labels.field == "facies"


def test_geological_symbol_library_presets_exist() -> None:
    for name in ("fault", "contour", "formation_boundary", "well", "annotation", "facies"):
        assert name in STYLE_LIBRARY, name

    fault = STYLE_LIBRARY["fault"]
    assert fault.line_pattern is LinePattern.FAULT
    assert fault.line_pattern.dash_pattern(fault.stroke_width)

    well = STYLE_LIBRARY["well"]
    assert well.marker is MarkerSymbol.WELL

    contour = STYLE_LIBRARY["contour"]
    assert contour.labels is not None and contour.labels.visible


def test_line_patterns_have_dash_patterns_only_when_not_solid() -> None:
    assert LinePattern.SOLID.dash_pattern(1.0) == ()
    assert LinePattern.BOUNDARY.dash_pattern(1.0) == ()
    for pattern in (LinePattern.DASH, LinePattern.DOT, LinePattern.DASH_DOT, LinePattern.FAULT):
        dashes = pattern.dash_pattern(2.0)
        assert dashes and len(dashes) % 2 == 0
        assert all(value > 0.0 for value in dashes)


def test_default_style_for_matches_established_compatibility_colors() -> None:
    # Existing projects must render unchanged: the presets replace previously
    # hard-coded defaults with identical values.
    assert default_style_for("facies").fill == "#6c8ebf"
    assert default_style_for("facies").stroke == "#26364d"
    assert default_style_for("well").fill == "#22b8a7"
    assert default_style_for("line").stroke == "#f08c46"
    assert default_style_for("line").stroke_width == 2.0
    assert default_style_for("label").marker_size == 4.0


def test_style_library_save_and_load_round_trip(tmp_path) -> None:
    path = tmp_path / "styles.json"
    custom = {"my_fault": VectorStyle(stroke="#ff00ff", line_pattern=LinePattern.FAULT)}

    save_style_library(path, styles=custom)
    loaded = load_style_library(path)

    assert loaded["my_fault"] == custom["my_fault"]


def test_style_dict_revision_is_content_stable_and_change_sensitive() -> None:
    base = {"fill": "#111111", "stroke": "#222222", "nested": {"a": [1, 2, 3]}}

    assert style_dict_revision(base) == style_dict_revision(dict(base))
    assert style_dict_revision(base) != style_dict_revision({**base, "fill": "#333333"})
    assert style_dict_revision(base) != style_dict_revision(
        {"fill": "#111111", "stroke": "#222222", "nested": {"a": [1, 2, 4]}}
    )


def test_invalid_enum_values_fall_back_to_defaults() -> None:
    parsed = VectorStyle.from_dict({"line_pattern": "zigzag", "marker": "volcano"})

    assert parsed.line_pattern is LinePattern.SOLID
    assert parsed.marker is MarkerSymbol.CIRCLE
