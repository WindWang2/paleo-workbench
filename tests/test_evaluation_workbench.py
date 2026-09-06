"""V6 §13 — interpolation evaluation workbench: LOWO + metrics semantics."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("scipy")

from paleo_workbench.workflow.interpolation_evaluation import (
    EvaluationMetrics,
    leave_one_well_out_folds,
    signed_r_squared,
    spatial_fold_assignment,
)


def _points(n_per_well: int = 6, wells: int = 5, seed: int = 5):
    rng = np.random.default_rng(seed)
    pts = []
    for w in range(wells):
        cx, cy = rng.uniform(0.0, 1000.0, 2)
        for _ in range(n_per_well):
            pts.append(
                {
                    "well_id": f"well-{w}",
                    "name": f"W{w}",
                    "x": float(cx + rng.normal(0, 3.0)),
                    "y": float(cy + rng.normal(0, 3.0)),
                    "value": float(rng.normal(0, 1.0)),
                }
            )
    rng.shuffle(pts)
    return pts


class TestLeaveOneWellOut:
    def test_folds_group_by_well(self):
        pts = _points(wells=4)
        folds = leave_one_well_out_folds(pts)
        assert len(folds) == 4
        for fold in folds:
            ids = {pts[i]["well_id"] for i in fold}
            assert len(ids) == 1, "each fold holds out exactly one well"

    def test_together_folds_cover_all_samples(self):
        pts = _points()
        folds = leave_one_well_out_folds(pts)
        flat = sorted(int(i) for fold in folds for i in fold)
        assert flat == list(range(len(pts)))

    def test_anonymous_samples_are_singletons(self):
        pts = [{"x": 0.0, "y": 0.0, "value": 1.0}, {"x": 1.0, "y": 1.0, "value": 2.0}]
        folds = leave_one_well_out_folds(pts)
        assert sorted(len(f) for f in folds) == [1, 1]

    def test_name_fallback(self):
        pts = [
            {"name": "W-1", "x": 0.0, "y": 0.0, "value": 1.0},
            {"name": "W-1", "x": 1.0, "y": 1.0, "value": 1.5},
            {"name": "W-2", "x": 2.0, "y": 2.0, "value": 2.0},
        ]
        folds = leave_one_well_out_folds(pts)
        assert len(folds) == 2
        assert sorted(len(f) for f in folds) == [1, 2]


class TestMetricsSemantics:
    def test_r_squared_sign_is_clear(self):
        observed = np.array([1.0, 2.0, 3.0])
        perfect = signed_r_squared(observed, observed.copy())
        assert perfect == pytest.approx(1.0)
        terrible = signed_r_squared(observed, np.array([10.0, -10.0, 30.0]))
        assert terrible < 0.0, "worse-than-mean prediction must be negative"

    def test_metrics_from_arrays_counts_skipped(self):
        observed = np.array([1.0, 2.0, 3.0])
        predicted = np.array([1.0, np.nan, 3.0])
        metrics = EvaluationMetrics.from_arrays(observed, predicted)
        assert metrics.n_samples == 2
        assert metrics.n_skipped == 1


class TestSpatialFolds:
    def test_deterministic(self):
        pts = _points()
        x = [p["x"] for p in pts]
        y = [p["y"] for p in pts]
        a = spatial_fold_assignment(x, y, k=4)
        b = spatial_fold_assignment(x, y, k=4)
        assert all(np.array_equal(fa, fb) for fa, fb in zip(a, b))
