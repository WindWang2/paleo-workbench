"""Unit tests for StratigraphicCorrelationEngine fluent builder module."""

from __future__ import annotations

import numpy as np
import pytest
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.viz.stratigraphic_correlation_engine import (
    CorrelationSectionResult,
    StratigraphicCorrelationEngine,
)


def test_stratigraphic_correlation_engine_fluent_pipeline():
    wells = [
        {
            "name": "Well-01",
            "tops": [{"name": "H1", "depth": 1000.0}, {"name": "H2", "depth": 1200.0}],
            "curves": {"GR": np.array([45.0, 52.0, 88.0, 95.0, 30.0], dtype=np.float32)},
        },
        {
            "name": "Well-02",
            "tops": [{"name": "H1", "depth": 1050.0}, {"name": "H2", "depth": 1260.0}],
            "curves": {"GR": np.array([42.0, 50.0, 90.0, 93.0, 32.0], dtype=np.float32)},
        },
    ]

    engine = (
        StratigraphicCorrelationEngine()
        .with_wells(wells)
        .with_datum(mode="horizon", target_horizon="H1")
        .with_layout({"Well-01": 0.0, "Well-02": 300.0})
        .with_dtw_config(window=5, depth_step=1.0)
    )

    result = engine.execute(top_names=["H1", "H2"], curve_key="GR")

    assert isinstance(result, CorrelationSectionResult)
    assert result.shifts["Well-01"] == -1000.0
    assert result.shifts["Well-02"] == -1050.0
    assert len(result.polygons) == 1
    assert ("Well-01", "Well-02") in result.alignments


def test_stratigraphic_correlation_engine_recommend_top():
    wells = [
        {
            "name": "W1",
            "curves": {"GR": np.sin(np.linspace(0, 4 * np.pi, 50))},
        },
        {
            "name": "W2",
            "curves": {"GR": np.roll(np.sin(np.linspace(0, 4 * np.pi, 50)), 3)},
        },
    ]

    engine = StratigraphicCorrelationEngine().with_wells(wells)
    rec = engine.recommend_top(ref_well="W1", target_well="W2", ref_top_depth=10.0)

    assert rec.suggested_depth >= 10.0
    assert rec.confidence > 0.0


def test_recommend_top_without_bound_wells_returns_ui_detectable_sentinel():
    """#405: unbound engine must return the empty-input sentinel so the UI can
    show '不可用' instead of rendering a misleading 0.00 confidence."""
    engine = StratigraphicCorrelationEngine()
    rec = engine.recommend_top(ref_well="W1", target_well="W2", ref_top_depth=10.0)
    assert rec.confidence == 0.0
    assert rec.dtw_cost >= 999.0  # sentinel marker the page checks


def test_recommend_top_confidence_normalized_over_decimated_cells():
    """#405/C40: confidence must be normalized by the cells DTW actually
    accumulated (decimated), not the full input length (which inflated it)."""
    from paleo_workbench.viz.dtw_log_matcher import DTWLogMatcher

    n = 5000  # 25e6 cells -> forced decimation (1e6 cap)
    base = np.sin(np.linspace(0, 8 * np.pi, n))
    ref = base.copy()
    target = np.roll(base, 7)
    wells = [
        {"name": "W1", "curves": {"GR": ref}},
        {"name": "W2", "curves": {"GR": target}},
    ]
    engine = StratigraphicCorrelationEngine().with_wells(wells)
    rec = engine.recommend_top(ref_well="W1", target_well="W2", ref_top_depth=100.0)
    assert 0.0 < rec.confidence <= 1.0

    alignment = engine.align_curves("W1", "W2", curve_key="GR")
    assert len(alignment.path_ref) < n, "long curves must be decimated"
    expected = float(np.exp(-alignment.cost / (len(alignment.path_ref) * 2.0)))
    assert rec.confidence == pytest.approx(expected)
