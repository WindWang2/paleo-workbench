"""InterpolationPlan + multi-factor batch geometry reuse."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    batch_prepare_factor_maps,
)
from paleo_workbench.workflow.interpolation_plan import (
    apply_idw_plan,
    build_idw_plan,
    extract_values_aligned,
)


def _shared_xy_points(values: list[float]) -> list[dict]:
    base = [
        (0.0, 0.0),
        (1.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
        (0.5, 0.5),
    ]
    return [
        {"x": x, "y": y, "value": float(v)}
        for (x, y), v in zip(base, values)
    ]


def test_plan_apply_matches_single_task_idw_grid():
    values = [1.0, 2.0, 3.0, 4.0, 2.5]
    points = _shared_xy_points(values)
    plan = build_idw_plan(points, grid_n=16, power=2.0)
    planned = apply_idw_plan(plan, values)
    task = FactorMapTask(
        name="t",
        target_horizon="H",
        factor_type="f",
        method="IDW",
        parameters={"sample_points": points},
        status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=16, power=2.0)
    single = factor_grid_result_for_task(task)
    np.testing.assert_allclose(
        planned["grid_z"],
        single.grid_z.astype(np.float64),
        rtol=1e-5,
        atol=1e-5,
        equal_nan=True,
    )
    np.testing.assert_allclose(planned["grid_x"], single.grid_x)
    np.testing.assert_allclose(planned["grid_y"], single.grid_y)


def test_batch_reuses_axes_across_shared_geometry_factors():
    project = ProjectDocument.new("Batch")
    project.stratigraphy.target_horizon = "H1"
    # Four factors, identical XY, different values.
    value_sets = [
        [1.0, 2.0, 3.0, 4.0, 2.5],
        [10.0, 20.0, 30.0, 40.0, 25.0],
        [0.1, 0.2, 0.3, 0.4, 0.25],
        [5.0, 5.0, 5.0, 5.0, 5.0],
    ]
    for i, vals in enumerate(value_sets):
        project.factor_map_tasks.append(
            FactorMapTask(
                name=f"f{i}",
                target_horizon="H1",
                factor_type=f"type{i}",
                method="IDW",
                parameters={"sample_points": _shared_xy_points(vals)},
                status="pending",
            )
        )
    prepared = batch_prepare_factor_maps(project, method="IDW", grid_n=20)
    assert len(prepared) == 4
    grids = [factor_grid_result_for_task(t) for t in prepared]
    # Shared geometry references
    for g in grids[1:]:
        assert g.grid_x is grids[0].grid_x
        assert g.grid_y is grids[0].grid_y
    # Different values produce different surfaces (except possibly constant)
    assert not np.allclose(grids[0].grid_z, grids[1].grid_z)
    assert np.allclose(grids[3].grid_z, 5.0, atol=1e-3)


def test_extract_values_aligned_rejects_geometry_mismatch():
    points = _shared_xy_points([1, 2, 3, 4, 5])
    plan = build_idw_plan(points, grid_n=10)
    bad = _shared_xy_points([1, 2, 3, 4, 5])
    bad[0]["x"] = 9.0
    with pytest.raises(ValueError, match="does not match"):
        extract_values_aligned(bad, plan)


def test_single_task_still_works_without_plan():
    task = FactorMapTask(
        name="solo",
        target_horizon="H",
        factor_type="t",
        method="IDW",
        parameters={"sample_points": _shared_xy_points([1, 2, 3, 4, 5])},
        status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=12)
    assert task.status == "complete"
    assert "grid_z" not in (task.parameters or {})
    assert factor_grid_result_for_task(task).shape == (12, 12)


def test_multi_factor_plan_matches_single_and_geoviz():
    """Non-degenerate multi-factor path must match per-factor plan and geoviz."""
    from geoviz import interpolate_idw
    from paleo_workbench.workflow.interpolation_plan import apply_idw_plan_multi

    value_sets = [
        [1.0, 2.0, 3.0, 4.0, 2.5],
        [10.0, 12.0, 8.0, 15.0, 11.0],
        [0.5, 1.5, 2.5, 3.5, 2.0],
    ]
    points0 = _shared_xy_points(value_sets[0])
    plan = build_idw_plan(points0, grid_n=24, power=2.0)
    stack = np.stack(
        [extract_values_aligned(_shared_xy_points(v), plan) for v in value_sets],
        axis=0,
    )
    multi = apply_idw_plan_multi(plan, stack)
    for i, vals in enumerate(value_sets):
        single = apply_idw_plan(plan, vals)
        np.testing.assert_allclose(
            multi[i]["grid_z"], single["grid_z"], rtol=1e-14, atol=1e-14, equal_nan=True
        )
        # Geoviz reference (same power / axes / samples)
        ref = interpolate_idw(
            plan.source_x,
            plan.source_y,
            stack[i],
            plan.grid_x,
            plan.grid_y,
            power=2.0,
        )
        np.testing.assert_allclose(
            multi[i]["grid_z"], ref, rtol=1e-12, atol=1e-12, equal_nan=True
        )
