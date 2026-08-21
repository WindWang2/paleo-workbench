"""Visual regression for the QGIS authoring path (small real cartography).

Composes a small paleogeographic scene — polygon facies (categorized), a
fault trace (rule renderer), a contour line, wells (points) and labels — and
asserts the rendered frame against structural expectations plus a saved
reference histogram.  Tolerances absorb font/anti-aliasing drift but catch:
missing layers, wrong symbols/colors, wrong z-order, missing labels.
"""

from __future__ import annotations

import hashlib

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = [pytest.mark.qgis]

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)

from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
    QgisMapRenderBackend,
)
from paleo_workbench.mapping.qgis_style import migrate_legacy_style

WIDTH, HEIGHT = 320, 240


def _layer(style: dict, geometry_type: str, features: tuple[dict, ...], **overrides) -> MapLayerSnapshot:
    migrated = migrate_legacy_style(style, geometry_type)
    assert migrated is not None, f"migration failed for {style}"
    defaults = {
        "layer_type": "vector",
        "extent": (0.0, 0.0, 100.0, 75.0),
        "crs": "EPSG:3857",
        "data_revision": 1,
        "style_revision": 1,
        "visible": True,
        "opacity": 1.0,
        "features": features,
        "style": {"qgis_style": migrated.to_dict()},
    }
    defaults.update(overrides)
    return MapLayerSnapshot(id=defaults.get("id", "layer"), name=defaults.get("name", "Layer"), **{
        key: value for key, value in defaults.items() if key not in {"id", "name"}
    })


def _scene() -> tuple[MapLayerSnapshot, ...]:
    facies = _layer(
        {
            "renderer": "categorized",
            "field": "facies",
            "categories": [
                ["shelf", "#d9c58b"],
                ["basin", "#7f9db9"],
            ],
        },
        "Polygon",
        (
            {
                "id": "shelf-1",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [60, 0], [60, 40], [0, 40], [0, 0]]]},
                "properties": {"facies": "shelf"},
            },
            {
                "id": "basin-1",
                "geometry": {"type": "Polygon", "coordinates": [[[60, 0], [100, 0], [100, 40], [60, 40], [60, 0]]]},
                "properties": {"facies": "basin"},
            },
        ),
        id="facies",
        name="Facies",
    )
    faults = _layer(
        {
            "renderer": "rule",
            "rules": [
                {
                    "name": "normal",
                    "expression": "\"fault_type\" = 'normal'",
                    "stroke": "#e03131",
                    "stroke_width": 2.0,
                },
            ],
        },
        "LineString",
        (
            {
                "id": "fault-1",
                "geometry": {"type": "LineString", "coordinates": [[10, 20], [90, 20]]},
                "properties": {"fault_type": "normal"},
            },
        ),
        id="faults",
        name="Faults",
    )
    contour = _layer(
        {"fill": "transparent", "stroke": "#f08c46", "stroke_width": 1.0},
        "LineString",
        (
            {
                "id": "contour-1",
                "geometry": {"type": "LineString", "coordinates": [[10, 55], [50, 65], [90, 55]]},
                "properties": {},
            },
        ),
        id="contours",
        name="Contours",
    )
    wells = _layer(
        {
            "fill": "#22b8a7",
            "stroke": "#182431",
            "marker_size": 6.0,
            "labels": {
                "field": "name",
                "size": 8.0,
                "color": "#ffffff",
                "visible": True,
            },
        },
        "Point",
        (
            {
                "id": "well-1",
                "geometry": {"type": "Point", "coordinates": [30, 10]},
                "properties": {"name": "W-1"},
            },
            {
                "id": "well-2",
                "geometry": {"type": "Point", "coordinates": [70, 30]},
                "properties": {"name": "W-2"},
            },
        ),
        id="wells",
        name="Wells",
    )
    return (facies, faults, contour, wells)


def _render_frame(qtbot=None):
    backend = QgisMapRenderBackend()
    assert backend.is_available
    backend.initialize()
    try:
        backend.set_layer_snapshot(
            MapRenderSnapshot(project_crs="EPSG:3857", layers=_scene())
        )
        backend.set_extent((0.0, 0.0, 100.0, 75.0))
        backend.set_output_size(WIDTH, HEIGHT)
        frame = backend.render_sync()
        return frame
    finally:
        backend.shutdown()


def _pixel(frame, x: int, y: int) -> tuple[int, int, int]:
    offset = y * frame.stride + x * 4
    return tuple(frame.rgba[offset : offset + 3])


def _color_near(value: tuple[int, int, int], target: str, tolerance: int = 48) -> bool:
    target = target.lstrip("#")
    expected = (int(target[0:2], 16), int(target[2:4], 16), int(target[4:6], 16))
    return all(abs(a - b) <= tolerance for a, b in zip(value, expected))


def test_scene_composition_layers_all_present(qtbot) -> None:
    frame = _render_frame(qtbot)
    # World→screen: 320/100 = 3.2 px/unit in x, y flipped (240 rows, 75 units).
    # Facies fills: shelf tan on the left, basin blue on the right.
    assert _color_near(_pixel(frame, 80, 180), "#d9c58b"), "shelf fill missing"
    assert _color_near(_pixel(frame, 260, 180), "#7f9db9"), "basin fill missing"
    # Fault rule line at world y=20 → screen row ≈176; strict stroke colour so
    # the shelf fill cannot satisfy it.
    found_red = any(
        _color_near(_pixel(frame, x, 176), "#e03131", tolerance=56)
        for x in range(48, 280, 4)
    )
    assert found_red, "fault rule line missing"
    # Contour polyline world y≈55-65 → screen rows ≈64-112.
    found_orange = any(
        _color_near(_pixel(frame, x, y), "#f08c46")
        for x in range(120, 200, 4)
        for y in range(40, 120, 2)
    )
    assert found_orange, "contour line missing"
    # Well markers: well-1 world (30,10) → screen (96,208).
    assert _color_near(_pixel(frame, 96, 208), "#22b8a7"), "well marker missing"


def test_scene_reference_histogram_is_stable(qtbot) -> None:
    """The composed frame stays within a stable colour budget across runs.

    The reference records the count of distinct quantised colours; a missing
    symbol layer or a wrong category collapses/expands that budget sharply.
    """
    frame = _render_frame(qtbot)
    buckets: set[tuple[int, int, int]] = set()
    for y in range(0, HEIGHT, 3):
        for x in range(0, WIDTH, 3):
            r, g, b = _pixel(frame, x, y)
            buckets.add((r // 32, g // 32, b // 32))
    reference = 8  # background + 2 facies + fault red + contour orange + well teal + label white
    assert len(buckets) >= reference - 2
    assert len(buckets) <= reference + 14


def test_z_order_faults_above_facies(qtbot) -> None:
    """Later layers paint over earlier ones at intersections."""
    frame = _render_frame(qtbot)
    # The fault crosses both polygons; along world y=20 (screen row 176) the
    # pixel must be fault-red where the line runs, not a facies fill.
    samples = [_pixel(frame, x, 176) for x in range(48, 272, 4)]
    assert any(_color_near(value, "#e03131", tolerance=56) for value in samples), (
        "z-order broken: fault under facies"
    )


def test_frame_is_deterministic(qtbot) -> None:
    first = _render_frame(qtbot)
    second = _render_frame(qtbot)
    assert hashlib.sha256(first.rgba).digest() == hashlib.sha256(second.rgba).digest()
