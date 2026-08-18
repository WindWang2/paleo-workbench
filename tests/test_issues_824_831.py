"""Regression tests for #824 and #831 (unified map canvas).

#824: ``mouseMoveEvent`` referenced an unassigned local ``handled`` and emitted
``tool_operation`` without its required bool payload — every tool hover/drag
raised NameError inside the override (swallowed by shiboken), so rubber lines
never repainted and the signal never fired.

#831: #522's letterbox fix covered exports but the *screen* chrome and pan
math still used the raw view extent — the on-screen scale bar was mislabeled
by up to 2× on the expanded axis (contradicting the export bar), and drags
jumped back half their travel once the re-rendered frame arrived.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas


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


def _canvas(qtbot, width: int = 400, height: int = 200) -> UnifiedMapCanvas:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(width, height)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    canvas.show()
    qtbot.waitUntil(lambda: canvas.width() == width and canvas.height() == height, timeout=2000)
    return canvas


class _RecordingTool:
    edits_data = False

    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []

    def mouse_move(self, point, *, modifiers=()) -> bool:
        self.moves.append(tuple(point))
        return True


class _Controller:
    def __init__(self, tool) -> None:
        self.active_tool = tool


def test_tool_mouse_move_emits_bool_and_schedules_repaint(qtbot, monkeypatch) -> None:
    """#824: a handled tool hover emits tool_operation(bool) and repaints."""
    canvas = _canvas(qtbot)
    tool = _RecordingTool()
    canvas.set_map_tool_controller(_Controller(tool))
    emitted: list[bool] = []
    canvas.tool_operation.connect(emitted.append)
    updates: list[int] = []
    monkeypatch.setattr(canvas, "update", lambda: updates.append(1))

    qtbot.mouseMove(canvas, pos=QPoint(120, 60))
    qtbot.wait(10)

    assert tool.moves, "tool.mouse_move was never reached"
    # Pre-fix, the override aborted on NameError before emitting anything.
    assert emitted and isinstance(emitted[0], bool) and emitted[0] is False
    assert updates, "handled hover must schedule an overlay repaint"


def test_pan_by_pixels_keeps_world_point_under_cursor(qtbot) -> None:
    """#831: pan converts pixels via the letterboxed span, not the raw span."""
    canvas = _canvas(qtbot, 400, 200)  # 2:1 widget, square view → x span 20
    world = (5.0, 5.0)

    start = canvas.map_to_screen(world)
    canvas.pan_by_pixels(40.0, 0.0)
    after = canvas.map_to_screen(world)
    # Dragging right by 40 px must move the content right by exactly 40 px.
    assert after.x() - start.x() == pytest.approx(40.0, abs=0.5)

    start_y = canvas.map_to_screen(world)
    canvas.pan_by_pixels(0.0, 30.0)
    after_y = canvas.map_to_screen(world)
    assert after_y.y() - start_y.y() == pytest.approx(30.0, abs=0.5)


def test_screen_scale_bar_measures_the_letterboxed_extent(qtbot, monkeypatch) -> None:
    """#831: screen chrome must read the fitted extent, matching the export bar."""
    canvas = _canvas(qtbot, 400, 200)
    canvas.set_overlay_provider(lambda: {"decorations": {}})
    captured: dict = {}
    original = UnifiedMapCanvas._paint_decorations

    def spy(painter, decorations, **kwargs):
        captured.update(kwargs)
        return original(canvas, painter, decorations, **kwargs)

    monkeypatch.setattr(canvas, "_paint_decorations", spy)
    canvas.grab()

    extent = captured.get("extent")
    assert extent is not None, "screen paint must pass an explicit extent"
    xmin, _, xmax, _ = extent
    # View 10×10 letterboxed into a 2:1 widget → fitted x span is 20, not 10.
    assert xmax - xmin == pytest.approx(20.0)
    spec = UnifiedMapCanvas._scale_bar_spec(extent, canvas.width())
    assert spec is not None
    units, pixels = spec
    # The bar is a true measurement: bar pixels × units-per-pixel == label.
    assert pixels * canvas.map_units_per_pixel == pytest.approx(units, rel=1e-6)


def test_export_and_screen_scale_bars_agree(qtbot) -> None:
    """The exported bar and the screen bar must describe the same geometry."""
    canvas = _canvas(qtbot, 400, 200)
    screen_spec = UnifiedMapCanvas._scale_bar_spec(canvas._fitted_extent(), canvas.width())
    export_spec = UnifiedMapCanvas._scale_bar_spec(
        canvas._letterboxed_extent(canvas.width(), canvas.height()), canvas.width()
    )
    assert screen_spec is not None and export_spec is not None
    assert screen_spec == export_spec
