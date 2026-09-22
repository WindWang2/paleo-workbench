"""Fallback QPainter facies pattern-overlay tests (subtask ③).

A categorized polygon layer carrying ``fill_patterns`` must render as base
colour plus SVG linework texture; layers without patterns render exactly as
before.
"""

from __future__ import annotations

import numpy as np

from paleo_workbench.mapping.facies_brush_cache import FaciesPatternBrushCache
from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
    _category_patterns,
)
from paleo_workbench.mapping.map_styles import VectorStyle

_BASE = "#e6c9a8"
_BASE_2 = "#cfd8c9"


def _polygon_feature(feature_id: str, x0: float, x1: float, value: str) -> dict:
    return {
        "id": feature_id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[x0, 2.0], [x1, 2.0], [x1, 18.0], [x0, 18.0], [x0, 2.0]]
            ],
        },
        "properties": {"facies_name": value},
    }


def _render(style: dict, features: tuple[dict, ...], size: int = 200) -> np.ndarray:
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(
        MapRenderSnapshot(
            project_crs="EPSG:3857",
            layers=(
                MapLayerSnapshot(
                    id="facies",
                    name="Facies",
                    layer_type="vector",
                    extent=(0.0, 0.0, 20.0, 20.0),
                    crs="EPSG:3857",
                    data_revision=1,
                    style_revision=1,
                    features=features,
                    style=style,
                ),
            ),
        )
    )
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(size, size)
    backend.set_dpi(96.0)
    frame = backend.render_sync()
    return np.frombuffer(frame.rgba, dtype=np.uint8).reshape(
        (frame.height, frame.stride // 4, 4)
    )[:, : frame.width, :]


def _dark_count(image: np.ndarray, x0: int, x1: int, y0: int, y1: int) -> int:
    sub = image[y0:y1, x0:x1, :3].astype(int)
    return int((sub.max(axis=2) < 100).sum())


def _categorized_style(*, patterns: dict | None = None) -> dict:
    style = {
        "renderer": "categorized",
        "field": "facies_name",
        "categories": [["delta", _BASE, "d"], ["lacustrine", _BASE_2, "l"]],
        "stroke": "#26364d",
        "stroke_width": 1.0,
    }
    if patterns is not None:
        style["fill_patterns"] = patterns
    return style


def test_category_patterns_lookup() -> None:
    assert _category_patterns(VectorStyle()) is None
    assert _category_patterns(VectorStyle(renderer="categorized")) is None
    style = VectorStyle.from_dict(
        {"renderer": "categorized", "fill_patterns": {"delta": "delta"}}
    )
    assert _category_patterns(style) == {"delta": "delta"}


def test_brush_cache_resolves_tiles_and_misses() -> None:
    cache = FaciesPatternBrushCache()
    assert cache.path_for("delta") is not None
    assert cache.path_for("missing-xyz") is None
    assert cache.path_for(None) is None
    brush = cache.brush_for("delta")
    assert brush is not None
    assert cache.brush_for("delta") is brush
    assert cache.brush_for("missing-xyz") is None
    assert cache.brush_for("") is None


def test_pattern_overlay_adds_texture_over_base() -> None:
    features = (
        _polygon_feature("a", 2.0, 10.0, "delta"),
        _polygon_feature("b", 10.0, 18.0, "lacustrine"),
    )
    plain = _render(_categorized_style(), features)
    textured = _render(
        _categorized_style(patterns={"delta": "delta", "lacustrine": "lacustrine"}),
        features,
    )
    assert not np.array_equal(plain, textured)
    for window in ((40, 80), (120, 160)):
        x0, x1 = window
        assert _dark_count(plain, x0, x1, 60, 140) == 0
        assert _dark_count(textured, x0, x1, 60, 140) >= 20


def test_different_patterns_render_differently_on_identical_geometry() -> None:
    features = (_polygon_feature("a", 2.0, 18.0, "X"),)
    style = {
        "renderer": "categorized",
        "field": "facies_name",
        "categories": [["X", _BASE, "x"]],
        "stroke": "#26364d",
        "stroke_width": 1.0,
    }
    delta_style = dict(style, fill_patterns={"X": "delta"})
    lacustrine_style = dict(style, fill_patterns={"X": "lacustrine"})
    assert np.array_equal(_render(delta_style, features), _render(delta_style, features))
    assert not np.array_equal(
        _render(delta_style, features), _render(lacustrine_style, features)
    )
    assert np.array_equal(_render(style, features), _render(style, features))


def test_unknown_pattern_id_falls_back_to_base_fill() -> None:
    features = (
        _polygon_feature("a", 2.0, 10.0, "delta"),
        _polygon_feature("b", 10.0, 18.0, "lacustrine"),
    )
    plain = _render(_categorized_style(), features)
    unknown = _render(_categorized_style(patterns={"delta": "missing-xyz"}), features)
    assert np.array_equal(plain, unknown)


def test_class_without_pattern_entry_renders_base_only() -> None:
    features = (
        _polygon_feature("a", 2.0, 10.0, "delta"),
        _polygon_feature("b", 10.0, 18.0, "lacustrine"),
    )
    textured = _render(_categorized_style(patterns={"delta": "delta"}), features)
    assert _dark_count(textured, 40, 80, 60, 140) >= 20
    assert _dark_count(textured, 120, 160, 60, 140) == 0


def test_single_symbol_style_ignores_fill_patterns() -> None:
    features = (_polygon_feature("a", 2.0, 18.0, "delta"),)
    plain = {"fill": _BASE, "stroke": "#26364d", "stroke_width": 1.0}
    with_patterns = dict(plain, fill_patterns={"delta": "delta"})
    assert np.array_equal(_render(plain, features), _render(with_patterns, features))
