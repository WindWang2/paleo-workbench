"""Numerical correctness regression tests for the constrained-IDW algorithm.

Locks the fixes for the constrained/plain-IDW algorithm correctness issue group:

- #369 边界井落插值域外：hull 缓冲区死代码 → 最外圈井不被锚定、R² 均值伪造
- #370 断层走廊被填充为观测最小值而非空值
- #382 4096 域单元阈值两侧 line-of-sight 语义不一致
- #399 重复坐标井 anchor last-wins 与 exact-hit first-wins 不一致
- #400 米制常数直接用于度 CRS 工程

Style follows ``tests/test_factor_interpolation_correctness.py`` (tight, justified
tolerances; NaN-aware grid comparisons).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from paleo_workbench.workflow import constrained_idw_adapter as cia
from paleo_workbench.workflow.constrained_idw_adapter import (
    run_constrained_idw,
)


def _pts(*triples: tuple[float, float, float]) -> list[dict]:
    return [{"x": x, "y": y, "value": v} for x, y, v in triples]


def _nearest_cell(gx, gy, x: float, y: float) -> tuple[int, int]:
    col = int(np.argmin(np.abs(np.asarray(gx) - x)))
    row = int(np.argmin(np.abs(np.asarray(gy) - y)))
    return row, col


# --------------------------------------------------------------------------- #
# #369 — boundary wells inside the interpolation domain; R² without faking
# --------------------------------------------------------------------------- #


def test_369_hull_wells_anchored_finite_and_equal_to_observations():
    """Hull (outermost) wells must sit inside the domain and be residual-anchored.

    z = 0.5 + 0.5·x + 0.5·y is an exact plane; every well's nearest grid node
    must be finite and reproduce the observed value (previously the raw hull
    ring excluded the corner wells from anchoring).
    """
    pts = _pts(
        (0.0, 0.0, 0.5),
        (10.0, 0.0, 5.5),
        (0.0, 10.0, 5.5),
        (10.0, 10.0, 10.5),  # hull corners
        (5.0, 0.0, 3.0),
        (0.0, 5.0, 3.0),
        (5.0, 10.0, 8.0),
        (10.0, 5.0, 8.0),  # hull edge midpoints
        (5.0, 5.0, 5.5),  # interior
    )
    result = run_constrained_idw(pts, grid_n=50, power=2.0)
    gz, gx, gy = result["grid_z"], result["grid_x"], result["grid_y"]
    for p in pts:
        row, col = _nearest_cell(gx, gy, p["x"], p["y"])
        assert math.isfinite(float(gz[row, col])), (
            f"well ({p['x']}, {p['y']}) nearest cell is outside the domain"
        )
        assert float(gz[row, col]) == pytest.approx(p["value"], rel=1e-6, abs=1e-4)


def test_369_exact_surface_r_squared_approaches_one():
    """LOO R² on an exactly reproduced plane must be ≈1.0 (was 0.12–0.69)."""
    pts = _pts(
        (0.0, 0.0, 0.5),
        (10.0, 0.0, 5.5),
        (0.0, 10.0, 5.5),
        (10.0, 10.0, 10.5),
        (5.0, 5.0, 5.5),
        (2.0, 2.0, 2.5),
        (8.0, 2.0, 5.5),
    )
    result = run_constrained_idw(pts, grid_n=50, power=2.0)
    assert result["r_squared"] > 0.99
    assert result["r_squared_n_skipped"] == 0
    # Grid max must express the observed max (10.5) — not fall short of it.
    assert result["max"] == pytest.approx(10.5, rel=0.02)
    # and the surface must actually reach it somewhere on the map.
    assert np.nanmax(result["grid_z"]) == pytest.approx(10.5, rel=0.02)


def test_369_boundary_geometry_keeps_promised_3_percent_buffer():
    """The documented 3% outward hull buffer must be measurable on the domain."""
    pts = _pts(
        (0.0, 0.0, 0.5),
        (10.0, 0.0, 5.5),
        (0.0, 10.0, 5.5),
        (10.0, 10.0, 10.5),
        (5.0, 5.0, 5.5),
    )
    from shapely.geometry import Point, Polygon

    wells = cia._build_wells(pts)
    _boundary, exterior = cia._boundary_from_samples(pts, wells)
    poly = Polygon(exterior)
    buf = 0.03 * 10.0
    for w in wells:
        dist = poly.boundary.distance(Point(w.x, w.y))
        assert dist >= buf * 0.99, (
            f"well ({w.x}, {w.y}) not buffered inside the domain (dist {dist})"
        )
    assert poly.contains(Point(5.0, 5.0))
    # Buffered hull bbox extends ≥ buf past the sample bbox on every side.
    xs = [w.x for w in wells]
    ys = [w.y for w in wells]
    assert min(p[0] for p in exterior) <= min(xs) - buf * 0.99
    assert max(p[0] for p in exterior) >= max(xs) + buf * 0.99
    assert min(p[1] for p in exterior) <= min(ys) - buf * 0.99
    assert max(p[1] for p in exterior) >= max(ys) + buf * 0.99


def test_369_loo_fidelity_counts_missing_instead_of_fabricating_mean():
    """Wells whose bilinear window hits nodata are excluded, never mean-faked."""
    xs = np.linspace(0.0, 4.0, 5)
    ys = np.linspace(0.0, 4.0, 5)
    # Exact plane z = x + y → bilinear sampling reproduces every well exactly.
    gx, gy = np.meshgrid(xs, ys)
    grid_z = gx + gy
    grid_z[0, :] = np.nan  # nodata row → well at (0, 0) window is not finite
    wells = cia._build_wells(_pts((0.0, 0.0, 0.0), (2.0, 2.0, 4.0), (4.0, 4.0, 8.0)))
    r2, skipped = cia._leave_one_out_grid_fidelity(grid_z, xs, ys, wells)
    assert skipped == 1
    # Remaining wells are reproduced exactly; the mean-fake path would have
    # yielded r2 ≈ 0 for this configuration.
    assert r2 == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# #370 — barrier corridor is nodata, never a fabricated minimum band
# --------------------------------------------------------------------------- #


def _thickness_points() -> list[dict]:
    """Five wells, thickness 20–80 m (issue #370 reproduction scenario)."""
    return _pts(
        (0.0, 0.0, 20.0),
        (5.0, 0.0, 40.0),
        (10.0, 0.0, 60.0),
        (0.0, 10.0, 30.0),
        (10.0, 10.0, 80.0),
    )


def test_370_barrier_corridor_cells_are_nodata():
    """Cells inside the fault blanking band must be NaN, not observed-min values."""
    breaks = [[(0.0, 5.0), (10.0, 5.0)]]
    result = run_constrained_idw(
        _thickness_points(), grid_n=50, power=2.0, break_polylines=breaks
    )
    gz, gx, gy = result["grid_z"], result["grid_x"], result["grid_y"]
    # Rows whose centers lie within one cell of the fault line y=5, restricted
    # to the central x-range the corridor fully covers (the blanking band does
    # not reach the map's outer edge cells).
    row = int(np.argmin(np.abs(np.asarray(gy) - 5.0)))
    central = (np.asarray(gx) >= 1.0) & (np.asarray(gx) <= 9.0)
    band = gz[max(0, row - 1): row + 2, :][:, central]
    assert not np.isfinite(band).any(), (
        "fault corridor must be nodata, got finite values "
        f"{sorted(set(float(v) for v in band[np.isfinite(band)]))[:6]}"
    )


def test_370_statistics_min_comes_from_real_data():
    from paleo_workbench.workflow.factor_grid_result import FactorGridResult

    breaks = [[(0.0, 5.0), (10.0, 5.0)]]
    result = run_constrained_idw(
        _thickness_points(), grid_n=50, power=2.0, break_polylines=breaks
    )
    grid = FactorGridResult.from_constrained_idw_dict(result, factor_name="thickness")
    # The fabricated 19.99999994 band previously defined the reported min;
    # now the corridor is nodata and the min is the true observation.
    assert grid.statistics.min == pytest.approx(20.0)
    assert result["min"] >= 20.0 - 1e-6


def test_370_contour_draft_has_no_min_level_isolines_along_fault():
    """No minimum-level isoline may be drawn along the fault blanking band.

    Before the fix the corridor was filled with the observed min (≈20.0 in
    float32), so marching squares traced a level-20 line along the band
    boundary. With the band as nodata the only level-20 geometry is the tiny
    anchor halo at the minimum well (bottom-left corner), far from the fault.
    """
    from paleo_workbench.project.models import (
        ConstraintLayers,
        ConstraintLine,
        FactorMapTask,
        ProjectDocument,
        ProjectMeta,
    )
    from paleo_workbench.workflow.contour_draft import contour_draft_from_factor_task
    from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task

    # Dead-end fault (does not span the map) so the band ends inside the domain.
    line = ConstraintLine(
        id="break-1",
        name="fault",
        role="break",
        coordinates=[[0.0, 5.0], [7.0, 5.0]],
    )
    project = ProjectDocument(meta=ProjectMeta(name="t"))
    project.constraint_layers.append(
        ConstraintLayers(id="cl-1", name="breaks", lines=[line])
    )
    task = FactorMapTask(
        name="H 厚度",
        target_horizon="H",
        factor_type="地层厚度",
        method="约束IDW",
        parameters={"sample_points": _thickness_points()},
        status="pending",
    )
    apply_interpolation_to_task(task, method="约束IDW", grid_n=50, project=project)
    draft = contour_draft_from_factor_task(task, levels=[20.0, 30.0, 40.0, 50.0, 60.0])
    on_fault = [
        (seg.level, p)
        for seg in draft.segments
        if seg.level == 20.0
        for p in seg.coordinates
        if 0.0 <= p[0] <= 7.0 and 4.0 <= p[1] <= 6.0
    ]
    assert not on_fault, f"min-level contour along the fault corridor: {on_fault[:3]}"
