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
