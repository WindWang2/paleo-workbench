"""Offscreen visible-frame contract for the primary unified map canvas."""

from __future__ import annotations

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
