"""QGIS geometry service contract: operations, edge cases, topological equality.

Requires the native bridge.  Results are compared by area/length/part count
and validity rather than exact coordinate sequences (GEOS output ordering is
not a contract).
"""

from __future__ import annotations

import json
import math

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = pytest.mark.qgis

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)

geometry = qgis_render_bridge.geometry


def _area(geojson: dict | str) -> float:
    data = json.loads(geojson) if isinstance(geojson, str) else geojson
    # Winding-independent planar area: first ring adds, subsequent rings
    # (holes) subtract; GEOS output winding is not a contract.
    polygons = (
        [data["coordinates"]]
        if data["type"] == "Polygon"
        else data["coordinates"]
        if data["type"] == "MultiPolygon"
        else None
    )
    if polygons is None:
        raise TypeError(f"unsupported geometry {data['type']}")
    total = 0.0

    def ring_area(ring) -> float:
        twice = 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i][:2]
            x2, y2 = ring[i + 1][:2]
            twice += x1 * y2 - x2 * y1
        return abs(twice) / 2

    for polygon in polygons:
        areas = [ring_area(ring) for ring in polygon]
        total += areas[0] - sum(areas[1:])
    return total


SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
SQUARE_B = {
    "type": "Polygon",
    "coordinates": [[[5, 5], [15, 5], [15, 15], [5, 15], [5, 5]]],
}
WITH_HOLE = {
    "type": "Polygon",
    "coordinates": [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
    ],
}


class TestOverlayOperations:
    def test_union_of_overlapping_squares(self) -> None:
        result = json.loads(geometry.union([SQUARE, SQUARE_B]))
        assert _area(result) == pytest.approx(175.0, rel=1e-6)

    def test_intersection(self) -> None:
        result = json.loads(geometry.intersection(SQUARE, SQUARE_B))
        assert _area(result) == pytest.approx(25.0, rel=1e-6)

    def test_difference(self) -> None:
        result = json.loads(geometry.difference(SQUARE, SQUARE_B))
        assert _area(result) == pytest.approx(75.0, rel=1e-6)

    def test_symdifference(self) -> None:
        result = json.loads(geometry.symdifference(SQUARE, SQUARE_B))
        assert _area(result) == pytest.approx(150.0, rel=1e-6)

    def test_polygon_hole_survives_union_with_distant_square(self) -> None:
        distant = {
            "type": "Polygon",
            "coordinates": [[[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]],
        }
        result = json.loads(geometry.union([WITH_HOLE, distant]))
        assert _area(result) == pytest.approx(96.0 + 100.0, rel=1e-6)


class TestEditingOperations:
    def test_split_polygon_by_crossing_line(self) -> None:
        cutter = {"type": "LineString", "coordinates": [[5, -5], [5, 15]]}
        pieces = geometry.split_by_line(json.dumps(SQUARE), json.dumps(cutter))
        assert len(pieces) == 2
        total = sum(_area(piece) for piece in pieces)
        assert total == pytest.approx(100.0, rel=1e-6)

    def test_split_near_vertex_does_not_lose_area(self) -> None:
        cutter = {"type": "LineString", "coordinates": [[9.999999, -1], [9.999999, 11]]}
        pieces = geometry.split_by_line(json.dumps(SQUARE), json.dumps(cutter))
        assert len(pieces) >= 2
        total = sum(_area(piece) for piece in pieces)
        assert total == pytest.approx(100.0, rel=1e-3)

    def test_split_that_misses_raises(self) -> None:
        cutter = {"type": "LineString", "coordinates": [[50, 50], [60, 60]]}
        with pytest.raises(Exception):  # noqa: B017 — native QgisGeometryError
            geometry.split_by_line(json.dumps(SQUARE), json.dumps(cutter))

    def test_buffer(self) -> None:
        result = json.loads(geometry.buffer(SQUARE, 1.0, 8))
        expected = 100 + 4 * 10 * 1.0 + math.pi
        assert _area(result) == pytest.approx(expected, rel=2e-2)


class TestValidityAndStructure:
    def test_validity_check(self) -> None:
        assert geometry.is_valid(SQUARE) is True

    def test_self_intersection_is_invalid_then_make_valid(self) -> None:
        bowtie = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]],
        }
        assert geometry.is_valid(bowtie) is False
        fixed = json.loads(geometry.make_valid(bowtie))
        assert geometry.is_valid(fixed) is True

    def test_touching_polygons_union_into_one(self) -> None:
        left = {"type": "Polygon", "coordinates": [[[0, 0], [5, 0], [5, 10], [0, 10], [0, 0]]]}
        right = {"type": "Polygon", "coordinates": [[[5, 0], [10, 0], [10, 10], [5, 10], [5, 0]]]}
        merged = json.loads(geometry.union([left, right]))
        assert _area(merged) == pytest.approx(100.0, rel=1e-6)

    def test_multipart_to_singlepart_and_back(self) -> None:
        multipolygon = {
            "type": "MultiPolygon",
            "coordinates": [SQUARE["coordinates"], SQUARE_B["coordinates"]],
        }
        parts = geometry.multipart_to_singlepart(multipolygon)
        assert len(parts) == 2
        collected = json.loads(geometry.singlepart_to_multipart(parts))
        assert collected["type"] in {"MultiPolygon", "GeometryCollection"}
        assert sum(
            _area(part if isinstance(part, str) else json.dumps(part)) for part in parts
        ) == pytest.approx(200.0, rel=1e-6)

    def test_empty_geometry_input_raises(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            geometry.is_valid("not-a-geometry")

    def test_precision_edge_case_keeps_closure(self) -> None:
        tiny = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1e-7, 0], [1e-7, 1e-7], [0, 1e-7], [0, 0]]],
        }
        buffered = json.loads(geometry.buffer(tiny, 1.0, 8))
        assert _area(buffered) > 3.0

    def test_clip(self) -> None:
        clipped = json.loads(geometry.clip(SQUARE, (5.0, 0.0, 20.0, 10.0)))
        assert _area(clipped) == pytest.approx(50.0, rel=1e-6)

    def test_simplify_reduces_vertices(self) -> None:
        zigzag = {
            "type": "LineString",
            "coordinates": [[0, 0], [1, 0.1], [2, 0], [3, 0.1], [4, 0], [5, 0]],
        }
        simplified = json.loads(geometry.simplify(zigzag, 0.5))
        assert len(simplified["coordinates"]) < len(zigzag["coordinates"])
