"""Offscreen host-canvas composition, cache, pan, and zoom contract."""

from __future__ import annotations

from PySide6.QtGui import QColor

from paleo_workbench.ui.native_map_canvas import NativeMapCanvas
from paleo_workbench.viz.native_factor_map import NativeMapScene
from tests.test_native_factor_map import _result


def _scene() -> NativeMapScene:
    scene = NativeMapScene()
    result = _result()
    scene.add_factor_grid(result, layer_id="surface")
    scene.add_contours("contours", [[(10.0, 35.0), (20.0, 35.0)]], extent=result.extent)
    scene.add_sample_points("samples", [(15.0, 35.0)], extent=result.extent)
    return scene


def test_native_canvas_composes_layers_and_reuses_scalar_cache(qtbot):
    scene = _scene()
    canvas = NativeMapCanvas(scene)
    qtbot.addWidget(canvas)
    canvas.resize(320, 200)
    canvas.show()
    canvas.repaint()

    scalar = scene.scalar_layer("surface")
    canvas.grab()
    qtbot.waitUntil(lambda: scalar.rasterize_count == 1, timeout=3000)
    image = canvas.grab().toImage()
    assert scalar.rasterize_count == 1
    assert image.deviceIndependentSize().toSize() == canvas.size()
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    assert center != QColor("#000000")

    scene.set_layer_opacity("surface", 0.25)
    canvas.repaint()
    canvas.grab()
    assert scalar.rasterize_count == 1
    scene.set_scalar_style("surface", gamma=2.0)
    canvas.repaint()
    canvas.grab()
    qtbot.waitUntil(lambda: scalar.rasterize_count == 2, timeout=3000)
    assert scalar.rasterize_count == 2


def test_native_canvas_pan_zoom_and_zoom_to_layer(qtbot):
    scene = _scene()
    canvas = NativeMapCanvas(scene)
    qtbot.addWidget(canvas)
    canvas.resize(300, 180)
    canvas.show()
    initial = canvas.view_extent
    canvas.zoom_by(0.5)
    zoomed = canvas.view_extent
    assert (zoomed[2] - zoomed[0]) < (initial[2] - initial[0])
    canvas.pan_by_pixels(20, 10)
    panned = canvas.view_extent
    assert panned != zoomed
    canvas.zoom_to_extent(scene.registry.get("surface").extent)
    assert canvas.view_extent == (10.0, 30.0, 20.0, 40.0)
