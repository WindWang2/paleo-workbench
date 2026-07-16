"""T-PREP-01: real IDW / SciPy factor map interpolation."""

from __future__ import annotations

import numpy as np

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
    assert result["r_squared"] is None or 0.0 <= result["r_squared"] <= 1.0


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
    assert "grid_z" in task.parameters
    assert len(task.parameters["grid_z"]) == 10
    assert "range" in task.quality_metrics
    assert task.quality_metrics.get("grid") == "10×10"


def test_batch_prepare_creates_default_tasks_when_empty():
    project = ProjectDocument.new("Prep")
    project.stratigraphy.target_horizon = "C6"
    prepared = batch_prepare_factor_maps(project, method="IDW", grid_n=12, seed=3)
    assert len(prepared) >= 3
    assert len(project.factor_map_tasks) == len(prepared)
    for task in prepared:
        assert task.status == "complete"
        assert task.target_horizon == "C6"
        assert task.parameters.get("grid_z")
        assert task.quality_metrics.get("n_points", 0) >= 2


def test_batch_prepare_upgrades_mock_factor_maps():
    project = ProjectDocument.new("Upgrade")
    mock = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=9)
    assert mock.method == "mock"
    assert "grid_z" not in (mock.parameters or {})

    batch_prepare_factor_maps(project, method="IDW", grid_n=16)
    assert mock.method == "IDW"
    assert "grid_z" in mock.parameters
    assert mock.status == "complete"
    # Sample points preserved for mapping / compile_map well overlay
    assert len(mock.parameters["sample_points"]) == 8


def test_synthetic_points_are_deterministic():
    a = synthetic_sample_points(seed=42, factor_type="砂")
    b = synthetic_sample_points(seed=42, factor_type="砂")
    assert a == b
