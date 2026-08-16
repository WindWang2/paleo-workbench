"""Uniform units-per-pixel: aspect-faithful map transforms (#522)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    fit_extent_to_aspect,
)
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas


def test_fit_extent_to_aspect_expands_short_axis_centered():
    ext = (0.0, 0.0, 10.0, 5.0)  # 2:1 world
    fitted = fit_extent_to_aspect(ext, 900, 900)  # 1:1 output
    xmin, ymin, xmax, ymax = fitted
    # World height expanded to 10 (aspect 1:1), centered.
    assert math.isclose(ymax - ymin, 10.0, rel_tol=1e-12)
    assert math.isclose(xmax - xmin, 10.0, rel_tol=1e-12)
    assert math.isclose(ymin, -2.5, rel_tol=1e-12)
    assert math.isclose(ymax, 7.5, rel_tol=1e-12)
    # Already-matching aspect is a no-op.
    assert fit_extent_to_aspect(ext, 800, 400) == ext


def test_canvas_roundtrip_preserves_shape_at_widget_aspect(qtbot):
    """screen_to_map / map_to_screen must be each other's inverse AND
    uniformly scaled — a world circle stays a circle at any widget size
    (the old independent x/y scales squashed it)."""
    canvas = UnifiedMapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 640)
    canvas.set_extent((0.0, 0.0, 10.0, 5.0), record_history=False)

    # units-per-pixel identical on both axes
    upp_x = (canvas._fitted_extent()[2] - canvas._fitted_extent()[0]) / 900
    upp_y = (canvas._fitted_extent()[3] - canvas._fitted_extent()[1]) / 640
    assert math.isclose(upp_x, upp_y, rel_tol=1e-9)

    # roundtrip stability
    pt = QPointF(123.0, 45.0)
    world = canvas.screen_to_map(pt)
    back = canvas.map_to_screen(world)
    assert math.isclose(back.x(), 123.0, abs_tol=1e-6)
    assert math.isclose(back.y(), 45.0, abs_tol=1e-6)

    # A world square maps to a screen square (equal pixel side lengths).
    a = canvas.map_to_screen((2.0, 1.0))
    b = canvas.map_to_screen((3.0, 1.0))
    c = canvas.map_to_screen((2.0, 2.0))
    dx = b.x() - a.x()
    dy = a.y() - c.y()
    assert math.isclose(dx, dy, rel_tol=1e-9), (dx, dy)

    # Resizing must not change shape fidelity.
    canvas.resize(640, 900)
    b2 = canvas.map_to_screen((3.0, 1.0))
    c2 = canvas.map_to_screen((2.0, 2.0))
    a2 = canvas.map_to_screen((2.0, 1.0))
    assert math.isclose(
        abs(b2.x() - a2.x()), abs(a2.y() - c2.y()), rel_tol=1e-9
    )


def test_backend_screen_point_letterboxes_uniformly():
    backend = FallbackMapRenderBackend()
    backend.set_extent((0.0, 0.0, 10.0, 5.0))
    backend.set_output_size(900, 900)
    p0 = backend._screen_point((0.0, 0.0))
    p1 = backend._screen_point((1.0, 0.0))
    p2 = backend._screen_point((0.0, 1.0))
    # One world unit covers the same pixel count on both axes.
    assert math.isclose(
        abs(p1.x() - p0.x()), abs(p0.y() - p2.y()), rel_tol=1e-9
    )


def test_export_png_default_height_follows_view_aspect(qtbot, tmp_path):
    canvas = UnifiedMapCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 640)
    canvas.set_extent((0.0, 0.0, 10.0, 5.0), record_history=False)

    out = tmp_path / "map.png"
    canvas.export_png(str(out), width=2400)
    from PySide6.QtGui import QImage

    img = QImage(str(out))
    assert not img.isNull()
    # Height derived from the 2:1 view aspect — not the old fixed 1600.
    assert img.height() == 1200
    assert img.width() == 2400
