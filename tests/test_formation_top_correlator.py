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


def test_dtw_confidence_normalized_by_matched_path_length():
    """Confidence must not inflate for decimated curves (issue #398).

    The DTW cost is accumulated over the actual matched path steps; normalizing
    by the full-resolution reference length overstates confidence when the
    curves were decimated before matching.  With path-length normalization the
    decimated and full-resolution confidences on equivalent noise curves must
    converge (acceptance: difference < 5%).
    """
    correlator = FormationTopCorrelator()
    rng = np.random.default_rng(123)

    full_confidences = []
    decimated_confidences = []
    for _ in range(3):
        # 1000 x 1000 cells = 1e6 <= _MAX_COST_CELLS -> no decimation.
        rec_full = correlator.recommend_top_depth(
            ref_curve=rng.normal(0.0, 1.0, 1000),
            target_curve=rng.normal(0.0, 1.0, 1000),
            ref_top_depth=500.0,
            start_depth=0.0,
            depth_step=1.0,
        )
        # 3000 x 3000 cells -> decimation stride 3 inside the matcher.
        rec_dec = correlator.recommend_top_depth(
            ref_curve=rng.normal(0.0, 1.0, 3000),
            target_curve=rng.normal(0.0, 1.0, 3000),
            ref_top_depth=1500.0,
            start_depth=0.0,
            depth_step=1.0,
        )
        full_confidences.append(rec_full.confidence)
        decimated_confidences.append(rec_dec.confidence)

    for full, dec in zip(full_confidences, decimated_confidences):
        assert abs(full - dec) < 0.05

    # Identical curves score ~1.0 at both resolutions (path cost ~ 0).
    x = np.sin(np.linspace(0.0, 40.0 * np.pi, 1000))
    rec = correlator.recommend_top_depth(
        ref_curve=x, target_curve=x, ref_top_depth=500.0,
        start_depth=0.0, depth_step=1.0,
    )
    assert rec.confidence > 0.99
    x2 = np.sin(np.linspace(0.0, 40.0 * np.pi, 3000))
    rec2 = correlator.recommend_top_depth(
        ref_curve=x2, target_curve=x2, ref_top_depth=1500.0,
        start_depth=0.0, depth_step=1.0,
    )
    assert rec2.confidence > 0.99
