"""M2 — unified interpolation accuracy evaluation.

Covers the shared metrics/fold/scoring helpers, surface cross-validation with
a production-mirroring engine closure, exact kriging LOO, kriging variogram
diagnostics, and the task-level attachment (RMSE/MAE/bias into quality
metrics, computation kept separate from display).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from paleo_workbench.project.factor_grid_artifacts import (
    clear_session_caches,
    peek_live_factor_grid,
)
from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    attach_cross_validation,
    attach_surface_check,
    cross_validate_factor_task,
)
from paleo_workbench.workflow.interpolation_evaluation import (
    CrossValidationReport,
    EvaluationMetrics,
    bilinear_sample_grid,
    cross_validate_surface,
    kriging_diagnostics,
    kriging_leave_one_out,
    residual_features,
    signed_r_squared,
    spatial_fold_assignment,
    surface_residuals,
)


@pytest.fixture(autouse=True)
def _clean_live_cache():
    clear_session_caches()
    yield
    clear_session_caches()


# ---------------------------------------------------------------------------
# metrics + scoring helpers
# ---------------------------------------------------------------------------


def test_evaluation_metrics_exact_values():
    metrics = EvaluationMetrics.from_arrays([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert metrics.rmse == pytest.approx(0.0)
    assert metrics.mae == pytest.approx(0.0)
    assert metrics.bias == pytest.approx(0.0)
    assert metrics.r_squared == pytest.approx(1.0)

    poor = EvaluationMetrics.from_arrays([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
    assert poor.rmse == pytest.approx(math.sqrt(8.0 / 3.0))
    assert poor.mae == pytest.approx(4.0 / 3.0)
    assert poor.bias == pytest.approx(0.0)
    assert poor.r_squared == pytest.approx(-3.0)  # signed, worse than mean


def test_evaluation_metrics_counts_skipped_not_silent():
    metrics = EvaluationMetrics.from_arrays(
        [1.0, 2.0, float("nan"), 4.0], [1.5, float("nan"), 9.0, 4.5]
    )
    assert metrics.n_samples == 2
    assert metrics.n_skipped == 2
    assert metrics.bias == pytest.approx(-0.5)


def test_bilinear_sample_grid_midpoint_and_nodata():
    gx = np.array([0.0, 1.0, 2.0])
    gy = np.array([0.0, 1.0])
    gz = np.array([[0.0, 10.0, 20.0], [0.0, 10.0, 20.0]])
    assert bilinear_sample_grid(gz, gx, gy, 0.5, 0.5) == pytest.approx(5.0)
    assert bilinear_sample_grid(gz, gx, gy, 2.0, 0.0) == pytest.approx(20.0)
    hole = gz.copy()
    hole[0, 1] = np.nan
    assert bilinear_sample_grid(hole, gx, gy, 0.5, 0.0) is None
    # Off-grid samples are unscorable (CV must not treat extrapolation as
    # interpolation skill). #1275
    assert bilinear_sample_grid(gz, gx, gy, 3.0, 0.0) is None


def test_signed_r_squared_constant_observed_convention():
    assert signed_r_squared(np.array([2.0, 2.0]), np.array([2.0, 1.0])) == 1.0


# ---------------------------------------------------------------------------
# spatial folds
# ---------------------------------------------------------------------------


def test_spatial_folds_deterministic_disjoint_complete():
    rng = np.random.default_rng(7)
    xs = rng.uniform(0, 100, 40)
    ys = rng.uniform(0, 100, 40)
    folds_a = spatial_fold_assignment(xs, ys, k=4)
    folds_b = spatial_fold_assignment(xs, ys, k=4)
    all_ids = sorted(int(i) for fold in folds_a for i in fold)
    assert all_ids == list(range(40))
    flat = [int(i) for fold in folds_a for i in fold]
    assert len(flat) == len(set(flat))
    assert [list(f) for f in folds_a] == [list(f) for f in folds_b]


def test_spatial_folds_reject_invalid_k():
    with pytest.raises(ValueError, match="k must be"):
        spatial_fold_assignment([0.0], [0.0], k=1)


# ---------------------------------------------------------------------------
# surface cross-validation
# ---------------------------------------------------------------------------


def _linear_field_points(n: int = 36) -> list[dict[str, float]]:
    rng = np.random.default_rng(11)
    pts = []
    for _ in range(n):
        x = float(rng.uniform(0, 100))
        y = float(rng.uniform(0, 100))
        pts.append({"x": x, "y": y, "value": 0.5 * x + 2.0 * y + 10.0})
    return pts


def test_cross_validate_surface_recovers_smooth_field():
    points = _linear_field_points()
    report = cross_validate_surface(
        points,
        run_fold=lambda train: _idw_fold(train),
        k=4,
        method_label="IDW",
        engine="idw",
    )
    assert report is not None
    assert report.scheme == "kfold_surface"
    assert len(report.folds) == 4
    assert report.metrics.n_samples >= 30
    # A smooth linear field must clearly beat the mean. Spatial folds hold
    # out whole angular sectors (honest peripheral extrapolation), so ~0.85+
    # R² is the truthful ceiling here — don't tune the fixture past reality.
    assert report.metrics.r_squared > 0.8
    value_std = float(np.std([p["value"] for p in points]))
    assert report.metrics.rmse < 0.35 * value_std
    assert report.metrics.to_dict()["n_skipped"] >= 0
    assert len(report.residuals) == report.metrics.n_samples


def _idw_fold(train):
    from geoviz import interpolate_factor_grid

    result = interpolate_factor_grid(list(train), method="IDW", grid_n=32)
    return result["grid_x"], result["grid_y"], result["grid_z"]


def test_cross_validate_surface_returns_none_when_too_few_points():
    points = _linear_field_points(4)
    assert cross_validate_surface(points, run_fold=_idw_fold, k=4) is None


def test_cross_validate_surface_surfaces_fold_failure():
    points = _linear_field_points()

    def boom(train):
        raise RuntimeError("engine exploded")

    report = cross_validate_surface(points, run_fold=boom, k=4, method_label="X")
    assert report is not None
    assert report.scheme == "unavailable"
    assert "engine exploded" in report.detail


def test_cross_validate_surface_counts_nodata_window_as_skipped():
    points = _linear_field_points(12)

    def run_fold_with_hole(train):
        gx, gy, gz = _idw_fold(train)
        gz = np.array(gz, dtype=float)
        gz[:, :] = np.nan  # entire surface unusable
        return gx, gy, gz

    report = cross_validate_surface(points, run_fold=run_fold_with_hole, k=4)
    assert report is not None
    assert report.metrics.n_samples == 0
    assert report.metrics.n_skipped == 12


class _Cancelled:
    def raise_if_cancelled(self):
        raise RuntimeError("cancelled")


def test_cross_validate_surface_honours_cancellation():
    points = _linear_field_points()
    with pytest.raises(RuntimeError, match="cancelled"):
        cross_validate_surface(points, run_fold=_idw_fold, k=4, cancellation_token=_Cancelled())


# ---------------------------------------------------------------------------
# kriging exact LOO + diagnostics
# ---------------------------------------------------------------------------


def test_kriging_leave_one_out_exact_on_smooth_field():
    points = _linear_field_points(20)
    report = kriging_leave_one_out(points)
    assert report is not None
    assert report.scheme == "loo_exact"
    assert report.metrics.n_samples == 20
    assert report.metrics.r_squared > 0.9
    assert abs(report.metrics.bias) < 2.0


def test_kriging_leave_one_out_insufficient_points_is_none():
    assert kriging_leave_one_out(_linear_field_points(2)) is None


def test_kriging_diagnostics_reports_variogram_fit():
    points = _linear_field_points(30)
    diag = kriging_diagnostics(points)
    assert diag is not None
    assert diag["fit"] == "fitted"
    assert diag["range"] > 0
    assert diag["sill"] >= 0
    assert diag["nugget"] >= 0
    assert len(diag["lags"]) == len(diag["semivariance"])
    assert all(s >= 0 for s in diag["semivariance"])


# ---------------------------------------------------------------------------
# task-level attachment
# ---------------------------------------------------------------------------


def _prepared_task(method="IDW", factor_type="孔隙度", n=24):
    task = FactorMapTask(
        name=f"T1 {factor_type}",
        target_horizon="T1",
        factor_type=factor_type,
        method=method,
        parameters={"sample_points": _linear_field_points(n)},
    )
    apply_interpolation_to_task(task, method=method, grid_n=12)
    return task


def test_attach_cross_validation_idw_writes_cv_metrics():
    task = _prepared_task(method="IDW", n=24)
    report = attach_cross_validation(task, k=4)
    assert report is not None
    cv = task.quality_metrics["cv"]
    assert cv["scheme"] == "kfold_surface"
    assert task.quality_metrics["cv_rmse"] >= 0.0
    assert task.quality_metrics["cv_mae"] >= 0.0
    assert isinstance(task.quality_metrics["cv_bias"], float)
    # in-sample surface check stored separately, clearly labelled
    check = task.quality_metrics["surface_check"]
    assert check["kind"] == "in_sample_surface_check"
    assert len(task.quality_metrics["surface_residuals"]) == check["n_samples"]


def test_attach_cross_validation_kriging_exact_loo():
    task = _prepared_task(method="克里金", n=20)
    report = attach_cross_validation(task, include_diagnostics=True)
    assert report is not None
    assert report.scheme == "loo_exact"
    assert task.quality_metrics["cv"]["scheme"] == "loo_exact"
    diag = task.quality_metrics["kriging_diagnostics"]
    assert diag["fit"] in ("fitted", "defaulted")


def test_attach_cross_validation_too_few_points_hides_metrics():
    task = _prepared_task(method="IDW", n=4)
    report = attach_cross_validation(task, k=4)
    assert report is None
    assert "cv" not in task.quality_metrics
    assert "cv_rmse" not in task.quality_metrics


def test_cross_validate_factor_task_constrained_routes_vendored_engine():
    pytest.importorskip("paleo_workbench._vendored.haiyou_constrained_idw")
    task = _prepared_task(method="约束IDW", n=14)
    report, diagnostics = cross_validate_factor_task(task, k=4)
    assert diagnostics is None
    if report is not None:
        assert report.engine == "constrained_idw"
        assert report.scheme in ("kfold_surface", "unavailable")


def test_residual_features_are_geojson_points():
    residuals = [
        {"x": 1.0, "y": 2.0, "value": 3.0, "predicted": 2.5, "residual": 0.5}
    ]
    features = residual_features(residuals)
    assert features[0]["geometry"]["type"] == "Point"
    assert features[0]["geometry"]["coordinates"] == [1.0, 2.0]
    assert features[0]["properties"]["residual"] == pytest.approx(0.5)


def test_surface_residuals_labelled_in_sample():
    task = _prepared_task(method="IDW", n=12)
    grid = peek_live_factor_grid(task.id)
    records, metrics = surface_residuals(
        task.parameters["sample_points"], grid.grid_x, grid.grid_y, grid.grid_z
    )
    assert len(records) == metrics.n_samples
    assert metrics.rmse >= 0.0
    payload = attach_surface_check(task)
    assert payload is not None
    assert payload["kind"] == "in_sample_surface_check"


def test_cross_validation_report_to_dict_is_json_safe():
    points = _linear_field_points(12)
    report = cross_validate_surface(points, run_fold=_idw_fold, k=4, method_label="IDW")
    payload = report.to_dict()
    import json as _json

    _json.dumps(payload, allow_nan=False)


def test_cross_validate_surface_tolerates_nonfinite_and_dedupes_twins():
    """R1-P1 / R3-P1: non-finite samples must not shift fold indices, and
    twin wells (same coordinates) must not anchor their own holdout."""
    points = _linear_field_points(24)
    points.append({"x": float("nan"), "y": 0.0, "value": 1.0})  # non-finite row
    report = cross_validate_surface(points, run_fold=_idw_fold, k=4)
    assert report is not None
    assert "non_finite_dropped=1" in report.detail

    # twins inflate CV when scored; they must be merged before folding
    clean = _linear_field_points(24)
    twins = clean[:20]  # 20 exact duplicates of existing wells
    with_twins = clean + twins
    base = cross_validate_surface(with_twins, run_fold=_idw_fold, k=4)
    assert base is not None
    assert "duplicates_merged=20" in base.detail
    # deduped CV must equal CV on the 24 unique wells
    unique = cross_validate_surface(clean, run_fold=_idw_fold, k=4)
    assert unique is not None
    assert base.metrics.rmse == pytest.approx(unique.metrics.rmse, rel=1e-9)
    # the dedupe contract itself: passing the twins through again changes
    # nothing (duplicate groups enter as ONE sample)
    again = cross_validate_surface(with_twins + with_twins[:0], run_fold=_idw_fold, k=4)
    assert again is not None and again.metrics.rmse == pytest.approx(
        unique.metrics.rmse, rel=1e-9
    )
