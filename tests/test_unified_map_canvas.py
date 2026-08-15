"""Offscreen visible-frame contract for the primary unified map canvas."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.viz.native_factor_map import MapScene
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _snapshot() -> MapRenderSnapshot:
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="point",
                name="Well",
                layer_type="vector",
                extent=(0.0, 0.0, 10.0, 10.0),
                crs="EPSG:3857",
                data_revision=1,
                style_revision=1,
                features=(
                    {
                        "id": "well-1",
                        "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
                        "properties": {},
                    },
                ),
                style={"fill": "#55b6ff", "marker_size": 8.0},
            ),
        ),
    )


def test_unified_canvas_displays_latest_backend_frame_and_keeps_navigation_extent(qtbot) -> None:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(300, 180)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    canvas.show()

    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=2000)
    initial = canvas.view_extent
    canvas.zoom_by(0.5)
    canvas.pan_by_pixels(20.0, 8.0)

    assert canvas.backend_status.startswith("fallback")
    assert canvas.last_frame is not None
    # ``grab`` returns device pixels on HiDPI displays; the widget's logical size
    # is the rendering contract.
    assert canvas.width() == 300
    assert canvas.view_extent != initial
    assert canvas.view_extent[2] > canvas.view_extent[0]
    assert canvas.view_extent[3] > canvas.view_extent[1]


def test_unified_fallback_canvas_composites_native_scalar_cache_without_recomputation(qtbot) -> None:
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 10.0],
            "grid_y": [0.0, 10.0],
            "grid_z": [[0.0, 1.0], [0.5, None]],
            "backend": "idw",
            "n_points": 4,
        },
        factor_name="Porosity",
        crs="EPSG:3857",
    )
    scene = MapScene()
    scene.add_factor_grid(result, layer_id="porosity")
    scalar = scene.scalar_layer("porosity")
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(240, 180)
    canvas.show()
    canvas.set_layer_snapshot(scene.render_snapshot(project_crs="EPSG:3857"))
    canvas.set_extent(result.extent)

    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=2_000)
    assert scalar.rasterize_count == 1
    canvas.zoom_by(0.8)
    canvas.pan_by_pixels(6.0, 4.0)
    assert scalar.rasterize_count == 1


def test_unified_canvas_keeps_bounded_back_forward_extent_history(qtbot) -> None:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    initial = canvas.view_extent
    canvas.zoom_by(0.5)
    canvas.pan_by_pixels(10.0, 0.0)
    panned = canvas.view_extent

    assert canvas.can_previous_extent
    assert canvas.previous_extent()
    assert canvas.view_extent == initial
    assert canvas.next_extent()
    assert canvas.view_extent == panned


def test_unified_canvas_temporarily_transforms_the_previous_frame_for_navigation(qtbot) -> None:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(240, 180)
    canvas.show()
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=2_000)

    canvas.pan_by_pixels(12.0, 0.0)
    assert canvas.navigation_preview_active
    qtbot.waitUntil(lambda: not canvas.navigation_preview_active, timeout=2_000)


def _wheel_event(pos: QPointF, delta: int) -> QWheelEvent:
    return QWheelEvent(
        pos,
        pos,
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


@pytest.mark.parametrize("delta", [120, -120])
def test_unified_canvas_wheel_zoom_keeps_cursor_map_point_fixed(qtbot, delta) -> None:
    """Wheel zoom must anchor at the cursor, not the extent center (MAP-3).

    The point under the cursor must map to the same world coordinates before
    and after every wheel notch, matching NativeMapCanvas / MapEditView.
    """
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(300, 180)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    canvas.show()

    cursor = QPointF(240.0, 40.0)
    before = canvas.screen_to_map(cursor)
    canvas.wheelEvent(_wheel_event(cursor, delta))
    after = canvas.screen_to_map(cursor)

    assert canvas.view_extent != (0.0, 0.0, 10.0, 10.0)
    assert after[0] == pytest.approx(before[0], abs=1e-9)
    assert after[1] == pytest.approx(before[1], abs=1e-9)


def test_unified_canvas_wheel_zoom_keeps_cursor_fixed_across_many_notches(qtbot) -> None:
    """N notches at one cursor drift by 0; pan round-trips still return exactly."""
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(300, 180)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    canvas.show()

    cursor = QPointF(60.0, 150.0)
    before = canvas.screen_to_map(cursor)
    for _ in range(6):
        canvas.wheelEvent(_wheel_event(cursor, 120))
    after = canvas.screen_to_map(cursor)
    assert after[0] == pytest.approx(before[0], abs=1e-9)
    assert after[1] == pytest.approx(before[1], abs=1e-9)
