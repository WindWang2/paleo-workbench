"""Unit tests for FormationTopCorrelator interactive correlation engine (Ticket 02)."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.formation_top_correlator import FormationTopCorrelator, TopRecommendation


def test_formation_top_correlator_polygon_quads():
    correlator = FormationTopCorrelator()
    well_a = {
        "name": "W1",
        "tops": [{"name": "H1", "depth": 100.0}, {"name": "H2", "depth": 200.0}],
    }
    well_b = {
        "name": "W2",
        "tops": [{"name": "H1", "depth": 110.0}, {"name": "H2", "depth": 210.0}],
    }

    polygons = correlator.compute_correlation_polygons(
        well_a, well_b, x_a=0.0, x_b=100.0, top_names=["H1", "H2"]
    )

    assert len(polygons) == 1
    poly = polygons[0]
    assert poly["name"] == "H1-H2"
    assert poly["polygon"].shape == (4, 2)
    assert np.allclose(poly["polygon"][0], [0.0, 100.0])
    assert np.allclose(poly["polygon"][1], [100.0, 110.0])


def test_formation_top_correlator_dtw_recommendation():
    correlator = FormationTopCorrelator()
    ref_curve = np.sin(np.linspace(0, 4 * np.pi, 100)).astype(np.float32)
    # Shifted target curve by +5 samples
    target_curve = np.roll(ref_curve, 5)

    recommendation = correlator.recommend_top_depth(
        ref_curve=ref_curve,
        target_curve=target_curve,
        ref_top_depth=20.0,
        start_depth=0.0,
        depth_step=1.0,
    )

    assert isinstance(recommendation, TopRecommendation)
    assert recommendation.suggested_depth >= 20.0
    assert recommendation.confidence > 0.0


# ---------------------------------------------------------------------------
# #420 — recommend_top_depth must handle descending depth axes (deepest-first
# LAS files) instead of clipping every shallow top to index 0, and must flag
# silent fallbacks to the uniform 0.5 grid.
# ---------------------------------------------------------------------------

_ASC_DEPTHS = np.array([1998.5, 1999.0, 1999.5, 2000.0])
_DESC_DEPTHS = np.array([2000.0, 1999.5, 1999.0, 1998.5])
_TARGET_DEPTHS = np.array([3000.0, 3000.5, 3001.0, 3001.5])


def _identical_curves(n=4):
    curve = np.sin(np.linspace(0.0, 2.0 * np.pi, n)).astype(np.float32)
    return curve, curve.copy()  # identical: DTW transfers index i -> i


def test_420_descending_ref_axis_maps_top_to_matching_sample():
    ref, target = _identical_curves()
    rec = FormationTopCorrelator().recommend_top_depth(
        ref_curve=ref,
        target_curve=target,
        ref_top_depth=1999.5,  # file index 1 in the descending axis
        ref_depths=_DESC_DEPTHS,
        target_depths=_TARGET_DEPTHS,
    )
    # 1999.5 is sample index 1: its target-domain depth is 3000.5, not the
    # index-0 clip (3000.0) the old uniform-grid fallback produced.
    assert rec.suggested_depth == 3000.5


def test_420_flipped_data_returns_same_suggested_depth():
    ref, target = _identical_curves()
    correlator = FormationTopCorrelator()
    asc = correlator.recommend_top_depth(
        ref_curve=ref,
        target_curve=target,
        ref_top_depth=1999.5,
        ref_depths=_ASC_DEPTHS,
        target_depths=_TARGET_DEPTHS,
    )
    desc = correlator.recommend_top_depth(
        ref_curve=ref[::-1],
        target_curve=target[::-1],
        ref_top_depth=1999.5,
        ref_depths=_ASC_DEPTHS[::-1],
        target_depths=_TARGET_DEPTHS[::-1],
    )
    # Same physical top on the same target domain regardless of file order.
    assert asc.suggested_depth == desc.suggested_depth
    assert asc.suggested_depth == 3001.0


def test_420_descending_axis_deep_top_maps_to_last_sample():
    ref, target = _identical_curves()
    rec = FormationTopCorrelator().recommend_top_depth(
        ref_curve=ref,
        target_curve=target,
        ref_top_depth=1998.5,  # deepest sample: file index 3
        ref_depths=_DESC_DEPTHS,
        target_depths=_TARGET_DEPTHS,
    )
    assert rec.suggested_depth == 3001.5


def test_420_non_monotonic_axis_warns_instead_of_silent_grid_fallback():
    ref = np.sin(np.linspace(0.0, 2.0 * np.pi, 3)).astype(np.float32)
    bad_depths = np.array([1000.0, 1001.0, 1000.0])  # median(diff) == 0
    with pytest.warns(UserWarning, match="回退到均匀 0.5 网格"):
        FormationTopCorrelator().recommend_top_depth(
            ref_curve=ref,
            target_curve=ref.copy(),
            ref_top_depth=1000.5,
            ref_depths=bad_depths,
        )
