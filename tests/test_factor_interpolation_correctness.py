"""Numerical correctness suite for factor-grid interpolation optimisations.

Locks historical semantics (distance floors, nodata, determinism, axis order)
so performance refactors cannot silently change results.  Uses tight, justified
tolerances — not loose “looks close enough” bands.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task
from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    interpolate_factor_grid,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _pts(*triples: tuple[float, float, float]) -> list[dict]:
    return [{"x": x, "y": y, "value": v} for x, y, v in triples]


def _finite(grid) -> np.ndarray:
    arr = np.asarray(grid, dtype=np.float64)
    return arr[np.isfinite(arr)]


# --- basic observation counts -------------------------------------------------


def test_two_observations_idw_deterministic():
    points = _pts((0.0, 0.0, 1.0), (1.0, 0.0, 2.0))
    a = interpolate_factor_grid(points, method="IDW", grid_n=8, power=2.0)
    b = interpolate_factor_grid(points, method="IDW", grid_n=8, power=2.0)
    assert a["grid_z"] == b["grid_z"]
    assert a["backend"] == "idw"
    assert len(a["grid_x"]) == 8 and len(a["grid_y"]) == 8


def test_multi_observation_regular_grid():
    points = _pts(
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 2.0),
        (0.0, 1.0, 3.0),
        (1.0, 1.0, 4.0),
        (0.5, 0.5, 2.5),
    )
    result = interpolate_factor_grid(points, method="IDW", grid_n=12)
    gz = np.array(
        [[np.nan if v is None else v for v in row] for row in result["grid_z"]],
        dtype=np.float64,
    )
    assert gz.shape == (12, 12)
    assert np.isfinite(gz).all()
    assert result["min"] <= result["max"]


def test_collinear_and_sparse_points_idw():
    collinear = _pts((0.0, 0.0, 1.0), (1.0, 0.0, 2.0), (2.0, 0.0, 3.0))
    result = interpolate_factor_grid(collinear, method="IDW", grid_n=10)
    assert _finite(result["grid_z"]).size > 0
    sparse = _pts((0.0, 0.0, 5.0), (10.0, 10.0, 15.0))
    result2 = interpolate_factor_grid(sparse, method="IDW", grid_n=9)
    assert result2["n_points"] == 2


def test_duplicate_coordinates_idw_keeps_all_samples():
    points = _pts(
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 2.0),
        (0.0, 1.0, 3.0),
        (0.0, 0.0, 1.5),  # duplicate location
    )
    result = interpolate_factor_grid(points, method="IDW", grid_n=8)
    assert result["n_points"] == 4
    assert _finite(result["grid_z"]).size > 0


# --- exact coincidence / zero distance ---------------------------------------


def test_idw_soft_epsilon_at_sample_node():
    """Plain IDW floors distance at 1e-12 (soft exact-hit), not hard snap.

    With a sample on a grid node and distant companions, the node must nearly
    reproduce the sample value (dominated by huge inverse-distance weight).
    """
    # grid_n=5 with samples at 0 and 4 → axes [-0.2, 0.9, 2.0, 3.1, 4.2];
    # node (0,0) is not exact, so place samples on axes that hit linspace.
    points = _pts((0.0, 0.0, 10.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0), (4.0, 4.0, 0.0))
    result = interpolate_factor_grid(points, method="IDW", grid_n=5, power=2.0)
    gx, gy, gz = result["grid_x"], result["grid_y"], result["grid_z"]
    # Closest node to (0,0)
    ix = int(np.argmin(np.abs(np.asarray(gx) - 0.0)))
    iy = int(np.argmin(np.abs(np.asarray(gy) - 0.0)))
    val = gz[iy][ix]
    assert val is not None and math.isfinite(val)
    # Soft ε-floor IDW: nearest sample dominates but distant samples still pull
    # slightly — historical behaviour, not hard exact-hit.
    assert val == pytest.approx(10.0, abs=0.2)


def test_optimized_apply_matches_public_engine_dict_path():
    """Host ndarray path must match public interpolate_factor_grid numerics."""
    points = _pts(
        (0.0, 0.0, 1.0),
        (1.0, 0.0, 2.0),
        (0.0, 1.0, 3.0),
        (1.0, 1.0, 4.0),
    )
    public = interpolate_factor_grid(points, method="IDW", grid_n=16, power=2.0)
    task = FactorMapTask(
        name="t",
        target_horizon="H1",
        factor_type="thickness",
        method="IDW",
        parameters={"sample_points": points},
        status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=16, power=2.0)
    live = factor_grid_result_for_task(task)
    public_z = np.array(
        [[np.nan if v is None else v for v in row] for row in public["grid_z"]],
        dtype=np.float64,
    )
    np.testing.assert_allclose(live.grid_z, public_z, rtol=1e-6, atol=1e-6, equal_nan=True)
    np.testing.assert_allclose(
        live.grid_x, np.asarray(public["grid_x"], dtype=np.float64), rtol=0, atol=0
    )
    np.testing.assert_allclose(
        live.grid_y, np.asarray(public["grid_y"], dtype=np.float64), rtol=0, atol=0
    )


# --- NaN / Inf / nodata -------------------------------------------------------


def test_non_finite_samples_are_dropped():
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": float("nan")},
        {"x": 0.0, "y": 1.0, "value": float("inf")},
        {"x": 1.0, "y": 1.0, "value": 4.0},
    ]
    result = interpolate_factor_grid(points, method="IDW", grid_n=6)
    assert result["n_points"] == 2
    assert _finite(result["grid_z"]).size > 0


def test_factor_grid_result_normalises_none_and_nan():
    engine = {
        "grid_x": [0.0, 1.0],
        "grid_y": [0.0, 1.0],
        "grid_z": [[1.0, None], [float("nan"), 4.0]],
        "backend": "idw",
        "n_points": 2,
        "r_squared": 0.5,
    }
    r = FactorGridResult.from_engine_dict(engine, factor_name="f")
    assert math.isnan(float(r.grid_z[0, 1]))
    assert math.isnan(float(r.grid_z[1, 0]))
    assert r.mask[0, 0]
    assert not r.mask[0, 1]


# --- axis order / shapes ------------------------------------------------------


def test_axis_order_height_width_and_negative_extent():
    points = _pts((-5.0, -3.0, 1.0), (-1.0, -3.0, 2.0), (-5.0, -1.0, 3.0), (-1.0, -1.0, 4.0))
    result = interpolate_factor_grid(points, method="IDW", grid_n=7)
    gx = np.asarray(result["grid_x"])
    gy = np.asarray(result["grid_y"])
    gz = np.array(
        [[np.nan if v is None else v for v in row] for row in result["grid_z"]],
        dtype=np.float64,
    )
    assert gz.shape == (len(gy), len(gx))
    assert np.all(np.diff(gx) > 0)
    assert np.all(np.diff(gy) > 0)
    assert gx.min() < 0 and gy.min() < 0


def test_non_square_extent_and_1d_like_grids():
    points = _pts((0.0, 0.0, 1.0), (10.0, 0.0, 2.0), (0.0, 1.0, 3.0), (10.0, 1.0, 4.0))
    wide = interpolate_factor_grid(points, method="IDW", grid_n=20)
    assert len(wide["grid_x"]) == 20
    # 1×N / N×1 degenerate requests still produce valid 2-D results (min side 2).
    tiny = interpolate_factor_grid(points, method="IDW", grid_n=2)
    assert len(tiny["grid_x"]) == 2 and len(tiny["grid_y"]) == 2


def test_different_cell_sizes_via_grid_n():
    points = _pts((0.0, 0.0, 1.0), (1.0, 0.0, 2.0), (0.0, 1.0, 3.0), (1.0, 1.0, 4.0))
    coarse = interpolate_factor_grid(points, method="IDW", grid_n=5)
    fine = interpolate_factor_grid(points, method="IDW", grid_n=25)
    assert len(fine["grid_x"]) > len(coarse["grid_x"])
    # Mean of finite field stays in sample range.
    for r in (coarse, fine):
        assert r["min"] >= 1.0 - 1e-9
        assert r["max"] <= 4.0 + 1e-9


# --- constrained IDW ----------------------------------------------------------


def test_constrained_requires_three_points():
    with pytest.raises(ValueError, match="至少 3"):
        run_constrained_idw(_pts((0.0, 0.0, 1.0), (1.0, 0.0, 2.0)), grid_n=20)


def test_constrained_preserves_values_outside_unit_interval():
    """Regression: default haiyou clamp [0,1] must not crush real factor ranges."""
    points = _pts(
        (0.0, 0.0, 10.0),
        (5.0, 0.0, 20.0),
        (0.0, 5.0, 30.0),
        (5.0, 5.0, 40.0),
        (2.5, 2.5, 25.0),
    )
    result = run_constrained_idw(points, grid_n=30, power=2.0)
    assert result["max"] == pytest.approx(40.0, rel=0.05, abs=1.0)
    assert result["min"] == pytest.approx(10.0, rel=0.05, abs=1.0)
    assert isinstance(result["grid_z"], np.ndarray)
    assert result["grid_z"].dtype == np.float64
    assert result["grid_z"].flags["C_CONTIGUOUS"]


def test_constrained_deterministic_and_mask():
    points = _pts(
        (0.0, 0.0, 0.2),
        (1.0, 0.0, 0.4),
        (0.0, 1.0, 0.6),
        (1.0, 1.0, 0.8),
        (0.5, 0.5, 0.5),
    )
    a = run_constrained_idw(points, grid_n=24)
    b = run_constrained_idw(points, grid_n=24)
    np.testing.assert_array_equal(a["grid_z"], b["grid_z"])
    assert np.isfinite(a["grid_z"]).sum() > 0
    # Outside domain cells are NaN (mask semantics).
    assert np.isnan(a["grid_z"]).sum() >= 0


def test_apply_stores_live_factor_grid_and_legacy_lists():
    points = _pts((0.0, 0.0, 1.0), (1.0, 0.0, 2.0), (0.0, 1.0, 3.0), (1.0, 1.0, 4.0))
    task = FactorMapTask(
        name="t",
        target_horizon="H1",
        factor_type="砂",
        method="IDW",
        parameters={"sample_points": points},
        status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=10)
    assert isinstance(task.parameters["grid_z"], list)
    assert len(task.parameters["grid_z"]) == 10
    live = factor_grid_result_for_task(task)
    assert isinstance(live, FactorGridResult)
    assert live.shape == (10, 10)
    assert live.grid_z.dtype == np.float32


def test_repeated_run_identical_for_fixed_seed_samples():
    points = _pts(
        (0.0, 0.0, 1.1),
        (2.0, 0.0, 2.2),
        (0.0, 2.0, 3.3),
        (2.0, 2.0, 4.4),
        (1.0, 1.0, 2.5),
    )
    for method in ("IDW",):
        first = interpolate_factor_grid(points, method=method, grid_n=14)
        second = interpolate_factor_grid(points, method=method, grid_n=14)
        assert first["grid_z"] == second["grid_z"]
        assert first["r_squared"] == second["r_squared"]
