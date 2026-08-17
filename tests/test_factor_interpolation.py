"""T-PREP-01: real IDW / SciPy factor map interpolation."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.factor_interpolation import (
    GENERATOR_VERSION,
    apply_interpolation_to_task,
    batch_prepare_factor_maps,
    extract_xy_values,
    interpolate_factor_grid,
    synthetic_sample_points,
)
from paleo_workbench.workflow.factors import create_mock_factor_map


def test_extract_xy_values_accepts_x_y_and_lng_lat():
    x, y, z = extract_xy_values(
        [
            {"x": 1.0, "y": 2.0, "value": 3.0},
            {"lng": 4.0, "lat": 5.0, "value": 6.0},
            {"x": "bad", "y": 0, "value": 1},
        ]
    )
    assert list(x) == [1.0, 4.0]
    assert list(y) == [2.0, 5.0]
    assert list(z) == [3.0, 6.0]


def test_interpolate_factor_grid_idw_shape_and_stats():
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 1.0, "value": 3.0},
        {"x": 1.0, "y": 1.0, "value": 4.0},
    ]
    result = interpolate_factor_grid(points, method="IDW", grid_n=8)
    assert result["backend"] == "idw"
    assert len(result["grid_x"]) == 8
    assert len(result["grid_y"]) == 8
    assert len(result["grid_z"]) == 8
    assert len(result["grid_z"][0]) == 8
    assert result["min"] <= result["max"]
    assert result["n_points"] == 4
    # LOO R² is signed (#687): worse-than-mean interpolation may be negative.
    assert result["r_squared"] is None or result["r_squared"] <= 1.0


def test_kriging_routes_to_real_variogram_backend():
    """ISS-KRIG-01 resolved: UI 克里金 routes to real ordinary kriging.

    The parent-side workflow maps the label to the engine method "kriging"
    (variogram fit + OK solve) BEFORE calling interpolate_factor_grid; the
    engine returns grid_var + variance_min/max. Backend math tests live in
    the geo-viz-engine child; here we cover the routing + passthrough.
    """
    from paleo_workbench.workflow.factor_interpolation import METHOD_LABEL_TO_ENGINE

    assert METHOD_LABEL_TO_ENGINE["克里金"] == "kriging"
    assert METHOD_LABEL_TO_ENGINE["克里金(MVP·线性)"] == "kriging"  # legacy alias
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 1.0, "value": 3.0},
        {"x": 1.0, "y": 1.0, "value": 4.0},
    ]
    result = interpolate_factor_grid(points, method="kriging", grid_n=8)
    assert result["backend"] == "kriging"
    assert "mvp_note" not in result
    assert result["grid_var"] is not None
    assert len(result["grid_var"]) == 8
    assert result["variance_min"] is not None
    assert result["variance_max"] is not None


def test_kriging_output_finite_deterministic_and_variance_nonnegative():
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 1.0, "value": 3.0},
        {"x": 1.0, "y": 1.0, "value": 4.0},
        {"x": 0.5, "y": 0.5, "value": 5.0},
    ]
    first = interpolate_factor_grid(points, method="kriging", grid_n=12)
    second = interpolate_factor_grid(points, method="kriging", grid_n=12)
    assert first["grid_z"] == second["grid_z"]
    assert first["grid_var"] == second["grid_var"]
    finite_z = [v for row in first["grid_z"] for v in row if v is not None]
    assert all(np.isfinite(v) for v in finite_z)
    finite_v = [v for row in first["grid_var"] for v in row if v is not None]
    assert all(v >= 0.0 for v in finite_v)


def test_kriging_is_exact_at_sample_grid_node():
    # Samples laid out so (2,2) lands exactly on a grid node (grid_n=5 axes:
    # [-0.2, 0.9, 2.0, 3.1, 4.2]) → ordinary kriging reproduces the value.
    samples = [(0, 0, 1.0), (4, 0, 2.0), (0, 4, 3.0), (4, 4, 4.0), (2, 2, 5.0)]
    points = [{"x": x, "y": y, "value": v} for x, y, v in samples]
    result = interpolate_factor_grid(points, method="kriging", grid_n=5)
    gx, gy, gz = result["grid_x"], result["grid_y"], result["grid_z"]
    ix = gx.index(2.0)
    iy = gy.index(2.0)
    assert gz[iy][ix] == pytest.approx(5.0, abs=1e-6)


def test_kriging_handles_duplicate_locations():
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 1.0, "value": 3.0},
        {"x": 1.0, "y": 1.0, "value": 4.0},
        {"x": 0.0, "y": 0.0, "value": 1.5},  # exact duplicate location
    ]
    result = interpolate_factor_grid(points, method="kriging", grid_n=8)
    assert result["backend"] == "kriging"
    assert result["n_points"] == 5
    assert result["min"] <= result["max"]
    finite = [v for row in result["grid_z"] for v in row if v is not None]
    assert all(np.isfinite(v) for v in finite)


def test_apply_interpolation_to_task_routes_kriging_label():
    task = FactorMapTask(
        name="厚度",
        target_horizon="H1",
        factor_type="地层厚度",
        method="克里金",
        parameters={"sample_points": synthetic_sample_points(seed=1, factor_type="厚度")},
        status="pending",
        source_kind="mixed",
    )
    apply_interpolation_to_task(task, method="克里金", grid_n=10)
    assert task.status == "complete"
    assert task.parameters["interp_backend"] == "kriging"
    assert "grid_var" not in task.parameters  # numerical arrays stay in FactorGrid cache
    from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task

    assert factor_grid_result_for_task(task).variance_grid is not None
    assert task.quality_metrics.get("variance_min") is not None
    assert task.quality_metrics.get("variance_max") is not None


def test_apply_interpolation_to_task_fills_grid_and_metrics():
    task = FactorMapTask(
        name="厚度",
        target_horizon="H1",
        factor_type="地层厚度",
        method="mock",
        parameters={"sample_points": synthetic_sample_points(seed=1, factor_type="厚度")},
        status="pending",
        source_kind="mock",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=10)
    assert task.status == "complete"
    assert task.method == "IDW"
    assert task.source_kind == "mixed"
    assert task.generator_version == GENERATOR_VERSION
    # Stage-3: numerical payload lives in live FactorGrid cache, not nested lists.
    assert "grid_z" not in (task.parameters or {})
    from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task

    live = factor_grid_result_for_task(task)
    assert live.shape == (10, 10)
    assert "range" in task.quality_metrics
    assert task.quality_metrics.get("grid") == "10×10"


def test_batch_prepare_creates_default_tasks_when_empty():
    project = ProjectDocument.new("Prep")
    project.stratigraphy.target_horizon = "C6"
    prepared = batch_prepare_factor_maps(project, method="IDW", grid_n=12, seed=3)
    assert len(prepared) >= 3
    assert len(project.factor_map_tasks) == len(prepared)
    from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task

    for task in prepared:
        assert task.status == "complete"
        assert task.target_horizon == "C6"
        assert "grid_z" not in (task.parameters or {})
        assert factor_grid_result_for_task(task).grid_z.size > 0
        assert task.quality_metrics.get("n_points", 0) >= 2


def test_batch_prepare_upgrades_mock_factor_maps():
    project = ProjectDocument.new("Upgrade")
    mock = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=9)
    assert mock.method == "mock"
    assert "grid_z" not in (mock.parameters or {})

    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    assert mock.method == "IDW"
    assert "grid_z" not in (mock.parameters or {})
    assert mock.status == "complete"
    from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task

    assert factor_grid_result_for_task(mock).shape[0] == 16
    # Sample points preserved for mapping / compile_map well overlay
    assert len(mock.parameters["sample_points"]) == 8


def test_synthetic_points_are_deterministic():
    a = synthetic_sample_points(seed=42, factor_type="砂")
    b = synthetic_sample_points(seed=42, factor_type="砂")
    assert a == b


def test_synthetic_points_do_not_depend_on_python_hash(monkeypatch):
    import builtins

    monkeypatch.setattr(builtins, "hash", lambda _value: 1)
    first = synthetic_sample_points(seed=7, factor_type="砂地比", count=3)
    monkeypatch.setattr(builtins, "hash", lambda _value: 999999)
    second = synthetic_sample_points(seed=7, factor_type="砂地比", count=3)

    assert first == second


def test_large_sample_loo_uses_a_bounded_deterministic_subset(monkeypatch):
    # The pure interpolation core (_run_grid / _leave_one_out_r2) was promoted
    # to geo-viz-engine's geoviz_plots.factor.interpolation (PR-A #256); it is
    # not re-exported through the public geoviz facade, so the test imports the
    # promoted module directly to verify the bounded LOO subset contract.
    from geoviz_plots.factor import interpolation as interpolation

    calls: list[float] = []

    def fake_grid(x, y, z, grid_x, grid_y, **_kwargs):
        calls.append(float(grid_x[0]))
        return np.asarray([[float(np.mean(z))]])

    monkeypatch.setattr(interpolation, "_run_grid", fake_grid)
    sample_count = 2_000
    x = np.linspace(0.0, 100.0, sample_count)
    y = np.linspace(10.0, 80.0, sample_count)
    z = np.sin(x / 10.0)

    interpolation._leave_one_out_r2(x, y, z, backend="idw", power=2.0)

    assert len(calls) == interpolation.MAX_LOO_SAMPLES
    assert calls[0] == x[0]
    assert calls[-1] == x[-1]
