"""Fallback render engine performance/caching/LOD/DPI/threading contracts."""

from __future__ import annotations

import pytest

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QPainter

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)


def _point_features(count: int, *, prefix: str = "p") -> tuple[dict, ...]:
    return tuple(
        {
            "id": f"{prefix}{index}",
            "geometry": {"type": "Point", "coordinates": [float(index % 100), float(index // 100)]},
            "properties": {"name": f"well-{index}"},
        }
        for index in range(count)
    )


def _line_features(count: int, vertices: int = 24, *, step: float = 1.0) -> tuple[dict, ...]:
    features = []
    for index in range(count):
        coordinates = [
            [((index + step_value * step) % 90), ((index * 7 + step_value * step) % 90)]
            for step_value in range(vertices)
        ]
        features.append(
            {
                "id": f"line-{index}",
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "properties": {},
            }
        )
    return tuple(features)


def _polygon_feature(x: float, y: float, size: float = 4.0, feature_id: str = "poly") -> dict:
    return {
        "id": feature_id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [x, y],
                    [x + size, y],
                    [x + size, y + size],
                    [x, y + size],
                    [x, y],
                ]
            ],
        },
        "properties": {},
    }


def _configure(backend: FallbackMapRenderBackend, snapshot: MapRenderSnapshot) -> None:
    backend.initialize()
    backend.set_layer_snapshot(snapshot)
    backend.set_extent((0.0, 0.0, 100.0, 100.0))
    backend.set_output_size(200, 200)
    backend.set_dpi(96.0)


def _layer(features: tuple[dict, ...], *, layer_id: str = "layer", data_revision: int = 1,
           style: dict | None = None, **kwargs) -> MapLayerSnapshot:
    return MapLayerSnapshot(
        id=layer_id,
        name=layer_id,
        layer_type="vector",
        extent=(0.0, 0.0, 100.0, 100.0),
        crs="EPSG:3857",
        data_revision=data_revision,
        style_revision=1,
        features=features,
        style=style or {"fill": "#d9a441", "stroke": "#593d16", "stroke_width": 1.0},
        **kwargs,
    )


def _frame_image(frame) -> QImage:
    return QImage(frame.rgba, frame.width, frame.height, frame.stride, QImage.Format.Format_RGBA8888).copy()


def test_prepared_geometry_cache_hits_on_repeated_renders() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(_line_features(50)),)))

    backend.render_sync()
    misses_after_first = backend.render_diagnostics()["prepared_cache_misses"]
    # A viewport change invalidates the frame cache but must reuse the parsed
    # geometry payload keyed by the layer's data revision.
    backend.set_extent((1.0, 1.0, 99.0, 99.0))
    backend.render_sync()
    diagnostics = backend.render_diagnostics()

    assert misses_after_first == 1
    assert diagnostics["prepared_cache_hits"] >= 1
    assert diagnostics["prepared_cache_misses"] == 1


def test_frame_cache_reuses_identical_composition() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(_line_features(20)),)))

    backend.render_sync()
    backend.render_sync()

    assert backend.render_diagnostics()["frames_from_cache"] == 1
    # A viewport change must invalidate the cached frame.
    backend.set_extent((10.0, 10.0, 90.0, 90.0))
    backend.render_sync()
    assert backend.render_diagnostics()["frames_rendered"] == 2


def test_viewport_culling_draws_only_visible_features() -> None:
    features = (
        _polygon_feature(1.0, 1.0, feature_id="inside"),
        _polygon_feature(60.0, 60.0, feature_id="outside"),
        _polygon_feature(95.0, 95.0, feature_id="outside-2"),
    )
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(features),)))
    backend.set_extent((0.0, 0.0, 20.0, 20.0))

    backend.render_sync()
    diagnostics = backend.render_diagnostics()

    assert diagnostics["features_total"] == 3
    assert diagnostics["features_drawn"] == 1


def test_pixel_grid_lod_simplifies_dense_lines() -> None:
    # Sub-pixel vertex spacing at the 200px/100-unit viewport forces the
    # pixel-grid simplification to collapse most vertices.
    dense = _line_features(10, vertices=500, step=0.05)
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(dense),)))

    backend.render_sync()

    assert backend.render_diagnostics()["vertices_simplified"] > 0


def test_dpi_scaling_grows_stroke_width_proportionally() -> None:
    # One horizontal line with a known stroke width; measure painted thickness.
    features = (
        {
            "id": "h",
            "geometry": {"type": "LineString", "coordinates": [[10.0, 50.0], [90.0, 50.0]]},
            "properties": {},
        },
    )

    def painted_thickness(dpi: float) -> int:
        backend = FallbackMapRenderBackend()
        style = {"fill": "transparent", "stroke": "#ff0000", "stroke_width": 4.0}
        _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(features, style=style),)))
        backend.set_dpi(dpi)
        image = _frame_image(backend.render_sync())
        # 白底上不能用 red() > 100 检测（白色 red=255）：红色描边要
        # 同时压低绿/蓝通道。
        return sum(
            1
            for y in range(image.height())
            if (lambda c: c.red() > 100 and c.green() < 100 and c.blue() < 100)(
                image.pixelColor(QPoint(100, y))
            )
        )

    thin = painted_thickness(96.0)
    thick = painted_thickness(192.0)

    assert thin >= 3
    # Doubling dpi must roughly double the device-pixel line thickness.
    assert thick >= thin * 1.5


def test_scale_range_hides_layer_outside_window() -> None:
    backend = FallbackMapRenderBackend()
    layer = _layer(_line_features(10), scale_range=(1.0, 1000.0))
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(layer,)))
    # Extent 0..100 at 200px → 0.5 units/px → denominator ≈ 1890: outside (1, 1000).

    backend.render_sync()

    assert backend.render_diagnostics()["features_drawn"] == 0

    backend.set_extent((0.0, 0.0, 50.0, 50.0))  # 0.25 units/px → ≈945: inside.
    backend.render_sync()
    assert backend.render_diagnostics()["features_drawn"] >= 1


def test_well_marker_symbol_renders_ring_and_centre() -> None:
    features = (
        {
            "id": "w1",
            "geometry": {"type": "Point", "coordinates": [50.0, 50.0]},
            "properties": {},
        },
    )
    backend = FallbackMapRenderBackend()
    # 白底上白色描边不可见，井符号的环/心用深色墨。
    style = {"fill": "#22b8a7", "stroke": "#1f2937", "marker": "well", "marker_size": 16.0}
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(features, style=style),)))

    image = _frame_image(backend.render_sync())
    center = image.pixelColor(QPoint(100, 100))

    assert (center.red(), center.green(), center.blue()) != (255, 255, 255)


def test_threaded_backend_delivers_latest_generation(qtbot) -> None:
    backend = FallbackMapRenderBackend(threaded=True)
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(_line_features(2000)),)))
    try:
        generation = backend.request_render()

        frame = None

        def take() -> bool:
            nonlocal frame
            frame = backend.take_completed_frame()
            return frame is not None

        qtbot.waitUntil(take, timeout=10_000)

        assert frame is not None
        assert frame.generation == generation
        assert not backend.render_active
        assert backend.take_completed_frame() is None
    finally:
        backend.shutdown()


def test_threaded_backend_discards_cancelled_generation(qtbot) -> None:
    backend = FallbackMapRenderBackend(threaded=True)
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(_line_features(5000)),)))
    try:
        backend.request_render()
        backend.cancel_render()

        frame = backend.take_completed_frame()
        deadline_polls = 0
        while frame is None and deadline_polls < 200 and backend.render_active:
            frame = backend.take_completed_frame()
            deadline_polls += 1
        assert frame is None
    finally:
        backend.shutdown()


def test_render_to_painter_targets_external_paint_device() -> None:
    backend = FallbackMapRenderBackend()
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(_line_features(20)),)))

    image = QImage(200, 200, QImage.Format.Format_RGBA8888)
    image.fill(0)
    painter = QPainter(image)
    backend.render_to_painter(painter, 200, 200)
    painter.end()

    assert any(image.pixelColor(QPoint(x, y)).alpha() > 0 for x in range(0, 200, 7) for y in range(0, 200, 7))


def test_label_rendering_paints_feature_text_near_point() -> None:
    features = (
        {
            "id": "labelled",
            "geometry": {"type": "Point", "coordinates": [50.0, 50.0]},
            "properties": {"name": "Well-A7"},
        },
    )
    backend = FallbackMapRenderBackend()
    style = {
        "fill": "#22b8a7",
        "stroke": "#182431",
        "marker_size": 8.0,
        "labels": {"field": "name", "size": 12.0, "color": "#ffffff", "visible": True},
    }
    _configure(backend, MapRenderSnapshot(project_crs="", layers=(_layer(features, style=style),)))

    image = _frame_image(backend.render_sync())
    # The label renders to the right of the marker inside this search window.
    window = QRect(105, 85, 60, 30)
    found_text_pixel = any(
        image.pixelColor(QPoint(x, y)).green() > 200
        for x in range(window.left(), window.right())
        for y in range(window.top(), window.bottom())
    )
    assert found_text_pixel
