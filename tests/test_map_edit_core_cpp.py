"""Tests for optional map_edit_core C++ extension (skipped if not built)."""

from __future__ import annotations

import pytest

from paleo_workbench.mapping import map_edit_api as api

pytestmark = pytest.mark.skipif(
    not api.HAS_CPP,
    reason="map_edit_core C++ extension not installed",
)


def test_has_cpp_true():
    assert api.HAS_CPP is True
    import map_edit_core  # noqa: F401


def test_cpp_hit_test_point_and_polygon():
    records = [
        {"id": "w1", "coordinates": [1.0, 2.0]},
        {
            "id": "f1",
            "coordinates": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]],
        },
    ]
    assert api.hit_test(records, 1.0, 2.0, 0.1) == "w1"
    assert api.hit_test(records, 5.0, 5.0, 0.0) == "f1"
    assert api.hit_test(records, 50.0, 50.0, 0.0) is None


def test_cpp_snap_and_validate_self_intersection():
    x, y = api.snap_point([(0.0, 0.0), (10.0, 0.0)], 0.2, 0.1, 0.5)
    assert (x, y) == (0.0, 0.0)
    # bowtie
    ring = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    issues = api.validate_ring(ring)
    assert any(i.get("code") == "self_intersection" for i in issues)


def test_cpp_vertex_ops_and_move():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    api.set_vertex(ring, 1, 3.0, 0.0)
    assert ring[1] == [3.0, 0.0]
    api.insert_vertex(ring, 2, 3.0, 1.0)
    assert ring[2] == [3.0, 1.0]
    assert api.delete_vertex(ring, 2) is True
    recs = {"p1": {"id": "p1", "coordinates": [1.0, 1.0]}}
    api.move_features(recs, ["p1"], 2.0, 3.0)
    assert recs["p1"]["coordinates"] == [3.0, 4.0]


def test_m11_hit_test_malformed_coords_skipped():
    records = [
        {"id": "bad1", "coordinates": "ab"},
        {"id": "bad2", "coordinates": [["invalid", "type"]]},
        {"id": "w1", "coordinates": [5.0, 5.0]},
    ]
    assert api.hit_test(records, 5.0, 5.0, 0.1) == "w1"


def test_m12_snap_miss_returns_original():
    x, y = api.snap_point([(0.0, 0.0)], 10.0, 10.0, 0.5)
    assert (x, y) == (10.0, 10.0)


def test_m13_move_feature_preserves_tuple_type():
    recs = {"p1": {"id": "p1", "coordinates": [(1.0, 1.0), (2.0, 2.0)]}}
    api.move_features(recs, ["p1"], 1.0, 1.0)
    assert isinstance(recs["p1"]["coordinates"][0], tuple)
    assert recs["p1"]["coordinates"][0] == (2.0, 2.0)


def test_m15_insert_vertex_closed_ring_reclosure():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    api.insert_vertex(ring, 4, 1.0, 1.0)  # insert at end of closed ring
    assert ring[0] == ring[-1]  # first == last maintained


def test_snap_indexed_cpp_matches_python_grid():
    """SymmetricParityContract: map_edit_core.snap_indexed == Python grid."""
    import map_edit_core

    assert hasattr(map_edit_core, "snap_indexed")
    candidates = [(float(i), float((i * 7) % 13)) for i in range(64)]
    records = [
        {"id": f"p{i}", "coordinates": [x, y]}
        for i, (x, y) in enumerate(candidates)
    ]
    reference = [(3.5, 4.5)]
    flat = [*candidates, *reference]
    xs = [p[0] for p in flat]
    ys = [p[1] for p in flat]
    for qx, qy, tol in [
        (0.2, 0.1, 0.5),      # hit
        (100.0, 100.0, 0.5),  # miss: original point returned
        (3.4, 4.4, 0.3),      # reference point hit
    ]:
        expected = api.snap_point(flat, qx, qy, tol=tol)
        assert api.snap_point_indexed(records, reference, qx, qy, tol) == expected
        cx, cy = map_edit_core.snap_indexed(xs, ys, qx, qy, tol)
        assert (cx, cy) == pytest.approx(expected)

