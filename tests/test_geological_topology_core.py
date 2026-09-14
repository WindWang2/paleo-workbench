"""Geological topology core — control-line polygonization (Ticket 1).

Contract source: ``docs/development/geotopo-editor/02-interface-contracts.md``.
These tests drive the host facade ``paleo_workbench.mapping.geotopo_service``
(bridge ``qgis_render_bridge.geotopo`` preferred, shapely fallback otherwise).
The fast leg runs without the bridge; the ``@pytest.mark.qgis`` class pins the
native DCEL core when the bridge is built.
"""

from __future__ import annotations

import json
import math

import pytest

from paleo_workbench.mapping import geotopo_service as gt

# ---------------------------------------------------------------------------
# Fixtures: control-line networks (id + path per 02-interface-contracts §1.1)
#
# Every fixture that expects bounded faces carries an explicit closed frame
# line: two crossing lines alone bound only UNBOUNDED regions, and the
# polygonizer correctly reports zero faces for them (unbounded face excluded).


def _frame(size: float = 10.0, fid: str = "frame") -> dict:
    return {"id": fid, "path": [
        [0.0, 0.0], [size, 0.0], [size, size], [0.0, size], [0.0, 0.0]]}


def _cross_network() -> list[dict]:
    return [
        _frame(),
        {"id": "shore", "path": [[0.0, 5.0], [10.0, 5.0]]},
        {"id": "boundary", "path": [[5.0, 0.0], [5.0, 10.0]]},
    ]


def _t_network() -> list[dict]:
    # Both endpoints of "graben" land on the INTERIOR of frame edges: T-junctions.
    return [
        _frame(),
        {"id": "graben", "path": [[5.0, 0.0], [5.0, 10.0]]},
    ]


def _ring_area(ring: list[list[float]]) -> float:
    return abs(sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1]
        - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring)))) / 2.0


def _polygon_area(geometry: dict) -> float:
    assert geometry["type"] == "Polygon", geometry["type"]
    return _ring_area(geometry["coordinates"][0]) - sum(
        _ring_area(ring) for ring in geometry["coordinates"][1:])


def _ccw_ring(ring: list[list[float]]) -> bool:
    signed = sum(
        ring[i][0] * ring[(i + 1) % len(ring)][1]
        - ring[(i + 1) % len(ring)][0] * ring[i][1]
        for i in range(len(ring)))
    return signed > 0


# ---------------------------------------------------------------------------
# Ticket 1 red/green suite (runs on either engine)


def test_cross_intersection_yields_four_faces():
    result = gt.polygonize_control_lines(_cross_network())
    assert result.engine in (gt.ENGINE_QGIS, gt.ENGINE_SHAPELY)
    assert len(result.polygons) == 4
    areas = sorted(round(p.area, 9) for p in result.polygons)
    assert areas == [25.0] * 4
    for poly in result.polygons:
        assert set(poly.source_lines) == {"frame", "shore", "boundary"}
        assert _ccw_ring(poly.geometry["coordinates"][0])


def test_t_intersection_yields_two_faces():
    result = gt.polygonize_control_lines(_t_network())
    assert len(result.polygons) == 2
    assert sorted(round(p.area, 9) for p in result.polygons) == [50.0, 50.0]


def test_dangling_line_is_pruned_and_reported():
    # A spine dying out inside the frame cannot bound a face: pruned + reported.
    lines = _t_network() + [{"id": "tip", "path": [[5.0, 5.0], [7.0, 5.0]]}]
    result = gt.polygonize_control_lines(lines)
    assert len(result.polygons) == 2
    assert result.dropped_dangles >= 1


def test_self_intersecting_figure_eight_yields_two_faces():
    lines = [{"id": "fold", "path": [[0.0, 0.0], [4.0, 4.0], [4.0, 0.0], [0.0, 4.0], [0.0, 0.0]]}]
    result = gt.polygonize_control_lines(lines)
    assert len(result.polygons) == 2
    assert sorted(round(p.area, 9) for p in result.polygons) == [4.0, 4.0]


def test_collinear_overlap_deduplicates_to_single_face():
    lines = [
        {"id": "bottom", "path": [[0.0, 0.0], [10.0, 0.0]]},
        {"id": "bottom_partial", "path": [[4.0, 0.0], [10.0, 0.0]]},
        {"id": "loop", "path": [[0.0, 0.0], [0.0, 6.0], [10.0, 6.0], [10.0, 0.0], [0.0, 0.0]]},
    ]
    result = gt.polygonize_control_lines(lines)
    assert len(result.polygons) == 1
    assert result.polygons[0].area == pytest.approx(60.0)
    assert set(result.polygons[0].source_lines) == {"bottom", "bottom_partial", "loop"}


def test_near_coincident_intersections_merge_under_tolerance():
    eps = 1e-9  # << tolerance 1e-6: the two verticals must fuse to one node column
    lines = [
        _frame(),
        {"id": "shore", "path": [[0.0, 5.0], [10.0, 5.0]]},
        {"id": "v1", "path": [[5.0 - eps, 0.0], [5.0 - eps, 10.0]]},
        {"id": "v2", "path": [[5.0, 0.0], [5.0, 10.0]]},
    ]
    result = gt.polygonize_control_lines(lines)
    assert len(result.polygons) == 4  # a sliver column between v1/v2 must NOT appear
    assert min(p.area for p in result.polygons) > 1.0


def test_clip_envelope_drops_outside_faces():
    result = gt.polygonize_control_lines(
        _cross_network(), clip_envelope=[0.0, 0.0, 5.0, 5.0])
    assert len(result.polygons) == 1
    assert result.polygons[0].area == pytest.approx(25.0)


def test_invalid_inputs_raise_contract_error_codes():
    with pytest.raises(gt.GeoTopoError) as nan_err:
        gt.polygonize_control_lines([{"id": "bad", "path": [[0.0, math.nan], [1.0, 1.0]]}])
    assert nan_err.value.code == "PWB-GT-001"
    with pytest.raises(gt.GeoTopoError) as tol_err:
        gt.polygonize_control_lines(_cross_network(), tolerance=0.0)
    assert tol_err.value.code == "PWB-GT-002"


def test_output_faces_are_valid_and_polygonization_is_idempotent():
    from shapely.geometry import shape

    result = gt.polygonize_control_lines(_cross_network())
    edge_lines: list[dict] = []
    for index, poly in enumerate(result.polygons):
        assert shape(poly.geometry).is_valid
        ring = poly.geometry["coordinates"][0]
        for i in range(len(ring) - 1):
            edge_lines.append({"id": f"e{index}", "path": [ring[i], ring[i + 1]]})
    replay = gt.polygonize_control_lines(edge_lines)
    assert len(replay.polygons) == 4
    assert sum(p.area for p in replay.polygons) == pytest.approx(100.0, rel=1e-9)


def test_engine_disclosure_and_diagnostics():
    result = gt.polygonize_control_lines(_cross_network())
    assert result.engine in (gt.ENGINE_QGIS, gt.ENGINE_SHAPELY)
    assert result.node_count >= 5  # 4 crossing-adjacent nodes + extent corners minimum
    assert result.edge_count >= 8
    assert result.elapsed_ms >= 0.0


def test_grid_50x50_polygonizes_on_either_engine():
    lines: list[dict] = []
    for i in range(51):
        lines.append({"id": f"h{i}", "path": [[float(x), float(i)] for x in range(51)]})
        lines.append({"id": f"v{i}", "path": [[float(i), float(y)] for y in range(51)]})
    result = gt.polygonize_control_lines(lines)
    assert len(result.polygons) == 2500
    assert sum(p.area for p in result.polygons) == pytest.approx(2500.0, rel=1e-9)


# ---------------------------------------------------------------------------
# Native DCEL core (bridge required)


@pytest.mark.qgis
class TestNativeDcelCore:
    def _bridge_geotopo(self):
        import qgis_render_bridge as native

        assert hasattr(native, "geotopo"), "geotopo submodule missing from bridge"
        return native.geotopo

    def test_json_envelope_contract(self):
        geotopo = self._bridge_geotopo()
        payload = json.loads(geotopo.polygonize_control_lines(
            json.dumps({"lines": _cross_network()})))
        assert payload["status"] == "ok"
        assert len(payload["polygons"]) == 4
        assert payload["dropped_dangles"] == 0
        assert payload["elapsed_ms"] >= 0.0

    def test_error_envelope_carries_code(self):
        geotopo = self._bridge_geotopo()
        # NaN cannot travel through strict JSON: the bridge layer reports the
        # malformed-json code (host facade reports PWB-GT-001 pre-serialization).
        bad_lines = json.dumps(
            {"lines": [{"id": "bad", "path": [[0.0, float("nan")], [1.0, 1.0]]}]})
        payload = json.loads(geotopo.polygonize_control_lines(bad_lines))
        assert payload["status"] == "error"
        assert payload["code"] == "PWB-GT-003"
        assert payload["message"]
        short_lines = json.dumps({"lines": [{"id": "short", "path": [[0.0, 1.0]]}]})
        payload = json.loads(geotopo.polygonize_control_lines(short_lines))
        assert payload["code"] == "PWB-GT-001"

    def test_performance_gate_5000_segments_under_30ms(self):
        lines: list[dict] = []
        for i in range(51):
            lines.append({"id": f"h{i}", "path": [[float(x), float(i)] for x in range(51)]})
            lines.append({"id": f"v{i}", "path": [[float(i), float(y)] for y in range(51)]})
        geotopo = self._bridge_geotopo()
        payload = json.loads(geotopo.polygonize_control_lines(json.dumps({"lines": lines})))
        assert payload["status"] == "ok"
        assert len(payload["polygons"]) == 2500
        assert payload["elapsed_ms"] <= 30.0, payload["elapsed_ms"]

    def test_host_facade_prefers_bridge_when_present(self):
        result = gt.polygonize_control_lines(_cross_network())
        assert result.engine == gt.ENGINE_QGIS
