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
    _ELEMENT_BUDGET,
    _chunk_cells_for_budget,
    _fault_blocked_mask,
    _fault_segments,
    _segments_intersect,
    apply_idw_plan,
    apply_idw_plan_multi,
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


# --------------------------------------------------------------------------- #
# Fault-barrier LOS mask (vectorized) — parity + caching (issue #371)
# --------------------------------------------------------------------------- #


def _wavy_breaks(n_polys: int = 2, n_verts: int = 12) -> list[list[tuple[float, float]]]:
    lines = []
    for p in range(n_polys):
        pts = []
        for i in range(n_verts):
            t = i / (n_verts - 1)
            x = 5.0 + t * 90.0
            y = 40.0 + (p * 15.0) + 8.0 * np.sin(t * 6.0 + p)
            pts.append((float(x), float(y)))
        lines.append(pts)
    return lines


def _reference_fault_mask(
    cell_x: np.ndarray,
    cell_y: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    fault_segments,
) -> np.ndarray:
    """Reference triple-loop mask (the pre-vectorization implementation)."""
    blocked = np.zeros((cell_x.size, xs.size), dtype=bool)
    for i, (node_x, node_y) in enumerate(zip(cell_x, cell_y)):
        node = (float(node_x), float(node_y))
        for j, (sx, sy) in enumerate(zip(xs, ys)):
            control = (float(sx), float(sy))
            if any(
                _segments_intersect(node, control, s0, s1)
                for s0, s1 in fault_segments
            ):
                blocked[i, j] = True
    return blocked


def _reference_idw_with_faults(
    plan, values: np.ndarray, stack: np.ndarray
) -> np.ndarray:
    """Reference IDW (pre-vectorization chunk loop + per-pair LOS mask)."""
    x = np.asarray(plan.source_x, dtype=np.float64)
    y = np.asarray(plan.source_y, dtype=np.float64)
    grid_x = np.asarray(plan.grid_x, dtype=np.float64)
    grid_y = np.asarray(plan.grid_y, dtype=np.float64)
    H, W = len(grid_y), len(grid_x)
    epsilon = 1e-12
    fault_segments = _fault_segments(plan.fault_polylines)
    cell_x = np.tile(grid_x, H)
    cell_y = np.repeat(grid_y, W)
    out = np.full((stack.shape[0], cell_x.size), np.nan, dtype=np.float64)
    chunk = 16_384
    for start in range(0, cell_x.size, chunk):
        stop = min(start + chunk, cell_x.size)
        dx = cell_x[start:stop, None] - x[None, :]
        dy = cell_y[start:stop, None] - y[None, :]
        distances = np.maximum(np.hypot(dx, dy), epsilon)
        weights = 1.0 / (distances ** plan.key.power)
        if fault_segments:
            for local_cell, (node_x, node_y) in enumerate(
                zip(cell_x[start:stop], cell_y[start:stop])
            ):
                node = (float(node_x), float(node_y))
                for sample_index, (sample_x, sample_y) in enumerate(zip(x, y)):
                    control = (float(sample_x), float(sample_y))
                    if any(
                        _segments_intersect(node, control, s0, s1)
                        for s0, s1 in fault_segments
                    ):
                        weights[local_cell, sample_index] = 0.0
        totals = np.sum(weights, axis=1)
        populated = totals > epsilon
        if np.any(populated):
            w_pop = weights[populated]
            t_pop = totals[populated]
            out[:, start:stop][:, populated] = (stack @ w_pop.T) / t_pop[None, :]
    return out.reshape(stack.shape[0], H, W)


def test_fault_mask_vectorized_matches_reference_loop():
    """Vectorized mask must equal the reference per-pair loop bit-for-bit."""
    rng = np.random.default_rng(7)
    gx = np.linspace(-5.0, 105.0, 20)
    gy = np.linspace(-5.0, 105.0, 20)
    cell_x = np.tile(gx, 20)
    cell_y = np.repeat(gy, 20)
    xs = rng.uniform(0.0, 100.0, 40)
    ys = rng.uniform(0.0, 100.0, 40)
    segments = _fault_segments(_wavy_breaks())
    got = _fault_blocked_mask(cell_x, cell_y, xs, ys, segments)
    ref = _reference_fault_mask(cell_x, cell_y, xs, ys, segments)
    assert got.shape == ref.shape
    np.testing.assert_array_equal(got, ref)
    assert ref.sum() > 0  # sanity: the case actually exercises crossings


@pytest.mark.parametrize(
    "brk,xs,ys",
    [
        # Collinear: wells sitting exactly on a horizontal fault line.
        ([[(0.0, 25.0), (100.0, 25.0)]], [10.0, 30.0, 50.0, 70.0], [25.0] * 4),
        # Grid-aligned vertical fault through a cell column.
        ([[(5.0, -1.0), (5.0, 11.0)]], [2.0, 4.0, 6.0, 8.0], [2.0, 4.0, 6.0, 8.0]),
        # Endpoint touch: fault endpoint lies exactly on a cell→well segment.
        ([[(2.0, 2.0), (2.0, 5.0)]], [1.0, 3.0], [1.0, 3.0]),
        # Collinear overlap: fault segment lying on the same grid row.
        ([[(2.0, 3.0), (4.0, 3.0)]], [1.0, 5.0], [3.0, 3.0]),
    ],
)
def test_fault_mask_vectorized_matches_reference_degenerate(brk, xs, ys):
    gx = np.arange(0.0, 8.0)
    gy = np.arange(0.0, 8.0)
    cell_x = np.tile(gx, 8)
    cell_y = np.repeat(gy, 8)
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    segments = _fault_segments(brk)
    got = _fault_blocked_mask(cell_x, cell_y, xs, ys, segments)
    ref = _reference_fault_mask(cell_x, cell_y, xs, ys, segments)
    np.testing.assert_array_equal(got, ref)


def test_fault_apply_bitwise_matches_reference_path():
    """Grid output with faults must be bit-identical to the pre-vectorization path."""
    rng = np.random.default_rng(11)
    n_wells = 60
    xs = rng.uniform(0.0, 100.0, n_wells)
    ys = rng.uniform(0.0, 100.0, n_wells)
    points = [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(xs, ys, rng.uniform(10.0, 100.0, n_wells))
    ]
    plan = build_idw_plan(points, grid_n=18, power=2.0, fault_polylines=_wavy_breaks())
    stack = np.ascontiguousarray(rng.uniform(5.0, 50.0, (3, n_wells)))
    got = apply_idw_plan_multi(plan, stack)
    ref = _reference_idw_with_faults(plan, None, stack)
    for i in range(3):
        np.testing.assert_array_equal(got[i]["grid_z"], ref[i])


def test_fault_mask_computed_once_per_plan(monkeypatch):
    """A batch of factors sharing one plan must compute the LOS mask exactly once."""
    import paleo_workbench.workflow.interpolation_plan as ip

    calls = {"n": 0}
    original = ip._fault_blocked_mask

    def counting_mask(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(ip, "_fault_blocked_mask", counting_mask)

    rng = np.random.default_rng(3)
    n_wells = 40
    xs = rng.uniform(0.0, 100.0, n_wells)
    ys = rng.uniform(0.0, 100.0, n_wells)
    points = [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(xs, ys, rng.uniform(10.0, 100.0, n_wells))
    ]
    plan = build_idw_plan(points, grid_n=16, power=2.0, fault_polylines=_wavy_breaks())
    stack = np.ascontiguousarray(rng.uniform(5.0, 50.0, (4, n_wells)))
    apply_idw_plan_multi(plan, stack)
    assert calls["n"] == 1
    # Cached on the plan: a second apply reuses the mask.
    apply_idw_plan_multi(plan, stack)
    assert calls["n"] == 1
    assert plan.fault_mask is not None


def test_fault_chunk_budget_scales_with_well_count():
    """Chunk cells are sized by the element budget, not a fixed cell count."""
    assert _chunk_cells_for_budget(_ELEMENT_BUDGET, 4000) == 1048
    assert _chunk_cells_for_budget(_ELEMENT_BUDGET, 400) == 10485
    assert _chunk_cells_for_budget(_ELEMENT_BUDGET, 10) == 419430
    # Larger well counts → smaller cell chunks (bounded per-chunk memory).
    assert _chunk_cells_for_budget(_ELEMENT_BUDGET, 8000) < _chunk_cells_for_budget(
        _ELEMENT_BUDGET, 1000
    )


def test_high_power_idw_populates_cells_with_positive_weight_totals():
    """#844: populated must test ``totals > 0``, not the 1e-12 distance epsilon.

    Distances are clamped to the 1e-12 epsilon before exponentiation, so the
    *weight* sum at distant cells is not a distance: with power>=3 on a large
    UTM box it stays positive but falls far below 1e-12. The old comparison
    left those cells NaN — power=3 on this fixture NaN'd all 16 cells (and
    ``apply_idw_plan`` raised 插值结果全为无效值), power=4 NaN'd 7/16. A
    positive weight sum always yields a well-defined weighted average.
    """
    rng = np.random.default_rng(11)
    points = [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(
            rng.uniform(0.0, 500_000.0, 6),
            rng.uniform(0.0, 500_000.0, 6),
            rng.uniform(10.0, 100.0, 6),
        )
    ]
    values = [p["value"] for p in points]
    for power in (3.0, 4.0):
        plan = build_idw_plan(points, grid_n=4, power=power)
        result = apply_idw_plan(plan, values)
        assert np.isfinite(result["grid_z"]).all(), (
            f"power={power} produced NaN cells"
        )
