"""Unit tests for Batch 1: Base Stability (DTW bounds, render backend safety, topology auto-healing)."""

import numpy as np
import pytest

from paleo_workbench.viz.dtw_log_matcher import DTWLogMatcher, AlignmentResult
from paleo_workbench.mapping.topology import repair_invalid_geometry


def test_dtw_empty_curves_guard():
    matcher = DTWLogMatcher()
    empty = np.array([], dtype=np.float64)
    valid = np.array([1.0, 2.0, 3.0], dtype=np.float64)

    # Empty vs valid
    res1 = matcher.match_curves(empty, valid)
    assert res1.cost == float("inf")
    assert res1.path_ref == []
    assert res1.path_target == []

    # Valid vs empty
    res2 = matcher.match_curves(valid, empty)
    assert res2.cost == float("inf")
    assert res2.path_ref == []
    assert res2.path_target == []

    # Both empty
    res3 = matcher.match_curves(empty, empty)
    assert res3.cost == float("inf")
    assert res3.path_ref == []
    assert res3.path_target == []


def test_dtw_nan_and_infinite_handling():
    matcher = DTWLogMatcher()
    c1 = np.array([np.nan, 10.0, np.nan, 20.0, 30.0], dtype=np.float64)
    c2 = np.array([10.0, 20.0, np.nan, 30.0], dtype=np.float64)

    res = matcher.match_curves(c1, c2)
    assert np.isfinite(res.cost)
    assert len(res.path_ref) > 0
    assert len(res.path_target) > 0


def test_dtw_transfer_top_index_safety():
    matcher = DTWLogMatcher()
    idx = matcher.transfer_top_index(5, [], [])
    assert idx == 5

    c1 = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    c2 = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    res = matcher.match_curves(c1, c2)
    transferred = matcher.transfer_top_index(2, res.path_ref, res.path_target)
    assert transferred == 2


def test_topology_repair_unclosed_ring():
    unclosed = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]  # not closed
        ]
    }
    repaired = repair_invalid_geometry(unclosed)
    assert repaired["type"] == "Polygon"
    ring = repaired["coordinates"][0]
    assert ring[0] == ring[-1]


def test_topology_repair_bowtie_polygon():
    # Self-intersecting bow-tie
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [10.0, 10.0], [0.0, 10.0], [10.0, 0.0], [0.0, 0.0]]
        ]
    }
    repaired = repair_invalid_geometry(bowtie)
    assert repaired["type"] in {"Polygon", "MultiPolygon"}
