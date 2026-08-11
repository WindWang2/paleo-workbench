"""Deterministic, tolerance-friendly offscreen visual contracts for map composition."""

from __future__ import annotations

from PySide6.QtGui import QImage

from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.viz.native_factor_map import MapScene
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


BACKGROUND = (24, 28, 34)


def _scene() -> MapScene:
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 10.0], "grid_y": [0.0, 10.0],
            "grid_z": [[0.0, 1.0], [0.5, None]], "backend": "idw", "n_points": 3,
        },
        factor_name="Porosity", crs="EPSG:3857",
    )
    scene = MapScene()
    scene.add_factor_grid(result, layer_id="grid")
    scene.add_contours("contours", [[(0.0, 5.0), (10.0, 5.0)]], extent=result.extent, crs=result.crs)
    scene.add_sample_points("samples", [(1.0, 1.0)], extent=result.extent, crs=result.crs)
    scene.add_vector_layer(
        "facies",
        ({"id": "f1", "geometry": {"type": "Polygon", "coordinates": [[[6, 6], [9, 6], [6, 9], [6, 6]]]}, "properties": {"name": "delta"}},),
        name="Facies", extent=result.extent, crs=result.crs,
        style={"fill": "#e03131", "stroke": "#ffffff", "stroke_width": 1.0},
    )
    return scene


def _frame(scene: MapScene):
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(scene.render_snapshot(project_crs="EPSG:3857"))
    backend.set_extent((0.0, 0.0, 10.0, 10.0))
    backend.set_output_size(160, 120)
    return backend.render_sync()


def _image(frame) -> QImage:
    return QImage(frame.rgba, frame.width, frame.height, frame.stride, QImage.Format.Format_RGBA8888).copy()


def test_golden_fallback_composition_has_scalar_contour_symbol_and_polygon_layers() -> None:
    frame = _frame(_scene())
    image = _image(frame)

    scalar = image.pixelColor(20, 20)
    contour = image.pixelColor(80, 60)
    polygon = image.pixelColor(110, 25)
    assert (scalar.red(), scalar.green(), scalar.blue()) != BACKGROUND
    # Anti-aliasing blends the one-pixel contour with the scalar beneath it, so
    # assert a light neutral line rather than an unstable exact white byte value.
    assert min(contour.red(), contour.green(), contour.blue()) > 100
    assert max(contour.red(), contour.green(), contour.blue()) - min(contour.red(), contour.green(), contour.blue()) < 12
    assert polygon.red() > 150 and polygon.green() < 100 and polygon.blue() < 100


def test_golden_layer_opacity_and_order_change_only_the_composed_frame() -> None:
    scene = _scene()
    baseline = _frame(scene).rgba
    assert scene.set_layer_opacity("facies", 0.25)
    translucent = _frame(scene).rgba
    scene.registry.move_layer("facies", 0)
    reordered = _frame(scene).rgba

    assert baseline != translucent
    assert translucent != reordered


def test_golden_selection_and_decorations_are_overlay_only(qtbot) -> None:
    scene = _scene()
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.resize(160, 120)
    canvas.show()
    canvas.set_layer_snapshot(scene.render_snapshot(project_crs="EPSG:3857"))
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.waitUntil(lambda: canvas.last_frame is not None, timeout=2_000)
    base_frame = canvas.last_frame
    canvas.set_overlay_provider(lambda: {
        "selected_features": scene.vector_features("facies"),
        "decorations": {"title": "Final Map", "elements": ["标题栏", "比例尺", "指北针", "图例"], "legend_items": ["Grid", "Facies"]},
    })
    image = canvas.grab().toImage()

    yellow_pixels = sum(
        1
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).red() > 220 and image.pixelColor(x, y).green() > 180 and image.pixelColor(x, y).blue() < 130
    )
    assert yellow_pixels > 0
    assert canvas.last_frame is base_frame
