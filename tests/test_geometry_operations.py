"""Unified geometry-operations facade (goal §4).

Every generic GIS operation has ONE entry point here.  The bridge
(``qgis_render_bridge.geometry``) is the preferred engine; results always
disclose which engine ran (QGIS | shapely-fallback | host), so degradation
is visible, never silent.  These tests run WITHOUT the bridge (fallback
engines); ``test_geometry_operations_qgis.py`` covers QGIS parity when the
bridge is built.
"""

from __future__ import annotations

import math

import pytest

from paleo_workbench.mapping import geometry_operations as ops

SQ_A = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
SQ_B = {"type": "Polygon", "coordinates": [[[5, 5], [15, 5], [15, 15], [5, 15], [5, 5]]]}
LINE = {"type": "LineString", "coordinates": [[0, 0], [10, 0], [10, 10]]}
MULTI = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        [[[2, 2], [3, 2], [3, 3], [2, 2]]],
    ],
}
BOWTIE = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]],
}


def _area(geom: dict) -> float:
    if geom["type"] == "Polygon":
        ring = geom["coordinates"][0]
        return abs(sum(
            ring[i][0] * ring[(i + 1) % len(ring)][1]
            - ring[(i + 1) % len(ring)][0] * ring[i][1]
            for i in range(len(ring)))) / 2
    if geom["type"] == "MultiPolygon":
        return sum(_area({"type": "Polygon", "coordinates": poly})
                   for poly in geom["coordinates"])
    raise AssertionError(geom["type"])


def test_engine_disclosure_on_every_op():
    assert ops.ENGINE_QGIS == "qgis"
    assert ops.ENGINE_SHAPELY == "shapely-fallback"
    assert ops.ENGINE_HOST == "host"
    probe = ops.engine_status()
    assert probe["bridge_available"] in (True, False)
    assert isinstance(probe["ops"], dict) and len(probe["ops"]) >= 20
    for op_name, engine in probe["ops"].items():
        assert engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY, ops.ENGINE_HOST), (
            op_name, engine)


def test_intersection_area_matches():
    result = ops.intersection(SQ_A, SQ_B)
    assert result.engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY)
    assert _area(result.geometry) == pytest.approx(25.0)


def test_difference_and_symdifference():
    diff = ops.difference(SQ_A, SQ_B)
    assert _area(diff.geometry) == pytest.approx(75.0)
    sym = ops.symdifference(SQ_A, SQ_B)
    assert _area(sym.geometry) == pytest.approx(150.0)


def test_union_and_dissolve():
    union = ops.union([SQ_A, SQ_B])
    assert _area(union.geometry) == pytest.approx(175.0)
    dissolved = ops.dissolve([SQ_A, SQ_B])
    assert dissolved.engine == union.engine
    assert _area(dissolved.geometry) == pytest.approx(175.0)


def test_buffer_grows_area():
    buffered = ops.buffer(SQ_A, 2.0, segments=16)
    assert _area(buffered.geometry) > 100.0


def test_clip_bbox():
    clipped = ops.clip(SQ_A, (2, 2, 8, 8))
    assert _area(clipped.geometry) == pytest.approx(36.0)


def test_multipart_roundtrip():
    parts = ops.multipart_to_singlepart(MULTI)
    assert parts.engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY)
    assert isinstance(parts.geometries, list) and len(parts.geometries) == 2
    merged = ops.singlepart_to_multipart(parts.geometries)
    assert merged.geometry["type"] == "MultiPolygon"
    assert len(merged.geometry["coordinates"]) == 2


def test_simplify_keeps_shape():
    dense = {"type": "LineString", "coordinates": [
        [0, 0], [1, 0.01], [2, 0], [3, 0.01], [4, 0], [5, 0]]}
    simplified = ops.simplify(dense, 0.5)
    assert len(simplified.geometry["coordinates"]) < len(dense["coordinates"])


def test_densify_adds_vertices():
    densified = ops.densify(LINE, 1.0)
    assert len(densified.geometry["coordinates"]) > len(LINE["coordinates"])


def test_validate_detects_bowtie():
    verdict = ops.validate(BOWTIE)
    assert verdict.engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY)
    assert verdict.valid is False
    ok = ops.validate(SQ_A)
    assert ok.valid is True


def test_repairs_bowtie():
    repaired = ops.repair(BOWTIE)
    assert repaired.engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY)
    assert _area(repaired.geometry) == pytest.approx(50.0)


def test_polygonize_closed_rings():
    rings = [
        {"type": "LineString", "coordinates": [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]},
    ]
    polygons = ops.polygonize(rings)
    assert polygons.engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY)
    assert _area(polygons.geometry) == pytest.approx(16.0)


def test_line_merge_joins_segments():
    segments = [
        {"type": "LineString", "coordinates": [[0, 0], [5, 0]]},
        {"type": "LineString", "coordinates": [[5, 0], [10, 0]]},
    ]
    merged = ops.line_merge(segments)
    assert merged.engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY)
    geoms = merged.geometries if merged.geometries else [merged.geometry]
    def _xy(pos):
        return (float(pos[0]), float(pos[1]))

    assert any(
        g["type"] == "LineString"
        and _xy(g["coordinates"][0]) == (0.0, 0.0)
        and _xy(g["coordinates"][-1]) == (10.0, 0.0)
        for g in geoms)


def test_point_in_polygon():
    inside = ops.point_in_polygon((5, 5), SQ_A)
    outside = ops.point_in_polygon((20, 20), SQ_A)
    assert inside.contains is True and outside.contains is False
    assert inside.engine == ops.ENGINE_HOST  # documented host authority


def test_area_length_with_unit_labels():
    # V6 §15 honest-unit policy: projected CRS areas are CRS-axis squares,
    # geographic areas are labelled local-scale approximations.
    m = ops.area_with_unit(SQ_A, crs="EPSG:32650")
    assert m.engine == ops.ENGINE_HOST
    assert m.unit == "EPSG:32650-unit²"
    assert m.value == pytest.approx(100.0)
    deg = ops.area_with_unit(SQ_A, crs="EPSG:4326")
    assert "≈m²" in deg.unit  # labelled approximation, never silent deg²
    length = ops.length_with_unit(LINE, crs="EPSG:32650")
    assert length.value == pytest.approx(20.0)
    assert length.unit == "EPSG:32650-unit"


def test_bounding_geometry():
    bbox = ops.bounding_geometry([SQ_A, SQ_B])
    assert bbox == (0.0, 0.0, 15.0, 15.0)


def test_nearest_feature():
    points = [
        {"id": "a", "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {"id": "b", "geometry": {"type": "Point", "coordinates": [10, 0]}},
    ]
    hit = ops.nearest_feature((9, 0), points)
    assert hit["id"] == "b"


def test_topology_check_reports_ring_issues():
    report = ops.topology_check([SQ_A, BOWTIE])
    assert report.engine == ops.ENGINE_SHAPELY
    assert report.invalid_count == 1
    assert report.issues and "bowtie" not in report.issues[0].lower()


def test_offset_curve_and_smooth_exist():
    offset = ops.offset_curve(LINE, 1.0)
    assert offset.engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY)
    smooth = ops.smooth(LINE, iterations=1)
    assert smooth.engine in (ops.ENGINE_QGIS, ops.ENGINE_SHAPELY)
    assert len(smooth.geometry["coordinates"]) >= len(LINE["coordinates"])


def test_unavailable_without_bridge_is_not_silent():
    """When the bridge is missing, bridge-only ops must say so — never
    pretend to be QGIS."""
    status = ops.engine_status()
    for op_name, engine in status["ops"].items():
        if engine == ops.ENGINE_QGIS:
            assert status["bridge_available"] is True, (
                f"{op_name} claims QGIS without the bridge")


def test_crs_transform_delegates_to_existing_authority():
    from paleo_workbench.mapping.map_render_backend import (
    make_crs_transformer,
    reproject_xy,
)

    x, y = ops.crs_transform_xy((100.0, 40.0), "EPSG:4326", "EPSG:32650")
    transformer = make_crs_transformer("EPSG:4326", "EPSG:32650")
    import numpy as np

    expected = reproject_xy(np.array([[100.0, 40.0]]), transformer)
    assert x == pytest.approx(float(expected[0, 0]))
    assert y == pytest.approx(float(expected[0, 1]))
