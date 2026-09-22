"""ISS-ALG-02: directional weighted trend surface."""

from __future__ import annotations

import math

import numpy as np

from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    ProjectDocument,
)
from paleo_workbench.workflow.directional_trend import (
    directional_distance,
    directional_trend_grid,
    directional_weights,
    resolve_anisotropy_params,
    rotate_to_uv,
    trend_value_at,
)
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    interpolate_factor_grid,
)
from paleo_workbench.ui import tokens


def test_interpolation_methods_include_directional():
    assert "方向趋势" in tokens.INTERPOLATION_METHODS


def test_directional_distance_formula():
    u = np.array([2.0, 0.0])
    v = np.array([0.0, 3.0])
    d = directional_distance(u, v, a=2.0, b=3.0)
    assert math.isclose(float(d[0]), 1.0)
    assert math.isclose(float(d[1]), 1.0)


def test_weights_include_q_and_b_i():
    d = np.array([0.0, 0.0])
    w = directional_weights(d, q=np.array([1.0, 0.5]), b_i=np.array([1.0, 0.2]))
    assert math.isclose(float(w[0]), 1.0)  # exp(0)*1*1
    assert math.isclose(float(w[1]), 0.1)  # exp(0)*0.5*0.2


def test_trend_is_weighted_mean_at_sample_with_equal_neighbors():
    # Two points equidistant; different z → mean when equal weights.
    xs = np.array([-1.0, 1.0])
    ys = np.array([0.0, 0.0])
    zs = np.array([0.0, 10.0])
    t = trend_value_at(0.0, 0.0, xs, ys, zs, azimuth_deg=0.0, a=1.0, b=1.0)
    assert math.isclose(t, 5.0, rel_tol=1e-9)


def test_anisotropy_favors_along_strike():
    """With a>>b, points along strike should dominate vs across strike."""
    # Azimuth 0°: strike along +Y (north).
    xs = np.array([0.0, 2.0])  # (0,2) along strike; (2,0) across
    ys = np.array([2.0, 0.0])
    zs = np.array([100.0, 0.0])
    # Strong anisotropy: a large, b small → across-strike distance large → low weight
    t = trend_value_at(
        0.0, 0.0, xs, ys, zs, azimuth_deg=0.0, a=4.0, b=0.25
    )
    # Expect closer to 100 (along-strike sample) than to 0
    assert t > 70.0


def test_directional_trend_grid_shape():
    xs = np.array([0.0, 1.0, 0.0, 1.0])
    ys = np.array([0.0, 0.0, 1.0, 1.0])
    zs = np.array([1.0, 2.0, 3.0, 4.0])
    gx = np.linspace(0, 1, 5)
    gy = np.linspace(0, 1, 6)
    grid = directional_trend_grid(xs, ys, zs, gx, gy, azimuth_deg=45.0, a=1.0, b=0.5)
    assert grid.shape == (6, 5)
    assert np.all(np.isfinite(grid))


def test_resolve_anisotropy_from_direction_params():
    az, a, b = resolve_anisotropy_params(
        [{"azimuth_deg": 30.0, "semi_major": 2.0, "semi_minor": 0.5}]
    )
    assert az == 30.0 and a == 2.0 and b == 0.5
    az0, a0, b0 = resolve_anisotropy_params([])
    assert az0 == 0.0 and a0 > 0 and b0 > 0


def test_interpolate_factor_grid_directional_backend():
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0, "q": 1.0, "b_i": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0, "q": 1.0, "b_i": 1.0},
        {"x": 0.0, "y": 1.0, "value": 3.0, "q": 1.0, "b_i": 1.0},
        {"x": 1.0, "y": 1.0, "value": 4.0, "q": 1.0, "b_i": 1.0},
    ]
    result = interpolate_factor_grid(
        points,
        method="方向趋势",
        grid_n=6,
        azimuth_deg=15.0,
        semi_major=2.0,
        semi_minor=0.5,
    )
    assert result["backend"] == "directional"
    assert result["azimuth_deg"] == 15.0
    assert result["semi_major"] == 2.0
    assert len(result["grid_z"]) == 6


def test_apply_pulls_direction_from_project_constraints():
    project = ProjectDocument.new("Dir")
    project.constraint_layers.append(
        ConstraintLayers(
            target_horizon="H1",
            lines=[
                ConstraintLine(
                    role="direction",
                    coordinates=[[0, 0], [0, 1]],
                    azimuth_deg=90.0,
                    semi_major=3.0,
                    semi_minor=0.3,
                    target_horizon="H1",
                )
            ],
        )
    )
    task = FactorMapTask(
        name="砂地比",
        target_horizon="H1",
        factor_type="砂地比",
        method="方向趋势",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "value": 0.2, "q": 1.0, "b_i": 1.0},
                {"x": 1.0, "y": 0.0, "value": 0.3, "q": 1.0, "b_i": 1.0},
                {"x": 0.0, "y": 1.0, "value": 0.4, "q": 1.0, "b_i": 1.0},
                {"x": 1.0, "y": 1.0, "value": 0.5, "q": 1.0, "b_i": 1.0},
            ]
        },
    )
    apply_interpolation_to_task(task, method="方向趋势", grid_n=8, project=project)
    assert task.status == "complete"
    assert task.parameters["interp_backend"] == "directional"
    assert task.parameters["azimuth_deg"] == 90.0
    assert task.parameters["semi_major"] == 3.0
    assert task.parameters["semi_minor"] == 0.3
    # Stage-3+: numerical payload lives in the live FactorGrid cache, not nested lists.
    assert "grid_z" not in task.parameters
    from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task

    assert np.isfinite(factor_grid_result_for_task(task).grid_z).sum() > 0


def test_flagged_points_skipped_in_directional_extract():
    from paleo_workbench.workflow.directional_trend import extract_xy_z_weights

    x, y, z, q, b = extract_xy_z_weights(
        [
            {"x": 0, "y": 0, "value": 1, "qc_flag": "ok"},
            {"x": 1, "y": 0, "value": 99, "qc_flag": "outlier"},
        ]
    )
    assert len(z) == 1
    assert float(z[0]) == 1.0
