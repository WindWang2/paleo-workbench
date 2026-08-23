"""Regression tests for cpp-core-review findings in map_edit_core.

Each test exercises a contract edge case the passing parity suite would
not catch. Findings reference .superpowers/sdd/cpp-core-review.md §3.
"""
from __future__ import annotations

import pytest

# #940-2: a bare module-level import made the whole file a collection ERROR
# (not a skip) wherever the geoviz graph is absent; importorskip keeps the
# skip semantics intact.
api = pytest.importorskip("geoviz", reason="geoviz facade not installed")
_map_edit_api = pytest.importorskip(
    "geoviz_plots.map_edit.api", reason="geoviz_plots not installed"
)
# Private pure-core helper (not part of the facade surface).
_hit_test_python = _map_edit_api._hit_test_python

pytestmark = pytest.mark.skipif(
    not api.HAS_CPP,
    reason="map_edit_core C++ extension not installed",
)

map_edit_core = pytest.importorskip(
    "map_edit_core", reason="map_edit_core C++ extension not installed"
)


# ---------------------------------------------------------------------------
# M11 — malformed coordinates threw cast_error instead of being skipped
# ---------------------------------------------------------------------------


def test_m11_malformed_string_coordinate_is_skipped_not_crash():
    # 'ab' is a str -> a sequence of 'a','b'; previously this raised cast_error
    # inside is_closed_ring. Now the whole feature is skipped.
    result = map_edit_core.hit_test([["id1", "ab"]], 0.0, 0.0, 0.1)
    assert result is None


def test_m11_valid_feature_found_despite_malformed_sibling():
    result = map_edit_core.hit_test(
        [["bad", "xy"], ["good", [1.0, 2.0]]], 1.0, 2.0, 0.1
    )
    assert result == "good"


# ---------------------------------------------------------------------------
# M13 — py::list(pt) silently converted tuples to lists (caller type mutation)
# ---------------------------------------------------------------------------


def test_m13_move_feature_preserves_tuple_type():
    coords = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
    map_edit_core.move_feature(coords, 1.0, 1.0)
    assert all(isinstance(c, tuple) for c in coords), "tuples were converted to lists"
    assert coords[0] == (1.0, 1.0)
    assert coords[1] == (2.0, 2.0)


def test_m13_move_feature_preserves_list_type():
    coords = [[0.0, 0.0], [1.0, 1.0]]
    map_edit_core.move_feature(coords, 1.0, 1.0)
    assert all(isinstance(c, list) for c in coords)
    assert coords[0] == [1.0, 1.0]


def test_m13_set_vertex_preserves_tuple_type():
    ring = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 0.0)]
    map_edit_core.set_vertex(ring, 1, 3.0, 0.0)
    assert isinstance(ring[1], tuple)
    assert ring[1] == (3.0, 0.0)


# ---------------------------------------------------------------------------
# M15 — insert_vertex on a closed ring silently broke closure
# ---------------------------------------------------------------------------


def test_m15_insert_at_end_of_closed_ring_maintains_closure():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    map_edit_core.insert_vertex(ring, 4, 5.0, 5.0)  # index == n on a closed ring
    assert ring[0] == ring[-1], "ring closure broken"
    assert [5.0, 5.0] in ring


def test_m15_insert_at_start_of_closed_ring_maintains_closure():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    map_edit_core.insert_vertex(ring, 0, -1.0, -1.0)
    assert ring[0] == ring[-1], "ring closure broken"


def test_m15_insert_on_open_ring_unchanged_behavior():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]]  # open (first != last)
    map_edit_core.insert_vertex(ring, 3, 5.0, 5.0)
    assert ring[-1] == [5.0, 5.0]


# ---------------------------------------------------------------------------
# M16 — dead 1e-30 division guard removed; point-in-ring still works
# M17 — dead on_segment removed; validate still detects proper intersections
# ---------------------------------------------------------------------------


def test_m16_point_in_ring_works_after_dead_guard_removal():
    polygon = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]]
    assert map_edit_core.hit_test([["p", polygon]], 5.0, 5.0, 0.0) == "p"
    assert map_edit_core.hit_test([["p", polygon]], 50.0, 50.0, 0.0) is None


def test_m17_validate_detects_bowtie_self_intersection():
    bowtie = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    issues = map_edit_core.validate(bowtie)
    assert any(
        isinstance(i, dict) and i.get("code") == "self_intersection" for i in issues
    )


# ---------------------------------------------------------------------------
# I6 — tolerance-semantics parity between C++ and Python (documented contract)
# ---------------------------------------------------------------------------


def test_i6_hit_test_point_and_polygon_match_python_contract():
    records = [
        {"id": "w1", "coordinates": [1.0, 2.0]},
        {"id": "f1", "coordinates": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 0.0]]},
    ]
    # C++ path (via the api wrapper, which delegates to map_edit_core)
    assert api.hit_test(records, 1.0, 2.0, 0.1) == "w1"
    assert api.hit_test(records, 5.0, 5.0, 0.0) == "f1"
    assert api.hit_test(records, 50.0, 50.0, 0.0) is None
    # Python fallback agrees on the polygon hit (tolerance contract is shared).
    assert _hit_test_python(records, 5.0, 5.0, 0.0) == "f1"
