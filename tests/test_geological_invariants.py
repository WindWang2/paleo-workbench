"""Geological invariant gate (geotopo Ticket 4).

Contract source: docs/development/geotopo-editor/02-interface-contracts.md §4.2.
Pure Python + shapely — no bridge dependency, the full matrix runs in fast CI.
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping import geological_invariants as gi

# ---------------------------------------------------------------------------
# Fixtures: two facies polygons sharing the x=10 edge (length 10).


def _square(x0: float, x1: float, y0: float = 0.0, y1: float = 10.0) -> dict:
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def _polygons(facies_a: str, facies_b: str) -> dict[str, list[dict]]:
    return {
        "facies_layer": [
            {"feature_id": "a", "geometry": _square(0.0, 10.0), "attributes": {"facies": facies_a}},
            {"feature_id": "b", "geometry": _square(10.0, 20.0), "attributes": {"facies": facies_b}},
        ]
    }


#: 8 builtin facies (facies_taxonomy.json tree keys).
FACIES = ["三角洲", "冲积扇", "深水盆地", "滨岸", "潟湖", "潮坪", "碳酸盐台地", "陆棚"]

#: Hand-derived expectation from D7 ranks (|Δ|≤1, plus 三角洲↔陆棚 whitelist).
_LEGAL_PAIRS = {
    ("三角洲", "三角洲"), ("三角洲", "冲积扇"), ("三角洲", "滨岸"), ("三角洲", "潟湖"),
    ("三角洲", "潮坪"), ("三角洲", "陆棚"),
    ("冲积扇", "冲积扇"), ("冲积扇", "三角洲"),
    ("滨岸", "滨岸"), ("滨岸", "三角洲"), ("滨岸", "潟湖"), ("滨岸", "潮坪"),
    ("滨岸", "碳酸盐台地"), ("滨岸", "陆棚"),
    ("潟湖", "潟湖"), ("潟湖", "三角洲"), ("潟湖", "滨岸"), ("潟湖", "潮坪"),
    ("潟湖", "碳酸盐台地"), ("潟湖", "陆棚"),
    ("潮坪", "潮坪"), ("潮坪", "三角洲"), ("潮坪", "滨岸"), ("潮坪", "潟湖"),
    ("潮坪", "碳酸盐台地"), ("潮坪", "陆棚"),
    ("碳酸盐台地", "碳酸盐台地"), ("碳酸盐台地", "滨岸"), ("碳酸盐台地", "潟湖"),
    ("碳酸盐台地", "潮坪"), ("碳酸盐台地", "陆棚"), ("碳酸盐台地", "深水盆地"),
    ("陆棚", "陆棚"), ("陆棚", "三角洲"), ("陆棚", "滨岸"), ("陆棚", "潟湖"),
    ("陆棚", "潮坪"), ("陆棚", "碳酸盐台地"), ("陆棚", "深水盆地"),
    ("深水盆地", "深水盆地"), ("深水盆地", "碳酸盐台地"), ("深水盆地", "陆棚"),
}


@pytest.mark.parametrize("facies_a", FACIES)
@pytest.mark.parametrize("facies_b", FACIES)
def test_adjacency_matrix_full_combination(facies_a: str, facies_b: str):
    adjacency = gi.FaciesAdjacency.builtin()
    allowed, reason = adjacency.may_touch(facies_a, facies_b)
    expected = (facies_a, facies_b) in _LEGAL_PAIRS or (facies_b, facies_a) in _LEGAL_PAIRS
    assert allowed == expected, (facies_a, facies_b, reason)
    if not expected:
        assert reason  # the refusal explains the missing transition
    violations = gi.validate_facies_adjacency(_polygons(facies_a, facies_b), adjacency=adjacency)
    assert bool(violations) == (not expected)
    if violations:
        assert violations[0].code == "facies_adjacency_gap"
        assert violations[0].severity == "error"
        assert set(violations[0].feature_ids) == {"a", "b"}


def test_deep_basin_touching_alluvial_fan_reports_missing_transition():
    violations = gi.validate_facies_adjacency(_polygons("深水盆地", "冲积扇"))
    assert len(violations) == 1
    message = violations[0].message
    assert "陆棚" in message or "滨岸" in message
    assert violations[0].hint


def test_short_shared_boundary_does_not_count_as_adjacency():
    records = {
        "facies_layer": [
            {"feature_id": "a",
             "geometry": {"type": "Polygon", "coordinates": [
                 [[0.0, 0.0], [10.0, 0.0], [10.0, 0.5], [0.0, 0.5], [0.0, 0.0]]]},
             "attributes": {"facies": "深水盆地"}},
            {"feature_id": "b",
             "geometry": {"type": "Polygon", "coordinates": [
                 [[10.0, 0.0], [20.0, 0.0], [20.0, 0.5], [10.0, 0.5], [10.0, 0.0]]]},
             "attributes": {"facies": "冲积扇"}},
        ]
    }
    violations = gi.validate_facies_adjacency(
        records, min_shared_len=1.0)  # shared edge only 0.5 long
    assert violations == []


def _fault_layer(paths: list[list[list[float]]]) -> dict[str, list[dict]]:
    return {
        "fault_layer": [
            {"feature_id": f"fault{i}", "geometry": {"type": "LineString", "coordinates": path},
             "attributes": {}}
            for i, path in enumerate(paths)
        ]
    }


class TestDanglingFaults:
    def _records(self, fault_path, polygons=None):
        return {
            "facies_layer": polygons if polygons is not None else [
                {"feature_id": "a", "geometry": _square(0.0, 10.0),
                 "attributes": {"facies": "滨岸"}}],
        }

    def test_fault_tip_dangling_inside_facies_polygon(self):
        faults = _fault_layer([[[5.0, 5.0], [5.0, 2.0]]])  # tip at (5,2), deep inside
        records = {**self._records(None), **faults}
        violations = gi.validate_dangling_faults(
            records, roles={"fault_layer": "fault_line", "facies_layer": "facies_polygon"})
        assert len(violations) == 1
        assert violations[0].code == "dangling_fault_unsealed"
        assert violations[0].layer_id == "fault_layer"

    def test_fault_reaching_polygon_boundary_is_legal(self):
        faults = _fault_layer([[[5.0, 5.0], [5.0, 0.0]]])  # tip exactly on boundary
        records = {**self._records(None), **faults}
        assert gi.validate_dangling_faults(
            records, roles={"fault_layer": "fault_line", "facies_layer": "facies_polygon"}) == []

    def test_fault_touching_another_fault_is_legal(self):
        faults = _fault_layer([[[5.0, 5.0], [5.0, 2.0]], [[0.0, 2.0], [5.0, 2.0]]])
        records = {**self._records(None), **faults}
        assert gi.validate_dangling_faults(
            records, roles={"fault_layer": "fault_line", "facies_layer": "facies_polygon"}) == []

    def test_fault_escaping_the_envelope_is_legal(self):
        # Starts ON the polygon boundary (x=0 edge) and runs out of the frame.
        faults = _fault_layer([[[0.0, 5.0], [15.0, 5.0]]])
        records = {**self._records(None), **faults}
        assert gi.validate_dangling_faults(
            records, roles={"fault_layer": "fault_line", "facies_layer": "facies_polygon"},
            envelope=[0.0, 0.0, 10.0, 10.0]) == []


class TestIsopathContinuity:
    def _records(self, isopath_path):
        return {
            "erosion_layer": [
                {"feature_id": "ero",
                 "geometry": {"type": "Polygon", "coordinates": [
                     [[5.0, -1.0], [15.0, -1.0], [15.0, 1.0], [5.0, 1.0], [5.0, -1.0]]]},
                 "attributes": {}}],
            "isopath_layer": [
                {"feature_id": "iso", "geometry": {"type": "LineString", "coordinates": isopath_path},
                 "attributes": {}}],
        }

    def _roles(self):
        return {"isopath_layer": "isopath_line", "erosion_layer": "erosion_boundary"}

    def test_isopath_crossing_unconformity_without_break(self):
        records = self._records([[0.0, 0.0], [20.0, 0.0]])  # straight through, no vertex at x=5/15
        violations = gi.validate_isopath_continuity(records, roles=self._roles())
        assert len(violations) == 1
        assert violations[0].code == "isopath_crosses_unconformity"

    def test_isopath_broken_at_unconformity_is_legal(self):
        records = self._records([[0.0, 0.0], [5.0, 0.0], [15.0, 0.0], [20.0, 0.0]])
        assert gi.validate_isopath_continuity(records, roles=self._roles()) == []


def test_run_geology_gate_dispatches_all_three_checks():
    records = {
        "facies_layer": [
            {"feature_id": "a", "geometry": _square(0.0, 10.0), "attributes": {"facies": "深水盆地"}},
            {"feature_id": "b", "geometry": _square(10.0, 20.0), "attributes": {"facies": "冲积扇"}},
        ],
        "fault_layer": [
            {"feature_id": "f", "geometry": {"type": "LineString",
                                             "coordinates": [[15.0, 5.0], [15.0, 2.0]]},
             "attributes": {}}],
    }
    violations = gi.run_geology_gate(
        records, roles={"fault_layer": "fault_line", "facies_layer": "facies_polygon"})
    codes = {v.code for v in violations}
    assert "facies_adjacency_gap" in codes
    assert "dangling_fault_unsealed" in codes


def test_project_override_replaces_builtin_adjacency():
    adjacency = gi.FaciesAdjacency(ranks={"甲": 0, "乙": 0}, allowed_pairs=[])
    assert adjacency.may_touch("甲", "乙")[0]
    assert not adjacency.may_touch("甲", "丙")[0]  # unknown facies refused, not crash
    violations = gi.validate_facies_adjacency(
        _polygons("甲", "乙"), adjacency=adjacency)
    assert violations == []
