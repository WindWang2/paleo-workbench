"""Offscreen visible-frame contract for the primary unified map canvas."""

from __future__ import annotations

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
    assert canvas.grab().toImage().size().width() == 300
    assert canvas.view_extent != initial
    assert canvas.view_extent[2] > canvas.view_extent[0]
    assert canvas.view_extent[3] > canvas.view_extent[1]
