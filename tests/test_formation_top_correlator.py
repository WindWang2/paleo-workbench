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
